import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Tests for code/buyorwait/metering.py."""

import unittest
from decimal import Decimal

from buyorwait.metering import UsageLedger, UsageRecord


def _rec(**overrides) -> UsageRecord:
    defaults = dict(
        provider="openai",
        model="gpt-6-astra",
        purpose="evidence_extraction:image",
        run_id="run-001",
        evaluation_request_id="request_33",
        input_tokens=1000,
        output_tokens=200,
        reasoning_tokens=0,
        cached_tokens=0,
        cost_usd=Decimal("0.01"),
        pricing_version="gpt-6-astra:2026-09-12",
        provider_response_id="resp_abc",
        provider_request_id="req_abc",
        latency_ms=1200.0,
        retries=0,
        repair_attempts=0,
        cache_hit=False,
    )
    defaults.update(overrides)
    return UsageRecord(**defaults)


class UsageLedgerTests(unittest.TestCase):
    def test_empty_ledger_reports_no_calls_explicitly(self):
        ledger = UsageLedger()
        report = ledger.render_markdown()
        self.assertIn("No model calls were made", report)

    def test_single_model_totals(self):
        ledger = UsageLedger()
        ledger.record(_rec(evaluation_request_id="request_33", input_tokens=1000, output_tokens=200, cost_usd=Decimal("0.01")))
        ledger.record(_rec(evaluation_request_id="request_35", input_tokens=1500, output_tokens=300, cost_usd=Decimal("0.015")))
        overall = ledger.overall()
        self.assertEqual(overall.calls, 2)
        self.assertEqual(overall.input_tokens, 2500)
        self.assertEqual(overall.output_tokens, 500)
        self.assertEqual(overall.total_tokens, 3000)
        self.assertEqual(overall.cost_usd, Decimal("0.025"))
        self.assertEqual(ledger.distinct_requests_served(), 2)

    def test_per_model_and_overall_both_present_with_two_models(self):
        ledger = UsageLedger()
        ledger.record(_rec(model="model-a", evaluation_request_id="request_1", input_tokens=100, output_tokens=10, cost_usd=Decimal("0.001")))
        ledger.record(_rec(model="model-b", evaluation_request_id="request_1", input_tokens=200, output_tokens=20, cost_usd=Decimal("0.002")))
        by_model = ledger.by_model()
        self.assertEqual(len(by_model), 2)
        overall = ledger.overall()
        self.assertEqual(overall.total_tokens, sum(s.total_tokens for s in by_model))
        self.assertEqual(overall.cost_usd, sum((s.cost_usd for s in by_model), Decimal(0)))
        report = ledger.render_markdown()
        self.assertIn("model-a", report)
        self.assertIn("model-b", report)
        self.assertIn("Overall", report)

    def test_reasoning_tokens_never_added_to_total_a_second_time(self):
        ledger = UsageLedger()
        # output_tokens=17 ALREADY includes the 10 reasoning tokens (real captured
        # shape from this stage's capability pilot); total must be input+output, not +reasoning again.
        ledger.record(_rec(input_tokens=20, output_tokens=17, reasoning_tokens=10, cost_usd=Decimal("0")))
        overall = ledger.overall()
        self.assertEqual(overall.total_tokens, 37)  # 20+17, NOT 20+17+10=47
        self.assertEqual(overall.reasoning_tokens, 10)

    def test_cache_hits_and_fresh_calls_counted_separately(self):
        ledger = UsageLedger()
        ledger.record(_rec(cache_hit=False, input_tokens=100, output_tokens=10, cost_usd=Decimal("0.001")))
        ledger.record(_rec(cache_hit=True, input_tokens=0, output_tokens=0, cost_usd=Decimal("0")))
        overall = ledger.overall()
        self.assertEqual(overall.fresh_calls, 1)
        self.assertEqual(overall.cache_hits, 1)
        report = ledger.render_markdown()
        self.assertIn("1 fresh, 1 cache-hit", report)

    def test_average_tokens_per_request_uses_distinct_requests_when_no_denominator_given(self):
        ledger = UsageLedger()
        ledger.record(_rec(evaluation_request_id="request_1", input_tokens=100, output_tokens=0, cost_usd=Decimal("0")))
        ledger.record(_rec(evaluation_request_id="request_1", input_tokens=50, output_tokens=0, cost_usd=Decimal("0")))
        self.assertEqual(ledger.distinct_requests_served(), 1)
        report = ledger.render_markdown()
        self.assertIn("Average tokens per touched request: 150.00", report)

    def test_explicit_denominator_used_for_final_run_report(self):
        ledger = UsageLedger()
        ledger.record(_rec(evaluation_request_id="request_1", input_tokens=100, output_tokens=0, cost_usd=Decimal("1.00")))
        report = ledger.render_markdown(denominator_n=250, output_csv_path="output.csv", output_csv_sha256="deadbeef")
        self.assertIn("denominator: 250", report)
        self.assertIn("Average tokens per request: 0.40", report)  # 100/250
        self.assertIn("output.csv", report)
        self.assertIn("deadbeef", report)

    def test_no_api_key_ever_appears_in_the_report(self):
        ledger = UsageLedger()
        ledger.record(_rec())
        report = ledger.render_markdown()
        self.assertNotIn("sk-", report)
        self.assertNotIn("OPENAI_API_KEY", report)

    def test_notes_are_rendered(self):
        ledger = UsageLedger()
        ledger.record(_rec())
        report = ledger.render_markdown(notes=("figures are estimates", "pricing per webfetch of official docs"))
        self.assertIn("figures are estimates", report)


if __name__ == "__main__":
    unittest.main()
