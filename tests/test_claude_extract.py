"""Offline tests for core/claude_extract.py - no API calls, no cost.

We test the parts around the API call: how messages are formatted for Claude,
how Claude's JSON becomes a peer, and that a failed call falls back to rules.
"""
import anthropic

from core.claude_extract import ClaudeExtractor, _format_message, _to_peer
from core.extract import build_peers

MSG = {
    "id": "m1", "author_handle": "Ana", "timestamp": "2026-10-03T11:00",
    "content": "Hi all, I'm Ana from BLR! https://www.linkedin.com/in/ana-sample/",
    "linkedin_urls": ["https://www.linkedin.com/in/ana-sample/"],
    "embed": {"name": "Ana Rao", "company": "Kestrel <AI>", "location": "Bengaluru", "headline": None},
}

CLAUDE_RESULT = {
    "message_id": "m1", "is_introduction": True, "name": "Ana Rao", "role": None, "company": "Kestrel AI",
    "location_as_written": "BLR", "city": "Bengaluru", "region": "Karnataka", "country": "India",
    "experience_years": 7, "skills": ["Python"], "open_to": ["Mentoring"],
    "uncertain_fields": ["city", "region"],
}


def test_message_is_tagged_and_escaped():
    text = _format_message(MSG)
    assert text.startswith('<message id="m1" author="Ana">')
    assert 'company="Kestrel &lt;AI&gt;"' in text  # preview values can't break the tags


def test_claude_json_becomes_peer():
    peer = _to_peer(MSG, CLAUDE_RESULT)
    assert peer["city"] == "Bengaluru" and peer["country"] == "India"
    assert peer["linkedin_url"] == "https://www.linkedin.com/in/ana-sample/"  # from regex, not Claude
    assert peer["experience"] == "7+ years"
    # "region" doubts are ignored; "city" doubts go to review.
    assert peer["uncertain_reasons"] == ["Claude interpreted: city"]


def test_not_an_introduction_returns_none():
    assert _to_peer(MSG, {**CLAUDE_RESULT, "is_introduction": False}) is None


def test_failed_api_call_falls_back_to_rules(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    extractor = ClaudeExtractor()

    def boom(batch):
        raise anthropic.APIConnectionError(request=None)

    monkeypatch.setattr(extractor, "_call", boom)
    peers = build_peers([MSG], extractor=extractor)
    assert extractor.failed_batches == 1
    assert peers[0]["linkedin_url"] == "https://www.linkedin.com/in/ana-sample/"
