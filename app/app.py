# python -c "import hashlib; print(hashlib.sha256('yourpassword'.encode()).hexdigest())"
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
from utils.auth import render_login, require_auth
from utils.theme import inject_css, status_bar, page_header

st.set_page_config(
    page_title="Analytics File Processor",
    page_icon="▪",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()

if not st.session_state.get("authenticated", False):
    render_login()
    st.stop()

# ── Home ───────────────────────────────────────────────────────────────────────

page_header("Analytics File Processor")

files: dict = st.session_state.get("files", {})
total_rows  = sum(v["meta"]["rows"]      for v in files.values()) if files else 0
total_steps = sum(len(v["pipeline"])     for v in files.values()) if files else 0

status_bar({
    "FILES":   str(len(files)) if files else "—",
    "ROWS":    f"{total_rows:,}" if files else "—",
    "PIPELINE STEPS": str(total_steps) if files else "—",
})

col1, col2 = st.columns([3, 2])

with col1:
    st.markdown("## Workflow")
    st.markdown(
        """
| Step | Page | Description |
|------|------|-------------|
| 1 | **Upload** | Load `.xlsx`, `.csv`, or `.txt` exports. Each file gets its own tab. |
| 2 | **Transform** | Rename, filter, cast, compute — per file, with a replayable pipeline. |
| 3 | **Export** | Download each file as Excel (formatted), CSV, or PDF. |
| 4 | **Templates** | Save pipelines as named templates and apply them to any loaded file. |
        """,
    )

with col2:
    st.markdown("## Session")
    if files:
        st.metric("Files loaded", len(files))
        st.metric("Total rows", f"{total_rows:,}")
        st.metric("Pipeline steps", total_steps)

        with st.expander("Files"):
            for fname, v in files.items():
                n_steps = len(v["pipeline"])
                st.markdown(
                    f'<div style="font-size:0.78rem;color:#A3A3A3;font-family:monospace;padding:2px 0">'
                    f'<b style="color:#E5E5E5">{fname}</b>'
                    f'&nbsp;&nbsp;{v["meta"]["rows"]:,} rows'
                    f'{"&nbsp;&nbsp;<span style=\'color:#F59E0B\'>" + str(n_steps) + " step(s)</span>" if n_steps else ""}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        if st.button("Clear all files", type="secondary", use_container_width=True):
            st.session_state.pop("files", None)
            st.rerun()
    else:
        st.info("No files loaded. Go to **Upload** to get started.", icon="ℹ️")

st.divider()
st.markdown(
    '<span style="font-size:0.7rem;color:#333;font-family:monospace">'
    "EAGLE PACE · ANALYTICS FILE PROCESSOR · INTERNAL USE ONLY"
    "</span>",
    unsafe_allow_html=True,
)
