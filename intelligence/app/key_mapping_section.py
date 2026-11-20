"""Streamlit section for the key-pair mapping flow (intelligence app).

Flow (as specified):
  1. the user's SCHEMA anchors on field_name -- pick a field_name;
  2. we DISCOVER the distinct keys inside that field_name's canonical_metrics
     (aggregated, with sample values) -- scoped to that field_name, so it scales
     to millions of rows;
  3. the user MAPS each key -> a column in their distinct table, names it (new
     schema field or existing -- we INFORM which), and
  4. saving/any change REWRITES the distinct table so it reflects the CURRENT
     mapping.

Pure glue over intelligence.key_mapping; no business logic here.
"""
from __future__ import annotations


def render_key_mapping_section(st, spark, gold_table: str, team_id: str,
                               schema_field_names, existing_columns,
                               load_mappings, save_mappings):
    """Render the section. Callbacks:
      load_mappings(team_id) -> list[mapping dict]
      save_mappings(team_id, list[mapping dict]) -> None
    """
    from ..key_mapping import (discover_keys_for_field, make_key_mapping,
                               classify_target, rewrite_user_table)

    st.header("Key mapping \u2014 name & map the pairs inside your metrics")
    st.caption("Anchor on a field, see the Key: Value pairs inside it, and map "
               "each key to a column in your table. Any change rewrites the table "
               "so it always shows the current mapping.")

    # 1. the user's distinct table name
    user_table = st.text_input("Your table (where mapped columns are written)",
                               key="km_user_table")

    # 2. pick a field_name (the schema anchor)
    field_name = st.selectbox("Field (anchor)", options=sorted(schema_field_names),
                              key="km_field")
    if not field_name:
        return

    # 3. discover keys for THIS field only (scalable -- filter gold to it)
    if st.button("Discover keys for this field", key="km_discover"):
        df = spark.table(gold_table).filter(
            spark.table(gold_table).field_name == field_name)
        rows = [r.asDict() for r in df.select("canonical_metric").limit(200000).collect()]
        st.session_state["km_keys"] = discover_keys_for_field(rows, field_name)

    keys = st.session_state.get("km_keys", [])
    if not keys:
        st.info("Pick a field and click \u2018Discover keys\u2019 to see its Key: Value "
                "pairs.")
        return

    existing = load_mappings(team_id) or []
    existing_by_key = {(m["field_name"], m["key"]): m for m in existing}

    st.subheader(f"Keys found in \u2018{field_name}\u2019")
    new_mappings = []
    for k in keys:
        label = k["key"] or "(unkeyed)"
        with st.expander(f"{label}  \u00b7  {k['count']} rows  \u00b7  e.g. "
                         f"{', '.join(str(s) for s in k['samples'][:3])}"):
            prev = existing_by_key.get((field_name, k["key"]))
            use = st.checkbox("Map this key", value=bool(prev),
                              key=f"km_use_{field_name}_{k['key']}")
            if use:
                col = st.text_input(
                    "Column name in your table",
                    value=(prev or {}).get("display_name", k["key"] or "value"),
                    key=f"km_col_{field_name}_{k['key']}")
                tgt = classify_target(col, existing_columns)
                if tgt == "existing":
                    st.warning(f"\u2018{col}\u2019 maps onto an EXISTING schema field.")
                else:
                    st.success(f"\u2018{col}\u2019 will be ADDED as a new schema field.")
                new_mappings.append(make_key_mapping(
                    field_name, k["key"], col, rename=col, target=tgt))

    # keep mappings for OTHER field_names untouched; replace this field's
    others = [m for m in existing if m.get("field_name") != field_name]
    merged = others + new_mappings

    if st.button("Save & rewrite table", key="km_save", type="primary"):
        save_mappings(team_id, merged)
        if user_table:
            try:
                n = rewrite_user_table(spark, gold_table, user_table, merged)
                st.success(f"Saved. Rewrote {user_table}: {n} rows reflect the "
                           f"current mapping.")
            except Exception as e:
                st.error(f"Saved the mapping, but the table rewrite failed: {e}")
        else:
            st.warning("Mapping saved. Set your table name to rewrite it.")
