"""Run this on YOUR confidential table blobs (data stays in your environment).
Paste a blob into HTML, or read it from your gold/bronze table, and see the
browser-faithful extraction. Compare it to how the table renders in Jupyter.
"""
import sys
# point this at your deployed package
# sys.path.insert(0, "/Workspace/Repos/<you>/preprocessing_etl")
from preprocessing_etl.custom.browser_table import browser_table_to_claims

# a lightweight claim holder so you can run this without the full schema
class Claim:
    def __init__(self, **k):
        for key, val in k.items(): setattr(self, key, val)

# ---- OPTION A: paste a blob here ----
BLOB = """<paste one of your complex table HTML blobs here>"""

# ---- OPTION B: read a real blob from a table (uncomment) ----
# row = spark.sql("SELECT content FROM <bronze_or_gold> WHERE element_type='table' LIMIT 1").collect()[0]
# BLOB = row["content"]

claims = browser_table_to_claims(BLOB, "test.pdf", page=1, title="TEST", claim_cls=Claim)
print(f"extracted {len(claims)} claims:\n")
for c in claims:
    print(f"  {c.canonical_metric} = {c.value}")

# compare the count + a few values to how the table renders in Jupyter.
# if they match the rendered table, the browser-faithful parser works on your data.
