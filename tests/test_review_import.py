"""Tests for the Review (approve) and Import (preview, export JSON) logic. Free: rules engine, temp DB."""
import pytest

from core import db
from core.ingest import parse_export_json
from core.pipeline import approve, import_text, preview
from core.ingest import parse_paste

PASTE = """\
Leela — 10/4/26, 11:37 AM
Leela from BLR! Data scientist. https://www.linkedin.com/in/leela-sample/
"""


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")


def test_preview_counts_only_new_messages():
    assert preview(parse_paste(PASTE))["new"] == 1
    import_text(PASTE, engine="rules")
    p = preview(parse_paste(PASTE))
    assert p["new"] == 0 and p["already_imported"] == 1 and p["estimated_cost"] == 0


def test_approve_moves_map_point_and_locks_record():
    import_text(PASTE, engine="rules")
    peer = db.list_peers()[0]
    approve(peer["id"], {"name": "Leela P.", "city": "Pune", "region": None, "country": "India",
                         "linkedin_url": "linkedin.com/in/Leela-Sample?utm=x", "skills": ["NLP"]})
    after = db.get_peer(peer["id"])
    assert after["city"] == "Pune" and 18 < after["lat"] < 19          # moved from Bengaluru to Pune
    assert after["linkedin_url"] == "https://www.linkedin.com/in/leela-sample/"
    assert after["reviewed"] == 1 and after["needs_review"] == 0


def test_approve_rejects_non_profile_link():
    import_text(PASTE, engine="rules")
    with pytest.raises(ValueError):
        approve(db.list_peers()[0]["id"], {"linkedin_url": "https://linkedin.com/company/acme"})


def test_discord_exporter_json():
    data = {"messages": [
        {"id": "111", "type": "Default", "timestamp": "2026-10-03T11:23:45.123+00:00",
         "content": "Hi, I'm Sam from Austin https://www.linkedin.com/in/sam-sample/",
         "author": {"id": "9", "name": "sam_k", "nickname": "Sam K"},
         "embeds": [{"url": "https://www.linkedin.com/in/sam-sample/", "title": "Sam Kim - Acme | LinkedIn",
                     "description": "Experience: Acme · Location: Austin · 500+ connections on LinkedIn."}]},
        {"id": "112", "type": "ThreadCreated", "content": "thread", "author": {"name": "x"}},
    ]}
    msgs = parse_export_json(data)
    assert len(msgs) == 1
    assert msgs[0]["author_handle"] == "Sam K" and msgs[0]["timestamp"] == "2026-10-03T11:23"
    assert msgs[0]["embed"]["company"] == "Acme"
