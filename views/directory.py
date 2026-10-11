"""Directory: search and filter peers, and connect with them on LinkedIn."""
import html
import math

import streamlit as st

from core import db
from ui.common import empty_state, load_peers, page_header, refresh
from ui.connect import connect_dialog, queue_active, start_queue

PER_PAGE = 24
STATUS_LABELS = {"not_contacted": "Not contacted", "sent": "Request sent",
                 "connected": "Connected", "skipped": "Skipped"}
STATUS_COLORS = {"not_contacted": "gray", "sent": "orange", "connected": "green", "skipped": "gray"}


def text(value) -> str | None:
    """pandas gives NaN for empty cells; turn that (and blanks) into None."""
    return value if isinstance(value, str) and value.strip() else None


def toggle_selected(peer_id: int) -> None:
    selected = st.session_state.setdefault("selected", set())
    selected.symmetric_difference_update({peer_id})


def set_status(peer_id: int, status: str) -> None:
    db.set_status(peer_id, status)
    refresh()


page_header("Directory", "Find your people")
df = load_peers()
if df.empty:
    empty_state()
    st.stop()

# ---------------------------------------------------------------- filters
place_options = df["place"].value_counts().index.tolist()
if "filter_place" in st.session_state:  # arriving from the Dashboard's "Top places"
    st.session_state["f_place"] = st.session_state.pop("filter_place")

f = st.columns([2.2, 1.3, 1.3, 1.1, 1.1])
query = f[0].text_input("Search", placeholder="Name, company, skill…", key="f_query")
place = f[1].selectbox("Place", place_options, index=None, placeholder="All places", key="f_place")
family = f[2].selectbox("Role", sorted(df["role_family"].dropna().unique()), index=None,
                        placeholder="All roles", key="f_role")
open_opts = sorted(df["open_to"].explode().dropna().unique())
open_to = f[3].selectbox("Open to", open_opts, index=None, placeholder="Anything", key="f_open")
status = f[4].selectbox("Status", list(STATUS_LABELS), format_func=STATUS_LABELS.get, index=None,
                        placeholder="Any status", key="f_status")

view = df
if query:
    q = query.lower()
    haystack = (view[["name", "discord_handle", "role", "company", "location"]].fillna("").agg(" ".join, axis=1)
                + " " + view["skills"].map(" ".join)).str.lower()
    view = view[haystack.str.contains(q, regex=False)]
if place:
    view = view[view["place"] == place]
if family:
    view = view[view["role_family"] == family]
if open_to:
    view = view[view["open_to"].map(lambda xs: open_to in xs)]
if status:
    view = view[view["status"] == status]

# ---------------------------------------------------------------- selection toolbar
selected: set = st.session_state.setdefault("selected", set())
connectable = view[view["linkedin_url"].notna() & (view["status"] == "not_contacted")]
limit = int(db.get_setting("weekly_limit", "100"))

bar = st.columns([3, 1.4, 1, 1.8])
bar[0].markdown(f"**{len(view)}** of {len(df)} peers"
                + (f" · **{len(selected)} selected**" if selected else "")
                + f" · sent this week: {db.sent_this_week()} / {limit}")
if bar[1].button(f"Select all {len(connectable)} not contacted", width="stretch",
                 disabled=connectable.empty, help="Peers shown here who have LinkedIn and haven't been contacted"):
    selected.update(connectable["id"].tolist())
    st.rerun()
if bar[2].button("Clear", width="stretch", disabled=not selected):
    selected.clear()
    st.rerun()
if bar[3].button(f"Start connect queue ({len(selected)})", type="primary", width="stretch",
                 disabled=not selected, icon=":material/play_arrow:"):
    start_queue(sorted(selected, key=lambda i: df.loc[df["id"] == i, "name"].fillna("").iloc[0]))

# ---------------------------------------------------------------- cards
pages = max(1, math.ceil(len(view) / PER_PAGE))
page = 1
if pages > 1:
    page = st.segmented_control("Page", list(range(1, pages + 1)), default=1, key="f_page") or 1

if view.empty:
    st.info("No peers match these filters.", icon=":material/search_off:")

display_name = view["name"].fillna(view["discord_handle"]).str.lower()  # sort by what the card shows
rows = view.loc[display_name.sort_values().index].iloc[(page - 1) * PER_PAGE: page * PER_PAGE]
cols = st.columns(3, gap="small")
for i, p in enumerate(rows.to_dict("records")):
    with cols[i % 3].container(border=True):
        name = text(p["name"]) or p["discord_handle"]
        head, pick = st.columns([6, 1])
        head.markdown(f"**{html.escape(name)}**")
        has_li = text(p["linkedin_url"]) is not None
        pick.checkbox("Select", value=p["id"] in selected, key=f"sel_{p['id']}", label_visibility="collapsed",
                      on_change=toggle_selected, args=(p["id"],), disabled=not has_li,
                      help="Add to connect queue" if has_li else "No LinkedIn link")

        st.caption(" · ".join(x for x in (text(p["role"]), text(p["company"])) if x) or "Role not shared")
        st.markdown(f":material/location_on: {html.escape(text(p['location']) or 'Location not shared')}  \n"
                    f":material/alternate_email: {html.escape(p['discord_handle'])}")

        chips = [f'<span class="chip">{html.escape(p["experience"])}</span>'] if text(p["experience"]) else []
        chips += [f'<span class="chip gold">{html.escape(o)}</span>' for o in p["open_to"]]
        if chips:
            st.markdown("".join(chips), unsafe_allow_html=True)
        if p["skills"]:
            st.caption(" · ".join(p["skills"]))

        foot = st.columns([1.6, 1, 0.5], vertical_alignment="center")
        foot[0].badge(STATUS_LABELS[p["status"]], color=STATUS_COLORS[p["status"]])
        if p["status"] == "connected":
            foot[1].link_button("Profile", p["linkedin_url"], width="stretch")
        elif has_li:
            if foot[1].button("Connect" if p["status"] == "not_contacted" else "Again",
                              key=f"connect_{p['id']}", type="primary" if p["status"] == "not_contacted" else "secondary",
                              width="stretch"):
                start_queue([p["id"]])
        else:
            foot[1].caption("No LinkedIn")
        with foot[2].popover("", icon=":material/more_vert:", help="Change status"):
            for key, label in STATUS_LABELS.items():
                if key != p["status"]:
                    st.button(f"Mark: {label}", key=f"st_{key}_{p['id']}", on_click=set_status,
                              args=(p["id"], key), width="stretch")

if queue_active():
    connect_dialog()
