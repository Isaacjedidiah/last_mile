"""Access-tier cascade for the extraction front end.

A document is tagged with a sensitivity tier; it is written to its own tier's
table AND every MORE-privileged tier, so each tier's viewers see everything they
are cleared for:

  access_     (everyone)            -> access_, limited_, restricted_
  limited_    (team components)     -> limited_, restricted_
  restricted_ (decision-makers)     -> restricted_

So restricted_ holds EVERYTHING (decision-makers get the full picture, e.g. Firm A
confidential docs plus all public docs); access_ holds only non-sensitive docs.
Physical separate tables per tier -> each is separately grantable, giving hard
confidentiality isolation (adding a user to a tier = granting that tier's table).
"""
from __future__ import annotations

TIERS = ("access", "limited", "restricted")

# tier -> the tiers it ALSO writes to (itself + all more-privileged)
_CASCADE = {
    "access":     ["access", "limited", "restricted"],
    "limited":    ["limited", "restricted"],
    "restricted": ["restricted"],
}


def normalize_tier(prefix: str) -> str:
    """Accept 'access', 'access_', 'ACCESS' -> 'access'. Raises on unknown."""
    t = str(prefix or "").strip().lower().rstrip("_")
    if t not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}, got {prefix!r}")
    return t


def target_tiers(prefix: str) -> list[str]:
    """The tiers a document of this prefix is written to (itself + more-privileged)."""
    return list(_CASCADE[normalize_tier(prefix)])


def tier_table(base_table: str, tier: str) -> str:
    """Prefix a base table name with the tier: ('gold_fx_exchange_report','access')
    -> 'access_gold_fx_exchange_report'. The base_table already carries the
    per-team+report layer name; the tier is the OUTER prefix for grants."""
    return f"{normalize_tier(tier)}_{base_table}"


def tiered_tables(base_table: str, prefix: str) -> list[str]:
    """Every tier-prefixed table a document of this prefix writes to."""
    return [tier_table(base_table, t) for t in target_tiers(prefix)]
