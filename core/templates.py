"""Connection-note templates: "Hi {first_name}, ..." -> "Hi Priya, ...".

LinkedIn caps notes on free accounts at about 200 characters, so the Settings page
checks the longest note the template would produce across everyone.
"""
import re

NOTE_LIMIT = 200

DEFAULT_TEMPLATE = (
    "Hi {first_name}, I'm {my_name} from the {cohort}. "
    "Great to find a fellow {role} in {city}. Would love to connect!"
)
DEFAULT_NAME = "Rajiv"
DEFAULT_COHORT = "Mastering AI class, October cohort"

# Variable -> what it means (shown on the Settings page)
VARIABLES = {
    "first_name": "Their first name",
    "full_name": "Their full name",
    "role": "Their role (or 'classmate' if unknown)",
    "company": "Their company (or 'your team' if unknown)",
    "city": "Their city, region or country (or 'our cohort')",
    "my_name": "Your name",
    "cohort": "How you describe the group",
}


def _text(value) -> str | None:
    """Treat None, NaN and blank strings the same: missing."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def fill(template: str, peer: dict, my_name: str, cohort: str) -> str:
    """Replace {variables} with this peer's details, with friendly fallbacks for gaps."""
    name = _text(peer.get("name")) or _text(peer.get("discord_handle")) or "there"
    values = {
        "first_name": name.split()[0],
        "full_name": name,
        "role": _text(peer.get("role")) or "classmate",
        "company": _text(peer.get("company")) or "your team",
        "city": (_text(peer.get("city")) or _text(peer.get("region"))
                 or _text(peer.get("country")) or "our cohort"),
        "my_name": my_name,
        "cohort": cohort,
    }
    note = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), template)
    return re.sub(r"\s{2,}", " ", note).strip()


def unknown_variables(template: str) -> list[str]:
    """Typos like {frist_name} that would be sent literally."""
    return [v for v in re.findall(r"\{(\w+)\}", template) if v not in VARIABLES]
