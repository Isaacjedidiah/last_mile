"""Sonnet STRUCTURES a table blob the deterministic chain couldn't parse.

This is the LAST-resort fallback for tables, used ONLY when pandas.read_html, the
grid parser, and flat-extract all fail to produce usable structured claims. It is
NON-deterministic (a model) -- a deliberate, bounded exception to the otherwise
deterministic table path, chosen because a raw BLOB in gold is worse than a
model-structured, flagged row.

CRITICAL: Sonnet does NOT extract or read values. The blob's values are
authoritative and complete; Sonnet only ARRANGES those exact values into the
table structure it sees in the image. The strict prompt below locks this down.
Every claim is tagged citation_tier=sonnet_structured so these are flagged and
reviewable.
"""
from __future__ import annotations

from typing import Optional

# STRICT prompt: structure the given values; never change/add/remove a value.
STRUCTURE_PROMPT = (
    "You are given (1) the RAW TEXT of a table that was already extracted (the "
    "BLOB, in the user content) and (2) an IMAGE of that same table. The values in "
    "the BLOB are AUTHORITATIVE, COMPLETE and CORRECT.\n"
    "\n"
    "Your ONLY job is to ARRANGE the BLOB's existing values into the correct table "
    "structure (rows x columns) that you can SEE in the image. You are formatting, "
    "not extracting.\n"
    "\n"
    "ABSOLUTE RULES:\n"
    "- Use ONLY the values present in the BLOB. Do NOT read any value from the "
    "image. Do NOT add, invent, infer, calculate, round, reformat or remove ANY "
    "value. Every number you output must appear verbatim in the BLOB.\n"
    "- The image is ONLY a guide to which row and column each existing value "
    "belongs to (alignment), where the BLOB's structure is unclear.\n"
    "- Preserve the exact row labels and column headers from the BLOB text.\n"
    "- If a value's position is genuinely unclear, keep it with the row/column the "
    "BLOB implies -- do not guess from the image.\n"
    "- Return JSON only: a list of cells, each {row_label, column_header, value}. "
    "Every value must be one that appears in the BLOB.\n"
)

_STRUCTURE_SCHEMA = {
    "name": "structure_table",
    "description": "Arrange the blob's existing values into rows x columns.",
    "parameters": {
        "type": "object",
        "properties": {
            "cells": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "row_label": {"type": "string"},
                        "column_header": {"type": "string"},
                        "value": {"type": "string",
                                  "description": "a value copied verbatim from the BLOB"},
                    },
                    "required": ["column_header", "value"],
                },
            },
        },
        "required": ["cells"],
    },
}


def _blob_values(blob):
    """Every numeric-looking token in the blob -- the authoritative value set.
    Used to VERIFY Sonnet didn't invent values (defence in depth)."""
    import re
    return set(re.findall(r"-?\d[\d,]*\.?\d*", str(blob or "")))


def sonnet_structure_blob(blob, crop_b64, filename, *, page=None, title=None,
                          team=None, report_type=None, entity_ref=None,
                          claim_cls=None, run_async_fn=None, llm_client=None,
                          vision_model_key="tier2", audit=None, run_id=None):
    """Structure a failed table blob with Sonnet (values from the blob, image for
    alignment). Returns claims tagged sonnet_structured, or [] on any failure.
    Verifies every output value exists in the blob -- drops any that don't (so
    Sonnet cannot inject a value even if it tries)."""
    if not (blob and crop_b64 and run_async_fn and llm_client):
        return []
    from ..shared.schema import CitationTier
    allowed = _blob_values(blob)
    import re
    _NUM = re.compile(r"-?\d[\d,]*\.?\d*")
    content = ("Table BLOB (authoritative values -- arrange these, do not change "
               "them):\n" + str(blob))
    try:
        resp = run_async_fn(llm_client.extract_two_images(
            vision_model_key, STRUCTURE_PROMPT, content, _STRUCTURE_SCHEMA,
            crop_b64=crop_b64, page_b64=None))
    except Exception:
        return []
    ta = getattr(resp, "tool_arguments", None)
    cells = ta.get("cells") if isinstance(ta, dict) else None
    if not isinstance(cells, list):
        return []
    claims = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        val = str(cell.get("value", "")).strip()
        if not val:
            continue
        m = _NUM.search(val)
        if not m:
            continue
        num = m.group(0)
        # DEFENCE: the value must exist in the blob, else Sonnet invented it -> drop
        if num not in allowed and num.replace(",", "") not in {a.replace(",", "") for a in allowed}:
            continue
        row_label = str(cell.get("row_label", "")).strip()
        col = str(cell.get("column_header", "")).strip()
        parts = [p for p in (title, row_label, col) if p]
        name = " | ".join(parts) if parts else col
        try:
            claims.append(claim_cls(
                field_name=col or name, canonical_metric=name, value=num,
                source_document=filename, page=page, team=team,
                report_type=report_type, entity_ref=entity_ref,
                element_type="table", element_id=None,
                model_used="sonnet_structured",
                citation_tier=CitationTier.SONNET_STRUCTURED.value))
        except Exception:
            continue
    if audit is not None:
        try:
            audit.log(run_id or "", "sonnet_structured_table",
                      f"{filename}-p{page}", document=filename, page=page,
                      n_cells=len(cells), n_kept=len(claims))
        except Exception:
            pass
    return claims
