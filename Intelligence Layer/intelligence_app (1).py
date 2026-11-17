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

# ------------------------------------------------------------------ branding
LOGO_PATH = None          # TODO: set to your logo image path/URL
HELP_URL = "#"            # TODO: set your help/docs link
APP_TITLE = "Intelligence Layer"
APP_TAGLINE = "Turn extraction gold into analysis-ready, team-defined tables"
COPYRIGHT = "© 2026 — Internal use only"   # TODO: adjust

st.set_page_config(page_title=APP_TITLE, page_icon="🧭", layout="wide")

# ------------------------------------------------------------------ styling
st.markdown("""
<style>
  .block-container {padding-top: 1.6rem; max-width: 1200px;}
  .il-header {display:flex; align-items:center; gap:16px; margin-bottom:4px;}
  .il-title {font-size: 1.9rem; font-weight: 700; color:#12304A; margin:0;}
  .il-tag {color:#5B6B7B; font-size:0.95rem; margin-top:2px;}
  .il-card {background:#F7F9FB; border:1px solid #E3E9EF; border-radius:12px;
            padding:16px 18px; margin-bottom:14px;}
  .il-pill {display:inline-block; background:#E8F0F6; color:#1F5C8B;
            border-radius:999px; padding:2px 10px; font-size:0.78rem; margin-left:8px;}
  .il-foot {color:#8A98A6; font-size:0.8rem; text-align:center; margin-top:28px;
            border-top:1px solid #EDF1F5; padding-top:12px;}
  .stButton>button {border-radius:8px; font-weight:600;}
  div[data-testid="stExpander"] {border:1px solid #E3E9EF; border-radius:10px;}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ header
c_logo, c_title, c_help = st.columns([0.10, 0.74, 0.16])
with c_logo:
    if LOGO_PATH:
        st.image(LOGO_PATH, width=64)
    else:
        st.markdown("<div style='font-size:42px'>🧭</div>", unsafe_allow_html=True)
with c_title:
    st.markdown(f"<div class='il-header'><div><p class='il-title'>{APP_TITLE}"
                f"</p><div class='il-tag'>{APP_TAGLINE}</div></div></div>",
                unsafe_allow_html=True)
with c_help:
    st.markdown(f"<div style='text-align:right;padding-top:14px'>"
                f"<a href='{HELP_URL}' target='_blank'>Help & docs ↗</a></div>",
                unsafe_allow_html=True)
st.divider()

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
            from pyspark.sql import SparkSession
            _sp = SparkSession.builder.getOrCreate()
            gold_columns = _sp.table(gold_table).columns
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
        spark = _get_spark()
        if spark is None:
            st.error("No Spark session available (run on Databricks).")
        else:
            from preprocessing_etl.intelligence.storage import save_team_config
            res = save_team_config(spark, guide_table, team_id,
                                   schemas=ss.schemas, mappings=ss.mappings,
                                   dictionaries=ss.dictionaries,
                                   created_by=created_by or None)
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
                    from preprocessing_etl.intelligence.process import build_team_intelligence
                    with st.spinner("Building your intelligent_gold…"):
                        out = build_team_intelligence(
                            spark, gold_table, guide_table, team_id, out_table,
                            review_table=review_table)
                    st.success(f"Done. {out['rows_out']} rows written to "
                               f"`{out_table}` ({out['flagged']} flagged for review).")
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
