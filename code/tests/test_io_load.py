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

"""Tests for code/buyorwait/io_load.py.

`RealDatasetLoadTests` runs against the actual `dataset/` directory shipped
with this repository -- this is the one test file in this stage that is NOT
independent of the real data, because loading the real data correctly is
exactly what this module is for. Every other class here builds a minimal,
synthetic, hand-written dataset in a temp directory so the validation logic
itself (unique IDs, ownership, referential integrity, hash checking) is
tested independently of whether the real 25,342-row file happens to be clean.
"""

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from buyorwait.io_load import DatasetValidationError, build_dataset, verify_csv_hashes

def _find_repo_root():
    p = Path(__file__).resolve().parents[1]
    if (p / 'dataset').exists(): return p
    if (p.parent / 'dataset').exists(): return p.parent
    return p
REPO_ROOT = _find_repo_root()
DATASET_DIR = _resolve_dataset_dir()


# A minimal but complete and internally-consistent set of the 9 CSVs, small
# enough to hand-verify by eye, used as the base for every synthetic test
# below. Individual tests copy this and corrupt exactly one thing.

_PROFILES = [
    {
        "user_id": "user_01",
        "home_currency": "USD",
        "current_available_balance": "1000",
        "minimum_balance_to_keep": "100",
        "financial_priorities": "education",
        "expense_categories_to_protect": "rent",
        "expense_categories_user_is_willing_to_reduce": "dining",
        "expense_categories_user_is_willing_to_stop": "streaming",
        "payment_methods_user_will_consider": "full_payment",
        "max_installment_months": "",
    }
]

_REQUESTS = [
    {
        "request_id": "request_01",
        "user_id": "user_01",
        "request_date": "2024-01-01",
        "request_type": "purchase",
        "requested_amount": "500",
        "desired_completion_date": "2024-01-15",
        "allows_partial_payment": "false",
        "request_text": "Can I afford this?",
    }
]

_SAMPLE_REQUESTS = []  # keep empty; sample_requests.csv still needs a header

_EVENTS = [
    {
        "event_id": "event_01",
        "user_id": "user_01",
        "event_type": "expense",
        "description": "Rent",
        "category": "rent",
        "direction": "debit",
        "amount": "300",
        "currency": "USD",
        "event_date": "2023-12-01",
        "settlement_date": "2023-12-01",
        "status": "settled",
        "linked_event_id": "",
        "flexibility": "fixed",
        "minimum_allowed_amount": "",
    }
]

_OPTIONS = [
    {
        "payment_option_id": "payment_option_01",
        "request_id": "request_01",
        "payment_method": "full_payment",
        "payment_amount": "500",
        "number_of_payments": "1",
        "first_payment_date": "2024-01-01",
        "payment_frequency_days": "",
        "financing_fee": "0",
        "total_payable_amount": "500",
    }
]

_MESSAGES = []
_IMAGES = []
_FX = [
    {"rate_date": "2024-01-15", "from_currency": "USD", "to_currency": "EUR", "rate": "0.9"},
]

_FILES = {
    "financial_profiles.csv": _PROFILES,
    "requests.csv": _REQUESTS,
    "financial_events.csv": _EVENTS,
    "request_payment_options.csv": _OPTIONS,
    "messages.csv": _MESSAGES,
    "images.csv": _IMAGES,
    "exchange_rates.csv": _FX,
}

_SAMPLE_HEADER = [
    "request_id", "user_id", "request_date", "request_type", "requested_amount",
    "desired_completion_date", "allows_partial_payment", "request_text",
    "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation",
]


def _write_csv(path: Path, rows: list[dict], header: list[str] | None = None) -> None:
    fieldnames = header if header is not None else (list(rows[0].keys()) if rows else [])
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


_OUTPUT_TEMPLATE_HEADER = [
    "request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation",
]


def _write_synthetic_dataset(directory: Path, overrides: dict[str, list[dict]] | None = None) -> None:
    overrides = overrides or {}
    for name, base_rows in _FILES.items():
        rows = overrides.get(name, base_rows)
        _write_csv(directory / name, rows)
    _write_csv(directory / "sample_requests.csv", overrides.get("sample_requests.csv", _SAMPLE_REQUESTS), header=_SAMPLE_HEADER)
    # output.csv content is never parsed by the loader; only its hash is checked
    # (it is one of the 9 files in EXPECTED_CSV_HASHES), so a header-only file suffices.
    _write_csv(directory / "output.csv", [], header=_OUTPUT_TEMPLATE_HEADER)


class RealDatasetLoadTests(unittest.TestCase):
    """Confirms the loader is actually correct against the real, fully
    inventoried dataset -- not just against synthetic fixtures."""

    def test_loads_with_expected_counts_and_zero_warnings(self):
        ds = build_dataset(DATASET_DIR)
        self.assertEqual(len(ds.requests), 250)
        self.assertEqual(len(ds.sample_requests), 25)
        self.assertEqual(len(ds.sample_labels), 25)
        self.assertEqual(len(ds.profiles), 275)
        self.assertEqual(len(ds.events), 25342)
        self.assertEqual(len(ds.payment_options), 790)
        self.assertEqual(len(ds.messages), 215)
        self.assertEqual(len(ds.images), 16)
        self.assertEqual(len(ds.exchange_rates), 134)
        self.assertEqual(ds.warnings, ())

    def test_sample_labels_are_never_reachable_from_all_requests_by_id_as_a_request(self):
        ds = build_dataset(DATASET_DIR)
        # request_01 is a sample; it must be a plain Request (8 fields), and
        # its label must live ONLY in sample_labels_by_id.
        req = ds.all_requests_by_id["request_01"]
        self.assertFalse(hasattr(req, "amount_safe_to_pay"))
        label = ds.sample_labels_by_id["request_01"]
        self.assertEqual(label.request_id, "request_01")

    def test_hash_verification_passes_on_the_untouched_dataset(self):
        self.assertEqual(verify_csv_hashes(DATASET_DIR), ())


class UniqueIdValidationTests(unittest.TestCase):
    def test_duplicate_request_id_across_requests_and_samples_is_rejected(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_synthetic_dataset(
                tmp_path,
                overrides={"sample_requests.csv": [
                    {**_REQUESTS[0], **{k: "" for k in _SAMPLE_HEADER if k not in _REQUESTS[0]},
                     "amount_safe_to_pay": "1", "affordability_status": "affordable_now",
                     "recommended_payment_method": "full_payment", "payment_plan": "none",
                     "earliest_date_for_full_payment": "", "spending_changes_needed": "none",
                     "decision_explanation": "x"}
                ]},
            )
            with self.assertRaises(DatasetValidationError) as ctx:
                build_dataset(tmp_path, verify_hashes=False)
            self.assertTrue(any("duplicate request" in e for e in ctx.exception.errors))

    def test_duplicate_event_id_is_rejected(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_synthetic_dataset(tmp_path, overrides={"financial_events.csv": _EVENTS + _EVENTS})
            with self.assertRaises(DatasetValidationError) as ctx:
                build_dataset(tmp_path, verify_hashes=False)
            self.assertTrue(any("duplicate event" in e for e in ctx.exception.errors))


class ReferentialIntegrityTests(unittest.TestCase):
    def test_event_referencing_unknown_user_is_rejected(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_event = {**_EVENTS[0], "user_id": "user_99"}
            _write_synthetic_dataset(tmp_path, overrides={"financial_events.csv": [bad_event]})
            with self.assertRaises(DatasetValidationError) as ctx:
                build_dataset(tmp_path, verify_hashes=False)
            self.assertTrue(any("unknown user_id" in e for e in ctx.exception.errors))

    def test_option_referencing_unknown_request_is_rejected(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_option = {**_OPTIONS[0], "request_id": "request_99"}
            _write_synthetic_dataset(tmp_path, overrides={"request_payment_options.csv": [bad_option]})
            with self.assertRaises(DatasetValidationError) as ctx:
                build_dataset(tmp_path, verify_hashes=False)
            self.assertTrue(any("unknown request_id" in e for e in ctx.exception.errors))

    def test_message_request_owned_by_a_different_user_is_rejected(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_message = {
                "message_id": "message_01", "user_id": "user_02", "request_id": "request_01",
                "related_event_id": "", "sent_at": "2024-01-01T00:00:00Z", "source_type": "bank",
                "message_text": "hi",
            }
            profiles = _PROFILES + [{**_PROFILES[0], "user_id": "user_02"}]
            _write_synthetic_dataset(tmp_path, overrides={"messages.csv": [bad_message], "financial_profiles.csv": profiles})
            with self.assertRaises(DatasetValidationError) as ctx:
                build_dataset(tmp_path, verify_hashes=False)
            self.assertTrue(any("different user" in e for e in ctx.exception.errors))

    def test_blank_amount_event_without_an_image_is_rejected(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank_amount_event = {**_EVENTS[0], "amount": ""}
            _write_synthetic_dataset(tmp_path, overrides={"financial_events.csv": [blank_amount_event]})
            with self.assertRaises(DatasetValidationError) as ctx:
                build_dataset(tmp_path, verify_hashes=False)
            self.assertTrue(any("violates S-21" in e for e in ctx.exception.errors))

    def test_blank_amount_event_WITH_a_matching_image_is_accepted(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank_amount_event = {**_EVENTS[0], "amount": ""}
            image = {"image_id": "image_01", "user_id": "user_01", "request_id": "request_01", "related_event_id": "event_01"}
            ds_dir = tmp_path
            _write_synthetic_dataset(ds_dir, overrides={"financial_events.csv": [blank_amount_event], "images.csv": [image]})
            ds = build_dataset(ds_dir, verify_hashes=False)
            self.assertIsNone(ds.events_by_id["event_01"].amount)
            self.assertEqual(len(ds.images_by_event["event_01"]), 1)


class EnumAndFieldValidationTests(unittest.TestCase):
    def test_unrecognized_enum_value_is_rejected(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_event = {**_EVENTS[0], "status": "not_a_real_status"}
            _write_synthetic_dataset(tmp_path, overrides={"financial_events.csv": [bad_event]})
            with self.assertRaises(DatasetValidationError):
                build_dataset(tmp_path, verify_hashes=False)

    def test_non_true_false_allows_partial_payment_is_rejected(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_request = {**_REQUESTS[0], "allows_partial_payment": "yes"}
            _write_synthetic_dataset(tmp_path, overrides={"requests.csv": [bad_request]})
            with self.assertRaises(DatasetValidationError):
                build_dataset(tmp_path, verify_hashes=False)

    def test_blank_amount_field_on_requested_amount_is_rejected_not_zeroed(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_request = {**_REQUESTS[0], "requested_amount": ""}
            _write_synthetic_dataset(tmp_path, overrides={"requests.csv": [bad_request]})
            with self.assertRaises(DatasetValidationError):
                build_dataset(tmp_path, verify_hashes=False)


class SoftWarningTests(unittest.TestCase):
    def test_full_payment_option_amount_mismatch_is_a_warning_not_an_error(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mismatched_option = {**_OPTIONS[0], "payment_amount": "499", "total_payable_amount": "499"}
            _write_synthetic_dataset(tmp_path, overrides={"request_payment_options.csv": [mismatched_option]})
            ds = build_dataset(tmp_path, verify_hashes=False)  # must NOT raise
            self.assertTrue(any("full_payment amount" in w for w in ds.warnings))

    def test_options_count_outside_2_to_4_is_a_warning(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_synthetic_dataset(tmp_path, overrides={"request_payment_options.csv": _OPTIONS})  # only 1 option
            ds = build_dataset(tmp_path, verify_hashes=False)
            self.assertTrue(any("payment options" in w for w in ds.warnings))


class HashVerificationTests(unittest.TestCase):
    def test_mismatched_hash_is_reported(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_synthetic_dataset(tmp_path)
            mismatches = verify_csv_hashes(tmp_path)
            # every one of our 9 synthetic files differs from the real dataset's recorded hash
            self.assertEqual(len(mismatches), 9)

    def test_build_dataset_raises_on_hash_mismatch_when_verify_hashes_true(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_synthetic_dataset(tmp_path)
            with self.assertRaises(DatasetValidationError) as ctx:
                build_dataset(tmp_path, verify_hashes=True)
            self.assertTrue(any("source hash mismatch" in e for e in ctx.exception.errors))

    def test_build_dataset_skips_hash_check_when_disabled(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_synthetic_dataset(tmp_path)
            ds = build_dataset(tmp_path, verify_hashes=False)  # must not raise
            self.assertEqual(len(ds.requests), 1)


if __name__ == "__main__":
    unittest.main()
