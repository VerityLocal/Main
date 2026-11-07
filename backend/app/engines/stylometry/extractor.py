"""Exactly 24 features; full/light profiles cannot be substituted at runtime."""

import unicodedata
from collections import Counter

import regex

from backend.app.document.chunking import sentence_spans
from backend.app.engines.stylometry.formulas import burstiness, entropy, mattr, richness

SCHEMA = "stylometry_24_v1"
FUNCTION_WORDS = frozenset(
    (
        "a an the this that these those I you he she it we they me him her us them my your his "
        "its our their of to in for on with at by from and or but if as than not no be is are "
        "was were been have has had do does did will would can could should may might must"
    )
    .casefold()
    .split()
)
GROUPS = [
    {"NOUN", "PROPN"},
    {"VERB", "AUX"},
    {"ADJ", "ADV"},
    {"PRON", "DET"},
    {"ADP", "CCONJ", "SCONJ"},
    {"NUM", "PART", "INTJ", "SYM", "X"},
]


def words(text):
    return regex.findall(r"\p{L}+(?:['’\-]\p{L}+)*", text.casefold())


class FeatureExtractor:
    def __init__(self, tokenizer=None, *, profile="light_v1", pos=None, reference=None):
        if profile not in {"light_v1", "full_v1"}:
            raise ValueError("Unknown feature profile")
        if profile == "full_v1" and reference is None:
            raise ValueError("The full profile requires its pinned reference LM")
        self.tokenizer, self.profile, self.pos, self.reference = tokenizer, profile, pos, reference

    def extract(self, document_text, language="en"):
        sentences = sentence_spans(document_text)
        document_words = words(document_text)
        counts = Counter(document_words)
        yule, honore = richness(document_words)
        shared = {
            4: entropy(list(counts.values())),
            5: mattr(document_words),
            6: yule,
            7: honore,
            8: burstiness([len(words(sentence.text)) for sentence in sentences]),
        }
        pos_entropies = [None] * 6
        if self.pos and language.startswith("en"):
            transitions = [Counter() for _ in GROUPS]
            for sentence in self.pos(document_text):
                tags = [tag for tag in sentence if tag not in {"PUNCT", "SPACE"}]
                for current, following in zip(tags, tags[1:], strict=False):
                    for group, counter in zip(GROUPS, transitions, strict=True):
                        if current in group:
                            counter[following] += 1
            pos_entropies = [entropy(list(counter.values())) for counter in transitions]
        stopwords = None
        if language.startswith("en"):
            try:
                from spacy.lang.en.stop_words import STOP_WORDS

                stopwords = STOP_WORDS
            except ImportError:
                pass
        rows = []
        for sentence in sentences:
            values = [None] * 24
            lexical = words(sentence.text)
            chars = [char for char in sentence.text if not char.isspace()]
            alpha = [char for char in chars if char.isalpha()]
            if self.tokenizer is not None:
                special = set(self.tokenizer.all_special_ids)
                values[0] = float(
                    sum(
                        token not in special
                        for token in self.tokenizer.encode(sentence.text, add_special_tokens=False)
                    )
                )
            values[1] = float(len(chars))
            values[2] = sum(map(len, lexical)) / len(lexical) if lexical else None
            values[3] = float(len(lexical))
            for index, value in shared.items():
                values[index] = value
            values[9] = (
                sum(unicodedata.category(c).startswith("P") for c in chars) / len(chars)
                if chars
                else None
            )
            values[10] = sum(c.isdigit() for c in chars) / len(chars) if chars else None
            values[11] = sum(c.isupper() for c in alpha) / len(alpha) if alpha else None
            values[12] = (
                sum(w in stopwords for w in lexical) / len(lexical)
                if lexical and stopwords is not None
                else None
            )
            function = [w for w in lexical if w in FUNCTION_WORDS]
            values[13] = (
                len(set(function)) / len(function)
                if function and language.startswith("en")
                else None
            )
            values[14:20] = pos_entropies
            if self.profile == "full_v1":
                values[20:24] = self.reference(document_text, sentence.start_cp, sentence.end_cp)
            rows.append(
                {
                    "features": values,
                    "feature_valid_mask": [value is not None for value in values],
                    "start_offset": sentence.start_offset,
                    "end_offset": sentence.end_offset,
                }
            )
        return {"schema": SCHEMA, "profile": self.profile, "sentences": rows}
