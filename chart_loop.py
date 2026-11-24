"""Chart extraction RETRY LOOP — solves INTERMITTENT SKIPS only.

Sonnet is non-deterministic: it returns nothing for a crop on one run but reads
it on another. This loop retries each crop (fresh, independent reads) until it
produces points OR a pass limit is reached; whatever never reads goes to review.

It uses the SAME proven chart extraction as the inline path (the caller passes a
read function built on CHART_DIGITISATION_PROMPT). No self-review — each read is a
fresh attempt, success judged OBJECTIVELY (did it return points), never by
Sonnet's opinion of its own work.

This module is ONLY about the skip problem. Shared-legend / colour-join is a
SEPARATE concern and is deliberately NOT handled here.

Flow per document:
    for pass in 1..MAX_PASSES:
        for crop still pending:
            points = read_fn(crop)          # proven read (CHART_DIGITISATION_PROMPT)
            if points: emit claims, done    # move out of pending
            # else: keep for the next pass
        if none pending: break
    pending after the loop -> on_unresolved (human review)
"""
from __future__ import annotations

from typing import Callable, Optional

MAX_PASSES = 6          # retry a crop across at most this many passes


def run_chart_loop(page_crops, read_fn, on_extracted=None, on_unresolved=None,
                   max_passes=MAX_PASSES, audit=None, run_id=None, document=None):
    """Retry-until-read loop over chart crops. Pure skip handling.

    page_crops : list of crop dicts; each must carry what read_fn/on_extracted
                 need (e.g. crop_b64, page, figure_index, el).
    read_fn(crop) -> points list (truthy) or falsy. MUST use the proven chart
                 read (CHART_DIGITISATION_PROMPT) so loop extraction == inline
                 extraction. A fresh call each time (no memory, no self-review).
    on_extracted(crop, points) : emit claims for a crop that read.
    on_unresolved(crop, reason): a crop that never read after max_passes.
    Returns {extracted, unresolved, passes_used}.
    """
    pending = list(page_crops)
    extracted = 0
    passes_used = 0
    for _pass in range(1, max_passes + 1):
        if not pending:
            break
        passes_used = _pass
        still = []
        for crop in pending:
            try:
                pts = read_fn(crop)
            except Exception:
                pts = None
            if pts:
                extracted += 1
                if on_extracted:
                    on_extracted(crop, pts)
                if audit is not None:
                    try:
                        audit.log(run_id or "", "chart_read",
                                  f"{document}-p{crop.get('page')}-fig{crop.get('figure_index')}",
                                  document=document, page=crop.get("page"),
                                  figure_index=crop.get("figure_index"),
                                  outcome="extracted", n_points=len(pts),
                                  pass_no=_pass)
                    except Exception:
                        pass
            else:
                still.append(crop)
        pending = still

    for crop in pending:
        reason = f"unresolved_after_{passes_used}_passes"
        if on_unresolved:
            on_unresolved(crop, reason)
        if audit is not None:
            try:
                audit.log(run_id or "", "chart_read",
                          f"{document}-p{crop.get('page')}-fig{crop.get('figure_index')}",
                          document=document, page=crop.get("page"),
                          figure_index=crop.get("figure_index"),
                          outcome="unresolved", n_points=0, reason=reason)
            except Exception:
                pass

    return {"extracted": extracted, "unresolved": len(pending),
            "passes_used": passes_used}


def run_chart_loop_concurrent(page_crops, async_read_fn, run_async_fn,
                              on_extracted=None, on_unresolved=None,
                              max_passes=MAX_PASSES, concurrency=5,
                              audit=None, run_id=None, document=None):
    """Same retry-until-read loop, but each PASS reads its pending crops
    CONCURRENTLY (bounded by `concurrency`) instead of one at a time. Accuracy is
    unchanged (reads are independent); only the serial waiting is removed -- the
    win for documents with many charts.

    async_read_fn(crop) -> awaitable yielding points (truthy) or falsy. Must use
                 the proven chart read so output == the sequential loop.
    run_async_fn(coro) -> runs one coroutine to completion (the caller's runner).
    """
    from .chart_concurrency import read_crops_concurrently

    pending = list(page_crops)
    extracted = 0
    passes_used = 0
    for _pass in range(1, max_passes + 1):
        if not pending:
            break
        passes_used = _pass
        # FIRST pass: concurrent (fast on many charts). RETRY passes: sequential
        # (concurrency=1) -- the stubborn charts get a clean, unpressured read,
        # which reduces spurious empty results before falling back.
        _conc = concurrency if _pass == 1 else 1
        results = run_async_fn(
            read_crops_concurrently(pending, async_read_fn, concurrency=_conc))
        still = []
        for crop, pts in zip(pending, results):
            if isinstance(pts, Exception):
                pts = None
            if pts:
                extracted += 1
                if on_extracted:
                    on_extracted(crop, pts)
                if audit is not None:
                    try:
                        audit.log(run_id or "", "chart_read",
                                  f"{document}-p{crop.get('page')}-fig{crop.get('figure_index')}",
                                  document=document, page=crop.get("page"),
                                  figure_index=crop.get("figure_index"),
                                  outcome="extracted", n_points=len(pts),
                                  pass_no=_pass)
                    except Exception:
                        pass
            else:
                still.append(crop)
        pending = still

    for crop in pending:
        reason = f"unresolved_after_{passes_used}_passes"
        if on_unresolved:
            on_unresolved(crop, reason)
        if audit is not None:
            try:
                audit.log(run_id or "", "chart_read",
                          f"{document}-p{crop.get('page')}-fig{crop.get('figure_index')}",
                          document=document, page=crop.get("page"),
                          figure_index=crop.get("figure_index"),
                          outcome="unresolved", n_points=0, reason=reason)
            except Exception:
                pass

    return {"extracted": extracted, "unresolved": len(pending),
            "passes_used": passes_used}
#####£

def _num_like_fallback(v):
    import re as _re
    return bool(_re.search(r"-?\d", str(v)))


def ai_parse_figure_to_claims(el, filename, *, title=None, team=None,
                              report_type=None, entity_ref=None, claim_cls=None):
    """Build claims from ai_parse's OWN figure extraction (el.content), used as a
    FALLBACK when Sonnet returns nothing after the chart loop. CONTENT ONLY --
    ai_parse's description is noisy prose for charts; the structured values live in
    content. Robust to several content shapes: {series:{label:num}},
    {series:[nums]}, flat {label:num}, and a list of point dicts under
    values/data/series/points/datasets. Tagged ai_parse_fallback."""
    import json as _json
    from ..shared.schema import CitationTier

    # CONTENT ONLY (per preference: description is noisy prose for charts).
    _content = getattr(el, "content", None)
    if not _content:
        return []
    sources = [_content]

    def _emit(series, label, num, chart_title, out):
        if num is None or not _num_like_fallback(num):
            return
        _series = str(series or "").strip()
        _label = str(label or "").strip()
        parts = [p for p in (title or chart_title, _series, _label) if p]
        canon = "-".join(parts) if parts else (f"{_series}-{_label}".strip("-") or "value")
        try:
            out.append(claim_cls(
                field_name=(f"{_series} {_label}".strip() or "value"),
                canonical_metric=canon, value=str(num),
                source_document=filename, page=getattr(el, "page", None),
                team=team, report_type=report_type, entity_ref=entity_ref,
                element_type="figure", element_id=getattr(el, "element_id", None),
                model_used="ai_parse_fallback",
                citation_tier=CitationTier.AI_PARSE_FALLBACK.value))
        except Exception:
            pass

    def _extract(source):
        try:
            data = _json.loads(source) if isinstance(source, str) else source
        except Exception:
            data = None
        if not isinstance(data, dict):
            # content is plain text -> try the text parser
            try:
                from .ai_parse_structurer import chart_description_to_claims
                return chart_description_to_claims(
                    str(source), filename, page=getattr(el, "page", None),
                    title=title, team=team, report_type=report_type,
                    entity_ref=entity_ref) or []
            except Exception:
                return []
        chart_title = str(data.get("title") or "").strip()
        if chart_title.lower() in ("none", "null", "n/a", ""):
            chart_title = ""
        # find the values block under any common key
        values = None
        for _k in ("values", "data", "series", "points", "datasets"):
            if isinstance(data.get(_k), (dict, list)):
                values = data.get(_k)
                break
        if values is None:
            try:
                from .ai_parse_structurer import chart_description_to_claims
                _txt = str(data.get("description") or data.get("text") or source)
                return chart_description_to_claims(
                    _txt, filename, page=getattr(el, "page", None),
                    title=title, team=team, report_type=report_type,
                    entity_ref=entity_ref) or []
            except Exception:
                return []
        out = []
        if isinstance(values, dict):
            for series, series_vals in values.items():
                if isinstance(series_vals, dict):
                    for label, num in series_vals.items():       # {series:{label:num}}
                        _emit(series, label, num, chart_title, out)
                elif isinstance(series_vals, list):
                    for i, num in enumerate(series_vals):        # {series:[nums]}
                        _emit(series, i, num, chart_title, out)
                else:
                    _emit("", series, series_vals, chart_title, out)  # flat
        elif isinstance(values, list):
            for item in values:
                if isinstance(item, dict):
                    _s = item.get("series") or item.get("name") or ""
                    _l = item.get("label") or item.get("x") or item.get("category") or ""
                    _n = item.get("value") if "value" in item else item.get("y")
                    _emit(_s, _l, _n, chart_title, out)
        return out

    for src in sources:
        got = _extract(src)
        if got:
            return got
    return []

#### 
[theme]
# a clean, professional light theme -- fixes white-on-white menus/toolbar
base = "light"
primaryColor = "#2E6DA4"            # buttons, accents (blue)
backgroundColor = "#FFFFFF"         # main canvas
secondaryBackgroundColor = "#F1F5FA" # sidebar, cards, inputs (soft blue-grey)
textColor = "#1F2933"              # dark text (fixes invisible white text)
font = "sans serif"

[server]
headless = true
