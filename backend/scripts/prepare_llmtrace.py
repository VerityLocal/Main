"""Pinned LLMTrace import: span-derived labels, grouped splits, bounded pilot."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path

from backend.app.core.config import PRIVATE_DATA_ROOT, Settings, load_platform_config
from backend.app.document.chunking import sentence_spans
from backend.app.document.offsets import Utf16Index
from backend.scripts.dataset_grouping import group_records
from backend.scripts.dataset_utils import file_sha256, read_records

REPOSITORY = "iitolstykh/LLMTrace_detection"
REVISION = "332053804f8798177ff2ecb1148e1839ed429ba3"
DOCUMENT_POLICY = "contains_annotated_ai_v1"
FILES = {
    "train.jsonl": "1bb15183e4156365cb67c870052730ea3691c30a6a975dfe3e25554688048b84",
    "valid.jsonl": "478c91dc43e07024388853e87cddac4e1cf347e3d93f4ade00f3b48c69d66910",
    "test.jsonl": "0b879a39d7a1c1147636f87e8f6a626a46c8e5cdf83a85d0c00a636c1c08e97e",
}


def stable_key(value, seed=42):
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def convert_annotations(row):
    text = row["text"]
    label = row.get("label")
    if not isinstance(text, str) or not text.strip() or label not in {"human", "ai", "mixed"}:
        raise ValueError("invalid_text_or_document_label")
    index = Utf16Index(text)
    intervals = row.get("ai_char_intervals")
    if not isinstance(intervals, list):
        raise ValueError("missing_ai_intervals")
    covered = bytearray(len(text))
    for interval in intervals:
        if (
            not isinstance(interval, list)
            or len(interval) != 2
            or any(type(value) is not int for value in interval)
            or not 0 <= interval[0] < interval[1] <= len(text)
        ):
            raise ValueError("invalid_code_point_interval")
        start, end = interval
        covered[start:end] = b"\x01" * (end - start)
    content = [i for i, char in enumerate(text) if not char.isspace()]
    ai_content = sum(covered[i] for i in content)
    if (label == "human" and intervals) or (label != "human" and not ai_content):
        raise ValueError("document_label_span_disagreement")
    if label == "ai" and ai_content != len(content):
        raise ValueError("fully_ai_label_has_unannotated_content")
    annotations, counts = [], Counter()
    spans = sentence_spans(text)
    if not spans or len(spans) > 128:
        raise ValueError("sentence_count_outside_profile")
    for span in spans:
        positions = [i for i in range(span.start_cp, span.end_cp) if not text[i].isspace()]
        overlap = sum(covered[i] for i in positions)
        if 0 < overlap < len(positions):
            counts["masked_partial"] += 1
            continue
        sentence_label = int(overlap > 0)
        counts["ai" if sentence_label else "human"] += 1
        annotations.append(
            {
                "start_offset": span.start_offset,
                "end_offset": span.end_offset,
                "label": sentence_label,
            }
        )
    return {
        "label": int(ai_content > 0),
        "sentence_labels": annotations,
        "sentence_supervision": dict(counts),
        "ai_spans_utf16": [[index.to_utf16(a), index.to_utf16(b)] for a, b in intervals],
        "sentence_count": len(spans),
    }


def assign_splits(records, roots, seed):
    origins = defaultdict(set)
    for row, root in zip(records, roots, strict=True):
        origins[root].add(row["upstream_split"])
    assigned, excluded = [], Counter()
    for row, root in zip(records, roots, strict=True):
        source = row["upstream_split"]
        if "test" in origins[root]:
            if source != "test":
                assigned.append(None)
                excluded[f"{source}/reserved_test_component"] += 1
                continue
            split = "final_test"
        elif "valid" in origins[root]:
            if source != "valid":
                assigned.append(None)
                excluded[f"{source}/reserved_validation_component"] += 1
                continue
            split = (
                "calibration"
                if int(stable_key(records[root]["id"], seed)[:8], 16) % 2
                else "validation"
            )
        else:
            split = "train"
        assigned.append(split)
    return assigned, {
        "excluded_development_records": dict(excluded),
        "cross_upstream_split_components": sum(len(values) > 1 for values in origins.values()),
        "policy": "reserve_test_then_validation_components; split_valid_components_50_50_by_hash",
    }


def balanced_sample(records, limit, seed, fields=("source_label", "domain", "generator_length")):
    """Nested round-robin: labels, domains, then generator/length strata."""
    if not fields:
        return sorted(records, key=lambda row: stable_key(row["id"], seed))[:limit]
    groups = defaultdict(list)
    for row in records:
        if fields[0] == "generator_length":
            length_bin = (
                128 if row["token_count"] <= 128 else 256 if row["token_count"] <= 256 else 512
            )
            key = (row["generator"], length_bin)
        else:
            key = row[fields[0]]
        groups[key].append(row)
    queues = [
        deque(balanced_sample(group, limit, seed, fields[1:]))
        for _, group in sorted(groups.items(), key=lambda item: str(item[0]))
    ]
    result = []
    while queues and len(result) < limit:
        following = []
        for queue in queues:
            result.append(queue.popleft())
            if len(result) == limit:
                return result
            if queue:
                following.append(queue)
        queues = following
    return result


def counts_for(records):
    return {
        "records": len(records),
        "groups": len({row["group_id"] for row in records}),
        "labels": dict(Counter(str(row["label"]) for row in records)),
        "source_labels": dict(Counter(row["source_label"] for row in records)),
        "domains": dict(Counter(row["domain"] for row in records)),
        "generators": dict(Counter(row["generator"] for row in records)),
        "sentence_supervision": dict(
            sum((Counter(row["sentence_supervision"]) for row in records), Counter())
        ),
        "token_count_min": min((row["token_count"] for row in records), default=None),
        "token_count_max": max((row["token_count"] for row in records), default=None),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw",
        type=Path,
        default=PRIVATE_DATA_ROOT / "datasets" / "llmtrace_detection" / REVISION / "raw",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true", help="Explicit pinned public download")
    parser.add_argument("--train-limit", type=int, default=4096)
    parser.add_argument("--validation-limit", type=int, default=768)
    parser.add_argument("--calibration-limit", type=int, default=768)
    parser.add_argument("--test-limit", type=int, default=1536)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    manifest_path = args.output.with_suffix(".manifest.json")
    if args.output.exists() or manifest_path.exists():
        raise SystemExit("Use new dataset and manifest paths")
    limits = {
        "train": args.train_limit,
        "validation": args.validation_limit,
        "calibration": args.calibration_limit,
        "final_test": args.test_limit,
    }
    if min(limits.values()) < 2 or not 2 <= args.max_tokens <= 512:
        raise SystemExit("Positive split limits >=2 and token limit <=512 required")
    if args.download:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=REPOSITORY,
            repo_type="dataset",
            revision=REVISION,
            local_dir=args.raw,
            allow_patterns=[*FILES, "README.md", "LICENSE*"],
        )
    progress = lambda value: print(json.dumps(value), flush=True)  # noqa: E731
    records, files, raw_counts = [], {}, Counter()
    for filename, expected in FILES.items():
        path = args.raw / filename
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"Pinned SHA-256 mismatch for {filename}")
        source_split = path.stem
        files[filename] = {"sha256": actual, "bytes": path.stat().st_size}
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                row = json.loads(line)
                raw_counts[f"{source_split}/{row.get('lang')}"] += 1
                if row.get("lang") != "eng":
                    continue
                if not isinstance(row.get("topic_id"), str) or not row["topic_id"]:
                    raise ValueError("English record lacks source topic identity")
                row.pop("prompt", None)
                row.update(
                    id=f"llmtrace:{REVISION[:12]}:{source_split}:{line_number}",
                    upstream_split=source_split,
                    source_line=line_number,
                )
                records.append(row)
    progress({"stage": "integrity_verified", "english_records": len(records)})
    roots, grouping = group_records(records, progress)
    assigned, split_audit = assign_splits(records, roots, args.seed)

    from transformers import AutoTokenizer

    settings = Settings()
    config = load_platform_config(settings.config_dir)
    spec = config.models.models["ai_backbone"]
    tokenizer_path = settings.model_cache / "ai_backbone" / spec.revision
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True, use_fast=True)
    eligible = defaultdict(list)
    exclusions = Counter()
    for row, root, split in zip(records, roots, assigned, strict=True):
        if split is None:
            continue
        try:
            if len(row["text"]) > 20_000:
                raise ValueError("over_character_limit")
            annotation = convert_annotations(row)
            token_count = len(tokenizer.encode(row["text"], truncation=False))
            if token_count > args.max_tokens:
                raise ValueError("over_token_limit_no_truncation")
        except ValueError as exc:
            exclusions[f"{split}/{exc}"] += 1
            continue
        eligible[split].append(
            {
                "id": row["id"],
                "group_id": "llmtrace_component:" + stable_key(records[root]["id"], args.seed),
                "split": split,
                "text": row["text"],
                "language": "en",
                **annotation,
                "document_label_policy": DOCUMENT_POLICY,
                "source_label": row["label"],
                "domain": row["data_type"],
                "generator": row.get("model") or "human",
                "mixed_document": row["label"] == "mixed",
                "token_count": token_count,
                "source": {
                    "repository": REPOSITORY,
                    "revision": REVISION,
                    "upstream_split": row["upstream_split"],
                    "line": row["source_line"],
                    "topic_id": row["topic_id"],
                    "prompt_type": row.get("prompt_type"),
                },
            }
        )
    selected = {}
    for split, limit in limits.items():
        selected[split] = (
            balanced_sample(eligible[split], limit, args.seed)
            if split == "train"
            else sorted(eligible[split], key=lambda row: stable_key(row["id"], args.seed))[:limit]
        )
        if {row["label"] for row in selected[split]} != {0, 1} or {
            label["label"] for row in selected[split] for label in row["sentence_labels"]
        } != {0, 1}:
            raise ValueError(f"Split {split} lacks both document/sentence classes")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        for split in limits:
            for row in selected[split]:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    read_records(args.output)  # Independent ID, exact-text and group leakage checks.
    manifest = {
        "schema_version": "llmtrace_import_v1",
        "timestamp": datetime.now(UTC).isoformat(),
        "repository": REPOSITORY,
        "revision": REVISION,
        "declared_release_license": "apache-2.0",
        "source_terms_scope": "Research corpus; underlying source terms not re-licensed here",
        "source_files": files,
        "raw_counts": dict(raw_counts),
        "document_label_policy": DOCUMENT_POLICY,
        "document_labels": {
            "0": "human/no annotated AI",
            "1": "contains annotated AI (ai or mixed)",
        },
        "sentence_label_policy": "full_nonwhitespace_coverage_ai; no_overlap_human; partial_masked",
        "offset_conversion": "upstream_half_open_code_points_to_original_half_open_utf16",
        "grouping": grouping,
        "split_assignment": split_audit,
        "exclusions": dict(exclusions),
        "eligible_counts": {split: counts_for(eligible[split]) for split in limits},
        "selected_counts": {split: counts_for(selected[split]) for split in limits},
        "sampling": {
            "seed": args.seed,
            "limits": limits,
            "train": "hierarchical_equal_source_label_domain_generator_length_round_robin",
            "evaluation": "label_independent_stable_id_hash_sample_within_reserved_splits",
        },
        "profile": {"max_tokens": args.max_tokens, "max_sentences": 128, "max_code_points": 20_000},
        "tokenizer": {"model_id": spec.model_id, "revision": spec.tokenizer_revision},
        "output_sha256": file_sha256(args.output),
    }
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
    progress({"output": str(args.output), "selected_counts": manifest["selected_counts"]})


if __name__ == "__main__":
    main()
