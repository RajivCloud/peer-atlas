"""Settings: your name, the connection-note template, weekly pacing, extraction engine."""
import os

import streamlit as st

from core import db
from core.templates import (DEFAULT_COHORT, DEFAULT_NAME, DEFAULT_TEMPLATE, NOTE_LIMIT, VARIABLES, fill,
                            unknown_variables)
from ui.common import load_peers, page_header

page_header("Settings", "Your note and preferences")
df = load_peers()

left, right = st.columns([1.4, 1], gap="large")

with left, st.container(border=True):
    st.subheader("Connection note", anchor=False)
    my_name = st.text_input("Your name", db.get_setting("my_name", DEFAULT_NAME))
    cohort = st.text_input("How you describe the group", db.get_setting("cohort", DEFAULT_COHORT))
    template = st.text_area("Template", db.get_setting("note_template", DEFAULT_TEMPLATE), height=110)
    st.caption("Variables: " + " · ".join(f"`{{{k}}}` {v.lower()}" for k, v in VARIABLES.items()))

    typos = unknown_variables(template)
    if typos:
        st.error("Unknown variable: " + ", ".join(f"{{{t}}}" for t in typos)
                 + ". It would be sent as-is.", icon=":material/error:")

    if not df.empty:
        notes = {p["id"]: fill(template, p, my_name, cohort) for p in df.to_dict("records")}
        sample = df[df["role"].notna() & df["city"].notna()].head(1).to_dict("records") or df.head(1).to_dict("records")
        st.markdown(f"**Preview for {sample[0]['name'] or sample[0]['discord_handle']}**")
        st.code(notes[sample[0]["id"]], language=None, wrap_lines=True)

        too_long = [n for n in notes.values() if len(n) > NOTE_LIMIT]
        longest = max(len(n) for n in notes.values())
        if too_long:
            st.warning(f"{len(too_long)} of {len(notes)} notes would be over {NOTE_LIMIT} characters "
                       f"(longest: {longest}). Shorten the template.", icon=":material/warning:")
        else:
            st.success(f"All {len(notes)} notes fit LinkedIn's limit (longest: {longest} / {NOTE_LIMIT}).",
                       icon=":material/check_circle:")

    a, b = st.columns(2)
    if a.button("Save", type="primary", width="stretch", disabled=bool(typos)):
        db.set_setting("my_name", my_name.strip())
        db.set_setting("cohort", cohort.strip())
        db.set_setting("note_template", template.strip())
        st.toast("Saved", icon=":material/check:")
    if b.button("Restore default template", width="stretch"):
        db.set_setting("note_template", DEFAULT_TEMPLATE)
        st.rerun()

with right:
    with st.container(border=True):
        st.subheader("Weekly pacing", anchor=False)
        limit = st.number_input("Warn me after this many requests per week", 10, 300,
                                int(db.get_setting("weekly_limit", "100")), step=10)
        if limit != int(db.get_setting("weekly_limit", "100")):
            db.set_setting("weekly_limit", str(limit))
            st.toast("Weekly limit saved", icon=":material/check:")
        st.caption("LinkedIn limits weekly invitations (roughly 100–200, depending on the account). "
                   "Staying under the limit keeps your account safe.")
        st.progress(min(db.sent_this_week() / limit, 1.0), text=f"Sent this week: {db.sent_this_week()} / {limit}")

    with st.container(border=True):
        st.subheader("Extraction engine", anchor=False)
        model = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
        key_set = bool(os.getenv("ANTHROPIC_API_KEY")) or os.path.exists(".env")
        st.markdown(f"**Claude model:** `{model}`  \n**API key:** {'found in .env' if key_set else 'missing'}")
        st.caption("Change the model by adding `CLAUDE_MODEL=claude-haiku-5-5` to your `.env` file "
                   "(cheaper, a little less accurate), then restart the app.")
