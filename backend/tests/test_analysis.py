from dataclasses import replace
from io import BytesIO
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from backend.tests.helpers import TestClient, create_app
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader, simpleSplit
from PIL import Image, ImageDraw

from backend.analysis.aggregation import aggregate
from backend.analysis.chunking import make_chunks, split_segment, token_count
from backend.analysis.extraction import extract_pdf, validate_pdf
from backend.analysis.extract_worker import ocr_regions, render, verify_layout_assets
from backend.analysis.extract_worker import source_code_cells
from backend.analysis.jobs import JobManager
from backend.analysis.ocr import parse_tsv
from backend.analysis.pipeline import AnalysisPipeline
from backend.analysis.segmentation import code_language, english_gate, segment_document
from backend.analysis.types import AnalysisError, Document, Page, Segment, SourceLine
from backend.config import Settings
from backend.detectors.inference import ChunkScore


PARAGRAPH = ("We measured the voltage across the resistor and recorded the data in our laboratory notebook. "
             "The results were compared with the theoretical values. Small differences can be caused by "
             "the component tolerances and the resolution of our measuring instruments. ")
PYTHON = "def sum_items(items):\n    # Keep the source comment and indentation.\n    total = 0\n    for item in items:\n        total += item\n    return total\n"


class CharTokenizer:
    def __call__(self,text,add_special_tokens=True,**kwargs):
        ids = list(range(len(text)))
        return {"input_ids":([-1]+ids+[-2]) if add_special_tokens else ids}


class FakeDetector:
    tokenizer = CharTokenizer()
    max_tokens = 512
    batch_size = 4

    def __init__(self,value=.8,fail=False):
        self.value,self.fail = value,fail

    def predict_chunks(self,texts):
        if self.fail:
            raise RuntimeError("inference error")
        return [ChunkScore(self.value,token_count(self.tokenizer,text,True)) for text in texts]


class FakeRuntime:
    def __init__(self,missing=(),fail=()):
        self.missing,self.fail = missing,fail

    def get_detector(self,kind):
        if kind in self.missing:
            raise RuntimeError("unavailable")
        return FakeDetector(fail=kind in self.fail)


def lines(values,page=1,y=100,**kwargs):
    return [SourceLine(value,page,[48,y+i*15,500,y+i*15+11],**kwargs) for i,value in enumerate(values)]


def fixture_pdf(page_count=2,image=False,encrypted=False,boxed=False):
    output = BytesIO()
    if encrypted:
        from reportlab.lib.pdfencrypt import StandardEncryption
        encrypt = StandardEncryption("secret")
    else:
        encrypt = None
    pdf = canvas.Canvas(output,pagesize=(612,792),encrypt=encrypt)
    for i in range(page_count):
        pdf.setFont("Helvetica",9)
        pdf.drawString(48,765,"Repeated course header")
        pdf.setFont("Helvetica-Bold",12)
        pdf.drawString(48,725,"Theory:")
        pdf.setFont("Helvetica",11)
        y = 702
        for value in simpleSplit(PARAGRAPH*2,"Helvetica",11,500):
            pdf.drawString(48,y,value);y-=15
        pdf.setFont("Helvetica-Bold",12)
        pdf.drawString(48,y-15,"Source Code:")
        pdf.setFont("Courier",10)
        y -= 35
        for value in PYTHON.splitlines():
            pdf.drawString(48,y,value);y-=14
        if boxed:
            pdf.rect(40,y-2,530,105,stroke=1,fill=0)
        pdf.setFont("Helvetica-Bold",12)
        pdf.drawString(48,y-15,"Output:")
        pdf.setFont("Courier",10)
        pdf.drawString(48,y-34,"12345")
        if image:
            picture = Image.new("RGB",(500,100),"white")
            ImageDraw.Draw(picture).text((8,8),"def screenshot_only():\n    return 123",fill="black")
            pdf.drawImage(ImageReader(picture),48,70,width=400,height=80)
            picture.close()
        pdf.showPage()
    pdf.save()
    return output.getvalue()


class SegmentationTests(unittest.TestCase):
    def test_prose_code_output_references_and_headers(self):
        pages = []
        for n in (1,2):
            page = Page(n,612,792,lines(["Repeated header"],n,y=40)+lines(
                ["Theory:",PARAGRAPH,"Source Code:",*PYTHON.splitlines(),"Output:","12345","References:","[1] Example 2024"],n))
            pages.append(page)
        segments = segment_document(Document(pages,"fixture"))
        code = [segment for segment in segments if segment.kind=="code"]
        self.assertTrue(code)
        self.assertTrue(all(segment.language=="python" for segment in code))
        self.assertIn("    total",code[0].text)
        self.assertNotIn("12345",code[0].text)
        self.assertTrue(any(segment.reason=="boilerplate" for segment in segments))
        self.assertTrue(any(segment.reason=="references" for segment in segments))
        self.assertTrue(any(segment.kind=="text" and segment.language=="english_likely" for segment in segments))

    def test_proportional_font_code_and_out_of_domain(self):
        document = Document([Page(1,612,792,lines(["function total(values) {","  const sum = 0;","  return sum;","}"]))],"fixture")
        self.assertEqual(segment_document(document)[0].language,"javascript")
        self.assertEqual(code_language('#include <stdio.h>\nint main() { return 0; }'),"outside_validation_domain")
        self.assertEqual(code_language("x += value"),"unknown")

    def test_new_heading_resets_code_continuation_context(self):
        document=Document([Page(1,612,792,lines([*PYTHON.splitlines(),"Theory:",PARAGRAPH],mono=True))],"fixture")
        segments=segment_document(document)
        self.assertTrue(any(segment.kind=="text" and PARAGRAPH in segment.text for segment in segments))

    def test_tables_and_pseudocode_not_forced_into_models(self):
        document = Document([Page(1,612,792,lines(["Item    Value","Apple   12"],hint="table")+
                                  lines(["Algorithm:","1. INPUT value","2. value ← value + 1"],y=200))],"fixture")
        segments = segment_document(document)
        self.assertFalse(any(segment.kind in {"text","code"} for segment in segments))
        self.assertTrue(any(segment.reason=="data_table" for segment in segments))
        self.assertTrue(any(segment.reason=="pseudocode" for segment in segments))

    def test_non_english_and_unknown_language_do_not_get_scores(self):
        for text in ("यह पाठ अंग्रेजी में नहीं है और इसका विश्लेषण नहीं किया जाना चाहिए।", "Bonjour ceci est une phrase française.", "resistor voltage current impedance"):
            self.assertEqual(english_gate(text),"non_english_or_unknown")
        self.assertEqual(english_gate(PARAGRAPH),"english_likely")

    def test_wrapped_results_sentence_and_repeated_body_are_not_headers(self):
        pages=[Page(n,612,792,lines(["Theory:","We measured the voltage and the data with our instrument.",
                                   "results were compared with the theoretical values in our notebook."],n,y=80))
               for n in (1,2)]
        segments=segment_document(Document(pages,"fixture"))
        text="\n".join(segment.text for segment in segments if segment.kind=="text")
        self.assertIn("results were",text)
        self.assertIn("We measured",text)

    def test_ocr_code_and_low_confidence_are_uncertain(self):
        document = Document([Page(1,612,792,lines(PYTHON.splitlines(),method="ocr",confidence=95))],"fixture")
        self.assertTrue(all(segment.reason=="ocr_code_uncertain" for segment in segment_document(document)))
        document.pages[0].lines[0].confidence = 50
        self.assertTrue(any(segment.reason=="extraction_quality" for segment in segment_document(document)))
        document.pages[0].lines = lines(["Conclusion: We compared the data with our values and the results were consistent."],
                                       method="ocr",confidence=40)
        self.assertFalse(any(segment.kind=="text" for segment in segment_document(document)))

    def test_inline_conclusion_not_double_counted(self):
        text = "Conclusion: "+PARAGRAPH
        document = Document([Page(1,612,792,lines([text]))],"fixture")
        # Heading detection is bounded; use a short inline conclusion for this case.
        document.pages[0].lines[0].text = "Conclusion: We compared the data with our values and the results were consistent."
        segments = segment_document(document)
        self.assertEqual(sum(len(segment.text) for segment in segments),len(document.pages[0].lines[0].text))


class ChunkAggregationTests(unittest.TestCase):
    def test_chunk_limit_stops_before_tokenizing_the_entire_document(self):
        from unittest.mock import Mock
        tokenizer=Mock(wraps=CharTokenizer())
        segment=Segment("s1","text","a"*100000,[])
        with self.assertRaises(AnalysisError) as error:
            make_chunks([segment],tokenizer,"text",16,1)
        self.assertEqual(error.exception.code,"chunk_limit")
        self.assertLess(tokenizer.call_count,30)

    def test_exact_nonoverlapping_source_slices_and_unicode(self):
        value = "def test():\n    # café 🙂\n    return 'α'\n"*20
        segment = Segment("s1","code",value,[{"page":1,"bbox":[1,2,3,4],"method":"native",
                                               "start":0,"end":len(value),"source_start":0,"source_end":len(value)}],language="python")
        chunks = split_segment(segment,CharTokenizer(),64)
        self.assertEqual("".join(chunk.text for chunk in chunks),value)
        self.assertTrue(all(chunk.input_tokens<=64 for chunk in chunks))
        self.assertEqual(sum(chunk.content_tokens for chunk in chunks),len(value))
        ranges = [(source["source_start"],source["source_end"]) for chunk in chunks for source in chunk.sources]
        self.assertEqual(ranges[0][0],0)
        self.assertEqual(ranges[-1][1],len(value))
        self.assertTrue(all(left[1]==right[0] for left,right in zip(ranges,ranges[1:])))

    def test_cross_page_attribution_without_crossing_exclusions(self):
        document = Document([Page(1,612,792,lines(PYTHON.splitlines()[:3],1)),
                             Page(2,612,792,lines(PYTHON.splitlines()[3:],2))],"fixture")
        segments = segment_document(document)
        chunks = make_chunks(segments,CharTokenizer(),"code",512,10)
        self.assertEqual({source["page"] for source in chunks[0].sources},{1,2})
        with self.assertRaises(AnalysisError):
            make_chunks(segments,CharTokenizer(),"code",16,1)

    def test_weighted_share_is_not_arithmetic_mean_and_equal_threshold_not_flagged(self):
        scored = [{"probability":.9,"content_tokens":10},{"probability":.1,"content_tokens":90},
                  {"probability":.5,"content_tokens":100}]
        result = aggregate(scored,.5)
        self.assertEqual(result["flagged_content_share"],.05)
        self.assertEqual(result["raw_mean_model_score"],.5)
        self.assertEqual(len(result["flagged_passages"]),1)
        self.assertIsNone(aggregate([],.5)["raw_mean_model_score"])
        with self.assertRaises(ValueError):
            aggregate([{"probability":float("nan"),"content_tokens":10}],.5)


class ExtractionTests(unittest.TestCase):
    def test_full_pdf_native_extraction_and_ocr_gaps(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/"input.pdf";path.write_bytes(fixture_pdf(image=True))
            settings = Settings(temp_dir=Path(temp))
            events = []
            document = extract_pdf(path,settings,lambda *event:events.append(event))
            self.assertEqual(len(document.pages),2)
            self.assertIn("Repeated course header",document.pages[0].lines[0].text)
            self.assertTrue(any("def sum_items" in line.text for page in document.pages for line in page.lines))
            self.assertTrue(any(event[0]=="extracting" for event in events))
            if not __import__("shutil").which("tesseract"):
                self.assertTrue(any(region["status"]=="ocr_unavailable" for page in document.pages for region in page.regions))

    def test_border_around_code_is_not_a_multicolumn_data_table(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"input.pdf";path.write_bytes(fixture_pdf(boxed=True))
            document=extract_pdf(path,Settings())
        self.assertTrue(any(segment.kind=="code" and "def sum_items" in segment.text
                            for segment in segment_document(document)))

    def test_code_cell_is_distinguished_from_data_or_pseudocode_cell(self):
        from types import SimpleNamespace
        table=SimpleNamespace(cells=[[40,90,510,250]])
        text_lines=[(line.bbox,line.text) for line in lines(["import pandas as pd",*PYTHON.splitlines()])]
        self.assertEqual(source_code_cells([table],text_lines),table.cells)
        table.cells=[[40,95+i*15,510,110+i*15] for i in range(len(text_lines))]
        self.assertEqual(source_code_cells([table],text_lines),table.cells)
        data=[(line.bbox,line.text) for line in lines(["Item Value","Apple 12","Pear 10"])]
        self.assertEqual(source_code_cells([table],data),[])
        pseudo=[(line.bbox,line.text) for line in lines(["BEGIN","x = 1","y = 2","print(x)","END IF"])]
        self.assertEqual(source_code_cells([table],pseudo),[])
        # Another distant cell sharing the column boundaries is not part of the listing.
        distant=[40,500,510,520]
        table.cells.append(distant)
        self.assertNotIn(distant,source_code_cells([table],text_lines+[(distant,"Item Value")]))

    def test_parser_timeout_and_cancellation_terminate_the_process(self):
        real_popen=subprocess.Popen
        for cancelled in (False,True):
            with self.subTest(cancelled=cancelled),TemporaryDirectory() as temp:
                path=Path(temp)/"input.pdf";path.write_bytes(fixture_pdf())
                processes=[]
                def blocking_parser(*args,**kwargs):
                    process=real_popen([sys.executable,"-c","import sys; sys.stdin.read()"],
                                       stdin=subprocess.PIPE,**kwargs)
                    processes.append(process)
                    return process
                def check():
                    if cancelled:
                        raise AnalysisError("shutdown","Test cancellation")
                with patch("backend.analysis.extraction.subprocess.Popen",side_effect=blocking_parser), \
                     patch("backend.analysis.extraction.time.monotonic",side_effect=[0,1000]):
                    with self.assertRaises(AnalysisError) as error:
                        extract_pdf(path,Settings(extraction_timeout_seconds=1),check=check)
                self.assertEqual(error.exception.code,"shutdown" if cancelled else "extraction_timeout")
                self.assertIsNotNone(processes[0].poll())
                self.assertTrue(processes[0].stdout.closed)
                processes[0].stdin.close()

    def test_native_content_limit_and_fallback_render_budget(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"input.pdf";path.write_bytes(fixture_pdf(image=True))
            with self.assertRaises(AnalysisError) as error:
                extract_pdf(path,Settings(max_extracted_chars=100))
            self.assertEqual(error.exception.code,"content_limit")
            budget=200000
            image=render(path,Page(1,612,792),[48,642,448,722],"pdfplumber",Settings(max_render_pixels=budget))
            try:
                self.assertLessEqual(image.width*image.height,budget)
                self.assertGreater(image.width,0)
            finally:
                image.close()

    def test_layout_asset_manifest_checks_hashes_and_path_confinement(self):
        import hashlib,json
        with TemporaryDirectory() as temp:
            directory=Path(temp)/"assets";directory.mkdir()
            asset=directory/"layout.bin";asset.write_bytes(b"local test asset")
            digest=hashlib.sha256(asset.read_bytes()).hexdigest()
            manifest=directory/"approved-manifest.json"
            manifest.write_text(json.dumps({"files":{"layout.bin":digest}}))
            verify_layout_assets(directory)
            extra=directory/"unapproved.bin";extra.write_bytes(b"extra")
            with self.assertRaises(ValueError):verify_layout_assets(directory)
            extra.unlink()
            asset.write_bytes(b"changed")
            with self.assertRaises(ValueError):verify_layout_assets(directory)
            manifest.write_text(json.dumps({"files":{"../outside.bin":digest}}))
            with self.assertRaises(ValueError):verify_layout_assets(directory)

    def test_encrypted_corrupt_empty_and_page_limit(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/"input.pdf"
            for data,settings,code in ((fixture_pdf(encrypted=True),Settings(),"encrypted_pdf"),
                                       (b"%PDF-1.7\ncorrupt\n%%EOF",Settings(),"invalid_pdf"),
                                       (fixture_pdf(),Settings(max_pages=1),"page_limit"),
                                       (fixture_pdf(page_count=0),Settings(),"empty_pdf")):
                with self.subTest(code=code):
                    path.write_bytes(data)
                    with self.assertRaises(AnalysisError) as error:
                        extract_pdf(path,settings)
                    self.assertEqual(error.exception.code,code)
            for data in (b"https://example.com/test.pdf",b"<html></html>",b"%PDF-1.7\nmissing end"):
                with self.assertRaises(AnalysisError):
                    validate_pdf(data,Settings())

    def test_ocr_tsv_geometry_confidence_and_indentation(self):
        header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        text = header+"5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t95\tdef\n"+"5\t1\t1\t1\t2\t1\t40\t40\t60\t10\t90\treturn\n"
        result = parse_tsv(text,3,[0,0,200,100],(200,100))
        self.assertEqual(result[0].page,3)
        self.assertEqual(result[0].bbox,[10,20,40,30])
        self.assertEqual(result[0].confidence,95)
        self.assertTrue(result[1].text.startswith("   "))

    def test_image_selection_avoids_small_images_and_existing_text(self):
        page = Page(1,600,800,lines([PARAGRAPH]))
        page.regions = [{"bbox":[0,0,10,10]},{"bbox":[40,98,510,115]},{"bbox":[40,300,500,600]}]
        pending = ocr_regions(Document([page],"fixture"),Settings())
        self.assertEqual(len(pending),1)
        self.assertEqual(page.regions[0]["status"],"ignored_small_image")
        self.assertEqual(page.regions[1]["status"],"native_text_present")


class PipelineTests(unittest.TestCase):
    def run_pipeline(self,document,runtime=None,settings=None):
        with TemporaryDirectory() as temp:
            path = Path(temp)/"input.pdf";path.write_bytes(fixture_pdf())
            pipeline = AnalysisPipeline(settings or Settings(),runtime or FakeRuntime(),
                                        extractor=lambda *args:document)
            return pipeline.run(path,.5)

    def test_separate_results_missing_modality_and_short_content(self):
        document = Document([Page(1,612,792,lines([PARAGRAPH*2]))],"fixture")
        result = self.run_pipeline(document)
        self.assertEqual(result["text"]["status"],"scored")
        self.assertEqual(result["code"]["status"],"no_content")
        self.assertIsNone(result["code"]["raw_mean_model_score"])
        self.assertIn("false positives",result["disclaimer"])
        document.pages[0].lines = lines(["We measured the data with our instrument."])
        result = self.run_pipeline(document)
        self.assertEqual(result["text"]["status"],"insufficient_or_unsupported_content")
        self.assertIsNone(result["text"]["flagged_content_share"])

    def test_one_inference_failure_does_not_destroy_other_modality(self):
        document = Document([Page(1,612,792,lines([PARAGRAPH*2,"Source Code:",*PYTHON.splitlines()]))],"fixture")
        result = self.run_pipeline(document,FakeRuntime(fail=("code",)))
        self.assertEqual(result["text"]["status"],"scored")
        self.assertEqual(result["code"]["status"],"inference_failed")
        self.assertIsNone(result["code"]["flagged_content_share"])
        self.assertEqual(result["code"]["flagged_passages"],[])
        result = self.run_pipeline(document,FakeRuntime(missing=("text",)))
        self.assertEqual(result["text"]["status"],"model_unavailable")
        self.assertEqual(result["code"]["status"],"scored")

    def test_image_only_document_has_no_scores_and_reports_unread_region(self):
        document = Document([Page(1,612,792,regions=[{"bbox":[0,0,600,700],"status":"ocr_unavailable"}])],"fixture")
        result = self.run_pipeline(document)
        self.assertEqual(result["coverage"]["unread_image_regions"],1)
        self.assertIsNone(result["text"]["flagged_content_share"])
        self.assertIsNone(result["code"]["flagged_content_share"])

    def test_unknown_language_chunk_is_withheld_even_in_an_english_segment(self):
        english=PARAGRAPH*5
        unknown="यह सामग्री अंग्रेजी में नहीं है। "*4
        self.assertEqual(english_gate(english+unknown),"english_likely")
        detector=FakeDetector();detector.max_tokens=202
        runtime=FakeRuntime();runtime.get_detector=lambda kind:detector
        result=self.run_pipeline(Document([Page(1,612,792,lines([english+unknown]))],"fixture"),runtime)
        self.assertGreater(result["text"]["skipped_tokens_by_reason"].get("non_english_or_unknown",0),0)

    def test_tokenizer_failure_keeps_the_other_modality_available(self):
        from unittest.mock import Mock
        text_detector=FakeDetector();text_detector.tokenizer=Mock(side_effect=ValueError("tokenizer error"))
        runtime=FakeRuntime();runtime.get_detector=lambda kind:text_detector if kind=="text" else FakeDetector()
        document=Document([Page(1,612,792,lines([PARAGRAPH*2,"Source Code:",*PYTHON.splitlines()]))],"fixture")
        result=self.run_pipeline(document,runtime)
        self.assertEqual(result["text"]["status"],"inference_failed")
        self.assertEqual(result["code"]["status"],"scored")


class ApiJobTests(unittest.TestCase):
    def app(self,settings,**kwargs):
        return create_app(settings,loader=lambda kind,settings:FakeDetector(),**kwargs)

    def wait(self,client,job_id):
        manager = client.app.state.jobs
        with manager._condition:
            finished = manager._condition.wait_for(lambda: manager.snapshot(job_id)["status"] in {"failed","completed"},timeout=15)
        self.assertTrue(finished,"Analysis did not finish")
        return client.get("/analyze/"+job_id).json()

    def test_real_pdf_upload_progress_results_cleanup_and_expiry(self):
        with TemporaryDirectory() as temp:
            settings = Settings(temp_dir=Path(temp))
            with TestClient(self.app(settings),base_url="http://localhost") as client:
                response = client.post("/analyze?threshold=0.7",content=fixture_pdf(),headers={"Content-Type":"application/pdf"})
                self.assertEqual(response.status_code,202,response.text)
                job_id = response.json()["job_id"]
                private = client.app.state.jobs._jobs[job_id].path.parent
                result = self.wait(client,job_id)
                self.assertEqual(result["status"],"completed",result)
                self.assertEqual(result["result"]["document"]["pages"],2)
                self.assertEqual(result["result"]["text"]["threshold"],.7)
                self.assertIn("segmenting",result["stages_seen"])
                self.assertEqual(result["progress"],1)
                self.assertFalse(private.exists())
                finished = client.app.state.jobs._jobs[job_id].finished
                with patch("backend.analysis.jobs.time.monotonic",return_value=finished+settings.result_ttl_seconds+1):
                    self.assertEqual(client.get("/analyze/"+job_id).status_code,404)
                self.assertEqual(client.get("/analyze/unknown").status_code,404)

    def test_upload_validation_size_streaming_threshold_and_origin(self):
        with TemporaryDirectory() as temp:
            settings = Settings(temp_dir=Path(temp),max_upload_bytes=2000)
            with TestClient(self.app(settings),base_url="http://localhost") as client:
                self.assertEqual(client.post("/analyze",json={}).status_code,415)
                for threshold in ("nan","1.2","-0.1"):
                    self.assertEqual(client.post("/analyze?threshold="+threshold,content=b"x",headers={"Content-Type":"application/pdf"}).status_code,422)
                self.assertEqual(client.post("/analyze",content=b"not pdf",headers={"Content-Type":"application/pdf"}).status_code,400)
                self.assertEqual(client.post("/analyze",content=b"x"*2001,headers={"Content-Type":"application/pdf"}).status_code,413)
                self.assertEqual(client.post("/analyze",content=iter([b"x"*1000,b"x"*1001]),headers={"Content-Type":"application/pdf"}).status_code,413)
                self.assertEqual(client.get("/health",headers={"Origin":"https://evil.example"}).status_code,403)
                self.assertEqual(client.get("/health",headers={"Host":"evil.example"}).status_code,400)
                self.assertEqual(list(Path(temp).iterdir()),[])

    def test_bounded_queue_and_single_worker(self):
        entered,release = Event(),Event()
        class Blocking:
            def __init__(self,*args):pass
            def run(self,*args):
                entered.set();release.wait(10)
                return {"done":True}
        with TemporaryDirectory() as temp:
            settings = Settings(temp_dir=Path(temp),max_active_jobs=2)
            with TestClient(self.app(settings,pipeline_factory=Blocking),base_url="http://localhost") as client:
                headers={"Content-Type":"application/pdf"}
                first=client.post("/analyze",content=fixture_pdf(),headers=headers)
                self.assertTrue(entered.wait(5))
                try:
                    second=client.post("/analyze",content=fixture_pdf(),headers=headers)
                    self.assertEqual(second.status_code,202)
                    self.assertEqual(client.get(second.json()["status_url"]).json()["status"],"queued")
                    third=client.post("/analyze",content=fixture_pdf(),headers=headers)
                    self.assertEqual(third.status_code,429)
                finally:
                    release.set()
                self.assertEqual(self.wait(client,first.json()["job_id"])["status"],"completed")

    def test_bad_pdf_job_failure_keeps_scores_absent(self):
        with TemporaryDirectory() as temp:
            with TestClient(self.app(Settings(temp_dir=Path(temp))),base_url="http://localhost") as client:
                response=client.post("/analyze",content=b"%PDF-1.7\ninvalid\n%%EOF",headers={"Content-Type":"application/pdf"})
                result=self.wait(client,response.json()["job_id"])
                self.assertEqual(result["status"],"failed")
                self.assertIsNone(result["result"])
                self.assertEqual(result["error"]["code"],"invalid_pdf")

    def test_cleanup_failure_does_not_silently_kill_the_worker(self):
        entered,release=Event(),Event()
        class Blocking:
            def __init__(self,*args):pass
            def run(self,*args):
                entered.set();release.wait(10)
                return {"done":True}
        with TemporaryDirectory() as temp:
            with TestClient(self.app(Settings(temp_dir=Path(temp)),pipeline_factory=Blocking),base_url="http://localhost") as client:
                response=client.post("/analyze",content=fixture_pdf(),headers={"Content-Type":"application/pdf"})
                self.assertTrue(entered.wait(5))
                job_id=response.json()["job_id"]
                job=client.app.state.jobs._jobs[job_id]
                try:
                    with patch.object(job.directory,"cleanup",side_effect=OSError("test cleanup error")), \
                         self.assertLogs("backend.analysis.jobs",level="ERROR"):
                        release.set()
                        result=self.wait(client,job_id)
                finally:
                    release.set()
                    job.directory.cleanup()
                self.assertEqual(result["status"],"failed")
                self.assertEqual(result["error"]["code"],"cleanup_failed")
                self.assertTrue(client.app.state.jobs.accepting)


if __name__ == "__main__":
    unittest.main()
