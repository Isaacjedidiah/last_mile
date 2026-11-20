"""Storage pipeline: write a team's config (from the UI) into intelligent_guide.

Append-only + versioned: each submitted entry gets the NEXT version for its
identity (so a change supersedes the old; a new entry starts at v1). The process
pipeline later reads the LATEST version per identity.

The UI submits lists of schema / mapping / dictionary definitions for a team;
this module turns them into versioned GuideEntry rows and appends them to the
intelligent_guide Delta table. It also validates each definition before writing,
so malformed config never reaches the table.
"""
from __future__ import annotations

from typing import Optional

from .config_model import (GuideEntry, schema_entry, mapping_entry,
                           dictionary_entry, next_version, resolve_latest,
                           MODALITIES, EXTRACTION_METHODS)


# ---- validation ----
def validate_mapping(defn: dict) -> Optional[str]:
    """Return an error string if a mapping definition is invalid, else None."""
    if not defn.get("column_name"):
        return "mapping needs a column_name"
    if defn.get("modality") not in MODALITIES:
        return f"modality must be one of {MODALITIES}"
    method = defn.get("method")
    if method not in EXTRACTION_METHODS:
        return f"method must be one of {EXTRACTION_METHODS}"
    params = defn.get("params", {})
    # per-method required params
    need = {"after_label": "label", "delimiter_position": "index",
            "contains": "terms", "regex": "pattern", "direct": "source",
            "literal": "value"}.get(method)
    if need and (need not in params or params.get(need) in (None, "", [])):
        return f"method '{method}' needs param '{need}'"
    return None


def validate_schema(defn: dict) -> Optional[str]:
    if not defn.get("column_name"):
        return "schema entry needs a column_name"
    return None


def validate_dictionary(defn: dict) -> Optional[str]:
    if not defn.get("term") or not defn.get("canonical"):
        return "dictionary entry needs 'term' and 'canonical'"
    return None


# ---- build versioned entries from UI submissions ----
def build_entries(existing_rows: list[dict], team_id: str,
                  schemas: list[dict] = None, mappings: list[dict] = None,
                  dictionaries: list[dict] = None, key_mappings: list[dict] = None,
                  created_by: str = None):
    """Turn UI definition lists into versioned GuideEntry objects, computing the
    next version per identity against existing_rows. Returns (entries, errors).
    errors is a list of (kind, definition, message) for anything rejected.
    """
    entries, errors = [], []

    for d in (schemas or []):
        err = validate_schema(d)
        if err:
            errors.append(("schema", d, err)); continue
        col = d["column_name"]
        v = next_version(existing_rows, team_id, "schema", col)
        e = schema_entry(team_id, col, d.get("data_type", "string"),
                         d.get("description", ""), created_by=created_by, version=v)
        if d.get("required"):
            e.definition["required"] = True
        entries.append(e)

    for d in (mappings or []):
        err = validate_mapping(d)
        if err:
            errors.append(("mapping", d, err)); continue
        col, mod = d["column_name"], d["modality"]
        ident = f"{col}|{mod}"
        v = next_version(existing_rows, team_id, "mapping", ident)
        e = mapping_entry(team_id, col, mod, d["method"], created_by=created_by,
                          version=v, **d.get("params", {}))
        entries.append(e)

    for d in (dictionaries or []):
        err = validate_dictionary(d)
        if err:
            errors.append(("dictionary", d, err)); continue
        ident = str(d["term"]).strip().lower()
        v = next_version(existing_rows, team_id, "dictionary", ident)
        e = dictionary_entry(team_id, d["term"], d["canonical"],
                             created_by=created_by, version=v)
        entries.append(e)

    # key_mappings: one entry per (field_name|key) -> {column, display_name, target}
    from .config_model import GuideEntry
    for d in (key_mappings or []):
        fn = str(d.get("field_name", "")).strip()
        key = str(d.get("key", "")).strip()
        if not fn:
            errors.append(("key_mapping", d, "field_name required")); continue
        ident = f"{fn}|{key}"
        v = next_version(existing_rows, team_id, "key_mapping", ident)
        entries.append(GuideEntry(
            team_id=team_id, config_type="key_mapping", identity_key=ident,
            definition={"field_name": fn, "key": key,
                        "column": d.get("column"), "display_name": d.get("display_name"),
                        "target": d.get("target", "new")},
            version=v, created_by=created_by))

    return entries, errors


def latest_team_config(spark, guide_table: str, team_id: str) -> dict:
    """Return the latest (highest-version, non-tombstoned) entries for a team,
    grouped by config_type: {schema:[...], mapping:[...], dictionary:[...],
    key_mapping:[...]}. Each list holds the definition dicts."""
    rows = _read_guide(spark, guide_table)
    mine = [r for r in rows if r.get("team_id") == team_id]
    # keep the highest version per (config_type, identity_key)
    best = {}
    for r in mine:
        k = (r.get("config_type"), r.get("identity_key"))
        if k not in best or r.get("version", 0) > best[k].get("version", 0):
            best[k] = r
    out = {"schema": [], "mapping": [], "dictionary": [], "key_mapping": []}
    for (ct, _ident), r in best.items():
        if r.get("tombstoned"):
            continue
        defn = r.get("definition")
        if isinstance(defn, str):
            try:
                import json as _j
                defn = _j.loads(defn)
            except Exception:
                defn = {}
        out.setdefault(ct, []).append(defn or {})
    return out


# ---- the storage pipeline ----
def _read_guide(spark, guide_table):
    try:
        return [r.asDict(recursive=True) for r in spark.table(guide_table).collect()]
    except Exception:
        return []   # table doesn't exist yet


def save_team_config(spark, guide_table: str, team_id: str,
                     schemas=None, mappings=None, dictionaries=None,
                     key_mappings=None, created_by=None) -> dict:
    """Validate + version + APPEND a team's config to intelligent_guide.

    guide_table : fully-qualified intelligent_guide table.
    Returns {appended, errors, versions}. Nothing is written if there are errors
    (all-or-nothing per submission, so a partial bad submit doesn't half-apply).
    """
    existing = _read_guide(spark, guide_table)
    entries, errors = build_entries(existing, team_id, schemas, mappings,
                                    dictionaries, key_mappings=key_mappings,
                                    created_by=created_by)
    if errors:
        return {"appended": 0, "errors": errors, "versions": []}
    if not entries:
        return {"appended": 0, "errors": [], "versions": []}

    rows = [e.to_row() for e in entries]
    (spark.createDataFrame(rows).write.format("delta")
     .mode("append").option("mergeSchema", "true").saveAsTable(guide_table))

    versions = [(e.config_type, e.identity_key, e.version) for e in entries]
    return {"appended": len(rows), "errors": [], "versions": versions}


def soft_delete_entry(spark, guide_table: str, team_id: str, config_type: str,
                      identity_key: str, created_by=None) -> dict:
    """Retire an identity by appending a tombstone (is_active False) at the next
    version. resolve_latest then drops it. Append-only -- history is kept."""
    existing = _read_guide(spark, guide_table)
    v = next_version(existing, team_id, config_type, identity_key)
    tomb = GuideEntry(team_id=team_id, config_type=config_type,
                      identity_key=identity_key, definition={}, version=v,
                      created_by=created_by, is_active=False)
    (spark.createDataFrame([tomb.to_row()]).write.format("delta")
     .mode("append").option("mergeSchema", "true").saveAsTable(guide_table))
    return {"tombstoned": f"{config_type}:{identity_key}", "version": v}
