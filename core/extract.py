"""Turn messages into peer records.

Two extractors produce the same output shape:
  rules_extractor          - free, offline pattern matching (this file)
  ClaudeExtractor          - more accurate, uses the Claude API (core/claude_extract.py)

An extractor takes a list of messages and returns a list of the same length:
a partial peer dict for each introduction, or None for chit-chat.

build_peers() runs an extractor over every message, merges multiple messages
from the same person, and flags records that need a human to check them.
"""
import re

# Words that end a name or a place ("Leo here from Tampa, Florida. Looking forward...")
NAME_STOP = {
    "from", "based", "here", "and", "a", "an", "the", "working", "located", "living", "currently",
    "also", "in", "with", "excited", "happy", "so", "of", "at", "to", "for", "glad", "really", "not",
    "enjoying", "greetings", "hello", "hi", "hey", "everyone", "all", "folks", "form", "from.",
    "located", "trying", "part", "joining", "new", "very", "looking", "eager", "on",
}
LOC_STOP = {
    "here", "and", "excited", "looking", "happy", "glad", "i", "i'm", "i’m", "im", "working", "currently",
    "eager", "nice", "please", "would", "feel", "to", "with", "for", "who", "where", "it", "this", "so",
    "but", "really", "area!", "too", "want",
}

NAME_PATTERNS = [
    # "I am Arun Mehta", "this is Kim Lee", "It's Sam"
    re.compile(r"(?i:my name is|i am|i'm|i’m|this is|it's|it’s)\s+(?P<n>[A-Za-z][\w'-]*(?:\s+[A-Za-z][\w'-]*){0,3})"),
    # "Hello all, Nora Field from ...", "Omar from Dallas", "Hi, Zed living in ..."
    re.compile(r"^(?:(?i:hi|hello|hey)\b[^,.!\n]*[,.!]\s*)?(?P<n>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(?i:from|living|based)\b",
               re.MULTILINE),
    # "Leo here", "Mira Shah here!" - checked last so "...from London here" doesn't make "London" a name
    re.compile(r"(?P<n>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(?i:here)\b"),
]
LOC_RE = re.compile(
    r"\b(?:from|based (?:in|out of)|living in|located in|currently in|i am in|i'm in|i’m in)\s+(?:the\s+)?"
    r"(?P<loc>(?:[^.!?\n(:\-–—]|\.(?=\S))+)",  # a dot inside "D.C." is fine; ". " ends the place
    re.IGNORECASE,
)
ROLE_RE = re.compile(
    r"\b((?:(?:senior|sr\.?|staff|principal|lead|chief|head|junior|associate|technical|solutions?|software|data|"
    r"ai|ml|product|program|project|network|cloud|devops|full[- ]stack|front[- ]end|back[- ]?end|iam|qa|"
    r"automation|integrations?|platform|machine learning|engineering|business|finance|compliance|risk|"
    r"mobile|applied|guidewire|technology)\s+){0,4}"
    r"(?:engineer|engieer|architect|manager|consultant|developer|scientist|analyst|designer|founder|"
    r"director|leader|sdet|programmer|strategist|specialist)s?)\b",
    re.IGNORECASE,
)
# "Senior Product Manager at Visa", "I work for Merck" - capitalized words, stopping at a sentence end.
COMPANY_RE = re.compile(r"\b(?:at|work(?:s|ing)? (?:for|at|with))\s+(?P<c>[A-Z][\w&]*(?:\s+[A-Z][\w&]*){0,3})")
YEARS_RE = re.compile(r"(\d{1,2})\+?\s*(?:years|yrs)", re.IGNORECASE)
ACRONYMS = {"ai", "ml", "iam", "qa", "sdet", "devops"}


def _take_words(text: str, stop: set[str], max_words: int) -> str:
    words = []
    for w in text.split():
        if w.lower().strip(",") in stop or w.lower().startswith(("http", "www.")):
            break
        words.append(w)
        if len(words) == max_words:
            break
    return " ".join(words).strip(" ,")


def find_name(text: str) -> str | None:
    for pattern in NAME_PATTERNS:
        for m in pattern.finditer(text):
            name = _take_words(m.group("n"), NAME_STOP, 4)
            if name and name.split()[0].lower() not in NAME_STOP:
                return " ".join(w if w[1:].lower() != w[1:] else w.capitalize() for w in name.split())
    return None


def find_location(text: str) -> str | None:
    """'Tampa, Florida. Looking forward' -> 'Tampa, Florida'"""
    for m in LOC_RE.finditer(text):
        parts = [p.strip() for p in m.group("loc").split(",")]
        first = _take_words(parts[0], LOC_STOP, 4)
        if not first or "linkedin" in first.lower() or "http" in first.lower():
            continue
        place = [first]
        for p in parts[1:]:  # keep short ", CA" / ", Canada" parts; stop at sentence-like ones
            short = _take_words(p, LOC_STOP, 3)
            if not short or short != p.strip() or len(short.split()) > 3:
                if short and len(short.split()) <= 2 and short[0].isupper():
                    place.append(short)
                break
            place.append(short)
        return ", ".join(place)
    return None


def find_role(text: str) -> str | None:
    for m in ROLE_RE.finditer(text or ""):
        role = m.group(1).replace("Engieer", "Engineer").replace("engieer", "engineer")
        if len(role.split()) == 1 and role.lower() in {"leader", "lead"}:
            continue
        return " ".join(w.upper() if w.lower() in ACRONYMS else w[0].upper() + w[1:] for w in role.split())
    return None


def _is_shortened(preview_name: str, message_name: str) -> bool:
    """True for preview 'Lena R.' vs message 'Lena Rao' (same first name, preview ends in an initial)."""
    p, m = preview_name.split(), message_name.split()
    return (len(p) >= 2 and len(m) >= 2 and p[0].lower() == m[0].lower()
            and re.fullmatch(r"[A-Z]\.?", p[-1]) is not None)


def _name_from_handle(handle: str) -> str | None:
    """'Nora Field' is usable; 'coolcoder' or 'nora1234' is not."""
    clean = re.sub(r"\[.*?\]", "", handle).strip(" ,")
    if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{2,}", clean) and (" " in clean or clean[0].isupper()):
        return clean
    return None


def extract_rules(message: dict) -> dict | None:
    """Pattern-match one message. Returns a partial peer dict, or None if it isn't an intro."""
    text = message["content"]
    preview = message.get("embed") or {}
    name_msg, loc_msg = find_name(text), find_location(text)
    urls = message.get("linkedin_urls") or []

    if not (urls or loc_msg or (name_msg and len(text) > 25)):
        return None  # chit-chat like "add me too" or "Happy to join as well!"

    company = preview.get("company")
    if not company and (m := COMPANY_RE.search(text)):
        company = m.group("c")
    years = YEARS_RE.search(text) or YEARS_RE.search(preview.get("headline") or "")

    # The LinkedIn preview usually has the full name, but sometimes it's shortened ("Lena R.")
    # while the message has more ("Lena Rao"). Keep whichever is fuller.
    name = preview.get("name") or name_msg
    if preview.get("name") and name_msg and _is_shortened(preview["name"], name_msg):
        name = name_msg

    peer = {
        "discord_handle": message["author_handle"],
        "name": name,
        "role": find_role(text) or find_role(preview.get("headline")),
        "company": company,
        "location_raw": loc_msg or preview.get("location"),
        "linkedin_url": urls[0] if urls else None,
        "experience": f"{years.group(1)}+ years" if years else None,
        "source_message_ids": [message["id"]],
        "source_text": text,
        # Where each value came from - shown in the demo and the Review screen.
        "field_sources": {
            "name": "linkedin preview" if preview.get("name") else ("message" if name_msg else None),
            "location": "message" if loc_msg else ("linkedin preview" if preview.get("location") else None),
        },
    }
    return peer


def display_location(peer: dict) -> str | None:
    """'Toronto, Ontario, Canada'; skips repeats like 'Dubai, Dubai'. Falls back to what they typed."""
    parts = []
    for part in (peer.get("city"), peer.get("region"), peer.get("country")):
        if part and part not in parts:
            parts.append(part)
    return ", ".join(parts) or peer.get("location_raw")


def rules_extractor(messages: list[dict]) -> list[dict | None]:
    return [extract_rules(m) for m in messages]


def _finalize(peer: dict) -> dict:
    """Fill gaps from the Discord handle, score confidence, decide whether it needs review."""
    reasons = list(peer.pop("uncertain_reasons", []))
    if not peer.get("name"):
        peer["name"] = _name_from_handle(peer["discord_handle"])
        peer["field_sources"]["name"] = "discord handle" if peer["name"] else None
        reasons.append("Name taken from Discord handle" if peer["name"] else "No name found")
    if not peer.get("location_raw"):
        reasons.append("No location found")
    elif peer["field_sources"].get("location") == "linkedin preview":
        reasons.append("Location taken from LinkedIn preview, not the message")
    if not peer.get("linkedin_url"):
        reasons.append("No LinkedIn link")

    found = [bool(peer.get("name")), bool(peer.get("location_raw")), bool(peer.get("linkedin_url")), bool(peer.get("role"))]
    peer["confidence"] = round(sum(found) / len(found) - 0.1 * len(reasons), 2)
    peer["needs_review"] = 1 if reasons else 0
    peer["review_reason"] = "; ".join(reasons) or None
    return peer


def _seed_from_saved(saved: dict) -> dict:
    """A peer already in the database, shaped so new messages can merge into it."""
    return {
        **{k: v for k, v in saved.items() if k not in ("id", "needs_review", "review_reason")},
        "source_text": saved.get("source_text") or "",
        "field_sources": {
            "name": "saved" if saved.get("name") else None,
            "location": "saved" if saved.get("location_raw") or saved.get("city") else None,
        },
        "uncertain_reasons": [],
    }


def build_peers(messages: list[dict], extractor=rules_extractor, saved: dict[str, dict] | None = None) -> list[dict]:
    """Extract every message, merge by Discord handle (earlier values win, later messages fill gaps),
    flag for review. `saved` maps handle -> peer already in the database, so a second import
    (e.g. someone's later "forgot my LinkedIn" message) adds to their record instead of replacing it."""
    ordered = sorted(messages, key=lambda m: m.get("timestamp") or "")
    saved = saved or {}
    by_handle: dict[str, dict] = {}
    for found in extractor(ordered):
        if not found:
            continue
        handle = found["discord_handle"]
        if handle not in by_handle and handle in saved:
            by_handle[handle] = _seed_from_saved(saved[handle])
        existing = by_handle.get(handle)
        if existing is None:
            by_handle[handle] = found
            continue
        existing["source_message_ids"] += found["source_message_ids"]
        existing["source_text"] += "\n---\n" + found["source_text"]
        existing.setdefault("uncertain_reasons", []).extend(found.get("uncertain_reasons", []))
        for key, value in found.items():
            if key in ("source_message_ids", "source_text", "field_sources", "uncertain_reasons"):
                continue
            if value and not existing.get(key):
                existing[key] = value
                # Only relabel where a value came from if we actually took the new value.
                label = {"name": "name", "location_raw": "location"}.get(key)
                if label:
                    existing["field_sources"][label] = found["field_sources"][label]
    return [_finalize(p) for p in by_handle.values()]
