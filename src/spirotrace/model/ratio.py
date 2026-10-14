"""Parse printed ratios (FEV1/FVC, RV/TLC, FRC/TLC) to a fraction, keeping the form.

Applied only to value-like roles (:data:`spirotrace.model.vocab.VALUE_ROLES`).
The %pred of a ratio is a percent of predicted, not a ratio, and is parsed as
an ordinary number.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .vocab import RatioForm

_RATIO_RE = re.compile(r"^\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<percent>%)?\s*$")


class RatioParseError(ValueError):
    """The text is not a ratio this module can interpret."""


def parse_ratio(text: str) -> tuple[float, RatioForm]:
    """Return ``(fraction, printed_form)`` for a printed ratio.

    Rules
    -----
    - An explicit ``%`` means percent: ``"78%"`` and ``"78 %"`` give 0.78.
    - Without ``%``, magnitude decides: a number above 1 and at most 100 is a
      percent (``"78"``, ``"78.0"``, ``"100"`` give 0.78, 0.78, 1.0); a number
      from 0 to 1 inclusive is a fraction (``"0.78"``, ``"0.5"``, ``"1"`` give
      0.78, 0.5, 1.0).
    - Anything above 100, a ``%`` on a value above 100, a negative sign or
      non-numeric text raises :class:`RatioParseError`.

    Arithmetic goes through :class:`~decimal.Decimal`, so ``"78"`` gives the
    float ``0.78`` exactly as written, and the row form prints ``0.78``.

    Parameters
    ----------
    text
        The cell text after the token grammar has cleaned it (decimal point,
        no thousands separators).

    Raises
    ------
    RatioParseError
        If ``text`` is not a plausible ratio.
    """
    m = _RATIO_RE.match(text)
    if m is None:
        raise RatioParseError(f"not a ratio: {text!r}")
    try:
        number = Decimal(m.group("number"))
    except InvalidOperation as exc:  # pragma: no cover - the regex prevents it
        raise RatioParseError(f"not a ratio: {text!r}") from exc
    if number > 100:
        raise RatioParseError(f"ratio above 100: {text!r}")
    if m.group("percent") or number > 1:
        return float(number / 100), RatioForm.PERCENT
    return float(number), RatioForm.FRACTION
