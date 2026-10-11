"""Extract peer details with Claude.

How it works:
  1. Messages are sent in batches of 20, each wrapped in <message> tags with its
     LinkedIn link preview (if any) as extra context.
  2. Structured outputs force Claude to answer with JSON matching RESULT_SCHEMA,
     so we never have to parse free text.
  3. LinkedIn URLs come from our own regex (core/ingest.py), never from Claude,
     so a link can't be invented.
  4. If a batch fails (network, rate limit), we fall back to the rules extractor
     for that batch and carry on.

Settings come from .env:
  ANTHROPIC_API_KEY   required
  CLAUDE_MODEL        optional, default claude-opus-5-5 (e.g. claude-haiku-5-5 for cheaper runs)
"""
import json
import os
from html import escape

import anthropic
from dotenv import load_dotenv

from core.extract import extract_rules

load_dotenv()

DEFAULT_MODEL = "claude-opus-5-5"
BATCH_SIZE = 20
REVIEW_FIELDS = {"name", "city", "role", "company"}

# USD per million tokens (input, output). Used only to show an estimated cost.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

SYSTEM_PROMPT = """\
You extract professional profile details from Discord messages posted in the general channel \
of an online AI course community. Members were asked to introduce themselves.

For each message, first decide whether it is a self-introduction: the author telling others \
who they are, where they are, or what they do. Greetings with no details, replies to other \
people, questions, group invitations and thank-you notes are not introductions, even if they \
mention a place.

For introductions, extract only what the author stated about themselves, plus facts from the \
LinkedIn link preview attached to their own message. Never guess; use null when something isn't stated.

- name: the author's own name. Prefer the fuller name from the LinkedIn preview when it is \
clearly the same person; otherwise the name used in the message.
- role: job title in Title Case with small words lowercase, e.g. "Senior Product Manager" or \
"Solutions Architect and Technical Lead". Take it from the message first, then from the \
preview headline. Null if neither states one.
- company: current employer, from the message or the preview's "company".
- location_as_written: the place exactly as the author wrote it, e.g. "BLR" or "the Bay".
- city, region, country: where they live now, normalized. City uses the common English name \
("Bengaluru", not "BLR"); region is the state, province or metro area ("California", \
"San Francisco Bay Area"); country is the English name ("United States"). If only a region \
or metro area is given, leave city null. If they come from one country but live in another, \
use where they live now. The message beats the preview's location.
- experience_years: whole number of years of experience if stated anywhere.
- skills: up to 5 skills, tools or domains they mention.
- open_to: any of "Mentoring", "Hiring", "Job search", "Collaborating", "Study group" that \
they explicitly offer or ask for. Empty list if none.
- uncertain_fields: names of the fields above that you filled by interpretation rather than a \
clear statement, e.g. ["city"] when "the Bay" became a city, or ["role"] when inferred. \
Filling region and country from a clearly named city is normal and is not uncertain.

Return one result for every message id you receive."""


def _nullable(type_: str) -> dict:
    return {"type": [type_, "null"]}


RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                    "is_introduction": {"type": "boolean"},
                    "name": _nullable("string"),
                    "role": _nullable("string"),
                    "company": _nullable("string"),
                    "location_as_written": _nullable("string"),
                    "city": _nullable("string"),
                    "region": _nullable("string"),
                    "country": _nullable("string"),
                    "experience_years": _nullable("integer"),
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "open_to": {"type": "array", "items": {"type": "string"}},
                    "uncertain_fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "message_id", "is_introduction", "name", "role", "company", "location_as_written",
                    "city", "region", "country", "experience_years", "skills", "open_to", "uncertain_fields",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def _format_message(m: dict) -> str:
    """One message as tagged text. The preview is labelled so Claude knows the author didn't type it."""
    preview = ""
    if p := m.get("embed"):
        attrs = " ".join(f'{k}="{escape(str(v))}"' for k, v in p.items() if v)
        preview = f"\n<linkedin_preview {attrs} />"
    return (f'<message id="{m["id"]}" author="{escape(m["author_handle"])}">\n'
            f"{escape(m['content'])}{preview}\n</message>")


def _to_peer(message: dict, r: dict) -> dict | None:
    """Claude's JSON for one message -> the partial peer dict build_peers() expects."""
    if not r["is_introduction"]:
        return None
    urls = message.get("linkedin_urls") or []
    place = ", ".join(x for x in (r["city"], r["region"], r["country"]) if x)
    # Only doubts about these fields are worth a human's time; region/country follow from the city.
    uncertain = [f for f in r["uncertain_fields"] if f in REVIEW_FIELDS]
    return {
        "discord_handle": message["author_handle"],
        "name": r["name"],
        "role": r["role"],
        "company": r["company"],
        "location_raw": r["location_as_written"] or place or None,
        "city": r["city"],
        "region": r["region"],
        "country": r["country"],
        "linkedin_url": urls[0] if urls else None,  # from regex, never from the model
        "experience": f"{r['experience_years']}+ years" if r["experience_years"] else None,
        "skills": r["skills"][:5],
        "open_to": r["open_to"],
        "source_message_ids": [message["id"]],
        "source_text": message["content"],
        "field_sources": {
            "name": "claude" if r["name"] else None,
            "location": "claude" if place else None,
        },
        "uncertain_reasons": [f"Claude interpreted: {', '.join(uncertain)}"] if uncertain else [],
    }


class ClaudeExtractor:
    """Callable extractor for build_peers(). Tracks token usage so the UI can show the cost."""

    def __init__(self, model: str | None = None, on_progress=None):
        self.model = model or os.getenv("CLAUDE_MODEL", DEFAULT_MODEL)
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.on_progress = on_progress or (lambda done, total: None)
        self.input_tokens = self.output_tokens = 0
        self.failed_batches = 0

    @property
    def estimated_cost(self) -> float | None:
        price = PRICES.get(self.model)
        if not price:
            return None
        return (self.input_tokens * price[0] + self.output_tokens * price[1]) / 1_000_000

    def _call(self, batch: list[dict]) -> dict[str, dict]:
        request = dict(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "\n\n".join(_format_message(m) for m in batch)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
        )
        if self.model.startswith("claude-haiku"):
            response = self.client.messages.create(**request)
        else:
            # If a safety classifier declines, retry on Anthropic's recommended fallback model.
            response = self.client.beta.messages.create(
                **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens

        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined this batch")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Response was cut off (max_tokens)")
        text = next(b.text for b in response.content if b.type == "text")
        return {r["message_id"]: r for r in json.loads(text)["results"]}

    def __call__(self, messages: list[dict]) -> list[dict | None]:
        out: list[dict | None] = []
        for start in range(0, len(messages), BATCH_SIZE):
            batch = messages[start : start + BATCH_SIZE]
            try:
                results = self._call(batch)
            except (anthropic.APIError, RuntimeError, json.JSONDecodeError, StopIteration) as e:
                print(f"Claude batch {start // BATCH_SIZE + 1} failed ({e}); using rules for it.")
                self.failed_batches += 1
                results = {}
            for m in batch:
                r = results.get(m["id"])
                out.append(_to_peer(m, r) if r else extract_rules(m))
            self.on_progress(min(start + BATCH_SIZE, len(messages)), len(messages))
        return out
