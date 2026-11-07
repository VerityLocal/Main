# Coordinate and normalization protocol

Browser strings index UTF-16 code units. Python strings index Unicode code
points. `😀` is one Python character and two browser units. UTF-8 bytes and
token positions are never accepted as browser spans.

All spans use `[start, end)` and `offset_unit: "utf16_code_unit"`. Conversion
requires a checked `Utf16Index` built for the exact original text. Unpaired
surrogates, negative positions, positions beyond the text, and positions inside
surrogate pairs are rejected. Do not slice a Python string with browser offsets.

## Normalization algorithm v1

1. Segment the original text with pinned `regex` extended grapheme clusters
   (`\X`). Record each cluster's original UTF-16 interval.
2. Apply **grapheme-local NFKC**, then optional case folding. This is an explicit
   algorithm, not a promise of equivalence to unrestricted whole-string NFKC.
3. Replace whitespace runs with one ASCII space and optionally trim exterior
   whitespace. Collapsed spaces map to the entire original whitespace run.
4. Every resulting normalized code point records the start and end of its
   originating cluster. Expansion (`ß -> ss`, `ﬁ -> fi`) repeats the source
   interval. Composition (`e + combining acute -> é`) maps the complete cluster.

The serialized map retains algorithm version, Python Unicode database version,
regex package version, options, normalized text, and interval arrays.
The normalized text and provenance are validated by recomputing the map.
Raw text remains the canonical representation. A changed Unicode database
version fails validation rather than silently producing different mappings.

`normalized_span_to_original(start_cp, end_cp)` returns the smallest covering
original UTF-16 interval for a nonempty normalized code-point span.
`original_span_to_normalized(start_utf16, end_utf16, original_text=...)` validates
the exact original text and surrogate boundaries, then returns the covering
normalized code-point span whose provenance intersects that original interval,
or `None` for removed whitespace. Empty query spans are rejected.
Mappings are conservative many-to-many provenance, not a bijection. Original
text is reconstructable because it is retained, not because normalization can
be inverted from the normalized string alone.

## Windows and browser mapping

Tokenizer fast offsets are Python code-point offsets into the tokenizer input.
Overflow windows retain offsets into the full original input; individually
tokenized chunks require their explicit original base offset. Convert through
the original text's UTF-16 index. For normalized input, project through its map.
Special tokens and padding have no source spans; attention masks exclude them.

DOM adapters keep an ordered text-node table with UTF-16 starts. Block
separators may have no DOM range. A range spanning several nodes must be split
or reconstructed without replacing those nodes. Text controls use mirror
geometry, not DOM Range on `.value`. Virtualized or canvas content must not be
treated as a complete DOM document.

Revision reconciliation is fail-closed: same document ID + newer revision
invalidates prior findings. Identical registered revisions must have identical
canonical content and metadata. Reordered blocks retain their original IDs only
when the adapter can establish identity.
