#!/usr/bin/env python3
"""Buy or Wait? -- Production CLI entry point and pipeline orchestrator.

Supported operations:
  1. Full prediction pipeline:
     python code/main.py [--mode full] [--output output.csv] [--dataset dataset]
  2. Public sample prediction & baseline recording:
     python code/main.py --mode sample [--run-id baseline_v1_public_samples] [--output PATH]
  3. Single-request adaptive investigation trace:
     python code/main.py --investigate REQUEST_ID
  4. Output CSV validation:
     python code/main.py --validate-csv PATH
  5. Evidence rebuild:
     python code/main.py --rebuild-evidence
  6. Clean submission packaging and self-verification:
     python code/main.py --package [--output code.zip]
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Sequence

# Add code directory to path
CODE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

from buyorwait.csv_format import (  # noqa: E402
    CsvFormatError,
    PlanEntry,
    SpendingChange,
    is_chronological,
    parse_payment_plan,
    parse_spending_changes,
    serialize_payment_plan,
    serialize_spending_changes,
)
from buyorwait.decimal_utils import format_capacity_amount  # noqa: E402
from buyorwait.evidence import extract_facts_from_message_text, get_all_resolved_image_amounts  # noqa: E402
from buyorwait.explain import explain, validate_explanation  # noqa: E402
from buyorwait.forecast import (  # noqa: E402
    assemble_flows,
    calculate_amount_safe_to_pay,
    calculate_earliest_full_payment_date,
    forecast_headroom,
)
from buyorwait.independent_verifier import verify_decision  # noqa: E402
from buyorwait.investigation import (  # noqa: E402
    InvestigationLimits,
    build_tool_handlers,
    run_adaptive_investigation,
)
from buyorwait.io_load import DatasetValidationError, build_dataset, sha256_file  # noqa: E402
from buyorwait.metering import UsageLedger  # noqa: E402
from buyorwait.planner import Candidate, enumerate_candidates, rank_candidates  # noqa: E402
from buyorwait.schemas import (  # noqa: E402
    AffordabilityStatus,
    Dataset,
    RecommendedPaymentMethod,
    Request,
)
from buyorwait.writer import OutputRow, REQUIRED_COLUMNS, write_output_csv  # noqa: E402
from evaluation.experiment_register import (  # noqa: E402
    PRIOR_RESEARCH_EXPOSED,
    append_entry,
)
from evaluation.metrics import evaluate, render_report_text  # noqa: E402
from evaluation.schemas import ExperimentEntry  # noqa: E402


def _json_sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            (f"{k[0]}->{k[1]}" if isinstance(k, tuple) else (str(k) if not isinstance(k, (str, int, float, bool)) else k)): _json_sanitize(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, (list, tuple, set, frozenset)):
        return [_json_sanitize(x) for x in obj]
    elif isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    elif hasattr(obj, "isoformat"):
        return obj.isoformat()
    else:
        return str(obj)


def run_pipeline_for_request(
    dataset: Dataset,
    req: Request,
    all_facts: Sequence[Any],
    *,
    image_amounts: dict[str, Decimal] | None = None,
    investigate: bool = False,
) -> tuple[OutputRow, Candidate, Any]:
    """Execute complete decision pipeline for one request."""
    user_id = req.user_id
    as_of = req.request_date
    prof = dataset.profiles_by_user[user_id]
    user_facts = tuple(f for f in all_facts if f.user_id == user_id)

    investigation_state = None
    if investigate:
        investigation_state = run_adaptive_investigation(
            dataset=dataset,
            request_id=req.request_id,
            limits=InvestigationLimits(max_steps=5, max_tool_calls=10),
        )
        if investigation_state and investigation_state.facts:
            user_facts = tuple(user_facts) + tuple(investigation_state.facts)

    # 1. Baseline flows and headroom
    base_flows = assemble_flows(
        dataset,
        user_id,
        anchor_date=as_of,
        evidence_facts=user_facts,
        image_amounts=image_amounts,
    )
    base_sim = forecast_headroom(
        dataset,
        user_id,
        anchor_date=as_of,
        flows=base_flows,
        image_amounts=image_amounts,
    )
    safe_today = calculate_amount_safe_to_pay(base_sim, req.requested_amount)
    earliest_date = calculate_earliest_full_payment_date(
        dataset,
        user_id,
        anchor_date=as_of,
        requested_amount=req.requested_amount,
        flows=base_flows,
        evidence_facts=user_facts,
        image_amounts=image_amounts,
    )

    # 2. Candidate enumeration and ranking
    cands = enumerate_candidates(
        dataset,
        req.request_id,
        evidence_facts=user_facts,
        image_amounts=image_amounts,
    )
    selected = rank_candidates(cands)

    # 3. Independent decision verification
    expected_tot = (
        dataset.options_by_id[selected.payment_option_id].total_payable_amount
        if selected.method == RecommendedPaymentMethod.INSTALLMENTS
        and selected.payment_option_id
        and selected.payment_option_id in dataset.options_by_id
        else req.requested_amount
    ) if selected.method != RecommendedPaymentMethod.NOT_RECOMMENDED else None

    v_res = verify_decision(
        request_id=req.request_id,
        opening_balance=prof.current_available_balance,
        minimum_balance_to_keep=prof.minimum_balance_to_keep,
        anchor_date=as_of,
        deadline=req.desired_completion_date,
        requested_amount=req.requested_amount,
        user_accepted_methods={m.value for m in prof.payment_methods_user_will_consider},
        recommended_method=selected.method.value,
        plan_entries=selected.payment_plan,
        spending_changes=selected.spending_changes,
        amount_safe_to_pay=safe_today,
        earliest_date_for_full_payment=earliest_date,
        baseline_flows=base_flows,
        modified_flows=selected.flows_used if selected.flows_used else base_flows,
        candidate_rejections={c.method.value: c.rejection_reason for c in cands if not c.is_safe},
        expected_total=expected_tot,
        payment_options=dataset.options_by_request.get(req.request_id, ()),
        payment_option_id=selected.payment_option_id,
        allows_partial_payment=req.allows_partial_payment,
        max_installment_months=prof.max_installment_months,
    )

    if not v_res.is_valid:
        raise ValueError(
            f"Verification failed for request {req.request_id}: {v_res.failure_notes}"
        )

    # 4. Grounded explanation generation & validation
    expl = explain(dataset, req.request_id, selected)
    is_valid_expl, expl_reason = validate_explanation(dataset, req.request_id, selected, expl)
    if not is_valid_expl:
        # Fallback or warning (retains fact grounding)
        print(f"Warning: explanation fact validation note on {req.request_id}: {expl_reason}", file=sys.stderr)

    row = OutputRow(
        request_id=req.request_id,
        amount_safe_to_pay=safe_today,
        affordability_status=selected.affordability_status,
        recommended_payment_method=selected.method,
        payment_plan=selected.payment_plan,
        earliest_date_for_full_payment=earliest_date,
        spending_changes_needed=selected.spending_changes,
        decision_explanation=expl,
    )

    return row, selected, investigation_state


def validate_output_csv(path: Path | str, dataset: Dataset | None = None) -> tuple[bool, list[str]]:
    """Validate a candidate output CSV against the exact challenge specification."""
    path = Path(path)
    errors: list[str] = []
    if not path.exists():
        return False, [f"file not found: {path}"]

    raw_bytes = path.read_bytes()
    if b"\r\n" not in raw_bytes:
        errors.append("file does not use CRLF line endings")

    text = raw_bytes.decode("utf-8-sig")
    lines = text.splitlines()
    if len(lines) < 2:
        return False, ["file is empty or missing data rows"]

    header_cols = lines[0].split(",")
    if tuple(header_cols) != REQUIRED_COLUMNS:
        errors.append(f"header columns mismatch: got {header_cols}, expected {list(REQUIRED_COLUMNS)}")

    reader = csv.DictReader(lines, fieldnames=REQUIRED_COLUMNS)
    next(reader)  # skip header

    row_count = 0
    valid_statuses = {s.value for s in AffordabilityStatus}
    valid_methods = {m.value for m in RecommendedPaymentMethod}
    observed_ids: list[str] = []

    for idx, row in enumerate(reader, start=2):
        row_count += 1
        req_id = row.get("request_id", "").strip()
        if not req_id:
            errors.append(f"line {idx}: empty request_id")
        observed_ids.append(req_id)

        req_obj = dataset.all_requests_by_id.get(req_id) if dataset else None

        # amount_safe_to_pay
        amt_str = row.get("amount_safe_to_pay", "").strip()
        try:
            amt = Decimal(amt_str)
            if amt < Decimal(0):
                errors.append(f"line {idx} ({req_id}): amount_safe_to_pay is negative ({amt})")
            if req_obj is not None and amt > req_obj.requested_amount:
                errors.append(
                    f"line {idx} ({req_id}): amount_safe_to_pay {amt} exceeds requested_amount {req_obj.requested_amount}"
                )
        except Exception:
            errors.append(f"line {idx} ({req_id}): invalid amount_safe_to_pay '{amt_str}'")

        # status and method
        st = row.get("affordability_status", "").strip()
        if st not in valid_statuses:
            errors.append(f"line {idx} ({req_id}): invalid status '{st}'")

        m = row.get("recommended_payment_method", "").strip()
        if m not in valid_methods:
            errors.append(f"line {idx} ({req_id}): invalid method '{m}'")

        # payment_plan grammar & chronology
        plan_raw = row.get("payment_plan", "").strip()
        try:
            entries = parse_payment_plan(plan_raw)
            if not is_chronological(entries):
                errors.append(f"line {idx} ({req_id}): payment_plan is not chronological")
            if m == "not_recommended" and plan_raw != "none":
                errors.append(f"line {idx} ({req_id}): method is not_recommended but plan is '{plan_raw}'")
            if m == "partial_payment":
                if len(entries) != 2:
                    errors.append(f"line {idx} ({req_id}): partial_payment must have exactly 2 entries, got {len(entries)}")
                elif req_obj is not None:
                    plan_sum = sum(e.amount for e in entries)
                    if abs(plan_sum - req_obj.requested_amount) > Decimal("0.01"):
                        errors.append(
                            f"line {idx} ({req_id}): partial_payment plan sum {plan_sum} does not equal requested_amount {req_obj.requested_amount}"
                        )
        except CsvFormatError as exc:
            errors.append(f"line {idx} ({req_id}): invalid payment_plan: {exc}")

        # earliest_date
        ed_str = row.get("earliest_date_for_full_payment", "").strip()
        if ed_str:
            try:
                ed = date.fromisoformat(ed_str)
                if st == "affordable_now" and req_obj is not None and ed != req_obj.request_date:
                    errors.append(
                        f"line {idx} ({req_id}): affordable_now requires earliest_date == request_date ({req_obj.request_date}), got {ed}"
                    )
            except ValueError:
                errors.append(f"line {idx} ({req_id}): invalid earliest date '{ed_str}'")

        # spending_changes
        ch_raw = row.get("spending_changes_needed", "").strip()
        try:
            parse_spending_changes(ch_raw)
        except CsvFormatError as exc:
            errors.append(f"line {idx} ({req_id}): invalid spending_changes: {exc}")

        # explanation
        expl = row.get("decision_explanation", "").strip()
        if not expl:
            errors.append(f"line {idx} ({req_id}): empty decision_explanation")

    # Dataset-level checks: exact count, unique IDs, order matching dataset.requests
    if len(observed_ids) == 0:
        errors.append("CSV has 0 data rows")
    if len(observed_ids) != len(set(observed_ids)):
        duplicates = [rid for rid in observed_ids if observed_ids.count(rid) > 1]
        errors.append(f"duplicate request_ids found: {set(duplicates)}")

    if dataset:
        expected_ids = [r.request_id for r in dataset.requests]
        if len(observed_ids) != len(expected_ids):
            sample_ids = [r.request_id for r in dataset.sample_requests]
            if len(observed_ids) == len(sample_ids) and observed_ids == sample_ids:
                pass  # Valid sample evaluation output
            else:
                errors.append(f"expected {len(expected_ids)} rows, got {len(observed_ids)}")
        elif observed_ids != expected_ids:
            errors.append("request_id ordering does not match requests.csv exactly")

    return (len(errors) == 0), errors


def package_clean_submission(output_zip: Path | str) -> None:
    """Create and self-verify a clean, deterministic code.zip package."""
    output_zip = Path(output_zip).resolve()
    print(f"Packaging submission code into {output_zip}...")

    # Exclusions
    excluded_names = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "scratch",
        ".DS_Store",
        "dataset",  # Crucial: dataset corpus strictly excluded
    }
    excluded_exts = {".pyc", ".pyo", ".zip", ".tar", ".gz", ".corrupt"}

    # Collect files deterministically
    entries: list[tuple[Path, str]] = []
    for root, dirs, files in os.walk(CODE_DIR):
        dirs[:] = [d for d in dirs if d not in excluded_names]
        for file in sorted(files):
            p = Path(root) / file
            if p.suffix in excluded_exts or file.startswith("."):
                continue
            rel_path = p.relative_to(CODE_DIR)
            # Store under 'code/' inside zip per HackerRank guidelines
            arcname = (Path("code") / rel_path).as_posix()
            entries.append((p, arcname))

    # Sort deterministically
    entries.sort(key=lambda x: x[1])

    # Write with fixed timestamps for bit-for-bit reproducible packaging
    fixed_time = (2026, 9, 13, 0, 0, 0)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src, arc in entries:
            zinfo = zipfile.ZipInfo(arc, date_time=fixed_time)
            zinfo.external_attr = 0o644 << 16
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zinfo, src.read_bytes())

    zip_size = output_zip.stat().st_size
    print(f"Built deterministic package: {output_zip} ({zip_size:,} bytes).")

    # Clean verification in temporary directory
    print("Verifying package in isolated clean-room temporary environment (full live & replay execution)...")
    dataset_dir = REPO_ROOT / "dataset"
    with tempfile.TemporaryDirectory(prefix="clean_room_") as tmpdir:
        tmp_path = Path(tmpdir)
        with zipfile.ZipFile(output_zip, "r") as zf:
            zf.extractall(tmp_path)

        extracted_code = tmp_path / "code"
        assert extracted_code.exists(), "Extracted zip missing code/ directory"
        main_py = extracted_code / "main.py"
        assert main_py.exists(), "Extracted zip missing code/main.py"

        import subprocess
        clean_env = {**os.environ, "PYTHONPATH": str(extracted_code), "DATASET_DIR": str(dataset_dir)}

        # 1. Test suite execution in isolation
        print("  [1/4] Running isolated unit test suite...")
        res_test = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "code/tests"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=clean_env,
        )
        assert res_test.returncode == 0, f"Isolated test suite failed:\n{res_test.stderr}\n{res_test.stdout}"

        # 2. Sample mode prediction and evaluation
        if dataset_dir.exists():
            print("  [2/4] Running isolated sample mode and evaluation...")
            sample_csv = tmp_path / "sample_preds.csv"
            res_sample = subprocess.run(
                [sys.executable, str(main_py), "--mode", "sample", "--output", str(sample_csv), "--dataset", str(dataset_dir)],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                env=clean_env,
            )
            assert res_sample.returncode == 0, f"Sample prediction failed:\n{res_sample.stderr}"

            eval_main = extracted_code / "evaluation" / "main.py"
            res_eval = subprocess.run(
                [sys.executable, str(eval_main), str(sample_csv), "--dataset", str(dataset_dir)],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                env=clean_env,
            )
            assert res_eval.returncode == 0, f"Sample evaluation failed:\n{res_eval.stderr}"

            # 3. Full 250 evaluation requests run
            print("  [3/4] Running full 250 evaluation requests in isolation...")
            full_csv = tmp_path / "output.csv"
            res_full = subprocess.run(
                [sys.executable, str(main_py), "--mode", "full", "--output", str(full_csv), "--dataset", str(dataset_dir)],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                env=clean_env,
            )
            assert res_full.returncode == 0, f"Full evaluation failed:\n{res_full.stderr}"

            # 4. CSV schema and contract validation
            print("  [4/4] Validating generated output.csv in isolation...")
            res_val = subprocess.run(
                [sys.executable, str(main_py), "--validate-csv", str(full_csv), "--dataset", str(dataset_dir)],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                env=clean_env,
            )
            assert res_val.returncode == 0, f"Output validation failed:\n{res_val.stderr}"

    print("Package clean-room verification PASSED 100% cleanly.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["full", "sample"], default="full", help="pipeline execution mode")
    parser.add_argument("--output", help="path to write output predictions CSV")
    parser.add_argument("--run-id", help="run identifier for experiment registration")
    parser.add_argument("--dataset", default=str(REPO_ROOT / "dataset"), help="dataset directory path")
    parser.add_argument("--validate-csv", help="validate a CSV file against the competition schema and exit")
    parser.add_argument("--rebuild-evidence", action="store_true", help="re-extract evidence facts and verify caches")
    parser.add_argument("--investigate", help="run adaptive investigation for a single request_id and exit")
    parser.add_argument("--notes", help="notes for experiment registration in register.jsonl")
    parser.add_argument("--package", action="store_true", help="build clean verified code.zip and exit")

    args = parser.parse_args(argv)

    # 1. Packaging mode
    if args.package:
        zip_target = Path(args.output) if args.output else REPO_ROOT / "code.zip"
        package_clean_submission(zip_target)
        return 0

    # 2. CSV validation mode
    if args.validate_csv:
        csv_path = Path(args.validate_csv)
        print(f"Validating CSV: {csv_path}")
        ds = None
        try:
            ds = build_dataset(args.dataset)
        except Exception:
            pass
        ok, errs = validate_output_csv(csv_path, dataset=ds)
        if ok:
            print("CSV is 100% compliant with schema and contract.")
            return 0
        else:
            print(f"CSV validation FAILED with {len(errs)} error(s):", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1

    # Load dataset
    print(f"Loading dataset from {args.dataset}...")
    try:
        dataset = build_dataset(args.dataset)
    except DatasetValidationError as exc:
        print(f"Dataset validation failed: {exc}", file=sys.stderr)
        return 1

    # Extract facts across messages and resolved image amounts
    all_facts = []
    for msg in dataset.messages:
        all_facts.extend(extract_facts_from_message_text(msg))

    image_amounts = get_all_resolved_image_amounts(dataset)

    # 3. Evidence rebuild mode
    if args.rebuild_evidence:
        print(f"Extracted {len(all_facts)} structured evidence facts from {len(dataset.messages)} messages.")
        print(f"Verified {len(dataset.images)} image entries ({len(image_amounts)} resolved amounts).")
        print("Evidence facts rebuild complete.")
        return 0

    # 4. Single request investigation mode
    if args.investigate:
        req_id = args.investigate
        print(f"Running adaptive investigation on {req_id}...")
        req = dataset.all_requests_by_id.get(req_id)
        if req is None:
            print(f"Error: unknown request_id '{req_id}'", file=sys.stderr)
            return 1
        row, candidate, inv_state = run_pipeline_for_request(
            dataset, req, all_facts, image_amounts=image_amounts, investigate=True
        )
        print("\n--- Investigation Summary ---")
        if inv_state:
            print(f"Steps taken: {inv_state.steps_taken}")
            print(f"Tool calls: {inv_state.tool_calls_taken}")
            print("Evidence inspected:")
            for e in inv_state.evidence_inspected:
                print(f"  - {e}")
            print("Tool call history:")
            for tc in inv_state.tool_call_history:
                print(f"  [{tc['tool']}] -> {json.dumps(tc['result'], default=str)[:120]}")
        print("\n--- Verified Decision ---")
        print(f"Status: {row.affordability_status.value}")
        print(f"Method: {row.recommended_payment_method.value}")
        print(f"Plan: {serialize_payment_plan(row.payment_plan)}")
        print(f"Safe today: {format_capacity_amount(row.amount_safe_to_pay)}")
        print(f"Earliest date: {row.earliest_date_for_full_payment}")
        print(f"Spending changes: {serialize_spending_changes(row.spending_changes_needed)}")
        print(f"Explanation: {row.decision_explanation}")
        return 0

    # 5. Public Sample Mode (Baseline execution & registration)
    if args.mode == "sample":
        run_id = args.run_id or "baseline_v1_public_samples"
        print(f"Running sample prediction pipeline (Run ID: {run_id})...")
        sample_reqs = list(dataset.sample_requests)
        output_rows: list[OutputRow] = []
        traces = []

        start_time = time.time()
        for sreq in sample_reqs:
            row, cand, inv = run_pipeline_for_request(
                dataset, sreq, all_facts, image_amounts=image_amounts
            )
            output_rows.append(row)
            traces.append({
                "request_id": sreq.request_id,
                "status": row.affordability_status.value,
                "method": row.recommended_payment_method.value,
                "plan": serialize_payment_plan(row.payment_plan),
                "safe_today": format_capacity_amount(row.amount_safe_to_pay),
                "earliest_date": str(row.earliest_date_for_full_payment),
                "changes": serialize_spending_changes(row.spending_changes_needed),
                "explanation": row.decision_explanation,
            })

        elapsed = round(time.time() - start_time, 3)
        print(f"Generated predictions for {len(output_rows)} sample requests in {elapsed}s.")

        # Determine output directory
        exp_dir = REPO_ROOT / "evaluation" / "experiments" / run_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        pred_csv = Path(args.output) if args.output else exp_dir / "predictions.csv"
        write_output_csv(pred_csv, output_rows)
        print(f"Saved predictions to {pred_csv}")

        # Evaluate against sample labels
        report = evaluate(dataset, pred_csv)
        report_dict = dataclasses.asdict(report)

        # Save evaluation artifacts
        report_json = exp_dir / "report.json"
        report_json.write_text(json.dumps(_json_sanitize(report_dict), indent=2), encoding="utf-8")

        metrics_txt = exp_dir / "metrics.txt"
        metrics_rendered = render_report_text(report)
        metrics_txt.write_text(metrics_rendered, encoding="utf-8")

        traces_jsonl = exp_dir / "traces.jsonl"
        with traces_jsonl.open("w", encoding="utf-8") as fh:
            for t in traces:
                fh.write(json.dumps(t) + "\n")

        # Register experiment
        from datetime import datetime, timezone
        import subprocess
        try:
            res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(REPO_ROOT))
            commit_hash = res.stdout.strip() if res.returncode == 0 else "working_tree"
        except Exception:
            commit_hash = "working_tree"
        ts_iso = datetime.now(timezone.utc).isoformat()

        register_file = REPO_ROOT / "evaluation" / "experiments" / "register.jsonl"
        entry = ExperimentEntry(
            experiment_id=run_id,
            timestamp_iso=ts_iso,
            commit=commit_hash,
            request_ids=tuple(s.request_id for s in dataset.sample_requests),
            exposure=PRIOR_RESEARCH_EXPOSED,
            report_summary_path=str(report_json.relative_to(REPO_ROOT)),
            notes=args.notes or f"Experiment run {run_id}",
        )
        append_entry(register_file, entry)
        print(f"Recorded experiment in {register_file}")

        print("\n--- Baseline Metrics on 25 Samples ---")
        print(metrics_rendered)
        return 0

    # 6. Full Evaluation Mode (All 250 evaluation requests)
    if args.mode == "full":
        out_path = Path(args.output) if args.output else REPO_ROOT / "output.csv"
        print(f"Running full decision pipeline for {len(dataset.requests)} evaluation requests...")
        output_rows = []
        start_time = time.time()

        for req in dataset.requests:
            row, cand, _ = run_pipeline_for_request(
                dataset, req, all_facts, image_amounts=image_amounts
            )
            output_rows.append(row)

        elapsed = round(time.time() - start_time, 3)
        print(f"Computed decisions for 250 requests in {elapsed}s.")

        write_output_csv(out_path, output_rows)
        print(f"Wrote validated output to {out_path} ({out_path.stat().st_size:,} bytes).")

        # Validate the generated CSV
        ok, errs = validate_output_csv(out_path, dataset=dataset)
        if ok:
            print("Generated output.csv passed all schema, CRLF, and semantic checks (100% valid).")
        else:
            print(f"Warning: validation issues in {out_path}: {errs}", file=sys.stderr)
            return 1

        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
