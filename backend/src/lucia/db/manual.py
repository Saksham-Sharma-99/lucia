"""Indexes created in raw SQL (not expressible in the ORM) that autogenerate must ignore."""

MANUAL_INDEXES = {
    "agents_search_trgm_idx",
    "subjects_title_trgm_idx",
    "subjects_external_ref_trgm_idx",
    "contact_points_name_trgm_idx",
    "conversations_title_trgm_idx",
    "episodes_conversation_idx",
}
