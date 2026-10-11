"""Tests for core/ingest.py using a made-up paste in Discord's real copy format.

(Fake people only - real community data must never be committed.)
"""
from datetime import date

from core.ingest import find_linkedin_urls, parse_paste

TODAY = date(2026, 10, 11)

PASTE = """\
cut-off line from a message above the copy
Jordan K — 10/3/26, 11:23 AM
Hello all, Jordan Kim from Austin, TX https://www.linkedin.com/in/Jordan-Kim-Sample/?utm_source=share
Jordan Kim - Lumen Labs | LinkedIn
Data scientist building forecasting tools… · Experience: Lumen Labs · Education: UT Austin · Location: Austin · 500+ connections on LinkedIn. View Jordan Kim’s profile on LinkedIn, a professional community of 1 billion members.
Image
Priya — 10/3/26, 11:25 AM
Hi, this is Priya from Pune.
Thread title preview
2 Messages ›
Priya
3d ago
#oct-2026-cohort  •  Friday
DevK [ABC],  — Yesterday at 2:13 PM
Hi This is Ram from NJ www.linkedin.com/in/ram-sample
Sam — 7:37 AM
add me too
"""


def test_splits_messages_and_skips_cut_off_line():
    msgs = parse_paste(PASTE, today=TODAY)
    assert [m["author_handle"] for m in msgs] == ["Jordan K", "Priya", "DevK [ABC]", "Sam"]


def test_timestamps_in_all_three_formats():
    msgs = parse_paste(PASTE, today=TODAY)
    assert [m["timestamp"] for m in msgs] == [
        "2026-10-03T11:23", "2026-10-03T11:25", "2026-10-10T14:13", "2026-10-11T07:37",
    ]


def test_link_preview_is_removed_from_text_and_parsed():
    jordan = parse_paste(PASTE, today=TODAY)[0]
    assert "Experience:" not in jordan["content"]
    assert "Image" not in jordan["content"]
    assert jordan["embed"]["name"] == "Jordan Kim"
    assert jordan["embed"]["company"] == "Lumen Labs"
    assert jordan["embed"]["location"] == "Austin"


def test_thread_preview_and_channel_divider_are_removed():
    priya = parse_paste(PASTE, today=TODAY)[1]
    assert priya["content"] == "Hi, this is Priya from Pune."


def test_same_paste_gives_same_ids():
    assert [m["id"] for m in parse_paste(PASTE, today=TODAY)] == [m["id"] for m in parse_paste(PASTE, today=TODAY)]


def test_linkedin_urls_are_normalized():
    assert find_linkedin_urls(
        "a http://linkedin.com/in/Ram-S-123/?isSelfProfile=true b www.linkedin.com/in/ram-s-123 c "
        "linkedin.com/company/acme"
    ) == ["https://www.linkedin.com/in/ram-s-123/"]
