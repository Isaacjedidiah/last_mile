"""Intelligence Layer — Streamlit app.

Teams define, per team:
  * SCHEMA      — the columns their intelligent_gold should contain
  * MAPPING     — how each column is extracted from gold (per modality)
  * DICTIONARY  — synonym -> canonical term normalisation
Then SAVE (-> intelligent_guide, versioned) and RUN (-> their intelligent_gold).

Runs on Databricks Apps (recommended) or standalone Streamlit with a Spark
session. The backend calls are:
  from preprocessing_etl.intelligence.storage import save_team_config
  from preprocessing_etl.intelligence.process import build_team_intelligence

Placeholders you (Isaac) will fill later are marked # TODO.
"""
import streamlit as st
import os, sys
# make the preprocessing_etl package importable wherever the app is launched
# (Databricks App / standalone Streamlit set a different working dir than a
# notebook). The package root is 3 dirs up: app/ -> intelligence/ ->
# preprocessing_etl/ -> <ROOT>.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ------------------------------------------------------------------ branding
LOGO_PATH = None          # TODO: set to your logo image path/URL
HELP_URL = "#"            # TODO: set your help/docs link
APP_TITLE = "Intelligence Layer"
APP_TAGLINE = "Turn extraction gold into analysis-ready, team-defined tables"
COPYRIGHT = "© 2026 — Internal use only"   # TODO: adjust
INTELLIGENCE_JOB_ID = None   # TODO: set to the Databricks Job id that runs
                             # intelligence_job.py (the heavy Spark processing)

st.set_page_config(page_title=APP_TITLE, page_icon="🧭", layout="wide")

# ------------------------------------------------------------------ styling
st.markdown("""
<style>
  /* ---- layout: more breathing room, wider canvas ---- */
  .block-container {padding-top: 2.2rem; padding-bottom: 3rem;
                    padding-left: 2.5rem; padding-right: 2.5rem; max-width: 1320px;}
  .main {background: #FFFFFF;}

  /* ---- headings: ensure they are dark + never clipped ---- */
  h1, h2, h3, h4, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
      color:#15324B !important; line-height:1.35 !important; overflow:visible;}
  h3 {margin-top:1.6rem !important; margin-bottom:0.4rem !important;
      padding-bottom:0.3rem; border-bottom:2px solid #EEF3F8;}

  /* ---- the gradient hero header ---- */
  .il-hero {background:linear-gradient(135deg,#1F3A5F 0%,#2E6DA4 100%);
            border-radius:16px; padding:26px 32px; margin-bottom:22px;
            box-shadow:0 6px 20px rgba(31,58,95,0.18);}
  .il-title {font-size:2.0rem; font-weight:800; color:#FFFFFF !important;
             margin:0; letter-spacing:-0.3px; line-height:1.3;}
  .il-tag {color:#CFE0F0 !important; font-size:1.02rem; margin-top:6px;}
  .il-help a {color:#CFE0F0 !important; text-decoration:none; font-weight:600;}

  /* ---- cards ---- */
  .il-card {background:#F7FAFD; border:1px solid #E2EBF3; border-radius:14px;
            padding:20px 24px; margin-bottom:18px; line-height:1.6;
            box-shadow:0 1px 3px rgba(31,58,95,0.05);}
  .il-card b {color:#1F3A5F;}
  .il-card code {background:#E8F0F8; color:#235784; padding:1px 7px;
                 border-radius:6px; font-size:0.86em;}

  /* ---- pills / tags ---- */
  .il-pill {display:inline-block; background:#E6EFF8; color:#235784;
            border-radius:999px; padding:3px 12px; font-size:0.74rem;
            font-weight:600; margin-left:8px; vertical-align:middle;}

  /* ---- buttons ---- */
  .stButton>button {border-radius:10px; font-weight:600; padding:0.5rem 1.1rem;
                    border:1px solid #D4E0EC; transition:all .15s ease;}
  .stButton>button:hover {border-color:#2E6DA4; box-shadow:0 2px 8px rgba(46,109,164,0.18);}
  button[kind="primary"] {background:#2E6DA4 !important; border:none !important;}

  /* ---- inputs: clear, not white-on-white ---- */
  .stTextInput input, .stSelectbox div[data-baseweb="select"],
  .stNumberInput input, .stTextArea textarea {
      background:#FFFFFF !important; color:#1F2933 !important;
      border:1px solid #D4E0EC !important; border-radius:8px !important;}
  label, .stMarkdown p {color:#2B3A47 !important;}

  /* ---- expanders ---- */
  div[data-testid="stExpander"] {border:1px solid #E2EBF3; border-radius:12px;
      background:#FFFFFF; margin-bottom:8px;}
  div[data-testid="stExpander"] summary {font-weight:600; color:#1F3A5F;}

  /* ---- sidebar ---- */
  section[data-testid="stSidebar"] {background:#F1F5FA; border-right:1px solid #E2EBF3;}
  section[data-testid="stSidebar"] * {color:#1F2933;}

  /* ---- footer ---- */
  .il-foot {color:#7A8A99; font-size:0.82rem; text-align:center; margin-top:34px;
            border-top:1px solid #EAF0F6; padding-top:16px;}

  /* keep the top toolbar/menu visible (not white-on-white) */
  header[data-testid="stHeader"] {background:#FFFFFF;}
  #MainMenu, header [data-testid="stToolbar"] {color:#1F3A5F !important;}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ header
st.markdown(
    f"""<div class='il-hero'>
      <div style='display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px;'>
        <div style='display:flex; align-items:center; gap:18px;'>
          <div style='font-size:46px; line-height:1;'>🧭</div>
          <div>
            <p class='il-title'>{APP_TITLE}</p>
            <div class='il-tag'>{APP_TAGLINE}</div>
          </div>
        </div>
        <div class='il-help'><a href='{HELP_URL}' target='_blank'>Help &amp; docs ↗</a></div>
      </div>
    </div>""", unsafe_allow_html=True)

# ------------------------------------------------------------------ what's automatic
from preprocessing_etl.intelligence.mapping_engine import INHERITED_METADATA
st.markdown("<div class='il-card'>"
            "<b>Automatically included in your table</b> — you don't map these:<br>"
            "• <b>metric</b> (from <code>field_name</code>, with the month/year split "
            "into <b>as_at_date</b> / <b>metric_date</b>)<br>"
            "• Metadata: <code>" + "</code>, <code>".join(INHERITED_METADATA) +
            "</code><br>• The metric <code>value</code>, <code>unit</code>, "
            "<code>currency</code> and traceability keys."
            "</div>", unsafe_allow_html=True)

# ------------------------------------------------------------------ config/session
MODALITIES = ["table", "text", "chart"]
METHODS = ["direct", "after_label", "delimiter_position", "contains", "regex", "literal"]
METHOD_HELP = {
    "direct": "Use a gold column value as-is (param: source).",
    "after_label": "Text after '<label>:' up to the next '|' (param: label).",
    "delimiter_position": "The Nth '|' segment of canonical_metric (param: index).",
    "contains": "First matching term found in the text (param: terms, comma-sep).",
    "regex": "Group 1 of a regex over the text (param: pattern).",
    "literal": "A fixed constant value (param: value).",
}

ss = st.session_state
ss.setdefault("schemas", [])        # [{column_name, data_type, description, required}]
ss.setdefault("mappings", [])       # [{column_name, modality, method, params{}}]
ss.setdefault("dictionaries", [])   # [{term, canonical}]
ss.setdefault("prompt_instructions", "")   # team RAG prompt
ss.setdefault("fewshots", [])              # [{question, answer}] up to 4

# ------------------------------------------------------------------ sidebar: team + tables
with st.sidebar:
    st.subheader("Workspace")
    team_id = st.text_input("Team", value="", placeholder="e.g. FX")
    with st.expander("Table settings", expanded=False):
        gold_table = st.text_input("Gold table", value="catalog.schema.gold")
        guide_table = st.text_input("Guide table", value="catalog.schema.intelligent_guide")
        out_table = st.text_input("Output (intelligent_gold)",
                                  value=f"catalog.schema.intelligent_gold_{team_id or 'team'}")
        review_table = st.text_input("Review (unmapped)",
                                     value=f"catalog.schema.intelligent_review_{team_id or 'team'}")
        prompt_table = st.text_input("Prompt store",
                                     value="catalog.schema.rag_prompt_store")
    created_by = st.text_input("Your name", value="", placeholder="for the audit trail")
    st.caption("Define schema, mapping and dictionary, then Save & Run.")

    # read the gold table's columns so mappings can pick from real column names
    gold_columns = []
    if st.button("🔄 Load gold columns"):
        try:
            # Databricks Apps have no pyspark -> use the SQL warehouse connector;
            # fall back to Spark when running in a notebook.
            from preprocessing_etl.intelligence.app.db_connect import (
                has_spark, table_columns)
            if has_spark():
                from pyspark.sql import SparkSession
                gold_columns = SparkSession.builder.getOrCreate().table(gold_table).columns
            else:
                gold_columns = table_columns(gold_table)
            st.session_state["gold_columns"] = gold_columns
            st.success(f"{len(gold_columns)} columns loaded")
        except Exception as e:
            st.error(f"Could not read {gold_table}: {e}")
gold_columns = st.session_state.get("gold_columns", [])

# ------------------------------------------------------------------ SCHEMA
st.markdown("### 1 · Schema <span class='il-pill'>what columns</span>",
            unsafe_allow_html=True)
st.caption("Define the columns your intelligent_gold table should contain.")

with st.container():
    sc1, sc2, sc3, sc4, sc5 = st.columns([0.30, 0.18, 0.30, 0.12, 0.10])
    new_col = sc1.text_input("Column name", key="new_col", placeholder="business_unit")
    new_type = sc2.selectbox("Type", ["string", "number", "date"], key="new_type")
    new_desc = sc3.text_input("Description", key="new_desc", placeholder="optional")
    new_req = sc4.checkbox("Required", key="new_req")
    if sc5.button("➕ Add", key="add_schema") and new_col.strip():
        ss.schemas.append({"column_name": new_col.strip(), "data_type": new_type,
                           "description": new_desc.strip(), "required": new_req})

for i, s in enumerate(ss.schemas):
    cc1, cc2 = st.columns([0.92, 0.08])
    cc1.markdown(f"<div class='il-card'><b>{s['column_name']}</b> "
                 f"<span class='il-pill'>{s['data_type']}</span>"
                 f"{' <span class=il-pill>required</span>' if s.get('required') else ''}"
                 f"<br><span style='color:#5B6B7B'>{s.get('description','')}</span></div>",
                 unsafe_allow_html=True)
    if cc2.button("🗑", key=f"del_schema_{i}"):
        ss.schemas.pop(i); st.rerun()

# ------------------------------------------------------------------ MAPPING
st.markdown("### 2 · Mapping <span class='il-pill'>where it comes from</span>",
            unsafe_allow_html=True)
st.caption("For each column, define how to extract it from gold — per modality "
           "(table / text / chart).")

if not ss.schemas:
    st.info("Add at least one schema column first.")
else:
    m1, m2, m3 = st.columns([0.26, 0.20, 0.24])
    map_col = m1.selectbox("Column", [s["column_name"] for s in ss.schemas], key="map_col")
    map_mod = m2.selectbox("Modality", MODALITIES, key="map_mod")
    map_method = m3.selectbox("Method", METHODS, key="map_method")
    st.caption(METHOD_HELP.get(map_method, ""))
    # method-specific param input
    param_val = None
    if map_method == "after_label":
        param_val = {"label": st.text_input("Label (before the ':')", key="p_label",
                                            placeholder="Industry")}
    elif map_method == "delimiter_position":
        param_val = {"index": st.number_input("Segment index (0-based)", 0, 20, 0,
                                              key="p_index")}
    elif map_method == "contains":
        terms = st.text_input("Terms (comma-separated)", key="p_terms",
                              placeholder="Revenue, Cost, Profit")
        param_val = {"terms": [t.strip() for t in terms.split(",") if t.strip()]}
    elif map_method == "regex":
        param_val = {"pattern": st.text_input("Regex (group 1)", key="p_regex")}
    elif map_method == "direct":
        if gold_columns:
            param_val = {"source": st.selectbox("Gold source column", gold_columns,
                                               key="p_source_sel")}
        else:
            param_val = {"source": st.text_input("Gold source column", key="p_source",
                                                placeholder="entity_ref (load gold columns in sidebar)")}
    elif map_method == "literal":
        param_val = {"value": st.text_input("Constant value", key="p_literal")}

    if st.button("➕ Add mapping", key="add_mapping"):
        ss.mappings.append({"column_name": map_col, "modality": map_mod,
                            "method": map_method, "params": param_val or {}})

for i, m in enumerate(ss.mappings):
    cc1, cc2 = st.columns([0.92, 0.08])
    cc1.markdown(f"<div class='il-card'><b>{m['column_name']}</b> "
                 f"<span class='il-pill'>{m['modality']}</span> "
                 f"<span class='il-pill'>{m['method']}</span>"
                 f"<br><span style='color:#5B6B7B'>{m.get('params',{})}</span></div>",
                 unsafe_allow_html=True)
    if cc2.button("🗑", key=f"del_map_{i}"):
        ss.mappings.pop(i); st.rerun()

# ------------------------------------------------------------------ DICTIONARY
st.markdown("### 3 · Dictionary <span class='il-pill'>normalise synonyms</span>",
            unsafe_allow_html=True)
st.caption("Map synonyms to a canonical term — e.g. RevPo and SevPo both mean "
           "'Stress Growth'.")

d1, d2, d3 = st.columns([0.35, 0.45, 0.20])
dt = d1.text_input("Term / synonym", key="d_term", placeholder="RevPo")
dc = d2.text_input("Canonical name", key="d_canon", placeholder="Stress Growth")
if d3.button("➕ Add term", key="add_dict") and dt.strip() and dc.strip():
    ss.dictionaries.append({"term": dt.strip(), "canonical": dc.strip()})

for i, d in enumerate(ss.dictionaries):
    cc1, cc2 = st.columns([0.92, 0.08])
    cc1.markdown(f"<div class='il-card'><b>{d['term']}</b> → {d['canonical']}</div>",
                 unsafe_allow_html=True)
    if cc2.button("🗑", key=f"del_dict_{i}"):
        ss.dictionaries.pop(i); st.rerun()

# ------------------------------------------------------------------ RAG PROMPT
st.markdown("### 4 · RAG prompt &amp; examples <span class='il-pill'>how answers read</span>",
            unsafe_allow_html=True)
st.caption("Shape how the RAG answers your team — write guidance and up to 4 "
           "example Q/A pairs (copy-paste). Use your canonical names (e.g. the "
           "dictionary output) in the examples.")

ss.prompt_instructions = st.text_area(
    "Prompt guidance", value=ss.prompt_instructions,
    placeholder="e.g. Answer concisely, always cite the page, use bullet points, "
                "and report figures with their period.", height=110)

st.markdown("<b>Few-shot examples</b> (up to 4)", unsafe_allow_html=True)
MAX_FS = 4
fq1, fq2, fq3 = st.columns([0.44, 0.44, 0.12])
_q = fq1.text_input("Example question", key="fs_q", placeholder="What was Stress Growth in Q2 2026?")
_a = fq2.text_input("Example answer", key="fs_a", placeholder="Stress Growth for Q2 2026 was 46 (p.3).")
if fq3.button("➕ Add", key="add_fs", disabled=len(ss.fewshots) >= MAX_FS) and _q.strip() and _a.strip():
    ss.fewshots.append({"question": _q.strip(), "answer": _a.strip()})
if len(ss.fewshots) >= MAX_FS:
    st.caption("Maximum of 4 few-shot examples reached.")

for i, f in enumerate(ss.fewshots):
    cc1, cc2 = st.columns([0.92, 0.08])
    cc1.markdown(f"<div class='il-card'><b>Q:</b> {f['question']}<br>"
                 f"<b>A:</b> {f['answer']}</div>", unsafe_allow_html=True)
    if cc2.button("🗑", key=f"del_fs_{i}"):
        ss.fewshots.pop(i); st.rerun()

# ------------------------------------------------------- KEY MAPPING (pairs)
st.markdown("### 5 · Key mapping <span class='il-pill'>name & map the pairs</span>",
            unsafe_allow_html=True)
st.caption("Anchor on a field, see the Key: Value pairs inside its metrics, and "
           "map each key to a column in your own table. Any change rewrites that "
           "table so it always reflects the current mapping.")

if not team_id:
    st.info("Enter a team (sidebar) to use key mapping.")
elif not ss.schemas:
    st.info("Define at least one schema column first — its name is the field anchor.")
else:
    from preprocessing_etl.intelligence.app.key_mapping_section import (
        render_key_mapping_section)
    from preprocessing_etl.intelligence.storage import (
        save_team_config, latest_team_config)

    def _load_key_mappings(_tid):
        try:
            sp = _get_spark()
            cfg = latest_team_config(sp, guide_table, _tid) if sp else {}
            return cfg.get("key_mapping", []) or []
        except Exception:
            return []

    def _save_key_mappings(_tid, _maps):
        sp = _get_spark()
        if sp is None:
            st.error("No Spark session (run on Databricks).")
            return
        save_team_config(sp, guide_table, _tid, key_mappings=_maps,
                         created_by=created_by or None)

    _sp = _get_spark()
    if _sp is not None:
        render_key_mapping_section(
            st, _sp, gold_table, team_id,
            schema_field_names=[s["column_name"] for s in ss.schemas],
            existing_columns=[s["column_name"] for s in ss.schemas],
            load_mappings=_load_key_mappings, save_mappings=_save_key_mappings)
    else:
        st.info("Key mapping runs on Databricks (needs a Spark session).")

# ------------------------------------------------------------------ SAVE & RUN
st.divider()
r1, r2, r3 = st.columns([0.25, 0.25, 0.50])
save_clicked = r1.button("💾 Save config", use_container_width=True,
                         disabled=not team_id)
run_clicked = r2.button("▶ Save & Run", type="primary", use_container_width=True,
                        disabled=not team_id)

def _get_spark():
    try:
        from pyspark.sql import SparkSession
        return SparkSession.builder.getOrCreate()
    except Exception:
        return None

if save_clicked or run_clicked:
    if not team_id:
        st.error("Enter a team first.")
    else:
        from preprocessing_etl.intelligence.app.db_connect import has_spark
        spark = _get_spark() if has_spark() else None
        # SAVE: with Spark (notebook) use save_team_config; without (Apps) build the
        # versioned entries and INSERT them via the SQL warehouse connector.
        from preprocessing_etl.intelligence.storage import save_team_config, build_entries
        if spark is not None:
            res = save_team_config(spark, guide_table, team_id,
                                   schemas=ss.schemas, mappings=ss.mappings,
                                   dictionaries=ss.dictionaries,
                                   created_by=created_by or None)
        else:
            from preprocessing_etl.intelligence.app.db_connect import (
                read_guide_rows, insert_guide_entries)
            existing = read_guide_rows(guide_table)
            entries, errors = build_entries(
                existing, team_id, schemas=ss.schemas, mappings=ss.mappings,
                dictionaries=ss.dictionaries, created_by=created_by or None)
            if errors:
                res = {"appended": 0, "errors": errors, "versions": []}
            else:
                ent_dicts = [e.__dict__ if hasattr(e, "__dict__") else e for e in entries]
                n = insert_guide_entries(guide_table, ent_dicts)
                res = {"appended": n, "errors": [], "versions": []}
        if True:
            if res["errors"]:
                st.error("Config not saved — fix these:")
                for kind, defn, msg in res["errors"]:
                    st.write(f"• **{kind}** — {msg}")
            else:
                st.success(f"Saved {res['appended']} config entries "
                           f"(versioned) to the guide.")
                # also save the team's RAG prompt + few-shots (separate store)
                if ss.prompt_instructions.strip() or ss.fewshots:
                    try:
                        from preprocessing_etl.rag.prompt_store import save_team_prompt
                        pres = save_team_prompt(
                            spark, prompt_table, team_id,
                            instructions=ss.prompt_instructions,
                            fewshots=ss.fewshots, created_by=created_by or None)
                        if pres["errors"]:
                            st.warning("Prompt not saved: "
                                       + "; ".join(e[2] for e in pres["errors"]))
                        else:
                            st.success(f"Saved RAG prompt + {len(ss.fewshots)} "
                                       f"example(s).")
                    except Exception as e:
                        st.warning(f"Prompt save skipped: {e}")
                if run_clicked:
                    if spark is not None:
                        # notebook: run the heavy build inline
                        from preprocessing_etl.intelligence.process import build_team_intelligence
                        with st.spinner("Building your intelligent_gold…"):
                            out = build_team_intelligence(
                                spark, gold_table, guide_table, team_id, out_table,
                                review_table=review_table)
                        st.success(f"Done. {out['rows_out']} rows written to "
                                   f"`{out_table}` ({out.get('flagged',0)} flagged for review).")
                    else:
                        # Databricks App: trigger the intelligence JOB (has Spark)
                        from preprocessing_etl.intelligence.app.db_connect import trigger_job
                        if not INTELLIGENCE_JOB_ID:
                            st.error("Set INTELLIGENCE_JOB_ID to the Databricks Job "
                                     "that runs intelligence_job.py.")
                        else:
                            rid = trigger_job(INTELLIGENCE_JOB_ID, {
                                "team_id": team_id, "guide_table": guide_table,
                                "gold_table": gold_table, "out_table": out_table})
                            st.success(f"Processing started as job run {rid}. "
                                       f"It builds `{out_table}` on Spark compute.")
                            st.session_state["intel_run_id"] = rid
                    st.write("**Columns:**", ", ".join(out.get("columns", [])))
                    try:
                        st.dataframe(spark.table(out_table).limit(50).toPandas(),
                                     use_container_width=True)
                    except Exception:
                        pass

# ------------------------------------------------------------------ footer
st.markdown(f"<div class='il-foot'>{COPYRIGHT} &nbsp;·&nbsp; "
            f"<a href='{HELP_URL}' target='_blank'>Help</a></div>",
            unsafe_allow_html=True)
