"""Extraction front end — run the content-extraction pipeline without code.

Users provide the inputs, pick an access tier, and trigger the extraction as a
Databricks JOB (async, so long runs don't block the UI). Auth uses the Databricks
AMBIENT identity (the app runs as the user / service principal on Databricks Apps)
-- no tokens are collected. When done, users browse a page and see its output plus
the page image (via page_url).

Run on Databricks Apps.
"""
import streamlit as st

# ------------------------------------------------------------------ branding
LOGO_PATH = None            # TODO: your logo path/URL
HELP_URL = "#"              # TODO: your help/docs link
APP_TITLE = "Content Extraction"
APP_TAGLINE = "Extract reports into governed tables — no code"
COPYRIGHT = "© 2026 — Internal use only"   # TODO: adjust

# TODO: the Databricks Job id that runs the extraction (parameterised below)
EXTRACTION_JOB_ID = None    # set to your Databricks Job id

st.set_page_config(page_title=APP_TITLE, page_icon="📄", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 1.6rem; max-width: 1150px;}
  .ex-title {font-size: 1.9rem; font-weight:700; color:#12304A; margin:0;}
  .ex-tag {color:#5B6B7B; font-size:0.95rem; margin-top:2px;}
  .ex-card {background:#F7F9FB; border:1px solid #E3E9EF; border-radius:12px;
            padding:16px 18px; margin-bottom:14px;}
  .ex-pill {display:inline-block; border-radius:999px; padding:2px 10px;
            font-size:0.78rem; margin-left:6px;}
  .ex-foot {color:#8A98A6; font-size:0.8rem; text-align:center; margin-top:28px;
            border-top:1px solid #EDF1F5; padding-top:12px;}
  .stButton>button {border-radius:8px; font-weight:600;}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ header
c_logo, c_title, c_help = st.columns([0.09, 0.75, 0.16])
with c_logo:
    if LOGO_PATH:
        st.image(LOGO_PATH, width=60)
    else:
        st.markdown("<div style='font-size:40px'>📄</div>", unsafe_allow_html=True)
with c_title:
    st.markdown(f"<p class='ex-title'>{APP_TITLE}</p>"
                f"<div class='ex-tag'>{APP_TAGLINE}</div>", unsafe_allow_html=True)
with c_help:
    st.markdown(f"<div style='text-align:right;padding-top:12px'>"
                f"<a href='{HELP_URL}' target='_blank'>Help & docs ↗</a></div>",
                unsafe_allow_html=True)
st.divider()

# ------------------------------------------------------------------ ambient identity
def _ambient():
    """Host + current user from the Databricks runtime -- no token collection."""
    host = user = None
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()                      # uses ambient auth on Apps
        host = w.config.host
        try:
            user = w.current_user.me().user_name
        except Exception:
            user = None
    except Exception:
        pass
    return host, user

_host, _user = _ambient()
st.caption(f"Signed in as **{_user or 'current user'}**"
           + (f" · {_host}" if _host else "")
           + " — the extraction runs under your Databricks identity.")

# ------------------------------------------------------------------ inputs
st.markdown("### Run an extraction")
with st.container():
    volume_link = st.text_input("Data volume (where your documents are)",
                                placeholder="/Volumes/<catalog>/<schema>/<volume>/submissions")
    img_out = st.text_input("Image output (images, sharpened, crops, missed)",
                            placeholder="/Volumes/<catalog>/<schema>/<volume>/img_out")
    target_space = st.text_input("Target space (where the extraction is written)",
                                 placeholder="<catalog>.<schema>")
    tier = st.selectbox("Access tier",
                        ["access_ (everyone)", "limited_ (team components)",
                         "restricted_ (decision-makers — confidential)"])
    _tier = tier.split("_")[0]    # access / limited / restricted

# show the cascade so the user sees where it lands
try:
    from preprocessing_etl.app.access_tiers import target_tiers
    _tgts = target_tiers(_tier)
    st.markdown("<div class='ex-card'>This extraction will be written to: "
                + " ".join(f"<span class='ex-pill' style='background:#E8F0F6;color:#1F5C8B'>"
                           f"{t}_*</span>" for t in _tgts)
                + "<br><span style='color:#5B6B7B;font-size:0.85rem'>"
                "A document is written to its tier and every more-privileged tier, "
                "so decision-makers (restricted) see the full picture.</span></div>",
                unsafe_allow_html=True)
except Exception:
    pass

run = st.button("▶ Run extraction", type="primary",
                disabled=not (volume_link and img_out and target_space))

if run:
    if EXTRACTION_JOB_ID is None:
        st.error("No extraction Job configured. Set EXTRACTION_JOB_ID to your "
                 "Databricks Job id.")
    else:
        try:
            from databricks.sdk import WorkspaceClient
            w = WorkspaceClient()
            run_resp = w.jobs.run_now(
                job_id=EXTRACTION_JOB_ID,
                job_parameters={
                    "volume_link": volume_link,
                    "img_out": img_out,
                    "target_space": target_space,
                    "access_tier": _tier,
                    "requested_by": _user or "",
                })
            st.session_state["last_run_id"] = run_resp.run_id
            st.success(f"Extraction started (run {run_resp.run_id}). "
                       "It runs in the background — check status below.")
        except Exception as e:
            st.error(f"Could not start the job: {e}")

# ------------------------------------------------------------------ status
if st.session_state.get("last_run_id"):
    rid = st.session_state["last_run_id"]
    if st.button("🔄 Check status"):
        try:
            from databricks.sdk import WorkspaceClient
            w = WorkspaceClient()
            info = w.jobs.get_run(run_id=rid)
            state = info.state.life_cycle_state
            result = getattr(info.state, "result_state", None)
            st.info(f"Run {rid}: {state}" + (f" · {result}" if result else ""))
        except Exception as e:
            st.error(f"Status check failed: {e}")

st.divider()

# ------------------------------------------------------------------ page viewer
st.markdown("### View extracted pages")
st.caption("After a run, pick a document and page to see the extracted output and "
           "the page image.")
view_table = st.text_input("Gold table to view",
                           placeholder="<catalog>.<schema>.restricted_gold_<team>_<report>")

def _spark():
    try:
        from pyspark.sql import SparkSession
        return SparkSession.builder.getOrCreate()
    except Exception:
        return None

if view_table:
    sp = _spark()
    if sp is None:
        st.error("No Spark session (run on Databricks).")
    else:
        try:
            docs = [r["source_document"] for r in sp.table(view_table)
                    .select("source_document").distinct().collect()]
            doc = st.selectbox("Document", docs)
            if doc:
                pages = [r["page"] for r in sp.table(view_table)
                         .where(f"source_document = '{doc}'")
                         .select("page").distinct().orderBy("page").collect()]
                page = st.selectbox("Page", pages)
                if page is not None:
                    rows = sp.table(view_table).where(
                        f"source_document = '{doc}' AND page = {page}").toPandas()
                    col_a, col_b = st.columns([0.55, 0.45])
                    with col_a:
                        st.markdown("**Extracted metrics**")
                        st.dataframe(rows.drop(columns=[c for c in ("page_url",)
                                     if c in rows.columns], errors="ignore"),
                                     use_container_width=True, height=440)
                    with col_b:
                        st.markdown("**Page image**")
                        purl = rows["page_url"].iloc[0] if "page_url" in rows.columns \
                            and len(rows) else None
                        if purl:
                            try:
                                st.image(purl, use_container_width=True)
                            except Exception:
                                st.caption(f"page_url: {purl}")
                        else:
                            st.caption("No page_url on these rows.")
        except Exception as e:
            st.error(f"Could not read {view_table}: {e}")

st.markdown(f"<div class='ex-foot'>{COPYRIGHT} &nbsp;·&nbsp; "
            f"<a href='{HELP_URL}' target='_blank'>Help</a></div>",
            unsafe_allow_html=True)
