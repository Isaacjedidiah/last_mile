"""Databricks SQL connector for the intelligence app running on Databricks Apps.

Databricks Apps are SERVERLESS and do NOT include pyspark / a SparkSession
(hence "No module named pyspark"). The Apps-native way to read and write Unity
Catalog tables is the databricks-sql-connector against a SQL warehouse, using the
app's own OAuth identity (no tokens to manage).

Set these as App resources / environment variables when you deploy:
  DATABRICKS_HOST          e.g. adb-1234.5.azuredatabricks.net   (no https://)
  DATABRICKS_WAREHOUSE_ID  the SQL warehouse id (or set DATABRICKS_HTTP_PATH)

This module degrades gracefully: if pyspark IS available (e.g. running in a
notebook), callers can still use Spark; this is the fallback for the Apps runtime.
"""
from __future__ import annotations

import os
from functools import lru_cache


def _http_path():
    hp = os.environ.get("DATABRICKS_HTTP_PATH")
    if hp:
        return hp
    wid = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    return f"/sql/1.0/warehouses/{wid}" if wid else None


@lru_cache(maxsize=1)
def _connection():
    """Open ONE cached SQL connection using the app's OAuth identity. Raises a
    clear error if the warehouse/host env vars are not set."""
    from databricks import sql
    from databricks.sdk.core import Config
    host = os.environ.get("DATABRICKS_HOST")
    path = _http_path()
    if not host or not path:
        raise RuntimeError(
            "Set DATABRICKS_HOST and DATABRICKS_WAREHOUSE_ID (or "
            "DATABRICKS_HTTP_PATH) as app resources so the app can reach a SQL "
            "warehouse.")
    cfg = Config()                      # app's ambient OAuth identity
    return sql.connect(server_hostname=host, http_path=path,
                       credentials_provider=lambda: cfg.authenticate)


def query(sql_text: str, params=None):
    """Run a SELECT and return (columns, rows) where rows is a list of dicts.
    Uses the SQL warehouse (works on Databricks Apps; no pyspark)."""
    conn = _connection()
    with conn.cursor() as cur:
        cur.execute(sql_text, params or {})
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return cols, rows


def table_columns(table: str) -> list:
    """Column names of a table, via the SQL warehouse (no pyspark)."""
    # LIMIT 0 returns the schema without scanning data
    cols, _ = query(f"SELECT * FROM {table} LIMIT 0")
    return cols


def table_preview(table: str, limit: int = 50):
    """(columns, rows) preview of a table."""
    return query(f"SELECT * FROM {table} LIMIT {int(limit)}")


def has_spark() -> bool:
    """True if pyspark is importable (notebook), False on Databricks Apps."""
    try:
        import pyspark  # noqa
        return True
    except Exception:
        return False


def read_guide_rows(guide_table: str) -> list:
    """Read the existing guide rows (for versioning) via the SQL warehouse."""
    try:
        _, rows = query(f"SELECT * FROM {guide_table}")
        return rows
    except Exception:
        return []


def _sql_str(v):
    if v is None:
        return "NULL"
    import json as _j
    if isinstance(v, (dict, list)):
        v = _j.dumps(v)
    return "'" + str(v).replace("'", "''") + "'"


def insert_guide_entries(guide_table: str, entries: list) -> int:
    """INSERT versioned GuideEntry dicts into the guide table via the SQL
    warehouse (small writes -> fine on Apps, no Spark). entries are dicts with
    team_id, config_type, identity_key, definition, version, created_by,
    tombstoned. Returns rows written."""
    if not entries:
        return 0
    conn = _connection()
    cols = ["team_id", "config_type", "identity_key", "definition",
            "version", "created_by", "tombstoned"]
    with conn.cursor() as cur:
        for e in entries:
            vals = ", ".join(_sql_str(e.get(c)) for c in cols)
            cur.execute(f"INSERT INTO {guide_table} ({', '.join(cols)}) VALUES ({vals})")
    return len(entries)


def trigger_job(job_id: int, notebook_params: dict):
    """Fire a Databricks Job (the heavy Spark processing) with the app's ambient
    identity -- same pattern as the extraction app. Returns the run id."""
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    resp = w.jobs.run_now(job_id=job_id, notebook_params=notebook_params)
    return resp.run_id


def job_status(run_id: int):
    """(state, result) of a job run."""
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    info = w.jobs.get_run(run_id=run_id)
    life = getattr(info.state, "life_cycle_state", None)
    res = getattr(info.state, "result_state", None)
    return (str(life) if life else "?", str(res) if res else "")


def distinct_metrics(gold_table: str, search: str = "", limit: int = 30):
    """Metric names + distinct canonical metrics in gold, for the Step 2 search.
    Returns (metric_names, canonicals) each a list of (name, count). Works on the
    SQL warehouse (Apps) or Spark (notebook)."""
    like = ""
    params = {}
    if search:
        like = "WHERE field_name ILIKE :s OR canonical_metric ILIKE :s"
        params = {"s": f"%{search}%"}
    try:
        _, names = query(
            f"SELECT field_name AS n, COUNT(*) AS c FROM {gold_table} {like} "
            f"GROUP BY field_name ORDER BY c DESC LIMIT {int(limit)}", params)
        _, canons = query(
            f"SELECT canonical_metric AS n, COUNT(*) AS c FROM {gold_table} {like} "
            f"GROUP BY canonical_metric ORDER BY c DESC LIMIT {int(limit)}", params)
        return ([(r["n"], r["c"]) for r in names if r["n"]],
                [(r["n"], r["c"]) for r in canons if r["n"]])
    except Exception:
        return ([], [])


def preconfirmed_metrics(guide_table: str, team_id: str):
    """Metrics already confirmed/defined for this team (Step 3 pre-confirmed list).
    Reads the guide table's key_mapping + schema entries."""
    try:
        rows = read_guide_rows(guide_table)
        out = []
        for r in rows:
            if r.get("team_id") != team_id or r.get("tombstoned"):
                continue
            if r.get("config_type") in ("key_mapping", "mapping"):
                defn = r.get("definition")
                if isinstance(defn, str):
                    import json as _j
                    try: defn = _j.loads(defn)
                    except Exception: defn = {}
                nm = (defn or {}).get("field_name") or (defn or {}).get("raw") or r.get("identity_key")
                if nm:
                    out.append(nm)
        return sorted(set(out))
    except Exception:
        return []
