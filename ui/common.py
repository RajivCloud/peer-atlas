"""Shared helpers for every page: styling, data loading, the header.

Pages import from here so the look and the data stay consistent.
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from core import db
from core.extract import display_location
from core.roles import role_family

CSS_PATH = Path(__file__).resolve().parent.parent / "assets" / "style.css"

# Colors used inside charts (Plotly can't read the Streamlit theme by itself).
PALETTE = {
    "light": {"gold": "#8E6A24", "ink": "#17150F", "muted": "#6B6455", "line": "#E2DCCD",
              "land": "#E4DDCC", "border": "#F7F5EF", "surface": "#FFFFFF", "bar": "#B08A35"},
    "dark": {"gold": "#C9A24A", "ink": "#EFE9DB", "muted": "#A1987F", "line": "#2B261D",
             "land": "#231F18", "border": "#0B0A08", "surface": "#17150F", "bar": "#C9A24A"},
}


def theme() -> str:
    """'light' or 'dark' - whichever the viewer picked in ⋮ → Settings (or their system)."""
    return "dark" if (st.context.theme.type or "dark") == "dark" else "light"


def colors() -> dict:
    return PALETTE[theme()]


def apply_style() -> None:
    """Inject our CSS once per page run."""
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=60)
def load_peers() -> pd.DataFrame:
    """All peers as a table, with a few derived columns for the UI. Cached for 60s;
    call refresh() after any change so pages show it immediately."""
    db.init_db()
    peers = db.list_peers()
    df = pd.DataFrame(peers)
    if df.empty:
        return df
    df["location"] = [display_location(p) for p in peers]
    df["place"] = df["city"].fillna(df["region"]).fillna(df["country"])  # map grouping label
    df["role_family"] = df["role"].map(role_family)
    df["first_name"] = df["name"].fillna(df["discord_handle"]).str.split().str[0]
    return df


def refresh() -> None:
    load_peers.clear()


def page_header(eyebrow: str, title: str, caption: str | None = None) -> None:
    st.markdown(f'<p class="eyebrow">{eyebrow}</p>', unsafe_allow_html=True)
    st.title(title, anchor=False)
    if caption:
        st.caption(caption)


def empty_state() -> None:
    st.info("No peers yet. Open **Import** to paste messages from Discord.", icon=":material/upload:")
