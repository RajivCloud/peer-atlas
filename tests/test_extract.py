"""Tests for the rules-only extractor in core/extract.py (made-up people)."""
from core.extract import build_peers, find_location, find_name, find_role


def msg(handle, text, mid, urls=None, embed=None, ts="2026-10-03T11:00"):
    return {"id": mid, "author_handle": handle, "timestamp": ts, "content": text,
            "linkedin_urls": urls or [], "embed": embed}


def test_find_name_patterns():
    assert find_name("Hello all, I am Bharat Kumar from Dublin, CA!") == "Bharat Kumar"
    assert find_name("Hey Guys! It's Sam from Australia!") == "Sam"
    assert find_name("Hello everyone, Lena Park here from Seattle") == "Lena Park"
    assert find_name("Hi, Mo living in Austin, TX") == "Mo"
    assert find_name("Hello, Greetings from Folsom, CA.") is None
    assert find_name("I am from India") is None


def test_find_location_stops_at_sentence_and_filler():
    assert find_location("Leo here from Tampa, Florida. Looking forward") == "Tampa, Florida"
    assert find_location("I'm Ana from Dallas,  Lead AI Engineer at Acme") == "Dallas"
    assert find_location("based out of Morganville NJ. https://x") == "Morganville NJ"
    assert find_location("from Washington D.C. area. Hi") == "Washington D.C"
    assert find_location("I work in the pharma industry") is None
    assert find_location("I am Priya from Dublin, CA https://www.linkedin.com/in/x") == "Dublin, CA"


def test_find_role():
    assert find_role("working as a Ai Engineer in Dallas") == "AI Engineer"
    assert find_role("I lead customer improvement") is None
    assert find_role("Staff software engineer from bay area") == "Staff Software Engineer"


def test_chit_chat_is_skipped_and_same_person_is_merged():
    messages = [
        msg("Chris", "Hi everyone, I'm Chris from London.", "m1"),
        msg("Chris", "forgot my linkedin", "m2", urls=["https://www.linkedin.com/in/chris-sample/"],
            ts="2026-10-03T11:05"),
        msg("Sam", "add me too", "m3"),
    ]
    peers = build_peers(messages)
    assert len(peers) == 1
    chris = peers[0]
    assert chris["location_raw"] == "London"
    assert chris["linkedin_url"] == "https://www.linkedin.com/in/chris-sample/"
    assert chris["source_message_ids"] == ["m1", "m2"]
    assert chris["needs_review"] == 0


def test_shortened_preview_name_loses_to_message_name():
    embed = {"name": "Remy R.", "company": "Acme", "location": "United Kingdom", "headline": None}
    peers = build_peers([msg("remy", "Hello all, Remy Rao from London here",
                             "m1", urls=["https://www.linkedin.com/in/remy/"], embed=embed)])
    assert peers[0]["name"] == "Remy Rao"
    assert peers[0]["company"] == "Acme"


def test_missing_linkedin_is_flagged_for_review():
    peers = build_peers([msg("Tom", "Hi Everyone, I am Tom, based out of Perth, Australia.", "m1")])
    assert peers[0]["needs_review"] == 1
    assert "No LinkedIn link" in peers[0]["review_reason"]
