"""Sonnet FORMATS a mis-structured table blob using the WHOLE PAGE image.

The deterministic chain (pandas flavours -> grid parser -> flat-extract) cannot
fix tables where ai_parse placed values in the WRONG columns -- that happens with
merged/spanning cells, where the grid structure is lost in the HTML and is NOT
recoverable from the HTML alone (an industry-wide frontier problem). The structure
DOES still exist in the page IMAGE, though.

So this fallback sends Sonnet the WHOLE PAGE image + the table BLOB and asks it to
RE-ARRANGE the blob's EXACT values into the correct rows/columns it can SEE on the
page. We send the whole page (not a crop) because cropping the table was the thing
that failed before -- the whole page always renders reliably.

CRITICAL: Sonnet does NOT read or invent values. The blob's values are
authoritative; Sonnet only fixes their row/column PLACEMENT from the image. Every
output value is verified to exist in the blob (invented values dropped). Tagged
citation_tier=sonnet_formatted, flagged for review. Non-deterministic in STRUCTURE
only; values stay from the blob.
"""
from __future__ import annotations

import re
from typing import Optional

FORMAT_PROMPT = (
    "You are given (1) the RAW TEXT of a table (the BLOB, in the user content) that "
    "was extracted from a document but whose COLUMN STRUCTURE is WRONG -- some "
    "values are in the wrong columns because the table has merged/spanning cells -- "
    "and (2) an IMAGE of the WHOLE PAGE the table appears on.\n"
    "\n"
    "Find THIS table on the page (match it by its values and labels from the BLOB) "
    "and RE-ARRANGE the BLOB's existing values into the correct rows and columns "
    "that you can SEE on the page. You are FORMATTING/re-aligning, not extracting.\n"
    "\n"
    "ABSOLUTE RULES:\n"
    "- Use ONLY the values present in the BLOB. Do NOT read any value from the "
    "image, and do NOT add, invent, infer, calculate or remove ANY value. Every "
    "number you output must appear verbatim in the BLOB.\n"
    "- The page image is ONLY a guide to the correct row/column placement.\n"
    "- Preserve the exact row labels and column headers from the BLOB.\n"
    "- Return JSON only: a list of cells, each {row_label, column_header, value}. "
    "Every value must be one that appears in the BLOB.\n"
)

_SCHEMA = {
    "name": "format_table",
    "description": "Re-align the blob's existing values into correct rows x columns.",
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

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _blob_values(blob):
    return set(_NUM.findall(str(blob or "")))


def sonnet_format_table(blob, page_b64, filename, *, page=None, title=None,
                        team=None, report_type=None, entity_ref=None,
                        claim_cls=None, run_async_fn=None, llm_client=None,
                        vision_model_key="tier2", audit=None, run_id=None):
    """Re-align a mis-structured table blob using the WHOLE PAGE image. Values from
    the blob (verified); structure from the page. Returns claims tagged
    sonnet_formatted, or [] on any failure. Never raises."""
    if not (blob and page_b64 and run_async_fn and llm_client and claim_cls):
        return []
    from ..shared.schema import CitationTier
    allowed = _blob_values(blob)
    allowed_nc = {a.replace(",", "") for a in allowed}
    content = ("Table BLOB (authoritative values -- re-arrange these into the "
               "correct columns, do not change them):\n" + str(blob))
    try:
        resp = run_async_fn(llm_client.extract_two_images(
            vision_model_key, FORMAT_PROMPT, content, _SCHEMA,
            crop_b64=page_b64, page_b64=None))   # the WHOLE PAGE is the primary image
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
        m = _NUM.search(val)
        if not m:
            continue
        num = m.group(0)
        # DEFENCE: value must exist in the blob, else Sonnet invented it -> drop
        if num not in allowed and num.replace(",", "") not in allowed_nc:
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
                model_used="sonnet_formatted",
                citation_tier=CitationTier.SONNET_FORMATTED.value))
        except Exception:
            continue
    if audit is not None:
        try:
            audit.log(run_id or "", "sonnet_formatted_table",
                      f"{filename}-p{page}", document=filename, page=page,
                      n_cells=len(cells), n_kept=len(claims))
        except Exception:
            pass
    return claims
