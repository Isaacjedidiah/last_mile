# Databricks notebook source
# ============================================================================
# PIPELINE EVALUATION NOTEBOOK  (deterministic, no LLM)
#
# Reports BOTH:
#   A) ACCURACY  -- precision / recall / accuracy / F1, overall AND per modality
#      (table / figure / text), from your ground-truth CSV. Matching is
#      VALUE-PRIMARY (document + page + value; field name only disambiguates
#      repeated values), so a correct value with a differently-formatted field is
#      NOT counted as a miss.
#   B) COVERAGE  -- did we PROCESS every page? pages processed (from the chunk
#      index) / total pages (counted from the raw files), per document, FLAGGING
#      pages that were skipped. This answers "did we cover everything".
# ============================================================================

# COMMAND ----------
# ---- CONFIG ----
GOLD_TABLE        = "<catalog>.<schema>.gold"            # claims to evaluate
CHUNK_TABLE       = "<catalog>.<schema>.chunks"          # the search index chunks (for coverage)
GROUND_TRUTH_CSV  = "/Volumes/<...>/ground_truth.csv"    # your filled template (CSV or XLSX)
ENTITY_REF        = None                                  # optional: filter to one entity's docs
CHART_TOL         = 0.03

# the documents being evaluated + their raw file paths (for the TRUE page count)
# {document_name: raw_file_path}  -- path used to count real pages (catches pages
# ai_parse itself skipped).
SUBMISSIONS = {
    # "Example_Report_2026": "/Volumes/<...>/Example_Report_2026.pdf",
}

# COMMAND ----------
# ---- load ground truth (CSV or XLSX) ----
truth_rows = []
if GROUND_TRUTH_CSV.lower().endswith((".xlsx", ".xls")):
    import pandas as pd
    _df = pd.read_excel(GROUND_TRUTH_CSV.replace("/Volumes", "/dbfs/Volumes"))
    truth_rows = _df.to_dict("records")
else:
    try:
        gt = spark.read.option("header", True).csv(GROUND_TRUTH_CSV)
        truth_rows = [r.asDict() for r in gt.collect()]
    except Exception:
        import csv
        with open(GROUND_TRUTH_CSV.replace("/Volumes", "/dbfs/Volumes"), newline="") as f:
            truth_rows = list(csv.DictReader(f))
for t in truth_rows:
    try: t["page"] = int(t["page"])
    except Exception: pass
_pos = sum(1 for t in truth_rows if str(t.get("should_extract","")).strip().lower() in ("true","1","yes","y"))
print(f"ground-truth rows: {len(truth_rows)}  (positives: {_pos}  decoys: {len(truth_rows)-_pos})")

# COMMAND ----------
# ---- load claims from gold ----
class _C:
    def __init__(self, d):
        self.canonical_metric=d.get("canonical_metric"); self.field_name=d.get("field_name")
        self.value=d.get("value"); self.page=d.get("page")
        self.element_type=d.get("element_type"); self.source_document=d.get("source_document")
gdf = spark.table(GOLD_TABLE)
if ENTITY_REF:
    gdf = gdf.filter(gdf.entity_ref == ENTITY_REF)
claims = [_C(r.asDict()) for r in gdf.collect()]
print(f"claims: {len(claims)}")

# COMMAND ----------
# ---- ACCURACY ----
import sys
# sys.path.insert(0, "/Workspace/Repos/<you>/preprocessing_etl")
from preprocessing_etl.custom.evaluation_suite import (
    evaluate_accuracy, evaluate_coverage, count_pages, full_report)

accuracy = evaluate_accuracy(claims, truth_rows, chart_tol=CHART_TOL)

# COMMAND ----------
# ---- COVERAGE: did we process EVERY page? ----
from preprocessing_etl.custom.evaluation_suite import total_pages_from_chunks
# pages the pipeline PROCESSED, from the chunk index
cdf = spark.table(CHUNK_TABLE)
if ENTITY_REF:
    cdf = cdf.filter(cdf.entity_ref == ENTITY_REF)
chunk_rows = [r.asDict() for r in cdf.select("source_document_id", "page").collect()]
print(f"chunk rows: {len(chunk_rows)}")

# total pages: from the RAW files if SUBMISSIONS is filled (stricter -- catches
# trailing pages that produced no chunk); else derived from the chunks' max page
# per document (no raw files needed; detects GAPS in the page sequence).
if SUBMISSIONS:
    total_pages_by_doc = {}
    for doc, path in SUBMISSIONS.items():
        n = count_pages(path)
        if n:
            total_pages_by_doc[doc] = n
    print(f"total pages from raw files: {total_pages_by_doc}")
else:
    total_pages_by_doc = total_pages_from_chunks(chunk_rows)
    print(f"total pages derived from chunks (max page per doc): {total_pages_by_doc}")
    print("  (to also catch trailing skipped pages, fill SUBMISSIONS with raw paths)")

coverage = evaluate_coverage(chunk_rows, total_pages_by_doc) if total_pages_by_doc else None
if not total_pages_by_doc:
    print("Coverage: no documents found in the chunk table "
          "(check CHUNK_TABLE + ENTITY_REF).")

# COMMAND ----------
# ---- FULL REPORT (accuracy + coverage, with MISSING-PAGE flags) ----
print(full_report(accuracy=accuracy, coverage=coverage))

# COMMAND ----------
# ---- explicit coverage check: anything skipped? ----
if coverage:
    miss = {d: v for d, v in coverage["page_coverage"].items() if v["missing_pages"]}
    if miss:
        print("\n*** NOT FULLY COVERED \u2014 pages were skipped: ***")
        for d, v in miss.items():
            print(f"  {d}: processed {v['pages_processed']}/{v['total_pages']} "
                  f"\u2192 {v['missing_pages']} page(s) MISSING")
    else:
        print(f"\n\u2713 FULL COVERAGE: all {coverage['total_pages']} pages processed.")
