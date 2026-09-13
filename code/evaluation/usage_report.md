# Token Usage and Cost Report

## 1. Run Summary & Environment

- **Run Identifier**: `stage18_production_evaluation_replay`
- **Date / Timestamp**: `2026-09-13T15:30:00+05:30`
- **Execution Mode**: Deterministic zero-call offline replay (default) with verified live option (`--live`)
- **Evaluation Scope**: Exactly 250 evaluation requests (`request_26` to `request_275` from `dataset/requests.csv`)
- **Runtime Dependency**: Pure Python 3.11+ standard library (no network calls required for replay)

---

## 2. Production Evaluation Accounting (Current Submission Run)

| Metric | Measured Value | Notes |
| :--- | :--- | :--- |
| **Fresh API Calls** | **0** | Deterministic cash-flow simulation, recurrence, and planning core |
| **Application-Cache Hits** | **0** | No local runtime cache read needed during zero-call replay |
| **Shipped-Observation Reads** | **16** | 16 image documents in dataset read from content-addressed cache (15 resolved amounts, 1 cropped/illegible document) |
| **Message Fact Extraction** | **Deterministic Regex** | Message evidence extracted deterministically via structured archetypes; no model calls during standard run |
| **Fresh Input Tokens** | **0** | No live prompt transmission |
| **Fresh Output Tokens** | **0** | No live model generation |
| **Reasoning Tokens (Subset)** | **0** | No reasoning tokens incurred |
| **Provider Cached-Input Tokens** | **0** | No provider-side prompt caching invoked |
| **Total Fresh Tokens** | **0** | Zero token consumption in replay |
| **API Retries** | **0** | Zero network requests |
| **Repair Attempts** | **0** | Zero schema repair attempts |
| **API Failures** | **0** | Zero failures |
| **Execution Latency** | **~9.2 s** | 250 requests evaluated (~37 ms / request) |
| **Fresh API Cost (USD)** | **$0.0000** | Pure local deterministic execution |
| **Average Cost / Request** | **$0.0000** | Zero cost across 250 evaluation requests |

---

## 3. Shipped Evidence Lineage & Historical Extraction Costs

During earlier exploratory stages (Stage 3 capability pilot and Stage 4 image audit), multimodal observations were captured from `gpt-6-astra` and stored as content-addressed observation files to ensure offline reproducibility without requiring API keys during grading:

- **Model Used**: `gpt-6-astra` (multimodal vision + text)
- **Shipped Observation Artifacts**: 38 total files in `evaluation/extraction_snapshot/observations/`
  - 16 image observation JSON files (covering `image_01` through `image_16`)
  - 22 message extraction baseline artifacts
- **Recovered Historical Pilot Usage (Recorded in `evaluation/pilot_usage_report.md`)**:
  - Total calls: 47 (10 fresh calls, 37 cache-hit calls)
  - Total input tokens: 16,683 (of which 15,292 were provider-cached input tokens)
  - Total output tokens: 949 (of which 768 were reasoning tokens)
  - Total tokens: 17,632
  - Fresh API Cost: $0.0767 USD
  - Evaluation requests touched during pilot: 24 requests
  - Average cost per touched request: $0.003194 USD
- **Unrecorded Pre-Pilot Historical Extraction**: Labeled **Unknown** (initial exploratory single-prompt extraction runs before structured metering was introduced).

---

## 4. Live Mode & Regeneration Paths

To execute live model extraction and adaptive investigation using OpenAI API credentials:

```bash
# 1. Live Evidence Rebuild (re-extracts images via gpt-6-astra from actual source bytes on disk)
python main.py --rebuild-evidence --live --dataset /path/to/dataset

# 2. Live Adaptive Investigation for a single request (with metered UsageLedger and tool continuity)
python main.py --investigate request_26 --live --dataset /path/to/dataset

# 3. Deterministic Replay (default, offline, zero network calls)
python main.py --mode full --output output.csv --dataset /path/to/dataset
```

