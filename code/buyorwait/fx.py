"""Foreign-currency conversion for cash events.

Spec-anchored (S-22, AGENTS.md 6.1): "For a foreign-currency cash event, use the
row for its settlement date and the stated `from_currency` to `to_currency`
direction." This module does exactly that lookup and nothing else -- it never
interpolates between dates, never inverts a missing direction, and never
estimates a rate that is not literally present in `exchange_rates.csv`.

`exchange_rates.csv` is directional with no inverse rows for most pairs
(evaluation/inventory.md S7): USD->INR, USD->IDR, USD->EUR, EUR->USD, EUR->ZAR
are the only five directed pairs that exist. There is no INR->USD row, for
example. Attempting to invert a missing pair would be inventing a rate the
dataset does not supply, which S-20 forbids, so a missing lookup raises.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Mapping

from .schemas import Currency, ExchangeRate

FxKey = tuple[date, Currency, Currency]


class FxRateUnavailable(LookupError):
    """Raised when no exchange-rate row exists for the exact
    (rate_date, from_currency, to_currency) triple requested. Never silently
    substituted with a nearby date or an inverted pair by this function --
    callers needing a fallback policy (e.g. U-FX-1's "latest rate on or before
    the projected date" for a not-yet-realized future credit) must apply that
    policy explicitly and are expected to say so in their own docstring."""


def build_fx_index(rates: tuple[ExchangeRate, ...]) -> Mapping[FxKey, Decimal]:
    """Build the (rate_date, from_currency, to_currency) -> rate lookup table
    used by `convert`. Raises if the same key appears twice with different
    rates (an ambiguous source file), and preserves the row's presence even
    when it repeats with the SAME rate (that is a harmless duplicate, not
    ambiguous)."""
    index: dict[FxKey, Decimal] = {}
    for r in rates:
        key = (r.rate_date, r.from_currency, r.to_currency)
        if key in index and index[key] != r.rate:
            raise ValueError(
                f"conflicting exchange rate for {key}: {index[key]} vs {r.rate}"
            )
        index[key] = r.rate
    return index


def convert(
    amount: Decimal,
    *,
    from_currency: Currency,
    to_currency: Currency,
    on_date: date,
    fx_index: Mapping[FxKey, Decimal],
) -> Decimal:
    """Convert `amount` from `from_currency` to `to_currency` using the exact
    rate row for `on_date`. Returns `amount` unchanged (no lookup performed)
    when the two currencies are identical, since that is not a "foreign
    currency event" at all.
    """
    if from_currency == to_currency:
        return amount
    key = (on_date, from_currency, to_currency)
    rate = fx_index.get(key)
    if rate is None:
        raise FxRateUnavailable(
            f"no exchange rate for {from_currency}->{to_currency} on {on_date.isoformat()}"
        )
    return amount * rate
