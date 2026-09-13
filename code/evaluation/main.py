#!/usr/bin/env python3
"""Evaluation CLI -- score a candidate output CSV against a label set.

This fills the organizer's starter file (previously empty). It runs
`evaluation.metrics.evaluate` (see that module's docstring for the exact join
and scoring rules) and prints the per-field report; no aggregate score is
computed or printed.

Usage:
    python code/evaluation/main.py <candidate_csv> [--dataset DIR]

By default, scores against the 25 public sample labels
(dataset/sample_requests.csv, via Dataset.sample_labels_by_id) -- so
<candidate_csv> must contain predictions for exactly request_01..request_25
in that mode. There is no full-dataset ground truth available to this
project (the 250 evaluation requests' true labels are held by the
organizer), so scoring the full output.csv is only possible once the
decision pipeline exists and is run in "blind" mode against the public
samples' input-only Request objects -- see evaluation/state.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buyorwait.io_load import build_dataset  # noqa: E402
from evaluation.experiment_register import append_entry, PRIOR_RESEARCH_EXPOSED
from evaluation.metrics import StrictJoinError, evaluate, render_report_text  # noqa: E402
from evaluation.schemas import ExperimentEntry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_csv", help="path to a candidate CSV shaped like output.csv")
    parser.add_argument(
        "--dataset", default=str(Path(__file__).resolve().parents[2] / "dataset"), help="dataset directory"
    )
    parser.add_argument("--record-experiment", help="optional experiment ID to record into register.jsonl")
    parser.add_argument("--output-json", help="optional path to save evaluation report as JSON")
    args = parser.parse_args(argv)

    ds = build_dataset(args.dataset)
    try:
        report = evaluate(ds, args.candidate_csv)
    except StrictJoinError as exc:
        print(f"JOIN FAILED: {exc}", file=sys.stderr)
        return 1

    print(render_report_text(report))

    if args.output_json:
        out_p = Path(args.output_json)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        import dataclasses
        import json

        def _json_sanitize(obj):
            if isinstance(obj, dict):
                return {(f"{k[0]}->{k[1]}" if isinstance(k, tuple) else (str(k) if not isinstance(k, (str, int, float, bool)) else k)): _json_sanitize(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple, set, frozenset)):
                return [_json_sanitize(x) for x in obj]
            elif isinstance(obj, (int, float, str, bool)) or obj is None:
                return obj
            elif hasattr(obj, "isoformat"):
                return obj.isoformat()
            else:
                return str(obj)

        out_p.write_text(json.dumps(_json_sanitize(dataclasses.asdict(report)), indent=2), encoding="utf-8")
        print(f"Saved JSON report to {out_p}")

    if args.record_experiment:
        from datetime import datetime, timezone
        import subprocess
        try:
            res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
            commit_hash = res.stdout.strip() if res.returncode == 0 else "working_tree"
        except Exception:
            commit_hash = "working_tree"
        reg_path = Path(__file__).resolve().parents[2] / "evaluation" / "experiments" / "register.jsonl"
        entry = ExperimentEntry(
            experiment_id=args.record_experiment,
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
            commit=commit_hash,
            request_ids=tuple(f"request_{i:02d}" for i in range(1, report.n_rows + 1)),
            exposure=PRIOR_RESEARCH_EXPOSED,
            report_summary_path=args.output_json or "",
            notes=f"Evaluation run on {Path(args.candidate_csv).name}",
        )
        append_entry(reg_path, entry)
        print(f"Recorded experiment {args.record_experiment} into {reg_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
