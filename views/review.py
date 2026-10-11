"""Review: check records the extractor wasn't sure about, next to the original Discord message."""
import html

import streamlit as st

from core import db
from core.pipeline import approve
from ui.common import empty_state, load_peers, page_header, refresh

OPEN_TO = ["Mentoring", "Hiring", "Job search", "Collaborating", "Study group"]


def text(value) -> str:
    return value if isinstance(value, str) else ""


page_header("Review", "Check what the extractor wasn't sure about",
            "Fix anything that's wrong, then approve. Approved records are locked: "
            "later imports won't overwrite your edits.")

df = load_peers()
if df.empty:
    empty_state()
    st.stop()

show_all = st.toggle("Show everyone, not just flagged records", key="review_all")
queue = df if show_all else df[(df["needs_review"] == 1) & (df["reviewed"] == 0)]
queue = queue.sort_values("name", key=lambda s: s.fillna("").str.lower())

if queue.empty:
    st.success("All caught up. Every flagged record has been checked.", icon=":material/task_alt:")
    st.stop()

left, right = st.columns([1, 2.2], gap="large")

with left:
    st.caption(f"{len(queue)} to check" if not show_all else f"{len(queue)} peers")
    labels = {r["id"]: f"{text(r['name']) or r['discord_handle']}" for r in queue.to_dict("records")}
    current = st.session_state.get("review_id")
    if current not in labels:
        current = next(iter(labels))
    peer_id = st.radio("Records", list(labels), index=list(labels).index(current),
                       format_func=labels.get, label_visibility="collapsed", key="review_pick")
    st.session_state["review_id"] = peer_id

peer = db.get_peer(peer_id)

with right, st.container(border=True):
    st.markdown(f"**Source message** · @{html.escape(peer['discord_handle'])}")
    for part in (peer["source_text"] or "").split("\n---\n"):
        st.markdown(f"> {html.escape(part).replace(chr(10), '  '+chr(10)+'> ')}")

    if peer["review_reason"]:
        st.warning(peer["review_reason"], icon=":material/flag:")
    elif peer["reviewed"]:
        st.success("You already reviewed this record.", icon=":material/verified:")

    with st.form(f"review_{peer_id}", border=False):
        a, b = st.columns(2)
        name = a.text_input("Name", text(peer["name"]))
        role = b.text_input("Role", text(peer["role"]))
        company = a.text_input("Company", text(peer["company"]))
        experience = b.text_input("Experience", text(peer["experience"]), placeholder="e.g. 10+ years")
        c1, c2, c3 = st.columns(3)
        city = c1.text_input("City", text(peer["city"]))
        region = c2.text_input("State / region", text(peer["region"]))
        country = c3.text_input("Country", text(peer["country"]))
        linkedin = st.text_input("LinkedIn URL", text(peer["linkedin_url"]), placeholder="linkedin.com/in/…")
        skills = st.text_input("Skills (comma-separated)", ", ".join(peer["skills"]))
        open_to = st.multiselect("Open to", OPEN_TO, [o for o in peer["open_to"] if o in OPEN_TO])

        ok, remove = st.columns([2, 1])
        approved = ok.form_submit_button("Approve", type="primary", icon=":material/check:", width="stretch")
        removed = remove.form_submit_button("Not an intro: remove", icon=":material/delete:", width="stretch")

    if approved:
        try:
            approve(peer_id, {
                "name": name, "role": role, "company": company, "experience": experience,
                "city": city, "region": region, "country": country, "linkedin_url": linkedin,
                "skills": [s.strip() for s in skills.split(",") if s.strip()], "open_to": open_to,
            })
        except ValueError as e:
            st.error(str(e), icon=":material/error:")
        else:
            refresh()
            st.session_state.pop("review_id", None)  # move on to the next record
            st.toast(f"Approved {name or peer['discord_handle']}", icon=":material/check:")
            st.rerun()
    if removed:
        db.delete_peer(peer_id)
        refresh()
        st.session_state.pop("review_id", None)
        st.toast("Removed. Their messages stay imported, so they won't be re-extracted.",
                 icon=":material/delete:")
        st.rerun()
