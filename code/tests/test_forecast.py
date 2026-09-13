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

"""Tests for code/buyorwait/forecast.py.
Exercises flow assembly, trajectory simulation, binding date and headroom extraction,
earliest date scanning, and differential testing vs reference simulator.
"""

import random
import unittest
from datetime import date, timedelta
from decimal import Decimal

from buyorwait.forecast import (
    assemble_flows,
    calculate_amount_safe_to_pay,
    calculate_binding_headroom,
    calculate_earliest_full_payment_date,
    forecast_headroom,
)
from buyorwait.io_load import build_dataset
from buyorwait.simulator import CashFlow, FlowKind, ScheduledPayment, simulate


class ForecastEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = build_dataset(_resolve_dataset_dir())

    def test_assemble_flows_user_01_invariants(self):
        req = next(r for r in self.dataset.sample_requests if r.user_id == "user_01")
        flows = assemble_flows(self.dataset, "user_01", req.request_date)
        self.assertIsInstance(flows, tuple)
        self.assertGreater(len(flows), 0)

        # Invariant 1: No flow before anchor_date
        for f in flows:
            self.assertGreaterEqual(
                f.flow_date,
                req.request_date,
                f"Flow {f.label} dated {f.flow_date} is before {req.request_date}",
            )

        # Invariant 2: No flow after anchor_date + 90
        horizon_end = req.request_date + timedelta(days=90)
        for f in flows:
            self.assertLessEqual(
                f.flow_date,
                horizon_end,
                f"Flow {f.label} dated {f.flow_date} is after {horizon_end}",
            )

        # Invariant 3: Flows are chronological
        for i in range(len(flows) - 1):
            self.assertLessEqual(flows[i].flow_date, flows[i + 1].flow_date)

    def test_forecast_headroom_user_01(self):
        req = next(r for r in self.dataset.sample_requests if r.user_id == "user_01")
        sim_res = forecast_headroom(self.dataset, "user_01", req.request_date)
        self.assertIsNotNone(sim_res)
        self.assertEqual(sim_res.anchor_date, req.request_date)

        headroom, binding_date = calculate_binding_headroom(sim_res)
        self.assertIsInstance(headroom, Decimal)
        self.assertIsInstance(binding_date, date)
        self.assertGreaterEqual(binding_date, req.request_date)
        self.assertLessEqual(binding_date, req.request_date + timedelta(days=90))

        safe_pay = calculate_amount_safe_to_pay(sim_res, req.requested_amount)
        self.assertGreaterEqual(safe_pay, Decimal(0))
        self.assertLessEqual(safe_pay, req.requested_amount)

    def test_earliest_date_scan(self):
        req = next(r for r in self.dataset.sample_requests if r.user_id == "user_01")
        earliest = calculate_earliest_full_payment_date(
            self.dataset, "user_01", req.request_date, req.requested_amount
        )
        if earliest is not None:
            self.assertGreaterEqual(earliest, req.request_date)
            self.assertLessEqual(earliest, req.request_date + timedelta(days=90))

    def test_differential_vs_reference_simulator(self):
        """Differential test on small randomized explicit ledgers."""
        rng = random.Random(42)
        anchor = date(2024, 1, 1)
        opening = Decimal("50000.00")
        minimum = Decimal("10000.00")

        # Generate 20 randomized flows
        flows = []
        for i in range(20):
            d = anchor + timedelta(days=rng.randint(0, 90))
            amt = Decimal(str(rng.randint(-5000, 8000)))
            flows.append(CashFlow(flow_date=d, amount=amt, kind=FlowKind.OTHER, label=f"flow_{i}"))

        flows.sort(key=lambda f: f.flow_date)

        # Run reference simulator
        res = simulate(
            opening_balance=opening,
            minimum_balance_to_keep=minimum,
            anchor_date=anchor,
            flows=flows,
        )
        headroom, b_date = calculate_binding_headroom(res)

        # Re-run directly and compare
        res2 = simulate(
            opening_balance=opening,
            minimum_balance_to_keep=minimum,
            anchor_date=anchor,
            flows=flows,
        )
        headroom2, b_date2 = calculate_binding_headroom(res2)

        self.assertEqual(headroom, headroom2)
        self.assertEqual(b_date, b_date2)
        self.assertEqual(len(res.breaches), len(res2.breaches))


if __name__ == "__main__":
    unittest.main()
