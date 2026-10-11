"""Group free-text job titles into a few families for charts and filters.

"Senior Data & ML Platform Engineer" and "Lead AI Engineer" are both useful titles,
but a chart with 40 one-person bars says nothing. Families make the pattern visible.
The first family whose keywords appear in the title wins, so order matters.
"""
FAMILIES = [
    ("AI & ML", ("ai ", " ai", "ml", "machine learning", "genai", "agentic")),
    ("Data", ("data", "analytics", "analyst", "scientist", "warehouse", "bi ")),
    ("Product & Program", ("product", "program", "project", "delivery")),
    ("Architecture", ("architect",)),
    ("Leadership", ("director", "head", "vp", "chief", "leader", "manager", "founder", "cto", "ceo")),
    ("Quality & Testing", ("qa", "sdet", "test", "quality")),
    ("Consulting", ("consultant", "advisor", "strategist")),
    ("Software Engineering", ("engineer", "developer", "programmer", "stack", "sre", "devops")),
]


def role_family(role: str | None) -> str | None:
    """'Lead AI Engineer' -> 'AI & ML'; 'Staff Software Engineer' -> 'Software Engineering'."""
    if not isinstance(role, str) or not role:  # pandas passes empty cells as NaN (a float)
        return None
    text = f" {role.lower()} "
    for family, keywords in FAMILIES:
        if any(k in text for k in keywords):
            return family
    return "Other"
