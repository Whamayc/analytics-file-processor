"""Audit log utilities."""

import io
import csv
import datetime
import streamlit as st


def log(action: str, detail: str = "") -> None:
    """Append an entry to st.session_state['audit_log']."""
    st.session_state.setdefault("audit_log", []).append({
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action":    action,
        "detail":    detail,
    })


def render_audit_log() -> None:
    """Render the session audit log expander at the bottom of a page."""
    entries = st.session_state.get("audit_log", [])

    with st.expander(f"Session audit log — {len(entries)} event(s)", expanded=False):
        if not entries:
            st.markdown(
                '<span style="font-size:0.75rem;color:#525252">No events recorded yet.</span>',
                unsafe_allow_html=True,
            )
            return

        # Build HTML table (newest first)
        rows_html = ""
        for e in reversed(entries):
            rows_html += (
                f'<tr>'
                f'<td style="white-space:nowrap;color:#525252">{e["timestamp"]}</td>'
                f'<td style="white-space:nowrap;color:#F59E0B">{e["action"]}</td>'
                f'<td style="color:#A3A3A3">{e["detail"]}</td>'
                f'</tr>'
            )

        st.markdown(
            f'<div style="max-height:260px;overflow-y:auto;'
            f'background:#0A0A0A;border:1px solid #1E1E1E;padding:6px">'
            f'<table style="width:100%;border-collapse:collapse;'
            f'font-family:\'Courier New\',monospace;font-size:0.7rem">'
            f'<thead><tr>'
            f'<th style="text-align:left;color:#333;padding:2px 8px 4px 0;'
            f'white-space:nowrap">TIMESTAMP</th>'
            f'<th style="text-align:left;color:#333;padding:2px 8px 4px 0;'
            f'white-space:nowrap">ACTION</th>'
            f'<th style="text-align:left;color:#333;padding:2px 0 4px 0">DETAIL</th>'
            f'</tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            f'</table></div>',
            unsafe_allow_html=True,
        )

        # Download button
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["timestamp", "action", "detail"])
        for e in entries:
            writer.writerow([e["timestamp"], e["action"], e["detail"]])
        st.download_button(
            "Download log as CSV",
            data=buf.getvalue().encode("utf-8"),
            file_name="audit_log.csv",
            mime="text/csv",
            key="_audit_dl",
        )
