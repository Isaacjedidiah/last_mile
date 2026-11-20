"""The mapping ENGINE: applies a team's resolved mapping (per modality) +
dictionary to a gold row, producing the team's intelligence columns.

This is the core. For each gold row:
  1. route by modality (element_type: table/text/figure->chart),
  2. for each of the team's schema columns, run its mapping METHOD against the
     row's canonical_metric / field_name / gold columns,
  3. apply the DICTIONARY (synonym -> canonical) to the extracted values,
  4. flag the row if a REQUIRED column could not be extracted.

Extraction methods (per the mapping's 'method' + 'params'):
  direct(source)            -> the gold column `source` value as-is
  after_label(label)        -> text after '<label>:' up to the next '|' (tables)
  delimiter_position(index) -> the Nth '|' segment of canonical_metric
  contains(terms)           -> the first term that appears in the text (charts/text)
  regex(pattern)            -> group 1 of the regex over the text
  literal(value)            -> a constant

Nothing here is LLM-based: it is deterministic string processing, so the same
gold row + same config always yields the same intelligence columns.
"""
from __future__ import annotations

import re
from typing import Any, Optional


# metadata every intelligent_gold row inherits automatically (team need not map)
INHERITED_METADATA = ["source_document", "extraction_date", "entity_ref",
                      "page", "page_url", "doc_id"]

# element_type (gold) -> modality (mapping)
_ELEMENT_TO_MODALITY = {
    "table": "table",
    "text": "text",
    "figure": "chart",
    "chart": "chart",
}


def modality_of(row: dict) -> str:
    et = str(row.get("element_type") or "").strip().lower()
    return _ELEMENT_TO_MODALITY.get(et, "text")


def _text_fields(row: dict) -> str:
    """The searchable text for extraction: canonical_metric (primary) + field_name."""
    cm = str(row.get("canonical_metric") or "")
    fn = str(row.get("field_name") or "")
    return cm if cm else fn


# ---- the extraction methods ----
def _m_direct(row, params):
    return row.get(params.get("source"))


def _m_after_label(row, params):
    """Extract after '<label>:' up to the next '|' (or end). Tables:
    'Page | Table | Industry: Water Utilities | Loan' , label='Industry'
    -> 'Water Utilities'."""
    label = params.get("label", "")
    text = _text_fields(row)
    if not label:
        return None
    m = re.search(rf"{re.escape(label)}\s*:\s*([^|]+)", text, re.I)
    return m.group(1).strip() if m else None


def _m_delimiter_position(row, params):
    """The Nth '|' segment (0-based) of canonical_metric."""
    idx = params.get("index")
    text = _text_fields(row)
    if idx is None:
        return None
    parts = [p.strip() for p in text.split("|")]
    try:
        return parts[int(idx)] if 0 <= int(idx) < len(parts) else None
    except (ValueError, TypeError):
        return None


def _m_contains(row, params):
    """The first of `terms` that appears in the text (charts/text). Robust to the
    varied separators charts use (':', '-', space)."""
    terms = params.get("terms") or []
    text = _text_fields(row).lower()
    for t in terms:
        if str(t).strip().lower() in text:
            return t
    return None


def _m_regex(row, params):
    pattern = params.get("pattern")
    text = _text_fields(row)
    if not pattern:
        return None
    try:
        m = re.search(pattern, text)
        return (m.group(1) if m.groups() else m.group(0)) if m else None
    except re.error:
        return None


def _m_literal(row, params):
    return params.get("value")


_METHODS = {
    "direct": _m_direct,
    "after_label": _m_after_label,
    "delimiter_position": _m_delimiter_position,
    "contains": _m_contains,
    "regex": _m_regex,
    "literal": _m_literal,
}


def _apply_dictionary(value, dictionary: dict) -> Any:
    """Normalise a value via the dictionary. A synonym is replaced IN PLACE wherever
    it appears as a WHOLE WORD, so 'RevPo Ratio' -> 'Stress Growth Ratio' (the
    qualifier is kept) and an exact 'RevPo' -> 'Stress Growth'. Word-boundary
    matching avoids false hits inside longer words (e.g. 'RevPoints').
    Longer synonyms are applied first so a multi-word term wins over a sub-part."""
    if value is None or not dictionary:
        return value
    out = str(value)
    # apply longest synonyms first (avoids a short term pre-empting a longer one)
    for term in sorted(dictionary.keys(), key=len, reverse=True):
        canon = dictionary[term]
        # whole-word, case-insensitive, in-place
        out = re.sub(rf"\b{re.escape(term)}\b", canon, out, flags=re.I)
    return out


def build_intelligence_row(gold_row: dict, mappings_by_col_mod: dict,
                           schema_cols: list[str], dictionary: dict,
                           required_cols: Optional[set] = None) -> dict:
    """Produce ONE intelligence row from a gold row.

    mappings_by_col_mod : {(column, modality): mapping_definition}
    schema_cols         : the ordered output columns the team defined
    dictionary          : {synonym_lower: canonical}
    required_cols       : columns that MUST resolve, else the row is flagged.
    Returns the intelligence row dict, including:
      * the team's columns,
      * carry-through keys (doc_id, source_document, page, value, etc.),
      * _mapped_ok (bool) and _unmapped (list of columns that didn't resolve).
    """
    modality = modality_of(gold_row)
    out = {}
    unmapped = []
    # METRIC ANCHOR: the metric comes from field_name; split any trailing period
    # into metric_date (or as_at_date if that gold column is empty).
    from .date_normalize import split_metric_date
    _fn = gold_row.get("field_name")
    _metric_name, _metric_date = split_metric_date(_fn) if _fn else (_fn, None)
    out["metric"] = _apply_dictionary(_metric_name, dictionary)   # normalise synonyms
    if _metric_date:
        if gold_row.get("as_at_date"):
            out["metric_date"] = _metric_date      # as_at_date already set -> keep both
        else:
            out["as_at_date"] = _metric_date       # fill empty as_at_date
            out["metric_date"] = _metric_date
    for col in schema_cols:
        mapping = mappings_by_col_mod.get((col, modality))
        if mapping is None:
            out[col] = None
            unmapped.append(col)
            continue
        method = mapping.get("method")
        params = mapping.get("params", {})
        fn = _METHODS.get(method)
        val = fn(gold_row, params) if fn else None
        val = _apply_dictionary(val, dictionary)
        out[col] = val
        if val is None:
            unmapped.append(col)

    # ALWAYS inherit the standard metadata (team doesn't map these)
    for k in INHERITED_METADATA:
        if k in gold_row:
            out[k] = gold_row[k]
    # plus the metric value + a few traceability keys
    for k in ("value", "numeric_value", "unit", "currency", "canonical_metric",
              "field_name", "element_type", "element_id", "observational_id"):
        if k in gold_row and k not in out:
            out[k] = gold_row[k]

    req = required_cols or set()
    out["_unmapped"] = [c for c in unmapped if c in req] if req else unmapped
    out["_mapped_ok"] = (len(out["_unmapped"]) == 0)
    return out


def index_mappings(latest_mappings: list[dict]) -> dict:
    """Turn resolved mapping entries into a {(column, modality): definition} index."""
    idx = {}
    for m in latest_mappings:
        d = m.get("definition", {})
        col = d.get("column_name")
        mod = d.get("modality")
        if col and mod:
            idx[(col, mod)] = d
    return idx


def build_dictionary(latest_dictionary: list[dict]) -> dict:
    """Turn resolved dictionary entries into {synonym_lower: canonical}."""
    out = {}
    for e in latest_dictionary:
        d = e.get("definition", {})
        term = str(d.get("term", "")).strip().lower()
        canon = d.get("canonical")
        if term and canon:
            out[term] = canon
    return out
