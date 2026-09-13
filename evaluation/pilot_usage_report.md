# Token Usage and Cost Report

Run: Stage 3 capability pilot + 16-image audit + 21-message pilot (pilot-f7c4f0e9961d)

## Per-model summary

| Provider | Model | Calls (fresh/cache-hit) | Input tokens | Output tokens | Reasoning tokens (subset) | Cached input tokens (subset) | Total tokens | Retries | Repairs | Cost (USD, estimate) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai | gpt-6-astra | 10/37 | 16683 | 949 | 768 | 15292 | 17632 | 0 | 0 | 0.0767 |

## Overall

- Total calls: 47 (10 fresh, 37 cache-hit)
- Total input tokens: 16683 (of which 15292 were the provider's own cached input)
- Total output tokens: 949 (of which 768 were reasoning tokens -- a SUBSET, not additional)
- Total tokens: 17632
- Total retries: 0; total repair attempts: 0
- Distinct evaluation requests served by at least one call or cache hit: 24
- Estimated total cost (USD): 0.0767 (an ESTIMATE, see pricing_version on each record)

### Pilot-only figures (denominator: 24 requests actually touched -- NOT the full 250-request evaluation set; this is a pilot, not a final run)

- Average tokens per touched request: 734.67
- Estimated cost per touched request (USD): 0.003194

## Fresh-call provenance (first 20 shown)

| purpose | evaluation_request_id | provider_response_id | latency_ms | cache_hit |
|---|---|---|---:|---|
| evidence_extraction:image_reread | request_03 | resp_0c6d5f08d834e5a1006aa56dae52f487d1b766062875f9589b | 4182.93709999125 | False |
| evidence_extraction:image_reread | request_16 | resp_01403f5bdbf597ed006aa56db1981887d19e9e2ddfbae94303 | 4259.37420000264 | False |
| evidence_extraction:image_reread | request_20 | resp_0baae1f16bbed7cf006aa56db6333887d18ebb665c26a034fa | 4051.404999991064 | False |
| evidence_extraction:image_reread | request_35 | resp_07a023ca8137a669006aa56db9e05487d1bdef152bb734f586 | 5450.817600009032 | False |
| evidence_extraction:image_reread | request_48 | resp_067a0a8c553e5d5f006aa56dbf530487d1ac70792822894c00 | 3006.208799997694 | False |
| evidence_extraction:image_reread | request_55 | resp_0b1c1f3ba9278784006aa56dc2543887d1918602f203bb6d83 | 2792.8922999999486 | False |
| evidence_extraction:image_reread | request_78 | resp_0ccdf95d89034829006aa56dc54d6087d18b1150fff9dffbb2 | 3901.534599994193 | False |
| evidence_extraction:image_reread | request_84 | resp_0b712a1c7392fb0f006aa56dc90b0487d19ad793f4a789ff0b | 3013.5451999958605 | False |
| evidence_extraction:image_reread | request_105 | resp_0f21e81c40c18fe2006aa56dcc127087d194a38cd9d77382aa | 2958.3890000067186 | False |
| evidence_extraction:image_reread | request_113 | resp_05858fb078e7d15d006aa56dcf0a5487d19626b4ef44328205 | 3616.7581000045175 | False |

## Notes

- This is a PILOT report, not the final full-dataset run required by AGENTS.md 6.5.
- Pricing per gpt-6-astra:2026-09-12:developers.openai.com (see buyorwait/config.py).
- cache_hit=True rows are re-runs served entirely from .llm_cache/ -- zero fresh tokens, zero cost.

