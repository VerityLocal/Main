"""Validate real JSONL records and group leakage; never invent labels."""

import hashlib
import json


def file_sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dataset_provenance(path, records):
    policies = {row.get("document_label_policy", "binary_authorship_v1") for row in records}
    if len(policies) != 1 or not policies <= {"binary_authorship_v1", "contains_annotated_ai_v1"}:
        raise ValueError("A dataset must use one supported document-label policy")
    policy = policies.pop()
    result = {"data_sha256": file_sha256(path), "document_label_policy": policy}
    manifest_path = path.with_suffix(".manifest.json")
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("output_sha256") != result["data_sha256"]:
            raise ValueError("Dataset no longer matches its import manifest checksum")
        if manifest.get("document_label_policy") != policy:
            raise ValueError("Dataset label policy differs from its import manifest")
        result.update(import_manifest=manifest, import_manifest_sha256=file_sha256(manifest_path))
    return result


def read_records(path):
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if not records:
        raise ValueError("Dataset is empty")
    ids, groups = set(), {}
    for record in records:
        if record.get("split") not in {
            "train",
            "validation",
            "calibration",
            "final_test",
        } or not record.get("id"):
            raise ValueError("Every record needs ID and a declared split")
        if record["id"] in ids:
            raise ValueError("Duplicate record IDs")
        ids.add(record["id"])
        if not record.get("group_id"):
            raise ValueError("Every record needs an author/source/near-duplicate group ID")
        fields = ("text", "query", "passage", "premise", "hypothesis")
        text = "\x1f".join(str(record[key]) for key in fields if key in record)
        if not text.strip():
            raise ValueError("Every record needs nonempty task text")
        digest = hashlib.sha256(" ".join(text.casefold().split()).encode("utf-8")).hexdigest()
        for key in [record["group_id"], "exact_normalized:" + digest]:
            if key in groups and groups[key] != record["split"]:
                raise ValueError("Cross-split grouping or normalized duplicate leakage")
            groups[key] = record["split"]
    return records


def split_identities(records):
    identities = {}
    for record in records:
        text = "\x1f".join(
            str(record[k])
            for k in ("text", "query", "passage", "premise", "hypothesis")
            if k in record
        )
        keys = ["group:" + str(record["group_id"]), "text:" + " ".join(text.casefold().split())]
        identities.setdefault(record["split"], set()).update(
            hashlib.sha256(key.encode("utf-8")).hexdigest() for key in keys
        )
    return {split: sorted(values) for split, values in identities.items()}
