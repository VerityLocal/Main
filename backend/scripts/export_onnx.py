"""Export a local cross-encoder and report actual CPU provider parity."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Export local cross-encoder FP32 and validate ONNX CPU execution"
    )
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output already exists")
    import numpy as np
    import onnxruntime as ort
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_dir, local_files_only=True
    ).eval()
    encoded = tokenizer("An evidence passage.", "A user claim.", return_tensors="pt")
    names = list(encoded)

    class Wrapper(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, *tensors):
            return self.inner(**dict(zip(names, tensors, strict=True))).logits

    torch.onnx.export(
        Wrapper(model).eval(),
        tuple(encoded.values()),
        str(args.output),
        input_names=names,
        output_names=["logits"],
        dynamic_axes={
            **{name: {0: "batch", 1: "sequence"} for name in names},
            "logits": {0: "batch"},
        },
        opset_version=17,
    )
    session = ort.InferenceSession(str(args.output), providers=["CPUExecutionProvider"])
    actual = session.run(None, {name: value.numpy() for name, value in encoded.items()})[0]
    with torch.inference_mode():
        expected = model(**encoded).logits.numpy()
    report = {
        "providers": session.get_providers(),
        "max_abs_logit_difference": float(np.max(np.abs(actual - expected))),
        "precision": "fp32",
        "parity_fixture_only_not_accuracy_evaluation": True,
    }
    args.output.with_suffix(".report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print("ONNX FP32 export and CPU parity fixture complete. No INT8/GPU improvement is assumed.")


if __name__ == "__main__":
    main()
