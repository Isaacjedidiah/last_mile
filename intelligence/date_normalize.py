"""Date normalisation for field_name metrics.

A field_name often carries a period on the metric name, in MANY variations:
  "Revenue June 2026", "Revenue Jun 26", "Revenue Jun-26", "Revenue 06/2026",
  "Revenue Q2 2026", "Revenue FY2026", "Revenue 2026".
This module splits a field_name into:
  * metric_name  -- the metric with the trailing period removed ("Revenue")
  * metric_date  -- a normalised date string ("2026-06", "2026-Q2", "2026"), or None
It FLAGS nothing silently: if no date is found, metric_date is None and the name
is returned unchanged. Deterministic -- pure parsing, no LLM.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

_MONTHS = {
    "jan":1,"january":1,"feb":2,"february":2,"mar":3,"march":3,"apr":4,"april":4,
    "may":5,"jun":6,"june":6,"jul":7,"july":7,"aug":8,"august":8,"sep":9,"sept":9,
    "september":9,"oct":10,"october":10,"nov":11,"november":11,"dec":12,"december":12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))

# trailing-period patterns, tried in order. Each returns (normalised_date, match_span).
# year can be 4-digit (2026) or 2-digit (26 -> 2026).
_Y4 = r"(?:19|20)\d{2}"
_Y2 = r"\d{2}"

_PATTERNS = [
    # Month Year:  June 2026 / Jun 26 / Jun-26 / Jun/2026
    (re.compile(rf"\b({_MONTH_ALT})[ \-/]*({_Y4}|{_Y2})\b", re.I), "month_year"),
    # Quarter Year: Q2 2026 / Q2-26 / 2026 Q2
    (re.compile(rf"\bQ([1-4])[ \-/]*({_Y4}|{_Y2})\b", re.I), "q_year"),
    (re.compile(rf"\b({_Y4})[ \-/]*Q([1-4])\b", re.I), "year_q"),
    # Numeric month/year: 06/2026 / 06-2026 / 2026-06
    (re.compile(rf"\b(0?[1-9]|1[0-2])[\-/]({_Y4})\b"), "mm_yyyy"),
    (re.compile(rf"\b({_Y4})[\-/](0?[1-9]|1[0-2])\b"), "yyyy_mm"),
    # Financial year: FY2026 / FY26
    (re.compile(rf"\bFY[ \-]?({_Y4}|{_Y2})\b", re.I), "fy"),
    # Year alone: 2026 (last resort, 4-digit only to avoid grabbing random 2-digit)
    (re.compile(rf"\b({_Y4})\b"), "year"),
]


def _y4(y: str) -> str:
    y = str(y)
    if len(y) == 2:
        n = int(y)
        return str(2000 + n)          # 26 -> 2026 (assumes 21st century)
    return y


def _normalise(kind: str, m) -> str:
    if kind == "month_year":
        mon = _MONTHS[m.group(1).lower()]
        return f"{_y4(m.group(2))}-{mon:02d}"
    if kind == "q_year":
        return f"{_y4(m.group(2))}-Q{m.group(1)}"
    if kind == "year_q":
        return f"{_y4(m.group(1))}-Q{m.group(2)}"
    if kind == "mm_yyyy":
        return f"{_y4(m.group(2))}-{int(m.group(1)):02d}"
    if kind == "yyyy_mm":
        return f"{_y4(m.group(1))}-{int(m.group(2)):02d}"
    if kind == "fy":
        return f"FY{_y4(m.group(1))}"
    if kind == "year":
        return _y4(m.group(1))
    return ""


def split_metric_date(field_name: str) -> Tuple[str, Optional[str]]:
    """Split a field_name into (metric_name, metric_date).
    metric_date is a normalised string or None if no period is found.
    The matched period is removed from the metric name; separators left behind are
    trimmed. The name is never emptied -- if stripping would blank it, the original
    is kept and the date still returned."""
    if not field_name:
        return field_name, None
    text = str(field_name)
    for rx, kind in _PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        date = _normalise(kind, m)
        # remove the matched span to get the clean metric name
        name = (text[:m.start()] + text[m.end():])
        name = re.sub(r"[\s\-/,]+$", "", name).strip()      # trailing junk
        name = re.sub(r"^[\s\-/,]+", "", name)              # leading junk
        name = re.sub(r"\s{2,}", " ", name)
        if not name:                 # don't blank the metric; keep original name
            name = text.strip()
        return name, date
    return text.strip(), None
