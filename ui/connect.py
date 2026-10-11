"""Assisted Connect: the pop-up that walks you through sending LinkedIn requests.

The app never clicks anything on LinkedIn for you (there is no API for invitations,
and automating clicks risks your account). It prepares the note, opens the profile,
and records what you did. The final "Send" on LinkedIn is yours.

A "queue" is just a list of peer ids in session_state; the dialog shows one at a time.
"""
import streamlit as st

from core import db
from core.extract import display_location
from core.templates import DEFAULT_COHORT, DEFAULT_NAME, DEFAULT_TEMPLATE, NOTE_LIMIT, fill
from ui.common import refresh


def start_queue(peer_ids: list[int]) -> None:
    st.session_state.queue = list(peer_ids)
    st.session_state.queue_pos = 0
    st.session_state.queue_stats = {"sent": 0, "skipped": 0}


def stop_queue() -> None:
    for key in ("queue", "queue_pos", "queue_stats"):
        st.session_state.pop(key, None)
    st.session_state.pop("selected", None)
    refresh()


def queue_active() -> bool:
    return bool(st.session_state.get("queue"))


def _next() -> None:
    st.session_state.queue_pos += 1
    st.rerun(scope="fragment")  # redraw only the dialog, keep it open


@st.dialog("Connect on LinkedIn", width="medium", on_dismiss=stop_queue)
def connect_dialog() -> None:
    queue, pos, stats = st.session_state.queue, st.session_state.queue_pos, st.session_state.queue_stats
    many = len(queue) > 1

    if pos >= len(queue):  # finished
        st.subheader(f"{stats['sent']} sent, {stats['skipped']} skipped", anchor=False)
        limit = int(db.get_setting("weekly_limit", "100"))
        st.caption(f"You've sent {db.sent_this_week()} of your {limit} requests this week.")
        if st.button("Done", type="primary"):
            stop_queue()
            st.rerun()
        return

    peer = db.get_peer(queue[pos])
    if many:
        st.progress(pos / len(queue), text=f"Person {pos + 1} of {len(queue)}")

    st.markdown(f"### {peer['name'] or peer['discord_handle']}")
    details = " · ".join(x for x in (peer["role"], peer["company"], display_location(peer)) if x)
    st.caption(details or "No details shared")

    limit = int(db.get_setting("weekly_limit", "100"))
    if db.sent_this_week() >= limit:
        st.warning(f"You've reached your weekly limit of {limit}. LinkedIn may restrict accounts "
                   "that send too many invitations. Consider continuing next week.", icon=":material/pace:")

    note = fill(db.get_setting("note_template", DEFAULT_TEMPLATE), peer,
                db.get_setting("my_name", DEFAULT_NAME), db.get_setting("cohort", DEFAULT_COHORT))
    if st.toggle("Edit this note", key=f"edit_{peer['id']}"):
        note = st.text_area("Note", value=note, key=f"note_{peer['id']}", label_visibility="collapsed")

    st.markdown("**1. Copy your note** (copy icon on the right)")
    st.code(note, language=None, wrap_lines=True)
    if len(note) > NOTE_LIMIT:
        st.warning(f"{len(note)} characters. LinkedIn free accounts allow about {NOTE_LIMIT}; "
                   "shorten it or LinkedIn will cut it off.", icon=":material/warning:")
    else:
        st.caption(f"{len(note)} / {NOTE_LIMIT} characters")

    st.markdown("**2. Open their profile**, then on LinkedIn: **Connect → Add a note → paste → Send**")
    st.link_button("Open LinkedIn profile", peer["linkedin_url"], icon=":material/open_in_new:",
                   type="primary", width="stretch")

    st.markdown("**3. Come back and record it**")
    sent_col, skip_col = st.columns(2)
    if sent_col.button("Mark as sent", icon=":material/check:", width="stretch", key=f"sent_{peer['id']}"):
        db.set_status(peer["id"], "sent")
        stats["sent"] += 1
        if many:
            _next()
        st.toast(f"Marked as sent to {peer['name']}", icon=":material/check:")
        stop_queue()
        st.rerun()
    if skip_col.button("Skip" if many else "Cancel", width="stretch", key=f"skip_{peer['id']}"):
        if many:
            stats["skipped"] += 1
            _next()
        stop_queue()
        st.rerun()
