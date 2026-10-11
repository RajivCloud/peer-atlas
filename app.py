"""Peer Atlas - entry point.

Run with:  streamlit run app.py

This file only sets up the page and the navigation bar. Each screen lives in views/.
"""
import streamlit as st
from dotenv import load_dotenv

from core import db

load_dotenv()  # ANTHROPIC_API_KEY and CLAUDE_MODEL from .env
from ui.common import apply_style

st.set_page_config(page_title="Peer Atlas", page_icon=":material/public:", layout="wide")
db.init_db()
apply_style()

to_review = sum(1 for p in db.list_peers() if p["needs_review"] and not p["reviewed"])

pages = [
    st.Page("views/dashboard.py", title="Dashboard", icon=":material/public:", default=True),
    st.Page("views/directory.py", title="Directory", icon=":material/group:"),
    st.Page("views/review.py", title=f"Review · {to_review}" if to_review else "Review",
            icon=":material/fact_check:"),
    st.Page("views/import_page.py", title="Import", icon=":material/upload:"),
    st.Page("views/settings.py", title="Settings", icon=":material/tune:"),
]
st.navigation(pages, position="top").run()
