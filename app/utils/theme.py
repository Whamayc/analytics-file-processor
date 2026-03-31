import streamlit as st

_CSS = """
<style>
/* ── Global ─────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Courier New', Courier, monospace !important;
}
.stApp { background-color: #0F1117; }

/* ── Sidebar ─────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #1A1D27;
    border-right: 1px solid #222;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    font-size: 0.78rem;
    color: #525252;
    letter-spacing: 0.06em;
}

/* ── Typography ──────────────────────────────────────────────── */
h1, h2, h3, h4 {
    font-family: 'Courier New', monospace !important;
    letter-spacing: 0.06em;
}
h1 { color: #F59E0B !important; font-size: 1.25rem !important; }
h2 { color: #D4D4D4 !important; font-size: 1rem !important; border-bottom: 1px solid #222; padding-bottom: 4px; }
h3 { color: #A3A3A3 !important; font-size: 0.88rem !important; text-transform: uppercase; letter-spacing: 0.1em; }

/* ── Buttons ─────────────────────────────────────────────────── */
.stButton > button {
    background: #1A1D27 !important;
    color: #F59E0B !important;
    border: 1px solid #F59E0B !important;
    border-radius: 2px !important;
    font-family: 'Courier New', monospace !important;
    font-size: 0.8rem !important;
    letter-spacing: 0.06em !important;
    padding: 4px 16px !important;
    transition: background 0.1s, color 0.1s !important;
}
.stButton > button:hover {
    background: #F59E0B !important;
    color: #0F1117 !important;
}
.stButton > button[kind="primary"] {
    background: #F59E0B !important;
    color: #0F1117 !important;
}
.stButton > button[kind="primary"]:hover {
    background: #D97706 !important;
}

/* ── Download buttons ────────────────────────────────────────── */
.stDownloadButton > button {
    background: #1A1D27 !important;
    color: #F59E0B !important;
    border: 1px solid #F59E0B !important;
    border-radius: 2px !important;
    font-family: 'Courier New', monospace !important;
    font-size: 0.8rem !important;
    letter-spacing: 0.06em !important;
    padding: 4px 16px !important;
    transition: background 0.1s, color 0.1s !important;
}
.stDownloadButton > button:hover {
    background: #F59E0B !important;
    color: #0F1117 !important;
}

/* ── Inputs / Selects ────────────────────────────────────────── */
input, textarea, [data-baseweb="select"] {
    background-color: #1A1D27 !important;
    border-color: #2A2A2A !important;
    color: #E5E5E5 !important;
    font-family: 'Courier New', monospace !important;
    border-radius: 2px !important;
}
[data-baseweb="select"] * { font-family: 'Courier New', monospace !important; }

/* ── DataFrames ──────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid #222 !important;
}
[data-testid="stDataFrame"] table {
    font-family: 'Courier New', monospace !important;
    font-size: 0.78rem !important;
}

/* ── Expanders ───────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid #222 !important;
    border-radius: 2px !important;
    background: #1A1D27 !important;
}
[data-testid="stExpander"] summary {
    font-size: 0.82rem !important;
    letter-spacing: 0.06em !important;
    color: #A3A3A3 !important;
}

/* ── Metrics ─────────────────────────────────────────────────── */
[data-testid="metric-container"] {
    background: #1A1D27 !important;
    border: 1px solid #222 !important;
    border-radius: 2px !important;
    padding: 10px 14px !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.68rem !important;
    letter-spacing: 0.1em !important;
    color: #525252 !important;
    text-transform: uppercase !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.3rem !important;
    color: #F59E0B !important;
}

/* ── Alerts / Info ───────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 2px !important;
    font-size: 0.8rem !important;
}

/* ── Dividers ────────────────────────────────────────────────── */
hr { border-color: #222 !important; margin: 0.75rem 0 !important; }

/* ── Responsive columns ──────────────────────────────────────── */
@media screen and (max-width: 900px) {
    [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        flex: 1 1 100% !important;
        min-width: 100% !important;
    }
}

/* ── Badges ──────────────────────────────────────────────────── */
.badge {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 2px;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    vertical-align: middle;
    line-height: 1.6;
}
.b-str  { background:#0C1929; color:#7DD3FC; border:1px solid #0369A1; }
.b-int  { background:#130F23; color:#C4B5FD; border:1px solid #6D28D9; }
.b-flt  { background:#0A1F14; color:#6EE7B7; border:1px solid #059669; }
.b-dt   { background:#1F0F0F; color:#FCA5A5; border:1px solid #B91C1C; }
.b-bool { background:#1F1800; color:#FDE68A; border:1px solid #B45309; }
.b-unk  { background:#141414; color:#525252; border:1px solid #333; }
.b-delim{ background:#1A1100; color:#F59E0B; border:1px solid #92400E; }
.b-enc  { background:#0A1F14; color:#34D399; border:1px solid #065F46; }
.b-xl   { background:#0A1F14; color:#34D399; border:1px solid #065F46; }
.b-csv  { background:#0C1929; color:#7DD3FC; border:1px solid #0369A1; }
.b-pdf  { background:#1F0F0F; color:#FCA5A5; border:1px solid #B91C1C; }

/* ── Pipeline steps ──────────────────────────────────────────── */
.pipe-step {
    background: #111;
    border-left: 3px solid #F59E0B;
    padding: 5px 10px;
    margin: 3px 0;
    font-size: 0.78rem;
    color: #D4D4D4;
    font-family: 'Courier New', monospace;
}
.pipe-step span { color: #F59E0B; }

/* ── Status bar ──────────────────────────────────────────────── */
.status-row {
    background: #1A1D27;
    border: 1px solid #1E1E1E;
    padding: 6px 12px;
    font-size: 0.72rem;
    color: #525252;
    letter-spacing: 0.05em;
    margin-bottom: 1rem;
    font-family: 'Courier New', monospace;
}
.status-row b { color: #A3A3A3; }

/* ── Section labels ──────────────────────────────────────────── */
.sec-label {
    font-size: 0.68rem;
    color: #525252;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    border-bottom: 1px solid #1E1E1E;
    padding-bottom: 3px;
    margin-bottom: 10px;
    font-family: 'Courier New', monospace;
}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


# ── Badge helpers ──────────────────────────────────────────────────────────────

def _badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{text}</span>'


_TYPE_MAP = {
    "string":  ("STR",   "b-str"),
    "integer": ("INT",   "b-int"),
    "float":   ("FLOAT", "b-flt"),
    "date":    ("DATE",  "b-dt"),
    "boolean": ("BOOL",  "b-bool"),
}

_DELIM_NAMES = {",": "CSV", "|": "PIPE", "\t": "TAB", ";": "SEMI"}


def type_badge(dtype: str) -> str:
    label, cls = _TYPE_MAP.get(dtype, ("?", "b-unk"))
    return _badge(label, cls)


def delim_badge(delim: str) -> str:
    return _badge(_DELIM_NAMES.get(delim, repr(delim)), "b-delim")


def enc_badge(enc: str) -> str:
    return _badge(enc.upper(), "b-enc")


def fmt_badge(fmt: str) -> str:
    cls = {"Excel": "b-xl", "CSV": "b-csv", "PDF": "b-pdf"}.get(fmt, "b-unk")
    return _badge(fmt.upper(), cls)


def status_bar(parts: dict) -> None:
    """Render a one-line status bar. parts = {label: value}."""
    html = '<div class="status-row">'
    html += "  ·  ".join(f"<b>{k}</b>&nbsp;{v}" for k, v in parts.items())
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def sec_label(text: str) -> None:
    st.markdown(f'<div class="sec-label">{text}</div>', unsafe_allow_html=True)


def page_header(title: str) -> None:
    """Render the AFP v1.0 version chip then the page h1."""
    st.markdown(
        '<span style="font-size:0.65rem;color:#525252;font-family:\'Courier New\',monospace;'
        'letter-spacing:0.1em;text-transform:uppercase">AFP v1.0</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f"# {title}")
