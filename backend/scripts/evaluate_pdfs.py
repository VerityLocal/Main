"""Read-only evaluation of input PDFs. Report coverage, not invented accuracy."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time

from backend.analysis.extraction import extract_pdf, validate_pdf
from backend.analysis.pipeline import AnalysisPipeline
from backend.analysis.types import AnalysisError
from backend.config import Settings
from backend.detectors.runtime import ModelRuntime


class UnavailableRuntime:
    def get_detector(self,kind):
        raise RuntimeError("Inference disabled in extraction-only evaluation")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,default=Path("test"))
    parser.add_argument("--output",type=Path,default=Path("backend/evaluation/phase2.json"))
    parser.add_argument("--score",action="store_true",help="Load the two existing local detectors once and score eligible content")
    parser.add_argument("--overwrite",action="store_true",help="Explicitly replace an existing evaluation report")
    args=parser.parse_args()
    if args.output.exists() and not args.overwrite:
        parser.error("Output already exists; choose a different path or explicitly use --overwrite")
    files=sorted(args.input.glob("*.pdf"))
    if not files:
        parser.error("No input PDFs found")
    settings=Settings.from_env()
    settings.temp_dir.mkdir(parents=True,mode=0o700,exist_ok=True)
    runtime=ModelRuntime(settings) if args.score else UnavailableRuntime()
    if args.score:
        runtime.initialize()
    rows=[];duplicates=defaultdict(list);started=time.monotonic()
    try:
        for original in files:
            try:
                with TemporaryDirectory(prefix="evaluation-",dir=settings.temp_dir) as directory:
                    path=Path(directory)/"input.pdf"
                    data=original.read_bytes();validate_pdf(data,settings);path.write_bytes(data);del data
                    document=extract_pdf(path,settings)
                    native="\n".join(line.text for page in document.pages for line in page.lines if line.method=="native")
                    if native.strip():
                        duplicates[hashlib.sha256(re.sub(r"\s+"," ",native).strip().encode()).hexdigest()].append(original.name)
                    result=AnalysisPipeline(settings,runtime,extractor=lambda *args:document).run(path,settings.threshold)
                    rows.append({"file":original.name,"status":"processed","document":result["document"],
                                 "coverage":result["coverage"],"warnings":result["warnings"],"timings":result["timings"],
                                  **{kind:{key:value for key,value in result[kind].items() if key not in {"flagged_passages","chunk_scores","unscored_passages"}}
                                    for kind in ("text","code")}})
                print(original.name,"processed",result["document"]["pages"],"pages",flush=True)
            except AnalysisError as exc:
                rows.append({"file":original.name,"status":"failed","error":{"code":exc.code,"message":str(exc)}})
                print(original.name,"failed",exc.code,flush=True)
        report={"mode":"real_model_scoring" if args.score else "extraction_only",
                "authorship_ground_truth_available":False,
                "authorship_metrics":None,
                "note":"No accuracy/precision/recall/F1 computed: the input PDFs have no authorship labels. Scores are not ground truth.",
                "summary":{"documents":len(rows),"processed":sum(row["status"]=="processed" for row in rows),
                           "pages_processed":sum(row.get("document",{}).get("pages",0) for row in rows),
                           "unread_image_regions":sum(row.get("coverage",{}).get("unread_image_regions",0) for row in rows),
                           "evaluation_seconds":time.monotonic()-started},
                "extracted_text_duplicates":[names for names in duplicates.values() if len(names)>1],"documents":rows}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
        print(json.dumps(report["summary"]),"report:",args.output)
    finally:
        if args.score:
            runtime.close()


if __name__=="__main__":
    main()
