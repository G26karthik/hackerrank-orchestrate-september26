import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Tests for code/evaluation/experiment_register.py."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluation.experiment_register import (
    INDEPENDENT_SYNTHETIC,
    PRIOR_RESEARCH_EXPOSED,
    ExperimentRegisterError,
    append_entry,
    read_entries,
)
from evaluation.schemas import ExperimentEntry


def _entry(**overrides) -> ExperimentEntry:
    defaults = dict(
        experiment_id="exp-001",
        timestamp_iso="2026-09-12T20:00:00+05:30",
        commit="963ad7e",
        request_ids=("request_01",),
        exposure=PRIOR_RESEARCH_EXPOSED,
        report_summary_path=None,
        notes="test",
    )
    defaults.update(overrides)
    return ExperimentEntry(**defaults)


class AppendAndReadTests(unittest.TestCase):
    def test_round_trip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "experiments.jsonl"
            append_entry(path, _entry())
            append_entry(path, _entry(experiment_id="exp-002", request_ids=("synthetic_fix_01",), exposure=INDEPENDENT_SYNTHETIC))
            entries = read_entries(path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].experiment_id, "exp-001")
        self.assertEqual(entries[1].exposure, INDEPENDENT_SYNTHETIC)

    def test_missing_file_reads_as_empty(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "does_not_exist.jsonl"
            self.assertEqual(read_entries(path), ())

    def test_append_never_truncates_prior_entries(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "experiments.jsonl"
            for i in range(5):
                append_entry(path, _entry(experiment_id=f"exp-{i}"))
            self.assertEqual(len(read_entries(path)), 5)


class ExposureEnforcementTests(unittest.TestCase):
    def test_public_sample_id_must_be_tagged_prior_research_exposed(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "experiments.jsonl"
            with self.assertRaises(ExperimentRegisterError):
                append_entry(path, _entry(request_ids=("request_01",), exposure=INDEPENDENT_SYNTHETIC))

    def test_synthetic_only_entry_accepts_independent_synthetic(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "experiments.jsonl"
            append_entry(path, _entry(request_ids=("synthetic_fix_01",), exposure=INDEPENDENT_SYNTHETIC))
            self.assertEqual(len(read_entries(path)), 1)

    def test_invalid_exposure_value_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "experiments.jsonl"
            with self.assertRaises(ExperimentRegisterError):
                append_entry(path, _entry(request_ids=("synthetic_fix_01",), exposure="made_up"))


if __name__ == "__main__":
    unittest.main()
