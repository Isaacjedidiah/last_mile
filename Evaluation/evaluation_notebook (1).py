# Databricks notebook source
# ============================================================================
# PIPELINE EVALUATION NOTEBOOK  (deterministic, no LLM)
#
# Reads the pipeline's STORED claims (gold/silver) + your GROUND-TRUTH CSV, and
# reports precision / recall / accuracy / F1 -- overall AND per modality
# (table / figure / text). Matching is Option A (document + page + fuzzy field +
# value; exact for table/text, within tolerance for charts).
#
# FILL the ground-truth CSV first (ground_truth_template.csv): one row per value
# you know the correct answer for. positives (should_extract=TRUE) and a few
# decoys (should_extract=FALSE, e.g. axis numbers) make precision meaningful.
# ============================================================================

# COMMAND ----------
# ---- CONFIG: point these at your tables + ground-truth file ----
GOLD_TABLE       = "<catalog>.<schema>.gold"          # the claims to evaluate
GROUND_TRUTH_CSV = "/Volumes/<...>/ground_truth.csv"  # your filled template
CHART_TOL        = 0.03                                 # chart value tolerance (3%)

# COMMAND ----------
# ---- load the ground truth (CSV -> list of dict rows) ----
import csv
truth_rows = []
# on Databricks you may read via spark; a local CSV works too:
try:
    gt = spark.read.option("header", True).csv(GROUND_TRUTH_CSV)
    truth_rows = [r.asDict() for r in gt.collect()]
except Exception:
    with open(GROUND_TRUTH_CSV, newline="") as f:
        truth_rows = list(csv.DictReader(f))
# normalise page to int where possible
for t in truth_rows:
    try:
        t["page"] = int(t["page"])
    except Exception:
        pass
print(f"ground-truth rows: {len(truth_rows)} "
      f"({sum(1 for t in truth_rows if str(t.get('should_extract','')).strip().lower() in ('true','1','yes','y'))} positives)")

# COMMAND ----------
# ---- load the pipeline's claims from gold (as lightweight objects) ----
class _C:
    def __init__(self, d):
        self.canonical_metric = d.get("canonical_metric")
        self.field_name = d.get("field_name")
        self.value = d.get("value")
        self.page = d.get("page")
        self.element_type = d.get("element_type")
        self.source_document = d.get("source_document")

gold = spark.table(GOLD_TABLE)
claims = [_C(r.asDict()) for r in gold.collect()]
print(f"claims loaded: {len(claims)}")

# COMMAND ----------
# ---- evaluate (deterministic, no LLM) ----
import sys
# ensure the package is importable (adjust the path to your deployed package)
# sys.path.insert(0, "/Workspace/Repos/<you>/preprocessing_etl")
from preprocessing_etl.custom.evaluation_suite import evaluate_accuracy

result = evaluate_accuracy(claims, truth_rows, chart_tol=CHART_TOL)

# COMMAND ----------
# ---- report ----
def _pct(x):
    return f"{x*100:.1f}%" if isinstance(x, (int, float)) else "n/a"

o = result["overall"]
print("=== OVERALL ===")
print(f"  TP={o['TP']} FP={o['FP']} FN={o['FN']} TN={o['TN']}")
print(f"  precision={_pct(o['precision'])}  recall={_pct(o['recall'])}  "
      f"accuracy={_pct(o['accuracy'])}  F1={_pct(o['f1'])}")

print("\n=== PER MODALITY ===")
for ty, m in result["by_element_type"].items():
    print(f"  [{ty}] precision={_pct(m['precision'])}  recall={_pct(m['recall'])}  "
          f"accuracy={_pct(m['accuracy'])}  F1={_pct(m['f1'])}  "
          f"(TP={m['TP']} FP={m['FP']} FN={m['FN']})")

print(f"\n=== MISSED (false negatives): {len(result['missed'])} ===")
for m in result["missed"][:20]:
    print(f"  {m['document']} p{m['page']}: {m['field']} = {m['value']}")

print(f"\n=== FALSE POSITIVES: {len(result['false_positives'])} ===")
for m in result["false_positives"][:20]:
    print(f"  {m['document']} p{m['page']}: {m['field']} = {m['value']}")

# COMMAND ----------
# ---- (optional) save the metrics to a table for tracking over time ----
# import datetime, json
# rows = [{"run_at": datetime.datetime.utcnow().isoformat(),
#          "scope": "overall", **o}]
# for ty, m in result["by_element_type"].items():
#     rows.append({"run_at": datetime.datetime.utcnow().isoformat(), "scope": ty, **m})
# spark.createDataFrame(rows).write.format("delta").mode("append").saveAsTable("<...>.eval_metrics")
