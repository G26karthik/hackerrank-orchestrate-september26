"""Shared Decimal helpers for money, rates, and CSV number formatting.

Every financial amount in this project is a `decimal.Decimal`, constructed only from
strings. `float` never touches a monetary value anywhere in this codebase: floats
cannot represent amounts like `0.10` exactly, and repeated conversion (parse ->
compute -> reformat) silently drifts. Decimal with string construction has none of
that behaviour and is the only type used for money, rates, and computed capacities.

Two output formatters are implemented, not one, because the 25 public samples show
two *different* conventions in the same file (evaluation/inventory.md O-30, O-29):

  * `amount_safe_to_pay` trims trailing zeros: 603.30 -> "603.3", 462.00 -> "462".
  * `payment_plan` entries and `reduce_to:<id>:<amount>` amounts always show two
    decimal places when the value is fractional, and no decimal point when the
    value is a whole number: 620.40 stays "620.40", 665950.00 becomes "665950".

No public document states either convention; both are mirrored from the samples as
U-ROUND-1 (evaluation/assumptions.md). Getting this wrong risks nothing but string
formatting -- the underlying Decimal values are exact either way.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTS = Decimal("0.01")


class DecimalParseError(ValueError):
    """Raised when a CSV cell that should hold a decimal number cannot be parsed.

    Never silently returns Decimal('0') for unparsable input -- that would be
    indistinguishable from a real zero and could hide a corrupt source file.
    """


def parse_decimal(raw: str, *, field: str = "<unknown>", context: str = "") -> Decimal:
    """Parse a CSV cell into a Decimal. Rejects blank input; use
    `parse_optional_decimal` when a blank cell is a legitimate, meaningful value
    (e.g. `financial_events.amount`, which must never be coerced to zero)."""
    text = raw.strip()
    if text == "":
        where = f" in {context}" if context else ""
        raise DecimalParseError(f"empty value for {field}{where}")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        where = f" in {context}" if context else ""
        raise DecimalParseError(f"cannot parse {field}={raw!r} as Decimal{where}") from exc


def parse_optional_decimal(raw: str, *, field: str = "<unknown>", context: str = "") -> Decimal | None:
    """Parse a CSV cell into a Decimal, or None when the cell is blank.

    A blank cell must never be silently treated as zero. `financial_events.amount`
    is blank exactly when the true amount is only recoverable from a linked image
    (problem_statement.md "When a financial event has a blank amount..."); a caller
    that received Decimal('0') instead of None could not tell the difference.
    """
    text = raw.strip()
    if text == "":
        return None
    return parse_decimal(raw, field=field, context=context)


def quantize_money(value: Decimal) -> Decimal:
    """Round to 2 decimal places using ROUND_HALF_UP.

    No public rule states a rounding mode (evaluation/assumptions.md U-ROUND-1).
    ROUND_HALF_UP is the conventional choice for money and is fixed here so every
    computed amount in this project rounds the same way exactly once, at the
    boundary where a Decimal is about to be compared or written, not repeatedly
    during intermediate arithmetic.
    """
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def format_capacity_amount(value: Decimal) -> str:
    """Format `amount_safe_to_pay` the way the public samples do: trailing zeros
    and a bare trailing point are trimmed. See evaluation/inventory.md O-30.

        603.30 -> "603.3"     433.40 -> "433.4"     462.00 -> "462"
        166.61 -> "166.61"    25256.00 -> "25256"
    """
    text = format(quantize_money(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_schedule_amount(value: Decimal) -> str:
    """Format a `payment_plan` entry or a `reduce_to:<id>:<amount>` amount the way
    the public samples do: exactly two decimals when fractional, none when whole.
    See evaluation/inventory.md O-23, O-29.

        620.40 -> "620.40"    996.60 -> "996.60"    23.50 -> "23.50"
        122500.00 -> "122500" 665950.00 -> "665950"
    """
    text = format(quantize_money(value), "f")
    if text.endswith(".00"):
        text = text[:-3]
    return text
