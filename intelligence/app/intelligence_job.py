"""Intelligence Job entry -- the HEAVY Spark processing, triggered by the app.

Databricks Apps have no Spark, so the app (UI + config save via SQL) triggers
THIS job to do the Spark work: build the team's intelligent_gold, and rewrite any
key-mapping user table. Runs on a cluster/job compute that HAS Spark.

Job notebook params (set by the app via run_now):
  team_id       the team whose config to apply
  guide_table   the intelligent_guide table
  gold_table    the source gold table
  out_table     the intelligent_gold output table
  user_table    (optional) the key-mapping distinct table to rewrite
"""
from __future__ import annotations


def run(team_id: str, guide_table: str, gold_table: str, out_table: str,
        user_table: str = None) -> dict:
    """Apply a team's config to gold -> intelligent_gold, and rewrite the
    key-mapping user table if requested. Spark is available here."""
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    result = {}

    # 1. build intelligent_gold from the team's config
    from preprocessing_etl.intelligence.process import build_team_intelligence
    result["intelligence"] = build_team_intelligence(
        spark, guide_table=guide_table, gold_table=gold_table,
        team_id=team_id, out_table=out_table)

    # 2. rewrite the key-mapping user table (if a mapping + table are set)
    if user_table:
        from preprocessing_etl.intelligence.storage import latest_team_config
        from preprocessing_etl.intelligence.key_mapping import rewrite_user_table
        cfg = latest_team_config(spark, guide_table, team_id)
        key_maps = cfg.get("key_mapping", [])
        if key_maps:
            n = rewrite_user_table(spark, gold_table, user_table, key_maps)
            result["user_table_rows"] = n

    return result


if __name__ == "__main__":
    # Databricks job: read params from the widgets and run.
    try:
        dbutils  # type: ignore
    except NameError:
        dbutils = None
    def _p(name, default=None):
        try:
            return dbutils.widgets.get(name)
        except Exception:
            return default
    run(team_id=_p("team_id"), guide_table=_p("guide_table"),
        gold_table=_p("gold_table"), out_table=_p("out_table"),
        user_table=_p("user_table") or None)
