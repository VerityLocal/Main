from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient as RawClient
from backend.app import create_app as production_app
from backend.tests.helpers import create_app, TestClient, TOKEN
from backend.tests.test_analysis import FakeDetector, FakeRuntime, CharTokenizer, PARAGRAPH, PYTHON, lines
from backend.config import Settings
from backend.analysis.languages import code_language
from backend.analysis.regions import deduplicate_regions
from backend.analysis.extract_worker import ocr_regions
from backend.analysis.source import source_document, decode_source
from backend.analysis.segmentation import segment_document
from backend.analysis.types import AnalysisError, Document, Page, Segment
from backend.analysis.chunking import make_chunks, split_segment, token_count
from backend.analysis.pipeline import AnalysisPipeline


JAVA = 'import java.util.Arrays;\nclass Demo {\n    static int sum(int[] values) {\n        int total = 0;\n        for (int value : values) {\n            total += value;\n        }\n        return total;\n    }\n}\n'
JS = 'function sum(values) {\n  const valid = values.filter(x => Number.isFinite(x));\n  return valid.reduce((total, x) => total + x, 0);\n}\n'


class LanguageRegressionTests(unittest.TestCase):
    def test_java_package_private_listing_is_not_python(self):
        self.assertEqual(code_language(JAVA), 'outside_validation_domain')
        segments = segment_document(Document([Page(1,612,792,lines(['Source Code:',*JAVA.splitlines()]))], 'fixture'))
        code = [item for item in segments if item.kind == 'code']
        self.assertTrue(code)
        self.assertTrue(all(item.reason == 'outside_validation_domain' for item in code))

    def test_supported_and_unsupported_syntax(self):
        for text, expected in [(PYTHON,'python'),(JS,'javascript'),
                ('#include <stdio.h>\nint main() { return 0; }','outside_validation_domain'),
                ('public class Demo { public static void main(String[] args) {} }','outside_validation_domain'),
                ('SELECT name\nFROM students;','outside_validation_domain'),
                ('<html><body>Hello</body></html>','outside_validation_domain'),
                ('value += amount','unknown'),('class Demo { int value = 1; }','unknown')]:
            with self.subTest(text=text): self.assertEqual(code_language(text), expected)

    def test_mixed_listings_are_withheld(self):
        for text in [PYTHON+JS, PYTHON+JAVA, JS+'\n#include <stdio.h>']:
            self.assertEqual(code_language(text), 'mixed')
            document = source_document(text.encode(), 'python', Settings())
            self.assertEqual(segment_document(document)[0].reason, 'mixed_code_languages')

    def test_comments_and_strings_do_not_supply_other_language_evidence(self):
        python = "def f():\n    # const value = 1;\n    value = '''public class Demo { }'''\n    return value\n"
        js = 'function f() {\n // import java.util.Arrays;\n const value = "def f():";\n return value;\n}\n'
        self.assertEqual(code_language(python), 'python')
        self.assertEqual(code_language(js), 'javascript')

    def test_unidentified_import_does_not_bypass_declared_language(self):
        document = source_document(JS.encode(), 'python', Settings())
        self.assertEqual(segment_document(document)[0].reason, 'declared_language_mismatch')


class RegionRegressionTests(unittest.TestCase):
    def test_exact_and_tolerant_duplicates_but_not_overlapping_regions(self):
        page = Page(1,600,800,regions=[{'bbox':box,'status':'unclassified_image'} for box in
            [[40,100,300,500],[40,100,300,500],[40.005,100.005,300,500],[41,100,301,500]]])
        deduplicate_regions(page)
        self.assertEqual(len(page.regions),2)
        self.assertEqual(page.duplicate_regions_removed,2)
        deduplicate_regions(page)
        self.assertEqual(page.duplicate_regions_removed,2)

    def test_rounding_boundary_and_per_page_deduplication(self):
        pages = [Page(n,600,800,regions=[{'bbox':box} for box in [[40.009,100,300,500],[40.011,100,300,500]]]) for n in (1,2)]
        pending = ocr_regions(Document(pages,'fixture'),Settings())
        self.assertEqual(len(pending),2)
        self.assertTrue(all(page.duplicate_regions_removed==1 for page in pages))


class BoundaryRegressionTests(unittest.TestCase):
    def test_functions_stay_whole_when_possible(self):
        value = PYTHON+'\n'+PYTHON.replace('sum_items','sum_other')
        segment = Segment('s1','code',value,[],language='python')
        chunks = split_segment(segment,CharTokenizer(),len(PYTHON)+20,minimum=40)
        self.assertEqual(''.join(item.text for item in chunks),value)
        self.assertEqual(len(chunks),2)
        self.assertTrue(chunks[1].text.startswith('def sum_other'))

    def test_javascript_function_boundaries_ignore_string_braces(self):
        value = JS+'\n'+JS.replace('sum(values)', 'other(values)')
        chunks = split_segment(Segment('s1','code',value,[],language='javascript'),CharTokenizer(),len(JS)+20,minimum=40)
        self.assertEqual(''.join(item.text for item in chunks),value)
        self.assertEqual(len(chunks),2)

    def test_paragraph_boundaries_and_balanced_short_tail(self):
        text = 'a'*90+'\n\n'+'b'*40
        chunks = split_segment(Segment('s1','text',text,[]),CharTokenizer(),112,minimum=30)
        self.assertEqual([item.text for item in chunks],['a'*90+'\n\n','b'*40])
        text = ('A sentence with words.\n'*9)+'tiny'
        chunks = split_segment(Segment('s1','text',text,[]),CharTokenizer(),202,minimum=30)
        self.assertEqual(''.join(item.text for item in chunks),text)
        self.assertTrue(all(item.content_tokens>=30 for item in chunks))

    def test_source_paragraphs_preserve_crlf_and_exact_provenance(self):
        value = PARAGRAPH+'\r\n\r\n'+PARAGRAPH
        document = source_document(value.encode(),'text',Settings())
        chunks = make_chunks(segment_document(document),CharTokenizer(),'text',150,100)
        self.assertEqual(''.join(item.text for item in chunks), value)
        for chunk in chunks:
            for source in chunk.sources:
                self.assertEqual(chunk.text[source['start']:source['end']],value[source['source_start']:source['source_end']])
                self.assertNotIn('page', source)
                self.assertNotIn('bbox', source)


class SourceApiTests(unittest.TestCase):
    def test_utf8_validation(self):
        self.assertEqual(decode_source(b'\xef\xbb\xbf'+PYTHON.encode(),Settings()),PYTHON)
        for data, code in [(b'\xff','invalid_encoding'),(b'a\x00b','binary_source'),(b' \n','empty_source')]:
            with self.subTest(code=code), self.assertRaises(AnalysisError) as error:
                decode_source(data,Settings())
            self.assertEqual(error.exception.code,code)
        with self.assertRaises(AnalysisError): decode_source(b'x'*100,Settings(max_extracted_chars=10))

    def wait(self,client,id):
        manager=client.app.state.jobs
        with manager._condition:
            self.assertTrue(manager._condition.wait_for(lambda:manager.snapshot(id)['status'] in {'completed','failed'},timeout=10))
        return client.get('/analyze/'+id).json()

    def test_source_uploads_preserve_content_and_have_no_pdf_pages(self):
        with TemporaryDirectory() as temp:
            with TestClient(create_app(Settings(temp_dir=Path(temp)),loader=lambda *args:FakeDetector()),base_url='http://localhost') as client:
                for format, text in [('python',PYTHON*2),('javascript',JS*2),('text',PARAGRAPH*3)]:
                    response=client.post('/analyze?format='+format,content=text.encode(),headers={'Content-Type':'text/plain'})
                    self.assertEqual(response.status_code,202,response.text)
                    result=self.wait(client,response.json()['job_id'])['result']
                    self.assertEqual(result['schema_version'],'2.0')
                    self.assertIsNone(result['document']['pages'])
                    kind='text' if format=='text' else 'code'
                    self.assertEqual(result[kind]['status'],'scored')
                    self.assertFalse(result[kind]['university_validated'])
                    self.assertEqual(''.join(chunk['text'] for chunk in result[kind]['chunk_scores']),text)
                    self.assertEqual(result['coverage']['source_characters'],len(text))
                    self.assertEqual(list(Path(temp).iterdir()),[])

    def test_unsupported_source_never_reaches_inference(self):
        detector=FakeDetector(); detector.predict_chunks=Mock(side_effect=AssertionError('Must not score'))
        with TemporaryDirectory() as temp:
            with TestClient(create_app(Settings(temp_dir=Path(temp)),loader=lambda *args:detector),base_url='http://localhost') as client:
                for text, reason in [(JAVA,'outside_validation_domain'),(PYTHON+JS,'mixed_code_languages')]:
                    response=client.post('/analyze?format=python',content=text.encode(),headers={'Content-Type':'text/plain'})
                    result=self.wait(client,response.json()['job_id'])['result']
                    self.assertIsNone(result['code']['flagged_content_share'])
                    self.assertEqual(result['code']['unscored_passages'][0]['reason'],reason)
        detector.predict_chunks.assert_not_called()

    def test_short_content_is_visible_with_a_reason(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'input.py';path.write_text('def f():\n    return 1\n')
            result=AnalysisPipeline(Settings(),FakeRuntime()).run(path,.5)
        self.assertEqual(result['code']['unscored_passages'][0]['reason'],'short_chunk')
        self.assertEqual(result['coverage']['unscored_characters'],len('def f():\n    return 1\n'))


class SecurityRegressionTests(unittest.TestCase):
    def test_isolated_python_path_does_not_resolve_venv_symlink(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)/'python-base'; base.write_text('fixture')
            venv = Path(temp)/'venv-python'; venv.symlink_to(base)
            self.assertEqual(Settings(extraction_python=venv).extraction_python, venv.absolute())

    def test_fail_closed_without_configuration(self):
        with RawClient(production_app(Settings()),base_url='http://localhost') as client:
            self.assertEqual(client.get('/health').status_code,503)
            self.assertEqual(client.get('/health',headers={'Host':'evil.example'}).status_code,400)

    def test_tokens_required_and_not_exposed(self):
        app=production_app(Settings(auth_token=TOKEN),loader=lambda *args:FakeDetector())
        with RawClient(app,base_url='http://localhost') as client:
            for path in ['/health','/analyze/unknown','/openapi.json']:
                self.assertEqual(client.get(path).status_code,401)
                self.assertEqual(client.get(path,headers={'Authorization':'Bearer wrong'}).status_code,401)
            response=client.get('/health',headers={'Authorization':'Bearer '+TOKEN})
            self.assertEqual(response.status_code,200)
            self.assertNotIn(TOKEN,response.text)

    def test_exact_extension_origin_and_restricted_preflight(self):
        id='a'*32; origin='chrome-extension://'+id
        app=production_app(Settings(auth_token=TOKEN,extension_id=id),loader=lambda *args:FakeDetector())
        with RawClient(app,base_url='http://localhost') as client:
            headers={'Origin':origin,'Authorization':'Bearer '+TOKEN}
            response=client.get('/health',headers=headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['access-control-allow-origin'],origin)
            for other in ['https://evil.example','null','chrome-extension://'+'b'*32,'http://localhost']:
                self.assertEqual(client.get('/health',headers={**headers,'Origin':other}).status_code,403)
            preflight={'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization, content-type'}
            self.assertEqual(client.options('/analyze',headers=preflight).status_code,200)
            self.assertEqual(client.options('/analyze',headers={**preflight,'Host':'evil.example'}).status_code,400)
            self.assertEqual(client.options('/analyze',headers={**preflight,'Access-Control-Request-Headers':'x-untrusted'}).status_code,403)

    def test_invalid_extension_id_and_short_tokens_rejected(self):
        for kwargs in [{'auth_token':'short'},{'extension_id':'*'},{'extension_id':'https://example.com'}]:
            with self.assertRaises(ValueError): Settings(**kwargs)
