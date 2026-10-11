"""Turn raw Discord text into clean message records.

When you copy messages out of Discord, the text looks like this:

    Lena R — 10/3/26, 11:23 AM                                         <- header: who + when
    Hello all, Lena from London https://www.linkedin.com/in/lena/      <- what they wrote
    Lena Rao - Acme | LinkedIn                                         <- link preview title
    Experience: Acme · Education: ... · Location: United Kingdom ...   <- link preview text
    Image                                                              <- attachment placeholder

Every header line starts a new message; everything until the next header
belongs to it. Link previews are pulled out separately because they carry
useful facts (full name, company, location) that the person didn't type.
"""
import hashlib
import html
import re
from datetime import date, datetime, timedelta

# "Name — 10/3/26, 11:23 AM" / "Name — Yesterday at 2:13 PM" / "Name — 7:37 AM"
HEADER_RE = re.compile(
    r"^(?P<handle>.+?)\s+[—–]\s+"
    r"(?P<when>(?:\d{1,2}/\d{1,2}/\d{2,4},\s*|Yesterday at\s+|Today at\s+)?\d{1,2}:\d{2}\s*[AP]M)\s*$",
    re.IGNORECASE,
)
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/([^\s/?#)\]>,]+)", re.IGNORECASE)

# Lines Discord adds that aren't part of what anyone wrote.
NOISE_RE = re.compile(r"^(Image|Forwarded|&nbsp;|\(edited\))$", re.IGNORECASE)
CHANNEL_DIVIDER_RE = re.compile(r"^#\S+\s+•")           # "#oct-2026-cohort  •  Friday"
THREAD_PREVIEW_RE = re.compile(r"^\d+ Messages? ›$")    # "2 Messages ›"
AGO_RE = re.compile(r"^\d+[smhdw] ago$")                 # "3d ago"

INVISIBLE = dict.fromkeys(map(ord, "‎‏​﻿"))  # direction marks etc.


def normalize_linkedin(slug: str) -> str:
    """'JaneDoe' / 'jane-doe-12345?utm=x' -> 'https://www.linkedin.com/in/janedoe/'"""
    return f"https://www.linkedin.com/in/{slug.rstrip('.').lower()}/"


def find_linkedin_urls(text: str) -> list[str]:
    """All personal LinkedIn profile links in the text, cleaned and de-duplicated."""
    return list(dict.fromkeys(normalize_linkedin(s) for s in LINKEDIN_RE.findall(text)))


def _parse_when(when: str, today: date) -> str:
    """Discord's three timestamp styles -> ISO string like '2026-10-03T11:23'."""
    clock = re.search(r"(\d{1,2}:\d{2})\s*([AP]M)$", when, re.IGNORECASE)
    t = datetime.strptime(clock.group(1) + clock.group(2).upper(), "%I:%M%p").time()
    if when.lower().startswith("yesterday"):
        d = today - timedelta(days=1)
    elif m := re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", when):
        month, day, year = map(int, m.groups())  # Discord's US format: M/D/YY
        d = date(year + 2000 if year < 100 else year, month, day)
    else:  # "Today at ..." or just a time
        d = today
    return datetime.combine(d, t).isoformat(timespec="minutes")


def _is_preview_text(line: str) -> bool:
    """The '... · Experience: X · Location: Y · 500+ connections on LinkedIn' line."""
    return "LinkedIn" in line and "·" in line and "linkedin.com" not in line.lower()


def _is_preview_title(line: str) -> bool:
    """The 'Full Name - Company | LinkedIn' line (sometimes cut off with '...')."""
    return " - " in line and ("|" in line or line.endswith("...")) and "linkedin.com" not in line.lower()


def parse_preview(title: str, text_lines: list[str]) -> dict:
    """Read name / company / location out of a LinkedIn link preview."""
    parts = [p.strip() for p in title.split(" - ")]
    preview = {"name": parts[0], "company": None, "location": None, "education": None, "headline": None}

    rest = " - ".join(parts[1:])
    if "|" in rest:
        first = rest.split("|")[0].strip()
        # "Toronto, Ontario, Canada | Professional Profile" is a place; "Intuit | LinkedIn" is a company.
        if re.search(r"\|\s*(Prof|プロフェッショナル)", rest):
            preview["location"] = first
        else:
            preview["company"] = first

    text = html.unescape(" ".join(text_lines))
    for i, segment in enumerate(s.strip() for s in text.split("·")):
        if m := re.match(r"^(Experience|Education|Location):\s*(.+)$", segment):
            key = {"Experience": "company", "Education": "education", "Location": "location"}[m.group(1)]
            preview[key] = m.group(2).strip()
        elif i == 0 and "connections" not in segment:
            preview["headline"] = segment.rstrip("…").strip()
    return preview


def _clean_body(lines: list[str]) -> tuple[list[str], dict | None]:
    """Remove Discord clutter and link previews. Returns (text lines, first LinkedIn preview)."""
    drop = set()
    preview = None
    for i, line in enumerate(lines):
        if NOISE_RE.match(line) or CHANNEL_DIVIDER_RE.match(line):
            drop.add(i)
        elif THREAD_PREVIEW_RE.match(line):
            # Thread preview block: "<thread title>", "2 Messages ›", "<author>", "3d ago"
            drop.update({i - 1, i, i + 1})
            if i + 2 < len(lines) and AGO_RE.match(lines[i + 2]):
                drop.add(i + 2)
        elif _is_preview_text(line):
            # Walk back to find the preview title; anything between is preview text too.
            start = i
            for j in range(i - 1, -1, -1):
                if _is_preview_title(lines[j]):
                    start = j
                    break
                if find_linkedin_urls(lines[j]):  # reached the message itself; no title found
                    break
            drop.update(range(start, i + 1))
            if preview is None and start < i:
                preview = parse_preview(lines[start], lines[start + 1 : i + 1])
    kept = [line for i, line in enumerate(lines) if i not in drop and line.strip()]
    return kept, preview


def parse_export_json(data: dict) -> list[dict]:
    """Messages from a DiscordChatExporter JSON file (what a moderator can export with a bot token).

    Same output shape as parse_paste(), but with real Discord message ids and timestamps.
    """
    messages = []
    for m in data.get("messages", []):
        content = (m.get("content") or "").strip()
        if not content or m.get("type") not in (None, "Default", "Reply"):
            continue
        author = m.get("author") or {}
        preview = None
        for embed in m.get("embeds") or []:
            if "linkedin.com/in/" in (embed.get("url") or "") and embed.get("title"):
                preview = parse_preview(embed["title"], [embed.get("description") or ""])
                break
        messages.append({
            "id": str(m["id"]),
            "author_id": str(author.get("id")) if author.get("id") else None,
            "author_handle": author.get("nickname") or author.get("name") or "unknown",
            "timestamp": (m.get("timestamp") or "")[:16] or None,  # "2026-10-03T11:23"
            "content": content,
            "linkedin_urls": find_linkedin_urls(content),
            "embed": preview,
        })
    return messages


def parse_paste(text: str, today: date | None = None) -> list[dict]:
    """Split pasted Discord text into message dicts.

    Each message: id, author_handle, timestamp, content, linkedin_urls, embed.
    `today` resolves "Yesterday at ..." / "7:37 AM" (defaults to the real today).
    Lines before the first header (a partial message cut off by the copy) are skipped.
    """
    today = today or date.today()
    messages, current = [], None

    def flush():
        if current is None:
            return
        body, preview = _clean_body(current["lines"])
        content = "\n".join(body).strip()
        if not content:
            return
        key = f"{current['handle']}|{current['timestamp']}|{content}"
        messages.append({
            "id": hashlib.sha1(key.encode("utf-8")).hexdigest()[:16],  # same text -> same id
            "author_handle": current["handle"],
            "timestamp": current["timestamp"],
            "content": content,
            "linkedin_urls": find_linkedin_urls(content),
            "embed": preview,
        })

    for raw in text.splitlines():
        line = raw.translate(INVISIBLE).rstrip()
        if header := HEADER_RE.match(line.strip()):
            flush()
            handle = header.group("handle").strip().rstrip(",").strip()  # "DevK [ABC]," -> "DevK [ABC]"
            current = {"handle": handle, "timestamp": _parse_when(header.group("when"), today), "lines": []}
        elif current is not None:
            current["lines"].append(line.strip())
    flush()
    return messages
