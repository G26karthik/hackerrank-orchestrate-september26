import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

import os
from pathlib import Path

def _resolve_dataset_dir() -> Path:
    if 'DATASET_DIR' in os.environ and Path(os.environ['DATASET_DIR']).exists():
        return Path(os.environ['DATASET_DIR'])
    for cand in [Path('dataset'), Path(__file__).resolve().parents[1] / 'dataset', Path(__file__).resolve().parents[2] / 'dataset']:
        if cand.exists() and (cand / 'requests.csv').exists():
            return cand
    return Path('dataset')

"""Tests for code/evaluation/metrics.py, using the real dataset (loaded once,
read-only) as the source of a known-good "perfect candidate" plus deliberate
corruptions of it. This is the evaluator testing itself against ground truth
it can fully control -- exactly the "trustworthy way to detect wrong answers"
this stage exists to build.
"""

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from buyorwait.io_load import build_dataset
from buyorwait.writer import REQUIRED_COLUMNS
from evaluation.metrics import StrictJoinError, evaluate

def _find_repo_root():
    p = Path(__file__).resolve().parents[1]
    if (p / 'dataset').exists(): return p
    if (p.parent / 'dataset').exists(): return p.parent
    return p
REPO_ROOT = _find_repo_root()
DATASET = build_dataset(_resolve_dataset_dir())  # loaded once; module-level, read-only


def _perfect_rows() -> list[dict[str, str]]:
    rows = []
    for rid, label in DATASET.sample_labels_by_id.items():
        rows.append({col: label.raw[col] if col != "request_id" else rid for col in REQUIRED_COLUMNS})
    return rows


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REQUIRED_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


class PerfectCandidateTests(unittest.TestCase):
    def test_perfect_candidate_scores_100_percent_on_every_field(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, _perfect_rows())
            report = evaluate(DATASET, path)
        self.assertEqual(report.n_rows, 25)
        self.assertEqual(report.amount_safe_to_pay.exact_matches, 25)
        self.assertEqual(report.affordability_status.exact_matches, 25)
        self.assertEqual(report.recommended_payment_method.exact_matches, 25)
        self.assertEqual(report.payment_plan.exact_matches, 25)
        self.assertEqual(report.payment_plan.parse_failures, ())
        self.assertEqual(report.earliest_date_for_full_payment.exact_matches, 25)
        self.assertEqual(report.spending_changes_needed.exact_set_matches, 25)
        self.assertEqual(report.spending_changes_needed.well_formed_count, 25)
        self.assertEqual(report.decision_explanation.grounded_count, 25)
        self.assertEqual(report.decision_explanation.empty_count, 0)


class WrongValueDetectionTests(unittest.TestCase):
    def test_wrong_amount_is_caught_and_isolated_to_its_currency(self):
        rows = _perfect_rows()
        for r in rows:
            if r["request_id"] == "request_05":  # ZAR user (evaluation/inventory.md sample)
                r["amount_safe_to_pay"] = "99999"
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, rows)
            report = evaluate(DATASET, path)
        self.assertEqual(report.amount_safe_to_pay.exact_matches, 24)
        zar_errors = report.amount_safe_to_pay.signed_errors_by_currency["ZAR"]
        self.assertTrue(any(e != 0 for e in zar_errors))
        # other currencies must be completely unaffected by a ZAR-row error
        for currency, errors in report.amount_safe_to_pay.signed_errors_by_currency.items():
            if currency != "ZAR":
                self.assertTrue(all(e == 0 for e in errors))

    def test_wrong_status_is_caught(self):
        rows = _perfect_rows()
        for r in rows:
            if r["request_id"] == "request_01":
                r["affordability_status"] = "not_affordable"  # was affordable_now
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, rows)
            report = evaluate(DATASET, path)
        self.assertEqual(report.affordability_status.exact_matches, 24)
        self.assertEqual(report.affordability_status.confusion[("affordable_now", "not_affordable")], 1)

    def test_malformed_payment_plan_is_a_parse_failure_not_silently_skipped(self):
        rows = _perfect_rows()
        for r in rows:
            if r["request_id"] == "request_07":
                r["payment_plan"] = "garbage-not-a-plan"
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, rows)
            report = evaluate(DATASET, path)
        self.assertIn("request_07", report.payment_plan.parse_failures)
        self.assertEqual(report.payment_plan.exact_matches, 24)

    def test_swapped_earliest_date_is_caught_and_named(self):
        rows = _perfect_rows()
        for r in rows:
            if r["request_id"] == "request_09":  # affordable_now -> earliest == request_date
                r["earliest_date_for_full_payment"] = "2099-01-01"
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, rows)
            report = evaluate(DATASET, path)
        self.assertEqual(report.earliest_date_for_full_payment.exact_matches, 24)
        mismatch_ids = [m[0] for m in report.earliest_date_for_full_payment.mismatches]
        self.assertIn("request_09", mismatch_ids)

    def test_spending_change_targeting_a_protected_category_is_flagged_as_a_rule_violation(self):
        # request_06's real spending change is stop:event_476 (streaming,
        # stoppable, not protected -- see evaluation/inventory.md O-29).
        # Retargeting it at a protected/fixed rent event must be flagged as
        # NOT well-formed even though it still needs a real event_id to parse.
        rows = _perfect_rows()
        # user_06's protected categories include rent (evaluation/inventory.md
        # sample request_06 profile: protect=rent|insurance|transport).
        rent_event_id = next(
            e.event_id
            for e in DATASET.events_by_user["user_06"]
            if e.category.value == "rent"
        )
        for r in rows:
            if r["request_id"] == "request_06":
                r["spending_changes_needed"] = f"stop:{rent_event_id}"
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, rows)
            report = evaluate(DATASET, path)
        self.assertLess(report.spending_changes_needed.well_formed_count, 25)
        violation_ids = [v[0] for v in report.spending_changes_needed.rule_violations]
        self.assertIn("request_06", violation_ids)


class JoinFailureTests(unittest.TestCase):
    def test_missing_row_raises_and_names_the_id(self):
        rows = [r for r in _perfect_rows() if r["request_id"] != "request_10"]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, rows)
            with self.assertRaises(StrictJoinError) as ctx:
                evaluate(DATASET, path)
        self.assertIn("request_10", ctx.exception.join_error.missing_in_candidate)

    def test_duplicate_row_raises_and_names_the_id(self):
        rows = _perfect_rows()
        rows.append(dict(rows[0]))  # duplicate request_01
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, rows)
            with self.assertRaises(StrictJoinError) as ctx:
                evaluate(DATASET, path)
        self.assertIn(rows[0]["request_id"], ctx.exception.join_error.duplicate_in_candidate)

    def test_extra_row_not_in_labels_raises(self):
        rows = _perfect_rows()
        extra = dict(rows[0])
        extra["request_id"] = "request_999"
        rows.append(extra)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, rows)
            with self.assertRaises(StrictJoinError) as ctx:
                evaluate(DATASET, path)
        self.assertIn("request_999", ctx.exception.join_error.extra_in_candidate)

    def test_never_scores_a_partial_overlap(self):
        # Dropping 5 of the 25 rows must raise, never silently score the
        # remaining 20 -- "Never shrink a denominator to the shorter file."
        rows = _perfect_rows()[:20]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, rows)
            with self.assertRaises(StrictJoinError) as ctx:
                evaluate(DATASET, path)
        self.assertEqual(len(ctx.exception.join_error.missing_in_candidate), 5)


class NoAggregateScoreTests(unittest.TestCase):
    def test_evaluation_report_has_no_score_field(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, _perfect_rows())
            report = evaluate(DATASET, path)
        field_names = {f for f in dir(report) if not f.startswith("_")}
        for forbidden in ("score", "overall_score", "total_score", "grade"):
            self.assertNotIn(forbidden, field_names)

    def test_currency_errors_are_never_pooled_across_currencies(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            _write(path, _perfect_rows())
            report = evaluate(DATASET, path)
        # at least two distinct currencies appear among the 25 samples
        # (evaluation/inventory.md: EUR, IDR, INR, USD, ZAR all present)
        self.assertGreaterEqual(len(report.amount_safe_to_pay.signed_errors_by_currency), 2)


class HeaderValidationTests(unittest.TestCase):
    def test_wrong_header_order_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.csv"
            wrong_order = list(REQUIRED_COLUMNS)
            wrong_order[0], wrong_order[1] = wrong_order[1], wrong_order[0]
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=wrong_order)
                w.writeheader()
            with self.assertRaises(ValueError):
                evaluate(DATASET, path)


if __name__ == "__main__":
    unittest.main()
