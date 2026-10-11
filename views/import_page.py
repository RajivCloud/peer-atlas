"""Import: add Discord messages (paste or export file), export the directory as CSV."""
import json

import streamlit as st

from core import db
from core.ingest import parse_export_json, parse_paste
from core.pipeline import import_messages, preview
from ui.common import load_peers, page_header, refresh

page_header("Import", "Add messages from Discord",
            "Messages are only extracted once, so pasting overlapping chunks is safe and costs nothing extra.")

counts = db.message_counts()
peers_total = len(db.list_peers())
st.caption(f"So far: {counts['total']} messages imported, {peers_total} peers.")

# ---------------------------------------------------------------- 1. get messages
paste_tab, file_tab = st.tabs(["Paste from Discord", "Upload export file"])
messages = []
with paste_tab:
    st.markdown("In Discord, select a stretch of messages (including the name/time lines), "
                "copy with **Ctrl+C**, and paste below. Tip: search `linkedin.com` in the channel to find intros fast.")
    pasted = st.text_area("Messages", height=220, label_visibility="collapsed",
                          placeholder="LenaR — 10/3/26, 11:23 AM\nHello all, Lena from London here …")
    if pasted.strip():
        messages = parse_paste(pasted)
with file_tab:
    st.markdown("If a server moderator exports the channel with **DiscordChatExporter** (JSON format), "
                "upload it here. A saved paste (`.txt`) works too.")
    upload = st.file_uploader("Export file", type=["json", "txt"], label_visibility="collapsed")
    if upload is not None:
        raw = upload.getvalue().decode("utf-8-sig")
        try:
            messages = parse_export_json(json.loads(raw)) if upload.name.endswith(".json") else parse_paste(raw)
        except (json.JSONDecodeError, KeyError) as e:
            st.error(f"Couldn't read that file: {e}. Is it a DiscordChatExporter JSON export?",
                     icon=":material/error:")

# ---------------------------------------------------------------- 2. preview + run
if messages:
    p = preview(messages)
    with st.container(border=True):
        st.subheader("Ready to import", anchor=False)
        m = st.columns(4)
        m[0].metric("Messages found", p["messages"])
        m[1].metric("New", p["new"])
        m[2].metric("Already imported", p["already_imported"])
        m[3].metric("Authors", p["authors"])

        engine = st.radio(
            "Extraction", ["claude", "rules"], horizontal=True,
            format_func=lambda e: (f"Claude · best accuracy · about ${p['estimated_cost']:.2f}"
                                   if e == "claude" else "Rules only · free · weaker on roles and places"),
        )
        if st.button(f"Import {p['to_extract']} message{'s' if p['to_extract'] != 1 else ''}", type="primary",
                     icon=":material/download:", disabled=p["to_extract"] == 0):
            bar = st.progress(0.0, text="Starting…")
            try:
                summary = import_messages(
                    messages, engine,
                    on_progress=lambda done, total: bar.progress(done / total, text=f"Claude: {done} / {total} messages"),
                )
            except Exception as e:  # missing API key, network down, etc.
                st.error(f"Import failed: {e}", icon=":material/error:")
            else:
                bar.progress(1.0, text="Done")
                refresh()
                cost = f" · cost ${summary['cost_usd']:.2f}" if summary["cost_usd"] is not None else ""
                st.success(f"Updated {summary['peers_updated']} peers from {summary['extracted']} messages; "
                           f"{summary['on_map']} on the map, {summary['need_review']} to review{cost}.",
                           icon=":material/check_circle:")
                st.page_link("views/review.py", label="Go to Review", icon=":material/fact_check:")
        if p["to_extract"] == 0:
            st.caption("Nothing new here: every message was already imported.")

# ---------------------------------------------------------------- export + maintenance
st.divider()
exp, fresh = st.columns(2, gap="large")
with exp:
    st.subheader("Export", anchor=False)
    df = load_peers()
    if not df.empty:
        cols = ["name", "role", "company", "city", "region", "country", "linkedin_url", "experience",
                "skills", "open_to", "discord_handle", "status", "sent_at"]
        out = df[cols].assign(skills=df["skills"].map(", ".join), open_to=df["open_to"].map(", ".join))
        st.download_button("Download directory (CSV)", out.to_csv(index=False).encode("utf-8-sig"),
                           "peer_atlas.csv", "text/csv", icon=":material/table:")
        st.caption("Opens in Excel or Google Sheets. Contains peers' details: keep it within the community.")
with fresh:
    st.subheader("Start extraction over", anchor=False)
    st.caption("Re-extract every message, e.g. after switching from rules to Claude. "
               "Records you reviewed or contacted are kept.")
    sure = st.checkbox("I understand unreviewed records will be rebuilt")
    if st.button("Reset extraction", disabled=not sure, icon=":material/restart_alt:"):
        removed = db.reset_extraction()
        refresh()
        st.success(f"Removed {removed} unreviewed records. Paste or upload your messages again to rebuild them "
                   "(already-imported messages will be re-extracted).", icon=":material/check:")
