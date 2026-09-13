"""Token and cost accounting for LLM calls, and the `usage_report.md` writer.

Extended in Stage 3 to capture everything item 10 of the LLM-harness
instruction requires: provider response/request ids, cache lineage,
latency, retries, repair attempts, run identity, and pricing version --
without ever double-counting reasoning tokens (they are a REPORTED SUBSET of
`output_tokens` in the OpenAI Responses API's own usage object, never an
addition to it: a real captured usage payload from this stage's capability
pilot was `{'output_tokens': 17, 'output_tokens_details': {'reasoning_tokens':
10}}` -- 17 total, of which 10 were reasoning, not 27).

Price table: no price is hardcoded as a project default. `UsageRecord.cost_usd`
is supplied by the caller per record, priced from whatever `pricing_version`
was current at call time; this module only sums and formats. `pricing_version`
is a free-text label (e.g. "gpt-6-astra:2026-09-12:webfetch") so a report
reader can tell which price list produced a given estimate -- all such
figures are ESTIMATES, labeled as such, never presented as an invoice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One metered model call, or one cache hit that avoided a call.

    `evaluation_request_id` names *this project's* `request_id` (e.g.
    "request_33") when the call served one -- deliberately not called
    `request_id` alone, to avoid colliding with `provider_request_id` (the
    OpenAI `x-request-id` response header), a genuinely different id from a
    genuinely different namespace.
    """

    provider: str  # e.g. "openai"
    model: str  # e.g. "gpt-6-astra"
    purpose: str  # e.g. "evidence_extraction:image", "evidence_extraction:message", "capability_pilot"
    run_id: str  # this project's own run identifier, groups records from one invocation
    evaluation_request_id: str | None  # e.g. "request_33"; None for calls not tied to one request
    input_tokens: int
    output_tokens: int  # ALREADY INCLUDES reasoning_tokens; never add reasoning_tokens again
    reasoning_tokens: int  # informational subset of output_tokens, per the API's own usage object
    cached_tokens: int  # subset of input_tokens the provider served from ITS OWN prompt cache
    cost_usd: Decimal  # an ESTIMATE, priced per pricing_version
    pricing_version: str
    provider_response_id: str | None
    provider_request_id: str | None
    latency_ms: float | None
    retries: int
    repair_attempts: int
    cache_hit: bool  # True: this row represents OUR local extraction cache satisfying the need,
    #                   no live call was made (input/output tokens are 0, cost_usd is 0)


@dataclass(frozen=True, slots=True)
class UsageSummary:
    provider: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    cost_usd: Decimal
    cache_hits: int
    fresh_calls: int
    retries: int
    repair_attempts: int


class UsageLedger:
    """Accumulates `UsageRecord`s and renders both a structured summary and
    the `evaluation/usage_report.md` deliverable text (AGENTS.md 6.5 /
    problem_statement.md "Token Usage and Cost Analysis"): providers and
    model names, call counts, input/output/total tokens, average tokens per
    evaluation request, and estimated total and per-request cost, with
    per-model AND overall totals when more than one model is used.

    `denominator_n` (default None) is the divisor used for "average tokens
    per request" / "cost per request" -- pass the ACTUAL final evaluation
    request count (normally 250) for a final run's report; leave it None for
    a pilot report, which instead reports totals only (there is no fixed
    "per request" denominator for an exploratory pilot that was never meant
    to cover all 250 requests).
    """

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []

    def record(self, usage: UsageRecord) -> None:
        self._records.append(usage)

    @property
    def records(self) -> tuple[UsageRecord, ...]:
        return tuple(self._records)

    def _fresh(self) -> list[UsageRecord]:
        return [r for r in self._records if not r.cache_hit]

    def by_model(self) -> tuple[UsageSummary, ...]:
        groups: dict[tuple[str, str], list[UsageRecord]] = {}
        for r in self._records:
            groups.setdefault((r.provider, r.model), []).append(r)
        out = []
        for (provider, model), records in sorted(groups.items()):
            input_tokens = sum(r.input_tokens for r in records)
            output_tokens = sum(r.output_tokens for r in records)
            out.append(
                UsageSummary(
                    provider=provider,
                    model=model,
                    calls=len(records),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    reasoning_tokens=sum(r.reasoning_tokens for r in records),
                    cached_tokens=sum(r.cached_tokens for r in records),
                    cost_usd=sum((r.cost_usd for r in records), Decimal(0)),
                    cache_hits=sum(1 for r in records if r.cache_hit),
                    fresh_calls=sum(1 for r in records if not r.cache_hit),
                    retries=sum(r.retries for r in records),
                    repair_attempts=sum(r.repair_attempts for r in records),
                )
            )
        return tuple(out)

    def overall(self) -> UsageSummary:
        records = self._records
        input_tokens = sum(r.input_tokens for r in records)
        output_tokens = sum(r.output_tokens for r in records)
        return UsageSummary(
            provider="ALL",
            model="ALL",
            calls=len(records),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            reasoning_tokens=sum(r.reasoning_tokens for r in records),
            cached_tokens=sum(r.cached_tokens for r in records),
            cost_usd=sum((r.cost_usd for r in records), Decimal(0)),
            cache_hits=sum(1 for r in records if r.cache_hit),
            fresh_calls=sum(1 for r in records if not r.cache_hit),
            retries=sum(r.retries for r in records),
            repair_attempts=sum(r.repair_attempts for r in records),
        )

    def distinct_requests_served(self) -> int:
        return len({r.evaluation_request_id for r in self._records if r.evaluation_request_id is not None})

    def render_markdown(
        self,
        *,
        run_label: str = "development pilot",
        output_csv_path: str | None = None,
        output_csv_sha256: str | None = None,
        denominator_n: int | None = None,
        denominator_label: str = "distinct evaluation requests served",
        notes: tuple[str, ...] = (),
    ) -> str:
        """Render the `evaluation/usage_report.md` deliverable text.

        `output_csv_path`/`output_csv_sha256` identify the exact run and
        output.csv this report describes (required for the FINAL report;
        omitted for a pilot, which produces no output.csv). `denominator_n`
        is the actual final request count (normally 250) for a final run's
        per-request averages -- never the number of calls made, and never
        silently substituted with `distinct_requests_served()` when the two
        differ (e.g. because some requests were served entirely from cache
        with zero fresh calls, or some calls served no single request).
        """
        lines = ["# Token Usage and Cost Report", "", f"Run: {run_label}"]
        if output_csv_path is not None:
            lines.append(f"output.csv: `{output_csv_path}`")
        if output_csv_sha256 is not None:
            lines.append(f"output.csv sha256: `{output_csv_sha256}`")
        lines.append("")

        if not self._records:
            lines.append(
                "No model calls were made in the run that produced this report. "
                "The deterministic core (loader, simulator, evaluator) requires no "
                "LLM call; this file will be regenerated with real figures once the "
                "evidence-extraction stage runs against the full dataset."
            )
            return "\n".join(lines) + "\n"

        overall = self.overall()
        n_requests = self.distinct_requests_served()
        fresh = self._fresh()

        lines.append("## Per-model summary")
        lines.append("")
        lines.append(
            "| Provider | Model | Calls (fresh/cache-hit) | Input tokens | Output tokens "
            "| Reasoning tokens (subset) | Cached input tokens (subset) | Total tokens | "
            "Retries | Repairs | Cost (USD, estimate) |"
        )
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for s in self.by_model():
            lines.append(
                f"| {s.provider} | {s.model} | {s.fresh_calls}/{s.cache_hits} | {s.input_tokens} | "
                f"{s.output_tokens} | {s.reasoning_tokens} | {s.cached_tokens} | {s.total_tokens} | "
                f"{s.retries} | {s.repair_attempts} | {s.cost_usd:.4f} |"
            )
        lines.append("")
        lines.append("## Overall")
        lines.append("")
        lines.append(f"- Total calls: {overall.calls} ({overall.fresh_calls} fresh, {overall.cache_hits} cache-hit)")
        lines.append(f"- Total input tokens: {overall.input_tokens} (of which {overall.cached_tokens} were the provider's own cached input)")
        lines.append(f"- Total output tokens: {overall.output_tokens} (of which {overall.reasoning_tokens} were reasoning tokens -- a SUBSET, not additional)")
        lines.append(f"- Total tokens: {overall.total_tokens}")
        lines.append(f"- Total retries: {overall.retries}; total repair attempts: {overall.repair_attempts}")
        lines.append(f"- Distinct evaluation requests served by at least one call or cache hit: {n_requests}")
        lines.append(f"- Estimated total cost (USD): {overall.cost_usd:.4f} (an ESTIMATE, see pricing_version on each record)")

        if denominator_n is not None:
            lines.append("")
            lines.append(f"### Per-request figures (denominator: {denominator_n} {denominator_label})")
            lines.append("")
            lines.append(f"- Average tokens per request: {overall.total_tokens / denominator_n:.2f}")
            lines.append(f"- Estimated cost per request (USD): {(overall.cost_usd / denominator_n):.6f}")
        elif n_requests:
            lines.append("")
            lines.append(
                f"### Pilot-only figures (denominator: {n_requests} requests actually touched -- "
                "NOT the full 250-request evaluation set; this is a pilot, not a final run)"
            )
            lines.append("")
            lines.append(f"- Average tokens per touched request: {overall.total_tokens / n_requests:.2f}")
            lines.append(f"- Estimated cost per touched request (USD): {(overall.cost_usd / n_requests):.6f}")

        if fresh:
            lines.append("")
            lines.append("## Fresh-call provenance (first 20 shown)")
            lines.append("")
            lines.append("| purpose | evaluation_request_id | provider_response_id | latency_ms | cache_hit |")
            lines.append("|---|---|---|---:|---|")
            for r in fresh[:20]:
                lines.append(
                    f"| {r.purpose} | {r.evaluation_request_id or ''} | {r.provider_response_id or ''} | "
                    f"{r.latency_ms if r.latency_ms is not None else ''} | {r.cache_hit} |"
                )
            if len(fresh) > 20:
                lines.append(f"| … {len(fresh) - 20} more fresh calls not shown … | | | | |")

        if notes:
            lines.append("")
            lines.append("## Notes")
            lines.append("")
            for n in notes:
                lines.append(f"- {n}")

        lines.append("")
        return "\n".join(lines) + "\n"
