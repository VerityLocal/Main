"""Conservative syntax evidence, not a claim of validated language detection."""

import re


def syntax_only(text: str) -> str:
    """Mask strings/comments while preserving offsets and line breaks.

    This small lexer handles common Python/JS/Java strings. It deliberately does
    not execute, repair, or normalize submitted code. Preprocessor lines survive.
    """
    pattern = re.compile(
        r"'''[\s\S]*?(?:'''|$)|\"\"\"[\s\S]*?(?:\"\"\"|$)|"
        r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`|"
        r"/\*[\s\S]*?(?:\*/|$)|//[^\n]*|\#(?!\s*include\b)[^\n]*")
    return pattern.sub(lambda match: ''.join('\n' if c == '\n' else ' ' for c in match[0]), text)


def language_evidence(text: str) -> set[str]:
    code = syntax_only(text)
    evidence = set()
    if re.search(r"^\s*(?:async\s+)?def\s+\w+\s*\([^\n]*\).*:\s*$|"
                 r"^\s*(?:from\s+[\w.]+\s+import\s+[\w*, ()]+|import\s+[\w., ]+)\s*$|"
                 r"^\s*(?:for|if|elif|while|with|except)\s+[^\n]+:\s*$|"
                 r"\b(?:print\s*\(|(?:pd|np|plt)\.)", code, re.M):
        evidence.add('python')
    if re.search(r"\b(?:async\s+)?function\s*(?:\w+\s*)?\(|"
                 r"\b(?:const|let|var)\s+\w+\s*=|=>|\bconsole\.(?:log|error)\s*\(|"
                 r"\brequire\s*\(|^\s*(?:export\s+)?(?:default\s+)?function\b|"
                 r"^\s*import\s+(?:\{|\*|\w+\s+from\b)", code, re.M):
        evidence.add('javascript')
    if re.search(r"^\s*(?:package\s+[\w.]+\s*;|import\s+(?:static\s+)?[\w.]+(?:\.\*)?\s*;)|"
                 r"\b(?:public|private|protected)\s+(?:(?:static|final|abstract)\s+)*(?:class|interface|void)\b|"
                 r"\bSystem\.(?:out|err)\.|\b(?:extends|implements)\s+\w+|"
                 r"\b(?:static\s+)?(?:void|int|double|boolean|String)\s+\w+\s*\([^\n]*\)\s*\{", code, re.M):
        evidence.add('java')
    explicit_c = re.search(r"#\s*include\b|\bstd::|\b(?:printf|scanf|malloc|sizeof)\s*\(|"
                           r"\b(?:struct|typedef)\s+\w+", code)
    main = re.search(r"\b(?:int|void)\s+main\s*\(", code)
    if explicit_c or (main and not re.search(r"\b(?:package|import|class|System)\b", code)):
        evidence.add('c_cpp')
        # main() alone is C-family evidence, not evidence of mixed Java/C.
        if 'java' in evidence and re.search(r"\b(?:int|void)\s+main\s*\(", code) and not re.search(
                r"\b(?:package|import|class|System)\b", code):
            evidence.discard('java')
    if re.search(r"<\s*(?:!DOCTYPE|/?(?:html|div|script|body|head|p|span))\b", code, re.I):
        evidence.add('html')
    if re.search(r"\bSELECT\b[\s\S]+?\bFROM\b|\bCREATE\s+TABLE\b|\bINSERT\s+INTO\b", code, re.I):
        evidence.add('sql')
    return evidence


def code_language(text: str) -> str:
    evidence = language_evidence(text)
    if len(evidence) > 1:
        return 'mixed'
    if evidence:
        language = next(iter(evidence))
        return language if language in {'python', 'javascript'} else 'outside_validation_domain'
    return 'unknown'


def withholding_reason(language: str) -> str:
    return {'outside_validation_domain': 'outside_validation_domain',
            'mixed': 'mixed_code_languages', 'unknown': 'unknown_code_language'}.get(language, '')
