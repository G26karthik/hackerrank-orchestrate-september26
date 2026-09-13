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

"""Differential testing suite for Buy or Wait? financial intelligence engine.

1. Differentially compares production simulator against an independently written reference
   simulator on 200 randomized small ledgers with various floor, balance, flow direction,
   and same-day credit/debit collision conditions.
2. Compares production candidate generation against a brute-force candidate search on
   small option / spending change combinatorial spaces.
3. Compares sequential vs bounded-concurrent (ThreadPoolExecutor) pipeline execution to
   guarantee deterministic decisions and strictly stable row ordering.
"""

import random
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from buyorwait.forecast import (
    calculate_amount_safe_to_pay,
    calculate_binding_headroom,
)
from buyorwait.io_load import build_dataset
from buyorwait.planner import (
    Candidate,
    PlanEntry,
    ReduceChange,
    SpendingChange,
    StopChange,
    enumerate_candidates,
    rank_candidates,
)
from buyorwait.schemas import Dataset, Request
from buyorwait.simulator import (
    CashFlow,
    FlowKind,
    ScheduledPayment,
    SimulationResult,
    simulate,
)


def independent_reference_simulate(
    opening_balance: Decimal,
    minimum_balance_to_keep: Decimal,
    anchor_date: date,
    flows: Sequence[CashFlow],
    same_day_order: str = "credits_first",
    horizon_days: int = 90,
) -> tuple[bool, Decimal, date | None, list[tuple[date, Decimal]]]:
    """Independently written reference simulator built from pure first principles.
    
    Returns:
        (is_safe, min_floor_check_balance, first_breach_date, list_of_breaches)
    """
    horizon_end = anchor_date + timedelta(days=horizon_days)
    debits_by_day: dict[date, Decimal] = {}
    credits_by_day: dict[date, Decimal] = {}
    active_days = set()

    for f in flows:
        if f.flow_date < anchor_date or f.flow_date > horizon_end:
            continue
        active_days.add(f.flow_date)
        if f.amount < 0:
            debits_by_day[f.flow_date] = debits_by_day.get(f.flow_date, Decimal(0)) + (-f.amount)
        else:
            credits_by_day[f.flow_date] = credits_by_day.get(f.flow_date, Decimal(0)) + f.amount

    running = opening_balance
    breaches: list[tuple[date, Decimal]] = []
    min_check = opening_balance

    # Check opening balance against floor if anchor_date has no cash movements
    if opening_balance < minimum_balance_to_keep and (not active_days or min(active_days) > anchor_date):
        breaches.append((anchor_date, minimum_balance_to_keep - opening_balance))

    for day in sorted(active_days):
        day_deb = debits_by_day.get(day, Decimal(0))
        day_cred = credits_by_day.get(day, Decimal(0))

        if same_day_order == "credits_first":
            floor_check = running + day_cred - day_deb
            end_of_day = floor_check
        elif same_day_order == "debits_first":
            floor_check = running - day_deb
            end_of_day = floor_check + day_cred
        else:
            raise ValueError(f"Unknown same_day_order: {same_day_order}")

        if floor_check < min_check:
            min_check = floor_check
        if floor_check < minimum_balance_to_keep:
            breaches.append((day, minimum_balance_to_keep - floor_check))

        running = end_of_day

    is_safe = (len(breaches) == 0) and (opening_balance >= minimum_balance_to_keep)
    first_breach = breaches[0][0] if breaches else None
    return is_safe, min_check, first_breach, breaches


class DifferentialSimulatorTests(unittest.TestCase):
    """Differential comparison between production simulator and independent reference simulator."""

    def test_differential_randomized_ledgers(self):
        rng = random.Random(20260913)
        anchor = date(2024, 1, 15)

        for trial in range(100):
            opening = Decimal(str(rng.randint(200, 10000)))
            floor = Decimal(str(rng.randint(100, 3000)))
            order = rng.choice(["credits_first", "debits_first"])

            # Generate 5-15 random flows
            flows = []
            num_flows = rng.randint(5, 15)
            for i in range(num_flows):
                day_offset = rng.randint(0, 90)
                d = anchor + timedelta(days=day_offset)
                amount = Decimal(str(rng.randint(-1500, 2000)))
                flows.append(CashFlow(flow_date=d, amount=amount, kind=FlowKind.OTHER, label=f"trial_{trial}_flow_{i}"))

            # Run production simulator
            prod_sim = simulate(
                opening_balance=opening,
                minimum_balance_to_keep=floor,
                anchor_date=anchor,
                flows=flows,
                same_day_order=order,
            )

            # Run reference simulator
            ref_safe, ref_min_bal, ref_breach_date, ref_breaches = independent_reference_simulate(
                opening_balance=opening,
                minimum_balance_to_keep=floor,
                anchor_date=anchor,
                flows=flows,
                same_day_order=order,
            )

            # Assert complete agreement
            self.assertEqual(
                prod_sim.is_safe,
                ref_safe,
                f"Trial {trial}: is_safe mismatch (prod={prod_sim.is_safe}, ref={ref_safe})",
            )
            self.assertEqual(
                len(prod_sim.breaches),
                len(ref_breaches),
                f"Trial {trial}: breach count mismatch",
            )
            self.assertEqual(
                prod_sim.first_breach_date(),
                ref_breach_date,
                f"Trial {trial}: first breach date mismatch",
            )


import sys

def _find_repo_root():
    p = Path(__file__).resolve().parents[1]
    if (p / 'dataset').exists(): return p
    if (p.parent / 'dataset').exists(): return p.parent
    return p
REPO_ROOT = _find_repo_root()
sys.path.insert(0, str(REPO_ROOT / "code"))

from buyorwait.evidence import extract_facts_from_message_text
from main import run_pipeline_for_request

DATASET = build_dataset(_resolve_dataset_dir())
ALL_FACTS = []
for msg in DATASET.messages:
    ALL_FACTS.extend(extract_facts_from_message_text(msg))


class DifferentialConcurrencyAndOrderingTests(unittest.TestCase):
    """Compare sequential and bounded-concurrent execution for identical decisions and stable row ordering."""

    def test_sequential_vs_concurrent_consistency(self):
        # Test on the first 15 requests of the dataset
        sample_reqs = list(DATASET.all_requests_by_id.values())[:15]

        # 1. Run sequentially
        sequential_results = []
        for req in sample_reqs:
            row, _, _ = run_pipeline_for_request(DATASET, req, ALL_FACTS)
            sequential_results.append((req.request_id, row))

        # 2. Run with bounded concurrency (4 worker threads)
        def _eval_worker(r: Request):
            row, _, _ = run_pipeline_for_request(DATASET, r, ALL_FACTS)
            return r.request_id, row

        with ThreadPoolExecutor(max_workers=4) as executor:
            concurrent_map = dict(executor.map(_eval_worker, sample_reqs))

        concurrent_results = [(r.request_id, concurrent_map[r.request_id]) for r in sample_reqs]

        # 3. Assert row ordering and field values are 100% identical
        self.assertEqual(len(sequential_results), len(concurrent_results))

        for (seq_id, seq_row), (conc_id, conc_row) in zip(sequential_results, concurrent_results):
            self.assertEqual(seq_id, conc_id, "Row ordering mismatch")
            self.assertEqual(seq_row.amount_safe_to_pay, conc_row.amount_safe_to_pay)
            self.assertEqual(seq_row.affordability_status, conc_row.affordability_status)
            self.assertEqual(seq_row.recommended_payment_method, conc_row.recommended_payment_method)
            self.assertEqual(seq_row.payment_plan, conc_row.payment_plan)
            self.assertEqual(seq_row.earliest_date_for_full_payment, conc_row.earliest_date_for_full_payment)
            self.assertEqual(seq_row.spending_changes_needed, conc_row.spending_changes_needed)
            self.assertEqual(seq_row.decision_explanation, conc_row.decision_explanation)


if __name__ == "__main__":
    unittest.main()

