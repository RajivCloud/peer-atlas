"""Dashboard: the cohort at a glance - headline numbers, world map, roles, outreach."""
import numpy as np
import plotly.graph_objects as go
import streamlit as st

from core import db
from ui.common import colors, empty_state, load_peers, page_header

page_header("Mastering AI · October cohort · #general", "The cohort at a glance")

df = load_peers()
if df.empty:
    empty_state()
    st.stop()

c = colors()

# ---------------------------------------------------------------- headline numbers
on_map = df[df["lat"].notna()]
cols = st.columns(5)
cols[0].metric("Peers", len(df), border=True)
cols[1].metric("Countries", df["country"].nunique(), border=True)
cols[2].metric("Places", on_map["place"].nunique(), border=True)
cols[3].metric("With LinkedIn", f"{df['linkedin_url'].notna().mean():.0%}", border=True)
cols[4].metric("Open to mentoring", int(df["open_to"].map(lambda xs: "Mentoring" in xs).sum()), border=True)

# ---------------------------------------------------------------- map + top places
places = (
    on_map.groupby("place")
    .agg(peers=("id", "size"), lat=("lat", "mean"), lon=("lon", "mean"), country=("country", "first"))
    .reset_index()
    .sort_values("peers", ascending=False)
)

with st.container(border=True):
    st.subheader("Where peers are based", anchor=False)
    st.caption(f"{len(on_map)} of {len(df)} peers shared a location. "
               "Pick a place on the right to see who's there.")
    map_col, list_col = st.columns([3, 1.1], gap="medium")

    with map_col:
        # No text on the map: peers cluster in a few metros, so labels would pile up.
        # The "Top places" list beside the map names them, and hovering a bubble shows details.
        fig = go.Figure(go.Scattergeo(
            lon=places["lon"], lat=places["lat"],
            customdata=np.stack([places["place"], places["country"].fillna(""), places["peers"]], axis=-1),
            mode="markers",
            marker=dict(
                size=places["peers"],
                sizemode="area",
                sizeref=2.0 * places["peers"].max() / (34 ** 2),  # biggest bubble ~34px across
                sizemin=7,
                color=c["gold"],
                opacity=0.85,
                line=dict(width=2, color=c["border"]),  # surface ring so overlapping bubbles stay distinct
            ),
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>%{customdata[2]} peers<extra></extra>",
        ))
        fig.update_geos(
            projection_type="natural earth",
            showland=True, landcolor=c["land"],
            showcountries=True, countrycolor=c["border"], countrywidth=0.6,
            showcoastlines=False, showframe=False, showocean=False, showlakes=False,
            bgcolor="rgba(0,0,0,0)",
            lataxis_range=[-48, 78],
        )
        fig.update_layout(
            height=430, margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            hoverlabel=dict(bgcolor=c["surface"], bordercolor=c["line"], font=dict(color=c["ink"], family="Manrope")),
            dragmode="pan",
        )
        # No scroll-zoom: the mouse wheel should scroll the page, not shrink the map.
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "scrollZoom": False})

    with list_col:
        board = places.head(10)[["place", "peers"]]
        picked = st.dataframe(
            board,
            hide_index=True,
            width="stretch",
            height=min(38 + 35 * len(board), 430),
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "place": st.column_config.TextColumn("Top places"),
                "peers": st.column_config.NumberColumn("Peers", width="small"),
            },
            key="top_places",
        )
        if picked.selection.rows:
            st.session_state["filter_place"] = board.iloc[picked.selection.rows[0]]["place"]
            st.switch_page("views/directory.py")

# ---------------------------------------------------------------- roles, open to, outreach
left, mid, right = st.columns([1.35, 1, 1], gap="medium")

with left, st.container(border=True):
    st.subheader("Roles", anchor=False)
    fam = df["role_family"].value_counts().sort_values()
    unknown = int(df["role_family"].isna().sum())
    fig = go.Figure(go.Bar(
        x=fam.values, y=fam.index, orientation="h",
        marker=dict(color=c["bar"], cornerradius=4),
        text=fam.values, textposition="outside", textfont=dict(color=c["muted"], family="IBM Plex Mono"),
        hovertemplate="%{y}: %{x} peers<extra></extra>",
        cliponaxis=False,
    ))
    fig.update_layout(
        height=40 + 34 * len(fam), margin=dict(l=150, r=30, t=4, b=0), bargap=0.35,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False),
        yaxis=dict(color=c["ink"], tickfont=dict(family="Manrope", size=12), automargin=False, ticksuffix="  "),
        hoverlabel=dict(bgcolor=c["surface"], bordercolor=c["line"], font=dict(color=c["ink"])),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption(f"{unknown} peers didn't mention a role.")

with mid, st.container(border=True):
    st.subheader("Open to", anchor=False)
    counts = df["open_to"].explode().value_counts()
    if counts.empty:
        st.caption("Nobody asked for mentoring, hiring or collaboration yet.")
    else:
        tiles = st.columns(2)
        for i, (label, n) in enumerate(counts.items()):
            tiles[i % 2].metric(label, int(n), border=True)

with right, st.container(border=True):
    st.subheader("Your outreach", anchor=False)
    status = df["status"].value_counts()
    sent, connected = int(status.get("sent", 0)), int(status.get("connected", 0))
    st.metric("Not contacted", int(status.get("not_contacted", 0)))
    a, b = st.columns(2)
    a.metric("Request sent", sent)
    b.metric("Connected", connected)
    limit = int(db.get_setting("weekly_limit", "100"))
    this_week = db.sent_this_week()
    st.progress(min(this_week / limit, 1.0), text=f"Sent this week: {this_week} / {limit}")
