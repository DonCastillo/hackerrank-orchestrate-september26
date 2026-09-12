"""Single source of truth for rounding and number formatting.

Convention (derived from dataset + sample_requests.csv):
  * All money is Decimal. Every currency in the dataset carries at most 2 dp.
  * Any arithmetic that can create extra digits (FX conversion, fee maths, splitting)
    is quantized to 0.01 with ROUND_HALF_UP via `q()` immediately.
  * Output formatting differs by column:
      - amount_safe_to_pay          -> fmt_safe():  minimal digits   (17229139.2, 603.3, 462)
      - payment_plan / reduce_to    -> fmt_plan():  2 dp if fractional, else integer
                                                    (620.40, 23.50, 25256)
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
ROUNDING = ROUND_HALF_UP


def q(x: Decimal) -> Decimal:
    """Quantize to 2 dp using the project rounding mode."""
    return x.quantize(CENT, rounding=ROUNDING)


def _plain(x: Decimal) -> str:
    """Decimal -> string with no exponent notation and no trailing zeros."""
    s = format(x.normalize(), "f")
    return "0" if s in ("-0", "") else s


def fmt_safe(x: Decimal) -> str:
    """amount_safe_to_pay style: quantize to 2 dp, then drop trailing zeros."""
    return _plain(q(x))


def fmt_plan(x: Decimal) -> str:
    """payment_plan / reduce_to style: '620.40' or '25256'."""
    x = q(x)
    if x == x.to_integral_value():
        return str(int(x))
    return f"{x:.2f}"
