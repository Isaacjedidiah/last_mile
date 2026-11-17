"""Key-pair mapping: turn the KEY:VALUE pairs inside a canonical_metric into
named columns in a user's own distinct table.

A canonical_metric often encodes structured pairs, e.g.
    "Name: Isaac Ltd | Sector: Industry"
This module lets a user (in the intelligence app):
  1. anchor on a FIELD_NAME (their schema's metric anchor) -- scalable, we only
     scan the gold rows for that field_name, never all 1M rows;
  2. DISCOVER the distinct keys that appear inside those rows' canonical_metrics
     (aggregated -- "Name" is ONE key however many values it takes), with sample
     values so the user can see what they're mapping;
  3. MAP each key -> a column in their distinct table, with a chosen name (add a
     new schema field, or map onto an existing one -- the caller tells the user
     which);
  4. a change to the mapping triggers a full REWRITE of the distinct table, so it
     always reflects the CURRENT mapping (today "Industry", even if yesterday it
     was "Company").

All deterministic: parsing + aggregation + projection, no LLM.
"""
from __future__ import annotations

import re
from typing import Optional

# a canonical_metric splits on " | " into parts; a KEY:VALUE part is "Key: Value".
_PAIR_DELIM = "|"
_KV_SPLIT = re.compile(r"^\s*([^:]{1,60}?)\s*:\s*(.+?)\s*$")


def parse_pairs(canonical_metric: str) -> dict:
    """Parse a canonical_metric into {key: value} pairs. Only parts of the form
    'Key: Value' become pairs; parts without a clean 'key:' are returned under the
    special key '' (unkeyed) so nothing is silently lost. Deterministic.

    "Name: Isaac Ltd | Sector: Industry" -> {"Name": "Isaac Ltd", "Sector": "Industry"}
    """
    pairs: dict = {}
    if not canonical_metric:
        return pairs
    for part in str(canonical_metric).split(_PAIR_DELIM):
        part = part.strip()
        if not part:
            continue
        m = _KV_SPLIT.match(part)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            # first value wins per metric; a key repeating in one metric is rare
            pairs.setdefault(key, val)
        else:
            pairs.setdefault("", part)       # unkeyed part -- kept, not lost
    return pairs


def discover_keys_for_field(rows, field_name: str, max_samples: int = 5) -> list[dict]:
    """For the gold rows of ONE field_name (the caller filters gold to this
    field_name -- scalable), aggregate the DISTINCT keys found inside their
    canonical_metrics, with a frequency and a few sample values each.

    ``rows`` is an iterable of dicts each having 'canonical_metric'. Returns a list
    of {key, count, samples} sorted by frequency (most common first). "Name"
    appearing with 500 values is ONE entry with 500 count and up to max_samples
    distinct sample values. The unkeyed bucket (key '') is included so the user
    can see metrics that don't split into pairs.
    """
    agg: dict = {}   # key -> {count, samples:set}
    for r in rows:
        cm = r.get("canonical_metric") if isinstance(r, dict) else getattr(r, "canonical_metric", None)
        if not cm:
            continue
        for key, val in parse_pairs(cm).items():
            slot = agg.setdefault(key, {"count": 0, "samples": []})
            slot["count"] += 1
            if val and val not in slot["samples"] and len(slot["samples"]) < max_samples:
                slot["samples"].append(val)
    out = [{"key": k, "count": v["count"], "samples": v["samples"]}
           for k, v in agg.items()]
    out.sort(key=lambda d: d["count"], reverse=True)
    return out


# ---- the mapping model ----------------------------------------------------

def make_key_mapping(field_name: str, key: str, column: str,
                     rename: Optional[str] = None, target: str = "new") -> dict:
    """One mapping entry: within canonical_metrics of this FIELD_NAME, the pair
    KEY -> a COLUMN in the user's distinct table (named ``rename`` or the key).
    ``target`` is 'new' (adds a schema field) or 'existing' (maps onto one) -- the
    app uses it to INFORM the user which is happening."""
    return {"field_name": field_name, "key": key, "column": column,
            "display_name": (rename or key), "target": target}


def classify_target(column: str, existing_columns) -> str:
    """Tell the user whether mapping to ``column`` ADDS a new schema field or maps
    onto an EXISTING one, so the app can inform them. Deterministic."""
    existing = {str(c).lower() for c in (existing_columns or [])}
    return "existing" if str(column).lower() in existing else "new"


# ---- building the user's distinct table (the "rewrite") -------------------

def project_row(gold_row: dict, mappings: list[dict]) -> dict:
    """Apply the key mappings to ONE gold row -> the user-table row: each mapped
    key's value under the mapped column name. Only mappings whose field_name
    matches this row apply. Carries the row's identity columns through."""
    out = {}
    # carry identity/context so the user table is usable on its own
    for idc in ("source_document", "page", "entity_ref", "team", "report_type",
                "field_name", "canonical_metric", "value", "page_title",
                "sub_header", "doc_id", "extraction_date"):
        if idc in gold_row:
            out[idc] = gold_row[idc]
    fn = gold_row.get("field_name")
    cm = gold_row.get("canonical_metric")
    pairs = parse_pairs(cm)
    for mp in mappings:
        if mp.get("field_name") and mp["field_name"] != fn:
            continue
        key = mp["key"]
        if key in pairs:
            out[mp["display_name"]] = pairs[key]
    return out


def rewrite_user_table(spark, gold_table: str, user_table: str,
                       mappings: list[dict], field_names=None) -> int:
    """FULL REWRITE of the user's distinct table from CURRENT mappings. Reads gold
    (optionally only the rows whose field_name is mapped -- scalable), projects
    each row's mapped key:value pairs into the mapped columns, and OVERWRITES the
    user table so it always reflects the current mapping. Returns rows written.

    Any change to the schema/mapping should call this: yesterday's 'Company' is
    gone, today's 'Industry' is what the table shows.
    """
    if spark is None:
        return 0
    df = spark.table(gold_table)
    # scope to the mapped field_names only (never scan unrelated rows)
    fns = field_names or sorted({m["field_name"] for m in mappings if m.get("field_name")})
    if fns:
        df = df.filter(df.field_name.isin(list(fns)))
    rows = [r.asDict() for r in df.collect()]
    projected = [project_row(r, mappings) for r in rows]
    projected = [p for p in projected if p]
    if not projected:
        # still overwrite with an empty frame so a removed mapping clears the table
        try:
            spark.createDataFrame([], df.schema).write.format("delta").mode(
                "overwrite").option("overwriteSchema", "true").saveAsTable(user_table)
        except Exception:
            pass
        return 0
    out_df = spark.createDataFrame(projected)
    (out_df.write.format("delta").mode("overwrite")
        .option("overwriteSchema", "true")       # rewrite: new mapping = new columns
        .saveAsTable(user_table))
    return len(projected)
