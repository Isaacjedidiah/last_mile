# Entry point for Databricks Apps. Launches the Streamlit intelligence app.
import os, sys, runpy
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
runpy.run_path(
    os.path.join(_ROOT, "preprocessing_etl", "intelligence", "app", "intelligence_app.py"),
    run_name="__main__")
