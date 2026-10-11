"""Tests for core/db.py. Run with:  python -m pytest -v

Each test gets its own throwaway database in a temp folder,
so your real data/peer_atlas.db is never touched.
"""
import pytest

from core import db


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def test_duplicate_messages_are_skipped():
    msg = {"id": "m1", "author_handle": "@priya", "content": "Hi, I'm Priya"}
    assert db.save_messages([msg]) == 1
    assert db.save_messages([msg]) == 0
    assert db.message_counts() == {"total": 1, "processed": 0}

    db.mark_processed(["m1"])
    assert db.pending_messages() == []


def test_new_peer_then_merge_from_second_message():
    pid = db.save_peer({"discord_handle": "@chris", "name": "Chris W.", "role": "Engineering Manager",
                        "source_message_ids": ["m1"]})
    # Second message only has the LinkedIn link; role must not be erased.
    db.save_peer({"discord_handle": "@chris", "role": "", "linkedin_url": "https://linkedin.com/in/chris",
                  "source_message_ids": ["m2"]})

    peer = db.get_peer(pid)
    assert peer["role"] == "Engineering Manager"
    assert peer["linkedin_url"] == "https://linkedin.com/in/chris"
    assert peer["source_message_ids"] == ["m1", "m2"]
    assert len(db.list_peers()) == 1


def test_reviewed_peer_is_not_overwritten():
    pid = db.save_peer({"discord_handle": "@nandini", "city": "BLR"})
    db.update_peer(pid, city="Bengaluru", reviewed=1)
    db.save_peer({"discord_handle": "@nandini", "city": "Bangalore"})
    assert db.get_peer(pid)["city"] == "Bengaluru"


def test_status_and_weekly_count():
    pid = db.save_peer({"discord_handle": "@sam"})
    assert db.sent_this_week() == 0
    db.set_status(pid, "sent")
    assert db.sent_this_week() == 1
    db.set_status(pid, "connected")
    assert db.get_peer(pid)["status"] == "connected"
    with pytest.raises(ValueError):
        db.set_status(pid, "best friends")


def test_settings_round_trip():
    assert db.get_setting("my_name", "Rajiv") == "Rajiv"
    db.set_setting("my_name", "Rajiv K")
    assert db.get_setting("my_name") == "Rajiv K"
