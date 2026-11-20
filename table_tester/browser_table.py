"""Browser-faithful HTML table extraction.

Discovery: ai_parse's HTML blobs for complex tables render at 95-100% fidelity in
a browser (Jupyter) -- colspan/rowspan and all. So the HTML is SOUND; the earlier
parsers were mishandling merges a browser resolves correctly. This module
replicates what the BROWSER does to lay out the table:

  1. parse the HTML with html5lib (the browser's own HTML5 parser) -> a DOM that
     matches what the browser built;
  2. expand every colspan/rowspan into an explicit CELL GRID -- a merged cell
     occupies (and its value fills) every grid position it spans, exactly as the
     browser renders it;
  3. read the grid: top rows = column headers (multi-level joined), left columns =
     row labels (nested, "Header: text" like ai_parse_structurer), each numeric
     body cell -> one claim.

Deterministic, no model. Output matches ai_parse_structurer's canonical format
(title | section | Header: row | ... | column) so these tables look identical to
the rest. Falls back cleanly (returns []) if html5lib isn't available or the HTML
has no table, so the caller can use the existing chain.
"""
from __future__ import annotations

import re
from typing import Optional

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _num_like(s) -> bool:
    t = str(s or "").strip()
    return bool(t) and bool(_NUM.search(t)) and not re.search(r"[A-Za-z]{2,}", t)


def _parse_dom(html: str):
    """Parse the HTML the way the browser does. Prefer html5lib (browser-grade);
    fall back to lxml, then Python's stdlib HTMLParser-based builder. Returns a
    list of <table> element trees, or []."""
    # 1. html5lib via BeautifulSoup (closest to the browser)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html5lib")
        tables = soup.find_all("table")
        if tables:
            return ("bs4", tables)
    except Exception:
        pass
    # 2. lxml.html
    try:
        import lxml.html as LH
        root = LH.fromstring(html)
        tables = root.xpath("//table")
        if tables:
            return ("lxml", tables)
    except Exception:
        pass
    return (None, [])


def _cells_bs4(table):
    """Yield rows of cells from a bs4 table; each cell = (text, colspan, rowspan, is_header)."""
    rows = []
    for tr in table.find_all("tr"):
        cells = []
        for cell in tr.find_all(["td", "th"]):
            txt = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
            cs = int(cell.get("colspan", 1) or 1)
            rs = int(cell.get("rowspan", 1) or 1)
            cells.append((txt, max(1, cs), max(1, rs), cell.name == "th"))
        if cells:
            rows.append(cells)
    return rows


def _cells_lxml(table):
    rows = []
    for tr in table.xpath(".//tr"):
        cells = []
        for cell in tr.xpath("./td | ./th"):
            txt = re.sub(r"\s+", " ", (cell.text_content() or "")).strip()
            cs = int(cell.get("colspan", 1) or 1)
            rs = int(cell.get("rowspan", 1) or 1)
            tag = cell.tag
            cells.append((txt, max(1, cs), max(1, rs), tag == "th"))
        if cells:
            rows.append(cells)
    return rows


def _build_grid(rowcells):
    """Expand colspan/rowspan into a full grid, exactly as a browser lays it out.
    Returns (grid, is_header_grid): grid[r][c] = text (merged values repeat across
    every spanned position); is_header_grid[r][c] = bool (was it a <th>)."""
    grid: dict = {}
    hdr: dict = {}
    # pending rowspans: col -> (text, remaining_rows, is_header)
    carry: dict = {}
    n_rows = len(rowcells)
    max_col = 0
    for r in range(n_rows):
        c = 0
        cells = rowcells[r]
        ci = 0
        # place any carried (rowspan) cells first / in order by scanning columns
        while ci < len(cells) or any(v[1] > 0 for v in carry.values()):
            # if a carried cell occupies this column, place it and move on
            if c in carry and carry[c][1] > 0:
                txt, rem, ish = carry[c]
                grid[(r, c)] = txt
                hdr[(r, c)] = ish
                carry[c] = (txt, rem - 1, ish)
                c += 1
                continue
            if ci >= len(cells):
                c += 1
                if c > max_col + 50:
                    break
                continue
            txt, cs, rs, ish = cells[ci]
            ci += 1
            for dc in range(cs):
                grid[(r, c + dc)] = txt
                hdr[(r, c + dc)] = ish
                if rs > 1:
                    carry[c + dc] = (txt, rs - 1, ish)
            c += cs
        max_col = max(max_col, c)
    # decrement spent carries each row is handled above; normalise to rectangular
    n_cols = (max(k[1] for k in grid) + 1) if grid else 0
    return grid, hdr, n_rows, n_cols


def _header_row_count(hdr, n_rows, n_cols):
    """How many leading rows are all-header (<th>) -> the column-header band."""
    hr = 0
    for r in range(n_rows):
        cells = [hdr.get((r, c), False) for c in range(n_cols)]
        if cells and all(cells):
            hr += 1
        else:
            break
    return max(hr, 1) if n_rows > 1 else 1   # at least the top row is headers


def _label_col_count(grid, hdr, header_rows, n_rows, n_cols):
    """How many leading columns are row LABELS (non-numeric in the body)."""
    lc = 0
    for c in range(n_cols):
        body_vals = [grid.get((r, c), "") for r in range(header_rows, n_rows)]
        if body_vals and not any(_num_like(v) for v in body_vals):
            lc += 1
        else:
            break
    return lc


def browser_table_to_claims(html, filename, *, page=None, title=None, team=None,
                            report_type=None, entity_ref=None, claim_cls=None,
                            element_id=None):
    """Extract claims from an HTML table the BROWSER way (html5lib + colspan/
    rowspan grid expansion). canonical_metric = title | <Header: row labels> |
    <column header path>, matching ai_parse_structurer. Returns [] if it can't
    parse (caller falls back). Deterministic, no model."""
    if claim_cls is None:
        from ..shared.schema import Claim as claim_cls
    if not html or "<" not in html:
        return []
    flavor, tables = _parse_dom(html)
    if not tables:
        return []
    claims = []
    for table in tables:
        rowcells = _cells_bs4(table) if flavor == "bs4" else _cells_lxml(table)
        if not rowcells:
            continue
        grid, hdr, n_rows, n_cols = _build_grid(rowcells)
        if n_rows < 2 or n_cols < 2:
            continue
        header_rows = _header_row_count(hdr, n_rows, n_cols)
        label_cols = _label_col_count(grid, hdr, header_rows, n_rows, n_cols)
        if label_cols == 0:
            label_cols = 1                      # assume the first col is labels

        # column header path per column = the header-band cells joined
        col_header = {}
        for c in range(n_cols):
            parts = []
            for r in range(header_rows):
                t = grid.get((r, c), "")
                if t and (not parts or parts[-1] != t):
                    parts.append(t)
            col_header[c] = " ".join(parts).strip()

        # each body row: row labels (Header: text) + each numeric value cell
        for r in range(header_rows, n_rows):
            row_ids = []
            for c in range(label_cols):
                t = grid.get((r, c), "")
                if not t:
                    continue
                h = col_header.get(c, "")
                row_ids.append(f"{h}: {t}" if h else t)
            for c in range(label_cols, n_cols):
                val = grid.get((r, c), "")
                if not _num_like(val):
                    continue
                col = col_header.get(c, "")
                parts = [x for x in ([title] + row_ids + [col]) if x]
                name = " | ".join(parts) if parts else (col or "value")
                try:
                    from .ai_parse_structurer import _split_currency_unit as _scu
                    _cur, _un = _scu(val)
                except Exception:
                    _cur, _un = (None, None)
                try:
                    claims.append(claim_cls(
                        field_name=(col or "value"), canonical_metric=name,
                        value=str(val).strip(), unit=_un, currency=_cur,
                        source_document=filename, page=page, team=team,
                        report_type=report_type, entity_ref=entity_ref,
                        element_type="table", element_id=element_id,
                        model_used="browser_grid"))
                except Exception:
                    continue
    return claims
