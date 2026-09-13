# Token Usage and Cost Report

## 1. Run Summary & Environment

- **Run Identifier**: `stage15_production_evaluation_replay`
- **Date / Timestamp**: `2026-09-13T12:45:00+05:30`
- **Execution Mode**: Deterministic zero-call offline replay
- **Evaluation Scope**: 250 evaluation requests (`request_01` to `request_250` from `dataset/requests.csv`)
- **Runtime Dependency**: Pure Python 3.11+ standard library (no network calls required)

---

## 2. Production Evaluation Accounting (Current Run)

| Metric | Measured Value | Notes |
| :--- | :--- | :--- |
| **Fresh API Calls** | **0** | Deterministic cash-flow simulation, recurrence, and planning core |
| **Application-Cache Hits** | **0** | No local runtime cache read needed during zero-call replay |
| **Shipped-Observation Reads** | **16** | 16 image documents in dataset read from `extraction_snapshot` (15 resolved amounts) |
| **Fresh Input Tokens** | **0** | No live prompt transmission |
| **Fresh Output Tokens** | **0** | No live model generation |
| **Reasoning Tokens (Subset)** | **0** | No reasoning tokens incurred |
| **Provider Cached-Input Tokens** | **0** | No provider-side prompt caching invoked |
| **Total Fresh Tokens** | **0** | Zero token consumption in replay |
| **API Retries** | **0** | Zero network requests |
| **Repair Attempts** | **0** | Zero schema repair attempts |
| **API Failures** | **0** | Zero failures |
| **Execution Latency** | **6.34 s** | 250 requests evaluated (~25.4 ms / request) |
| **Fresh API Cost (USD)** | **$0.0000** | Pure local deterministic execution |

---

## 3. Shipped Evidence Lineage & Historical Extraction Costs

During earlier exploratory stages (Stage 3 capability pilot and Stage 4 image audit), multimodal observations were captured from `gpt-6-astra` and stored as content-addressed observation files to ensure offline reproducibility without requiring API keys during grading:

- **Model Used**: `gpt-6-astra` (multimodal vision + text)
- **Shipped Observation Artifacts**: 38 total files in `evaluation/extraction_snapshot/observations/`
  - 16 image observation JSON files (covering `image_01` through `image_16`)
  - 22 message extraction baseline artifacts
- **Historical Token Usage & Costs**: **Unknown** (individual token accounting payloads were not retained in the hash digest manifest; labeled as Unknown per audit instructions).
- **Regeneration Path**:
  To regenerate all evidence observations from scratch using a live API key:
  ```bash
  export OPENAI_API_KEY="your-api-key"
  python main.py --rebuild-evidence --dataset /path/to/dataset
  ```
