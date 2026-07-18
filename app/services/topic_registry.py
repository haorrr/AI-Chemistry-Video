"""Owns the supported-concept scope: query -> concept_key mapping.

Single source of truth for "add a topic later" (master prompt requirement).
"""

SUPPORTED_QUERIES: dict[str, str] = {
    "How does the pH scale work?": "ph_scale",
    "Why do atoms form covalent bonds?": "covalent_bonds",
    "What is the difference between ionic and covalent bonding?": "ionic_vs_covalent",
}

MAX_QUERY_LENGTH = 200


def resolve_concept(raw_query: str) -> tuple[str, str] | None:
    """Trim/cap/case-fold raw_query and match against SUPPORTED_QUERIES.

    Returns (canonical_query, concept_key) on match, else None.
    """
    if not raw_query:
        return None
    trimmed = raw_query.strip()
    if not trimmed or len(trimmed) > MAX_QUERY_LENGTH:
        return None
    lowered = trimmed.lower()
    for canonical_query, concept in SUPPORTED_QUERIES.items():
        if canonical_query.lower() == lowered:
            return canonical_query, concept
    return None


def supported_queries() -> list[str]:
    return list(SUPPORTED_QUERIES.keys())
