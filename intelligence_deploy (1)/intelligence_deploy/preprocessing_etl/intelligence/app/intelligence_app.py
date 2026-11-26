"""Intelligence Layer — stepped wizard UI (Schema → Metrics → Confirm → Prompt).

Full-height sidebar holds the Source / Target storage tables. Each step is a card.
Reuses the existing intelligence logic (storage.save_team_config,
process.build_team_intelligence, db_connect for the SQL-warehouse path on
Databricks Apps). Runs on Databricks Apps (no pyspark) OR a notebook (Spark).
"""
import os, sys
# make preprocessing_etl importable wherever the app is launched
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st

APP_TITLE = "Intelligence Layer"
HELP_URL = "#"
INTELLIGENCE_JOB_ID = None    # TODO: set to the Databricks Job id for the heavy build

st.set_page_config(page_title=APP_TITLE, page_icon="🧭", layout="wide",
                   initial_sidebar_state="expanded")

# ---------------------------------------------------------------- THEME / CSS
st.markdown("""
<style>
  :root{
    --bg:#0C1322; --bg2:#0F1A2E; --panel:#13213C; --panel2:#17273F;
    --line:#223252; --line2:#2E4066; --ink:#ECF2FB; --ink-soft:#A4B7D6;
    --ink-dim:#6F86AC; --accent:#4F8DF7; --accent2:#7BA9FF; --glow:rgba(79,141,247,.33);
    --good:#35C28E; --violet:#A98BFF; --navy:#152138; --gold:#E8B34A;
  }
  .stApp{background:radial-gradient(1100px 560px at 20% -10%,rgba(79,141,247,.12),transparent 60%),var(--bg);}
  .block-container{padding-top:1.4rem;padding-bottom:3rem;max-width:1120px;}
  h1,h2,h3,h4{color:var(--ink)!important;letter-spacing:-.02em;}
  p,label,.stMarkdown{color:var(--ink-soft);}

  /* full-height purple sidebar */
  section[data-testid="stSidebar"]{
    background:linear-gradient(170deg,#3B2E63,#4A3A78)!important;border-right:1px solid rgba(255,255,255,.08);}
  section[data-testid="stSidebar"] *{color:#fff!important;}
  section[data-testid="stSidebar"] .stTextArea textarea,
  section[data-testid="stSidebar"] .stTextInput input{
    background:rgba(0,0,0,.22)!important;border:1px solid rgba(255,255,255,.14)!important;
    color:#fff!important;font-family:ui-monospace,monospace!important;font-size:12.5px!important;
    border-radius:8px!important;word-break:break-all;}
  .sb-sect{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
    color:rgba(255,255,255,.55)!important;margin:6px 0 2px;}

  /* top bars */
  .topbar{display:flex;gap:16px;margin-bottom:18px;}
  .top-logo,.top-help{flex:1;border-radius:12px;padding:15px 22px;font-weight:650;display:flex;
    align-items:center;background:linear-gradient(145deg,var(--accent),#3B6FD4);box-shadow:0 8px 22px var(--glow);color:#fff;}
  .top-help{flex:0 0 280px;justify-content:space-between;background:linear-gradient(145deg,#3B6FD4,#2B539F);}
  .top-help a{color:#fff;text-decoration:none;font-size:13px;opacity:.9;}

  /* hero + outcomes */
  .hero{display:grid;grid-template-columns:1fr 330px;border-radius:14px;overflow:hidden;border:1px solid var(--line);margin-bottom:18px;box-shadow:0 16px 40px rgba(0,0,0,.3);}
  .hero-msg{background:var(--navy);padding:30px;}
  .hero-msg h2{margin:0 0 8px;font-size:23px;}
  .hero-msg p{margin:0;color:var(--ink-soft);font-size:14px;}
  .hero-out{background:#111C31;padding:26px;border-left:1px solid var(--line);}
  .hero-out .t{font-size:13px;font-weight:700;color:var(--accent2);margin-bottom:14px;}
  .hero-out .o{display:flex;align-items:center;gap:11px;margin-bottom:13px;font-size:13.5px;color:var(--ink-soft);}
  .hero-out .o b{width:24px;height:24px;border-radius:7px;background:rgba(79,141,247,.16);color:var(--accent2);display:grid;place-items:center;font-size:12px;}

  /* stepper */
  .stepper{display:flex;align-items:center;max-width:720px;margin:0 auto 22px;}
  .step{display:flex;align-items:center;gap:10px;flex:1;}.step:last-child{flex:0;}
  .dot{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;font-weight:700;font-size:14px;
    background:var(--panel);border:1.5px solid var(--line2);color:var(--ink-dim);}
  .step.active .dot{background:linear-gradient(145deg,var(--accent),var(--accent2));border:none;color:#fff;box-shadow:0 5px 16px var(--glow);}
  .step.done .dot{background:var(--good);border:none;color:#05140E;}
  .step .lbl{font-size:13px;font-weight:600;color:var(--ink-dim);}
  .step.active .lbl{color:var(--ink);}.step.done .lbl{color:var(--ink-soft);}
  .sbar{height:2px;flex:1;background:var(--line);margin:0 10px;position:relative;}
  .sbar.fill::after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,var(--good),var(--accent));}

  .pill{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
    color:var(--accent2);background:rgba(79,141,247,.12);border:1px solid rgba(79,141,247,.25);padding:5px 11px;border-radius:999px;margin-bottom:10px;}
  .pre-chip{display:inline-block;font-size:11.5px;background:rgba(79,141,247,.12);border:1px solid rgba(79,141,247,.22);color:var(--accent2);padding:4px 10px;border-radius:7px;margin:3px 4px 3px 0;}
  .pre-chip.always{background:rgba(53,194,142,.12);border-color:rgba(53,194,142,.25);color:var(--good);}
  .added-metric{display:flex;align-items:center;gap:12px;background:var(--bg2);border:1px solid var(--line);border-radius:9px;padding:10px 14px;margin-bottom:8px;}
  .added-metric .nm{font-weight:600;color:var(--ink);}.added-metric .can{color:var(--accent2);}
  .added-metric .kp{margin-left:auto;font-size:11.5px;color:var(--violet);background:rgba(169,139,255,.1);padding:3px 9px;border-radius:6px;}
  .stButton>button{border-radius:10px;font-weight:650;border:1px solid var(--line2);background:var(--bg2);color:var(--ink);}
  .stButton>button:hover{border-color:var(--accent);}
  div[data-testid="stExpander"]{border:1px solid var(--line2)!important;border-radius:9px!important;background:var(--bg2)!important;}
  .stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"]{
    background:var(--bg2)!important;border:1px solid var(--line2)!important;color:var(--ink)!important;border-radius:9px!important;}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- STATE
ss = st.session_state
ss.setdefault("step", 0)
ss.setdefault("schemas", [])          # [{column_name, source_mapping, description}]
ss.setdefault("metrics", [])          # [{raw, canonical, key, schema_name}]
ss.setdefault("dictionaries", [])
ss.setdefault("prompt_instructions", "")
ss.setdefault("fewshots", [])
ss.setdefault("confirm_schema", {})   # name -> bool
ss.setdefault("confirm_metrics", {})  # name -> bool

ALWAYS_FIELDS = ["page_title", "sub_header"]
PRECONFIRMED = ["source_document", "page", "entity_ref", "extraction_date"]

def _get_spark():
    try:
        from pyspark.sql import SparkSession
        return SparkSession.builder.getOrCreate()
    except Exception:
        return None

def _has_spark():
    try:
        import pyspark  # noqa
        return True
    except Exception:
        return False

# ---------------------------------------------------------------- SIDEBAR
with st.sidebar:
    st.markdown("### 🧭 Intelligence Layer")
    st.markdown("<div class='sb-sect'>Source Storage</div>", unsafe_allow_html=True)
    gold_source = st.text_area("Gold source table", value=ss.get("gold_source", "catalog.schema.gold"),
                               key="gold_source", height=70)
    st.markdown("<div class='sb-sect'>Target Storage</div>", unsafe_allow_html=True)
    target_gold = st.text_area("Target gold table", value=ss.get("target_gold", "catalog.schema.intelligent_gold"),
                               key="target_gold", height=70)
    st.divider()
    team_id = st.text_input("Team", value=ss.get("team_id", ""), key="team_id",
                            placeholder="your team id")
    if st.button("🔄 Load gold columns", use_container_width=True):
        try:
            from preprocessing_etl.intelligence.app.db_connect import has_spark, table_columns
            if has_spark():
                cols = _get_spark().table(gold_source).columns
            else:
                cols = table_columns(gold_source)
            ss["gold_columns"] = cols
            st.success(f"{len(cols)} columns")
        except Exception as e:
            st.error(f"Could not load: {e}")

gold_columns = ss.get("gold_columns", [])

# ---------------------------------------------------------------- TOP BARS
st.markdown(f"""<div class='topbar'>
  <div class='top-logo'>LOGO · {APP_TITLE}</div>
  <div class='top-help'><span>HELP Doc</span><a href='{HELP_URL}' target='_blank'>Open ↗</a></div>
</div>""", unsafe_allow_html=True)

# hero only on step 1
if ss.step == 0:
    st.markdown("""<div class='hero'>
      <div class='hero-msg'><h2>Welcome 👋</h2>
      <p>Turn extraction gold into analysis-ready, team-defined tables. Four quick steps — schema, metrics, confirm, and prompt.</p></div>
      <div class='hero-out'><div class='t'>3 OUTCOMES</div>
        <div class='o'><b>1</b> Build Intelligence Gold</div>
        <div class='o'><b>2</b> Define important metrics</div>
        <div class='o'><b>3</b> Set your prompt preference</div></div>
    </div>""", unsafe_allow_html=True)

# stepper
_labels = ["Schema", "Metrics", "Confirm", "Prompt"]
_html = "<div class='stepper'>"
for i, lb in enumerate(_labels):
    cls = "active" if i == ss.step else ("done" if i < ss.step else "")
    mark = "✓" if i < ss.step else str(i+1)
    _html += f"<div class='step {cls}'><div class='dot'>{mark}</div><div class='lbl'>{lb}</div></div>"
    if i < len(_labels)-1:
        _html += f"<div class='sbar {'fill' if i < ss.step else ''}'></div>"
_html += "</div>"
st.markdown(_html, unsafe_allow_html=True)

# ================================================================ STEP 1 SCHEMA
if ss.step == 0:
    st.markdown("<span class='pill'>Step 1 · Schema</span>", unsafe_allow_html=True)
    st.markdown("## Define your schema")
    st.caption("Name the fields that anchor your metrics and map them to your source storage.")

    c1, c2 = st.columns(2)
    with c1:
        with st.expander("What is a schema?"):
            st.write("• Fields that anchor your metrics\n\n• Mapped to your source gold columns\n\n• Stable as data scales")
    with c2:
        with st.expander("Confirmed schema that will be present"):
            chips = "".join(f"<span class='pre-chip always'>{f}</span>" for f in ALWAYS_FIELDS)
            chips += "".join(f"<span class='pre-chip'>{f}</span>" for f in PRECONFIRMED)
            st.markdown(chips, unsafe_allow_html=True)
            st.caption("page_title and sub_header are always included (from the extraction).")

    sc1, sc2, sc3, sc4 = st.columns([1.3, 1.3, 1.5, 0.6])
    col_name = sc1.text_input("Column name", key="sc_col", placeholder="e.g. Revenue")
    col_src = sc2.selectbox("Source storage mapping",
                            [""] + gold_columns if gold_columns else [""], key="sc_src")
    col_desc = sc3.text_input("Description", key="sc_desc", placeholder="what it means")
    sc4.markdown("<br>", unsafe_allow_html=True)
    if sc4.button("➕ Add", key="add_schema", use_container_width=True) and col_name.strip():
        ss.schemas.append({"column_name": col_name.strip(), "source_mapping": col_src,
                           "description": col_desc.strip()})
        st.rerun()

    for i, s in enumerate(ss.schemas):
        r1, r2, r3, r4 = st.columns([1.3, 1.3, 1.5, 0.6])
        r1.markdown(f"**{s['column_name']}**")
        r2.caption(s.get("source_mapping") or "—")
        r3.caption(s.get("description") or "—")
        if r4.button("✕", key=f"del_s{i}"):
            ss.schemas.pop(i); st.rerun()

# ================================================================ STEP 2 METRICS
elif ss.step == 1:
    st.markdown("<span class='pill'>Step 2 · Metrics</span>", unsafe_allow_html=True)
    st.markdown("## Define important metrics")
    st.caption("Search a metric from storage, name it, map its Key: Value pair, and add as many as you need.")

    with st.expander("How metrics work"):
        st.write("• Search finds metric names & distinct canonical metrics already in storage\n\n• Give each a canonical name and map its key pair")

    search = st.text_input("🔍 Search a metric", key="m_search", placeholder="type to filter…")
    # LIVE: distinct metric names + canonical metrics from gold
    if search:
        try:
            from preprocessing_etl.intelligence.app.db_connect import distinct_metrics
            names, canons = distinct_metrics(gold_source, search)
            if names:
                st.markdown("**Metric names in storage**")
                for n, cnt in names[:6]:
                    if st.button(f"{n}   ·   {cnt} rows", key=f"pick_n_{n}"):
                        ss["m_raw"] = n; st.rerun()
            if canons:
                st.markdown("**Distinct canonical metrics**")
                for n, cnt in canons[:6]:
                    if st.button(f"{n}", key=f"pick_c_{n}"):
                        ss["m_canon"] = n; st.rerun()
        except Exception as e:
            st.caption(f"(search needs a loaded gold table — {e})")

    mc1, mc2 = st.columns(2)
    raw = mc1.text_input("Raw metric name", key="m_raw")
    canon = mc2.text_input("Canonical name", key="m_canon")
    mk1, mk2, mk3 = st.columns([1, 1, 0.4])
    mkey = mk1.text_input("Key", key="m_key", placeholder="e.g. Portfolio")
    mschema = mk2.text_input("Schema name", key="m_schema", placeholder="target column")
    mk3.markdown("<br>", unsafe_allow_html=True)
    if mk3.button("➕ Add", key="add_metric", use_container_width=True) and raw.strip():
        ss.metrics.append({"raw": raw.strip(), "canonical": canon.strip(),
                          "key": mkey.strip(), "schema_name": mschema.strip()})
        st.rerun()

    for i, m in enumerate(ss.metrics):
        kp = f"{m['key']} → {m['schema_name']}" if m.get("key") else "—"
        cc1, cc2 = st.columns([5, 0.5])
        cc1.markdown(f"<div class='added-metric'><span class='nm'>{m['raw']}</span> → "
                     f"<span class='can'>{m.get('canonical') or '—'}</span>"
                     f"<span class='kp'>{kp}</span></div>", unsafe_allow_html=True)
        if cc2.button("✕", key=f"del_m{i}"):
            ss.metrics.pop(i); st.rerun()

# ================================================================ STEP 3 CONFIRM
elif ss.step == 2:
    st.markdown("<span class='pill'>Step 3 · Confirm</span>", unsafe_allow_html=True)
    st.markdown("## Confirm your build")
    st.caption("Tick to confirm your schema fields and metrics. Anything unticked is ignored.")

    # build the lists: always fields + user schema; metrics
    schema_items = [(f, "ALWAYS") for f in ALWAYS_FIELDS] + \
                   [(s["column_name"], "USER") for s in ss.schemas]
    metric_items = [(m["raw"], "KEY PAIR" if m.get("key") else "METRIC") for m in ss.metrics]
    # LIVE: add PRE-CONFIRMED metrics already defined for this team
    try:
        from preprocessing_etl.intelligence.app.db_connect import preconfirmed_metrics
        _guide = f"{gold_source.rsplit('.',1)[0]}.intelligent_guide"
        _added = {m["raw"] for m in ss.metrics}
        for pm in preconfirmed_metrics(_guide, team_id):
            if pm not in _added:
                metric_items.append((pm, "PRE-CONFIRMED"))
    except Exception:
        pass

    n_sc_on = sum(1 for n, _ in schema_items if ss.confirm_schema.get(n, True))
    with st.expander(f"Schema fields — {n_sc_on} of {len(schema_items)} confirmed", expanded=True):
        for n, tag in schema_items:
            default = True if tag == "ALWAYS" else ss.confirm_schema.get(n, True)
            disabled = tag == "ALWAYS"
            ss.confirm_schema[n] = st.checkbox(f"{n}  ·  {tag}", value=default,
                                               key=f"cs_{n}", disabled=disabled)

    n_m_on = sum(1 for n, _ in metric_items if ss.confirm_metrics.get(n, True))
    with st.expander(f"Metrics — {n_m_on} of {len(metric_items)} confirmed", expanded=True):
        if not metric_items:
            st.caption("No metrics added yet (go back to Step 2).")
        for n, tag in metric_items:
            ss.confirm_metrics[n] = st.checkbox(f"{n}  ·  {tag}",
                                                value=ss.confirm_metrics.get(n, True), key=f"cm_{n}")
    st.caption("Unticked items become ignored — they stay out of the intelligent table.")

# ================================================================ STEP 4 PROMPT
elif ss.step == 3:
    st.markdown("<span class='pill'>Step 4 · Prompt</span>", unsafe_allow_html=True)
    st.markdown("## Set your prompt preference")
    st.caption("Give the RAG layer few-shot examples and any guidance.")

    with st.expander("RAG prompt few-shot examples"):
        st.write("Examples teach the RAG layer your team's answer style.")

    MAX_FS = 4
    fq1, fq2, fq3 = st.columns([2, 2, 0.5])
    _q = fq1.text_area("Example question", key="fs_q", height=90)
    _a = fq2.text_area("Example answer", key="fs_a", height=90)
    fq3.markdown("<br><br>", unsafe_allow_html=True)
    if fq3.button("➕", key="add_fs", disabled=len(ss.fewshots) >= MAX_FS) and _q.strip() and _a.strip():
        ss.fewshots.append({"question": _q.strip(), "answer": _a.strip()}); st.rerun()
    for i, f in enumerate(ss.fewshots):
        c1, c2 = st.columns([6, 0.5])
        c1.caption(f"**Q:** {f['question'][:60]} … **A:** {f['answer'][:60]}")
        if c2.button("✕", key=f"del_fs{i}"):
            ss.fewshots.pop(i); st.rerun()
    ss.prompt_instructions = st.text_area("Prompt guidance (if any)",
                                          value=ss.prompt_instructions, height=90)

# ---------------------------------------------------------------- NAV / ACTIONS
st.divider()
nav1, nav2 = st.columns([1, 1])
with nav1:
    if ss.step > 0 and st.button("← Back", use_container_width=True):
        ss.step -= 1; st.rerun()
with nav2:
    if ss.step < 3:
        if st.button("Continue →", use_container_width=True, type="primary"):
            ss.step += 1; st.rerun()
    else:
        if st.button("⚡ Build Intelligence Gold", use_container_width=True, type="primary"):
            if not team_id:
                st.error("Enter a team in the sidebar.")
            else:
                # save config + trigger build (reuses existing logic)
                try:
                    from preprocessing_etl.intelligence.storage import save_team_config, build_entries
                    spark = _get_spark() if _has_spark() else None
                    confirmed_schema = [s for s in ss.schemas
                                        if ss.confirm_schema.get(s["column_name"], True)]
                    confirmed_metrics = [m for m in ss.metrics
                                         if ss.confirm_metrics.get(m["raw"], True)]
                    if spark is not None:
                        save_team_config(spark, f"{gold_source.rsplit('.',1)[0]}.intelligent_guide",
                                         team_id, schemas=confirmed_schema,
                                         key_mappings=confirmed_metrics)
                        from preprocessing_etl.intelligence.process import build_team_intelligence
                        with st.spinner("Building intelligent_gold…"):
                            out = build_team_intelligence(spark, gold_source,
                                   f"{gold_source.rsplit('.',1)[0]}.intelligent_guide",
                                   team_id, target_gold)
                        st.success(f"Done — {out.get('rows_out','?')} rows to {target_gold}")
                    else:
                        from preprocessing_etl.intelligence.app.db_connect import (
                            read_guide_rows, insert_guide_entries, trigger_job)
                        guide = f"{gold_source.rsplit('.',1)[0]}.intelligent_guide"
                        entries, errors = build_entries(read_guide_rows(guide), team_id,
                                           schemas=confirmed_schema, key_mappings=confirmed_metrics)
                        if not errors:
                            insert_guide_entries(guide, [e.__dict__ for e in entries])
                        if INTELLIGENCE_JOB_ID:
                            rid = trigger_job(INTELLIGENCE_JOB_ID, {
                                "team_id": team_id, "guide_table": guide,
                                "gold_table": gold_source, "out_table": target_gold})
                            st.success(f"Build started as job run {rid}.")
                        else:
                            st.warning("Config saved. Set INTELLIGENCE_JOB_ID to trigger the build.")
                except Exception as e:
                    st.error(f"Build error: {e}")
