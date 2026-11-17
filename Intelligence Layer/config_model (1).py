"""Config data model for the intelligence layer.

The `intelligent_guide` table stores every team's SCHEMA, MAPPING and DICTIONARY
definitions, append-only and versioned. The process pipeline resolves the LATEST
version per identity for a team, then applies it to gold.

One row per config ENTRY:
    team_id        -- which team owns this entry
    config_type    -- 'schema' | 'mapping' | 'dictionary'
    identity_key   -- the stable identity of the entry (see below), so a newer
                      append with the same identity SUPERSEDES the older one, and
                      a new identity is an addition.
    definition     -- JSON payload (shape depends on config_type)
    version        -- integer, increments per identity (1, 2, 3...)
    created_at     -- UTC timestamp
    created_by     -- user who submitted (audit)
    is_active      -- True; a soft-delete sets this False (append a tombstone)

identity_key by config_type:
    schema      -> column_name                 (team's output column)
    mapping     -> column_name|modality        (one mapping per column per modality)
    dictionary  -> term                         (one canonical mapping per synonym)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


GUIDE_TABLE = "intelligent_guide"     # resolved via CONFIG.storage.fqtn at write time

CONFIG_TYPES = ("schema", "mapping", "dictionary", "key_mapping")
MODALITIES = ("table", "text", "chart")

# the extraction methods a mapping can use (per modality)
EXTRACTION_METHODS = (
    "direct",              # gold column value straight across
    "after_label",         # extract after '<label>:' up to the next '|'
    "delimiter_position",  # the Nth segment when split on '|'
    "contains",            # if a term appears anywhere, use it (charts/text)
    "regex",               # custom regex, group 1
    "literal",             # a fixed constant value
)


@dataclass
class GuideEntry:
    """One versioned config entry in intelligent_guide."""
    team_id: str
    config_type: str                  # schema | mapping | dictionary
    identity_key: str
    definition: dict                  # shape depends on config_type
    version: int = 1
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: Optional[str] = None
    is_active: bool = True

    def to_row(self) -> dict:
        r = asdict(self)
        r["definition"] = json.dumps(self.definition)   # store JSON as string
        return r


# ---- builders for the three config types (shape of `definition`) ----
def schema_entry(team_id, column_name, data_type="string", description="",
                 created_by=None, version=1) -> GuideEntry:
    """A team's output column. identity = column_name."""
    return GuideEntry(
        team_id=team_id, config_type="schema", identity_key=column_name,
        definition={"column_name": column_name, "data_type": data_type,
                    "description": description},
        version=version, created_by=created_by)


def mapping_entry(team_id, column_name, modality, method, created_by=None,
                  version=1, **params) -> GuideEntry:
    """How to populate `column_name` for rows of `modality`. identity =
    column_name|modality. params carry the method's arguments, e.g.
      after_label  -> label="Industry"
      delimiter_position -> index=1
      contains     -> terms=["POS","COS"]
      regex        -> pattern="..."
      direct       -> source="entity_ref"
      literal      -> value="..."
    """
    if modality not in MODALITIES:
        raise ValueError(f"modality must be one of {MODALITIES}")
    if method not in EXTRACTION_METHODS:
        raise ValueError(f"method must be one of {EXTRACTION_METHODS}")
    return GuideEntry(
        team_id=team_id, config_type="mapping",
        identity_key=f"{column_name}|{modality}",
        definition={"column_name": column_name, "modality": modality,
                    "method": method, "params": params},
        version=version, created_by=created_by)


def dictionary_entry(team_id, term, canonical, created_by=None,
                     version=1) -> GuideEntry:
    """Normalise a synonym to a canonical term. identity = term (lowercased).
    e.g. RevPo -> Stress Growth, SevPo -> Stress Growth."""
    return GuideEntry(
        team_id=team_id, config_type="dictionary",
        identity_key=str(term).strip().lower(),
        definition={"term": term, "canonical": canonical},
        version=version, created_by=created_by)


# ---- version resolution: latest active entry per identity, per team ----
def resolve_latest(entries: list[dict], team_id: str,
                   config_type: Optional[str] = None) -> list[dict]:
    """From raw guide rows, return the LATEST active entry per identity_key for a
    team (and optionally one config_type). This is what the process pipeline uses
    -- newer appends supersede older ones; tombstones (is_active False) drop the
    identity. Pure function over rows, so it works on a Spark collect() or a list.
    """
    latest: dict[tuple, dict] = {}
    for r in entries:
        if r.get("team_id") != team_id:
            continue
        if config_type and r.get("config_type") != config_type:
            continue
        key = (r.get("config_type"), r.get("identity_key"))
        cur = latest.get(key)
        if cur is None or (r.get("version", 0) > cur.get("version", 0)):
            latest[key] = r
    # drop tombstoned identities, parse definition JSON
    out = []
    for r in latest.values():
        if not r.get("is_active", True):
            continue
        rr = dict(r)
        d = rr.get("definition")
        if isinstance(d, str):
            try:
                rr["definition"] = json.loads(d)
            except Exception:
                rr["definition"] = {}
        out.append(rr)
    return out


def next_version(entries: list[dict], team_id, config_type, identity_key) -> int:
    """The next version number for an identity (max existing + 1, else 1).
    Used by the storage pipeline when a team appends/updates an entry."""
    mx = 0
    for r in entries:
        if (r.get("team_id") == team_id and r.get("config_type") == config_type
                and r.get("identity_key") == identity_key):
            mx = max(mx, r.get("version", 0))
    return mx + 1
