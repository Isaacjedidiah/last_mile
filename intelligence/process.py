"""Process pipeline: intelligent_guide + gold -> a team's intelligent_gold.

For a given team:
  1. read the team's LATEST config (schema, mapping, dictionary) from the
     intelligent_guide table (via resolve_latest),
  2. read the current gold table,
  3. apply the mapping ENGINE to every gold row (routed by modality),
  4. FULL REBUILD the team's intelligent_gold table (overwrite -- it is a derived
     view of gold + the team's current config, so a full rebuild is deterministic),
  5. write rows that could not fully map to a review table.

No LLM, no extraction -- pure deterministic transformation of gold using the
team's declared config.
"""
from __future__ import annotations

from typing import Optional

from .config_model import resolve_latest
from .mapping_engine import (build_intelligence_row, index_mappings,
                             build_dictionary)


def _collect_rows(df):
    """Spark DataFrame -> list[dict] (small configs; gold is read via Spark)."""
    return [r.asDict(recursive=True) for r in df.collect()]


def resolve_team_config(guide_rows: list[dict], team_id: str):
    """Return (schema_cols, mapping_index, dictionary, required_cols) for a team,
    from raw intelligent_guide rows."""
    schemas = resolve_latest(guide_rows, team_id, "schema")
    mappings = resolve_latest(guide_rows, team_id, "mapping")
    dicts = resolve_latest(guide_rows, team_id, "dictionary")

    # ordered schema columns
    schema_cols = [s["definition"].get("column_name") for s in schemas
                   if s.get("definition", {}).get("column_name")]
    # required columns: schema entries flagged required (default: none required)
    required = {s["definition"]["column_name"] for s in schemas
                if s.get("definition", {}).get("required")}
    mapping_index = index_mappings(mappings)
    dictionary = build_dictionary(dicts)
    return schema_cols, mapping_index, dictionary, required


def build_team_intelligence(spark, gold_table: str, guide_table: str,
                             team_id: str, out_table: str,
                             review_table: Optional[str] = None,
                             gold_filter: Optional[str] = None) -> dict:
    """Build a team's intelligent_gold from gold + their config.

    spark        : SparkSession
    gold_table   : the source gold table (fully-qualified)
    guide_table  : the intelligent_guide table (fully-qualified)
    team_id      : which team's config to apply
    out_table    : the team's intelligent_gold table (fully-qualified) -- OVERWRITTEN
    review_table : optional table for rows that did not fully map
    gold_filter  : optional SQL WHERE (e.g. "team = 'FX'") to scope the gold rows
    Returns {rows_in, rows_out, flagged, columns}.
    """
    # 1. team config
    guide_rows = _collect_rows(spark.table(guide_table))
    schema_cols, mapping_index, dictionary, required = \
        resolve_team_config(guide_rows, team_id)
    if not schema_cols:
        return {"rows_in": 0, "rows_out": 0, "flagged": 0, "columns": [],
                "note": "no schema defined for team"}

    # 2. gold rows
    gdf = spark.table(gold_table)
    if gold_filter:
        gdf = gdf.where(gold_filter)
    gold_rows = _collect_rows(gdf)

    # 3. apply the engine
    out_rows, flagged_rows = [], []
    for gr in gold_rows:
        ir = build_intelligence_row(gr, mapping_index, schema_cols,
                                    dictionary, required_cols=required)
        ir["team_id"] = team_id
        if ir.get("_mapped_ok"):
            out_rows.append(ir)
        else:
            flagged_rows.append(ir)
    # rows that mapped partially still go to intelligent_gold (what mapped is
    # useful); the review table lists the ones with UNMAPPED REQUIRED columns.
    all_rows = out_rows + flagged_rows

    # 4. FULL REBUILD the team's intelligent_gold (overwrite)
    if all_rows:
        # normalise: every row has the same keys (union), JSON-safe
        keys = []
        for r in all_rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        norm = []
        for r in all_rows:
            nr = {}
            for k in keys:
                v = r.get(k)
                # list -> string for the _unmapped column
                nr[k] = ",".join(v) if isinstance(v, list) else v
            norm.append(nr)
        (spark.createDataFrame(norm).write.format("delta")
         .mode("overwrite").option("overwriteSchema", "true")
         .saveAsTable(out_table))

    # 5. review table (rows with unmapped REQUIRED columns)
    if review_table and flagged_rows:
        rev = []
        for r in flagged_rows:
            rev.append({"team_id": team_id,
                        "doc_id": r.get("doc_id"),
                        "source_document": r.get("source_document"),
                        "page": r.get("page"),
                        "canonical_metric": r.get("canonical_metric"),
                        "element_type": r.get("element_type"),
                        "unmapped_columns": ",".join(r.get("_unmapped") or [])})
        (spark.createDataFrame(rev).write.format("delta")
         .mode("overwrite").option("overwriteSchema", "true")
         .saveAsTable(review_table))

    return {"rows_in": len(gold_rows), "rows_out": len(all_rows),
            "flagged": len(flagged_rows), "columns": schema_cols}
