"""Extraction JOB entry point — the Databricks Job the front-end app triggers.

The app (extraction_app.py) calls jobs.run_now with these job parameters:
    volume_link    -- where the documents are
    img_out        -- where images/sharpened/crops/missed go
    target_space   -- <catalog>.<schema> for the output tables
    access_tier    -- access | limited | restricted (the write cascade)
    requested_by   -- the user (audit)

This script reads them (dbutils widgets), builds the storage with the access_tier
set (so writes cascade to the tier tables), and runs the extraction. Deploy this
as a Databricks Job task; set EXTRACTION_JOB_ID in the app to that job's id.

It does NOT collect credentials -- the job runs under its own identity / the
app's service principal.
"""
from __future__ import annotations


def main():
    # Databricks injects spark + dbutils in a job task.
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    try:
        dbutils  # type: ignore  # injected
    except NameError:
        from pyspark.dbutils import DBUtils
        dbutils = DBUtils(spark)

    # --- read job parameters ---
    def _p(name, default=""):
        try:
            return dbutils.widgets.get(name)
        except Exception:
            return default

    volume_link = _p("volume_link")
    img_out = _p("img_out")
    target_space = _p("target_space")          # <catalog>.<schema>
    access_tier = _p("access_tier", "restricted")
    requested_by = _p("requested_by")

    # --- point config at the target space (catalog.schema) ---
    from preprocessing_etl.shared.config import CONFIG
    if target_space and "." in target_space:
        cat, sch = target_space.split(".", 1)
        CONFIG.storage.catalog = cat
        CONFIG.storage.schema = sch

    # --- build storage WITH the access tier (writes cascade to tier tables) ---
    from preprocessing_etl.custom.storage import DeltaLakeStorage
    storage = DeltaLakeStorage(spark=spark, access_tier=access_tier)

    # --- discover submissions under the volume (team/report from the folder) ---
    from preprocessing_etl.custom.ai_parse_pipeline import (
        run_ai_parse_batch, SCOPED_STORES)
    submissions = _discover_submissions(dbutils, volume_link)

    # --- run the extraction (scoped indexing + chart loop + sharpening on) ---
    result = run_ai_parse_batch(
        spark, submissions, storage,
        use_sonnet=True, image_output_path=img_out, dbutils=dbutils,
        use_chart_loop=True, resolve_shared_legend=False,
        search_store=SCOPED_STORES, sharpen_pdfs=True)

    print(f"Extraction complete for {requested_by}: "
          f"{getattr(result, 'documents', '?')} docs, tier={access_tier}")
    return result


def _discover_submissions(dbutils, volume_link):
    """List documents under the volume and derive team/report_type from the folder
    layout. Expected: <volume>/<team>/<report_type>/<files>. Adjust to your layout.
    """
    subs = []
    try:
        for team_entry in dbutils.fs.ls(volume_link):
            if not team_entry.isDir():
                continue
            team = team_entry.name.strip("/")
            for rpt_entry in dbutils.fs.ls(team_entry.path):
                if not rpt_entry.isDir():
                    continue
                report_type = rpt_entry.name.strip("/")
                for f in dbutils.fs.ls(rpt_entry.path):
                    if f.isDir():
                        continue
                    subs.append({"path": f.path, "team": team,
                                 "report_type": report_type,
                                 "entity_ref": None})
    except Exception as e:
        print("submission discovery error:", e)
    return subs


if __name__ == "__main__":
    main()
