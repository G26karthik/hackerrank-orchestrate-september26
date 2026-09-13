"""Environment and secret loading.

Secrets come from environment variables only (AGENTS.md 6.4, problem_statement.md
"Requirements", evaluation/workflow.md rule 10). `.env` at the repository root is
never read directly by any human-facing tool in this project's development
process, and this module never logs, prints, or writes the value it loads
anywhere -- not to `log.txt`, not to `evaluation/usage_report.md`, not to any
exception message. `get_openai_api_key()` returns the raw string or None; every
caller is expected to pass it straight to an SDK client and never format it into
a message.

No third-party `.env` loader is added as a dependency (python-dotenv is not
installed in this environment, and adding it for four lines of parsing would
violate the "small dependency set" instruction). `_load_dotenv_into_environ`
below is a deliberately minimal, stdlib-only parser: `KEY=VALUE` lines, optional
surrounding quotes, `#`-prefixed comment lines and blank lines skipped. It never
overrides a variable already present in `os.environ`, so an operator's real
shell environment always wins over the file.
"""

from __future__ import annotations

import os
from pathlib import Path

_DOTENV_LOADED = False


def _repo_root() -> Path:
    # This file lives at <repo_root>/code/buyorwait/config.py.
    return Path(__file__).resolve().parents[2]


def _load_dotenv_into_environ(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def ensure_dotenv_loaded() -> None:
    """Idempotently load `<repo_root>/.env` into `os.environ`, if present."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _load_dotenv_into_environ(_repo_root() / ".env")
    _DOTENV_LOADED = True


def get_openai_api_key() -> str | None:
    """Return `OPENAI_API_KEY` from the environment (loading `.env` first if
    it hasn't been loaded yet). Returns None when unset -- callers that need
    the key are expected to fail with a clear, actionable message rather than
    proceed with an empty string."""
    ensure_dotenv_loaded()
    return os.environ.get("OPENAI_API_KEY") or None


# ---------------------------------------------------------------------------
# Model configuration -- Stage 3.
#
# `gpt-6-astra` was NOT assumed from documentation. It was independently
# verified against this account, live, on 2026-09-12:
#   - `client.models.list()` includes it (130 models total on this account).
#   - `client.responses.create(model="gpt-6-astra", ...)` succeeds for text,
#     image input, structured outputs (strict JSON schema), and a full
#     function-call round trip -- every one exercised with a real call.
#   - `reasoning={"effort": ...}` accepts all five documented levels (low,
#     medium, high, xhigh, max); `high` visibly spent reasoning tokens on a
#     trivial arithmetic prompt where `low`/`medium` did not, which is
#     real differentiated behavior, not merely an accepted-but-ignored param.
#   - `temperature` is REJECTED for this model ("not supported with this
#     model", a 400 BadRequestError) and `seed` is not even a valid keyword
#     argument on `responses.create()` in this SDK -- there is no
#     determinism-via-parameter available at all; this is recorded, not
#     assumed, and is why nothing in this project treats repeated extraction
#     as guaranteed byte-identical (see U-LLM-DETERMINISM-1 in assumptions.md).
#   - Pricing ($10 / $1 cached / $50 per 1M tokens, input/cached-input/output;
#     $20/$2/$75 for the long-context tier) was read from
#     developers.openai.com/api/docs/models/gpt-6-astra and cross-checked
#     against developers.openai.com/api/docs/pricing on 2026-09-12 -- an
#     ESTIMATE basis, not a live billing API (OpenAI does not expose one to
#     this SDK), labeled with PRICING_VERSION below.
#
# The installed `openai` SDK in this machine's GLOBAL site-packages (1.58.1)
# predates the Responses API entirely (`hasattr(client, "responses")` is
# False) -- verified, not assumed. Upgrading it in place broke unrelated
# tools already installed globally (crewai, instructor, litellm all pin
# incompatible ranges), so the global install was restored to 1.58.1 and an
# isolated project virtual environment (`.venv/`, gitignored) carries the
# pinned `openai==3.13.0` this project actually needs. See
# `requirements-llm.txt` and `code/README.md` for the exact setup.

RUNTIME_MODEL = "gpt-6-astra"
"""The configured quality-first runtime model. Verified live on this account
(see the block above), not merely documented. A caller MAY override this
(e.g. `LLMConfig(model=...)`) but nothing in this codebase silently
substitutes a different model on its own initiative -- an unavailable
configured model is a BLOCKED condition to surface, never a reason to
quietly downgrade."""

SUPPORTED_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max")
"""All five verified live against this account on 2026-09-12."""

DEFAULT_REASONING_EFFORT = "high"
"""Quality-first initial configuration per the Stage 3 instruction. `xhigh`
and `max` are compared on measured-difficult cases (see
evaluation/llm_capability_pilot.md) and the measured winner is what a
specific extraction call actually requests -- this default is a starting
point, not a claim that `high` is always best."""

PRICING_VERSION = "gpt-6-astra:2026-09-12:developers.openai.com"
"""Names the exact source and date this project's price table was read from,
so a usage report reader can tell which price list produced an estimate."""

PRICE_USD_PER_MILLION_INPUT_TOKENS = 10.0
PRICE_USD_PER_MILLION_CACHED_INPUT_TOKENS = 1.0
PRICE_USD_PER_MILLION_OUTPUT_TOKENS = 50.0
"""Standard-context pricing, per 1,000,000 tokens, USD. These are stored as
`float` ONLY as a literal transcription of the source page; every actual
cost computation converts to `Decimal` via `str()` immediately (see
`buyorwait/openai_client.py::estimate_cost_usd`) and never does arithmetic on
these floats directly -- money is never computed in binary float in this
project, per the standing rule from Stage 2."""
