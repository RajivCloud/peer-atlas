"""End-to-end import test: paste -> database, using the free rules engine and a temp DB."""
import pytest

from core import db
from core.pipeline import import_text

FIRST = """\
Chris W — 10/3/26, 11:23 AM
Hey! Chris here, engineering manager based in London, UK.
Priya — 10/3/26, 11:25 AM
Hi all, I am Priya from Dublin, CA https://www.linkedin.com/in/priya-sample/
"""
LATER = FIRST + """\
Chris W — 10/4/26, 9:00 AM
forgot my linkedin: https://www.linkedin.com/in/chris-sample/
"""


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")


def test_import_puts_peers_on_the_map():
    summary = import_text(FIRST, engine="rules")
    assert summary["new_messages"] == 2 and summary["peers_updated"] == 2
    priya = next(p for p in db.list_peers() if p["discord_handle"] == "Priya")
    assert (priya["city"], priya["region"]) == ("Dublin", "California")
    assert 37 < priya["lat"] < 38


def test_reimport_only_processes_new_messages_and_merges():
    import_text(FIRST, engine="rules")
    summary = import_text(LATER, engine="rules")
    assert summary["new_messages"] == 1 and summary["extracted"] == 1

    peers = db.list_peers()
    assert len(peers) == 2
    chris = next(p for p in peers if p["discord_handle"] == "Chris W")
    assert chris["linkedin_url"] == "https://www.linkedin.com/in/chris-sample/"
    assert chris["city"] == "London"            # kept from the first message
    assert len(chris["source_message_ids"]) == 2


def test_fresh_reset_keeps_reviewed_peers():
    import_text(FIRST, engine="rules")
    priya = next(p for p in db.list_peers() if p["discord_handle"] == "Priya")
    db.update_peer(priya["id"], role="Data Scientist", reviewed=1)
    assert db.reset_extraction() == 1           # only Chris (unreviewed) removed
    import_text(FIRST, engine="rules")
    assert next(p for p in db.list_peers() if p["discord_handle"] == "Priya")["role"] == "Data Scientist"
