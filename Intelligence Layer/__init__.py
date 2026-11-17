"""Intelligence layer: turns the extraction gold table into team-usable,
analysis-ready tables via team-defined schema, mapping and dictionary.

Components (built one by one):
  config_model  -- the intelligent_guide config data model + version resolver
  mapping_engine -- applies a team's mapping (per modality) + dictionary to gold
  storage        -- UI config -> intelligent_guide (append + version)
  process        -- intelligent_guide + gold -> team's intelligent_gold
"""
