import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import io
import time
import oracledb
import streamlit as st
import pandas as pd
from utils.auth import require_auth
from utils.theme import inject_css, status_bar, sec_label, page_header
from utils.audit import log, render_audit_log
from utils.export import build_excel

st.set_page_config(
    page_title="Oracle Query — Analytics File Processor",
    page_icon="▪",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()
require_auth()

_MODE_QUERY = "Query (SELECT)"
_MODE_DML   = "Execute (DML / PL-SQL)"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _ora_error(exc: Exception) -> str:
    """Return a formatted ORA-XXXXX error string, or str(exc) as fallback."""
    try:
        e = exc.args[0]
        return f"ORA-{e.code}: {e.message}"
    except Exception:
        return str(exc)


def _log_ora_error(exc: Exception) -> None:
    try:
        e = exc.args[0]
        log("Oracle error", f"ORA-{e.code}")
    except Exception:
        log("Oracle error", str(exc)[:80])


def _build_dsn(host: str, port: str, service_name: str) -> str:
    return (
        f"(DESCRIPTION="
        f"(ADDRESS=(PROTOCOL=TCP)(HOST={host})(PORT={port}))"
        f"(CONNECT_DATA=(SERVICE_NAME={service_name}))"
        f")"
    )


def _init_state() -> None:
    defaults = {
        "ora_connection":    None,
        "ora_connected":     False,
        "ora_username":      "",
        "ora_dsn":           "",
        "ora_result_df":     None,
        "ora_last_sql":      "",
        "ora_sql_input":     "",
        "ora_xl_bytes":      None,
        "ora_xl_key":        None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


_init_state()

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    sub_view = st.radio(
        "View",
        ["Connection Settings", "Run Query"],
        label_visibility="collapsed",
    )

    if st.session_state["ora_connected"]:
        user = st.session_state["ora_username"]
        dsn  = st.session_state["ora_dsn"]
        st.markdown(
            f'<div style="font-size:0.72rem;font-family:\'Courier New\',monospace;'
            f'color:#34D399;margin-top:4px">🟢 Connected — {user}@{dsn}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="font-size:0.72rem;font-family:\'Courier New\',monospace;'
            'color:#EF4444;margin-top:4px">🔴 Not connected</div>',
            unsafe_allow_html=True,
        )

# ── Page header ────────────────────────────────────────────────────────────────

page_header("Oracle Query")

status_bar({
    "STATUS": "CONNECTED" if st.session_state["ora_connected"] else "DISCONNECTED",
    "USER":   st.session_state["ora_username"] or "—",
    "DSN":    st.session_state["ora_dsn"] or "—",
})

# ── Sub-view A: Connection Settings ───────────────────────────────────────────

if sub_view == "Connection Settings":
    sec_label("Oracle Connection")

    st.info(
        "Connecting in Thin mode — no Oracle Client installation required.",
        icon="ℹ️",
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        username = st.text_input("Username", key="ora_username_input")
    with c2:
        password = st.text_input("Password", type="password", key="ora_password_input")

    h1, h2, h3 = st.columns([3, 1, 2])
    with h1:
        ora_host = st.text_input("Host", key="ora_host_input", placeholder="myhost.example.com")
    with h2:
        ora_port = st.text_input("Port", key="ora_port_input", value="1521")
    with h3:
        ora_service = st.text_input("Service Name", key="ora_service_input", placeholder="ORCLPDB")

    if ora_host and ora_port and ora_service:
        dsn_input = _build_dsn(ora_host, ora_port, ora_service)
        st.code(dsn_input, language="text")
    else:
        dsn_input = ""

    st.divider()

    btn_c1, btn_c2 = st.columns(2)

    with btn_c1:
        if st.button("Test Connection", use_container_width=True):
            if not username or not password or not ora_host or not ora_port or not ora_service:
                st.error("Username, password, host, port, and service name are all required.", icon="✖️")
            else:
                try:
                    conn = oracledb.connect(user=username, password=password, dsn=dsn_input)
                    conn.close()
                    st.success("Connection successful.")
                except Exception as exc:
                    st.error(_ora_error(exc), icon="✖️")

    with btn_c2:
        if st.button("Connect", use_container_width=True, type="primary"):
            if not username or not password or not ora_host or not ora_port or not ora_service:
                st.error("Username, password, host, port, and service name are all required.", icon="✖️")
            else:
                try:
                    if st.session_state["ora_connected"] and st.session_state["ora_connection"]:
                        try:
                            st.session_state["ora_connection"].close()
                        except Exception:
                            pass
                    conn = oracledb.connect(user=username, password=password, dsn=dsn_input)
                    st.session_state["ora_connection"] = conn
                    st.session_state["ora_connected"]  = True
                    st.session_state["ora_username"]   = username
                    st.session_state["ora_dsn"]        = dsn_input
                    log("Oracle connected", f"{username}@{dsn_input}")
                    st.success(f"Connected as {username}@{dsn_input}.")
                    st.rerun()
                except Exception as exc:
                    st.error(_ora_error(exc), icon="✖️")
                    _log_ora_error(exc)

    if st.session_state["ora_connected"]:
        st.divider()
        if st.button("Disconnect", use_container_width=True):
            try:
                st.session_state["ora_connection"].close()
            except Exception:
                pass
            st.session_state["ora_connection"] = None
            st.session_state["ora_connected"]  = False
            log("Oracle disconnected", "")
            st.info("Disconnected.")
            st.rerun()

# ── Sub-view B: Run Query ──────────────────────────────────────────────────────

else:
    if not st.session_state["ora_connected"]:
        st.warning("No active connection. Go to Connection Settings.", icon="⚠️")
        st.stop()

    conn = st.session_state["ora_connection"]

    sec_label("SQL / PL-SQL Input")

    write_tab, load_tab = st.tabs(["Write SQL", "Load .sql File"])

    with write_tab:
        st.text_area(
            "SQL / PL-SQL",
            key="ora_sql_input",
            height=220,
            placeholder="SELECT * FROM schema.table WHERE ...",
            label_visibility="collapsed",
        )

        snip_c1, snip_c2, snip_c3 = st.columns(3)
        _SNIPPETS = {
            snip_c1: ("SELECT", "SELECT * FROM schema.table_name WHERE ROWNUM <= 100"),
            snip_c2: ("INSERT", "INSERT INTO schema.table_name (col1, col2) VALUES (:1, :2)"),
            snip_c3: ("BEGIN...END", "BEGIN\n  NULL; -- PL/SQL block\nEND;"),
        }
        for col, (label, snippet) in _SNIPPETS.items():
            with col:
                if st.button(label, use_container_width=True):
                    st.session_state["ora_sql_input"] = (
                        (st.session_state["ora_sql_input"] + "\n" + snippet).lstrip()
                    )
                    st.rerun()

    with load_tab:
        uploaded_sql = st.file_uploader(
            "Upload .sql file",
            type=["sql"],
            label_visibility="collapsed",
        )
        if uploaded_sql is not None:
            st.session_state["ora_sql_input"] = uploaded_sql.read().decode("utf-8")
            st.markdown(
                f'<span class="badge b-csv">Loaded: {uploaded_sql.name}</span>',
                unsafe_allow_html=True,
            )

    st.divider()

    sec_label("Execution")

    run_c, limit_c, mode_c = st.columns([2, 1, 1])
    with run_c:
        run_clicked = st.button("Run", type="primary", use_container_width=True)
    with limit_c:
        fetch_limit = st.number_input(
            "Fetch limit", min_value=1, max_value=100000, value=1000, step=100,
        )
    with mode_c:
        exec_mode = st.selectbox("Mode", [_MODE_QUERY, _MODE_DML])

    sql = st.session_state.get("ora_sql_input", "").strip()

    if run_clicked:
        if not sql:
            st.error("No SQL to execute.", icon="✖️")
        elif exec_mode == _MODE_QUERY:
            cursor = None
            try:
                t0 = time.perf_counter()
                cursor = conn.cursor()
                cursor.execute(sql)
                columns   = [col[0] for col in cursor.description]
                rows      = cursor.fetchmany(fetch_limit)
                df        = pd.DataFrame(rows, columns=columns)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                st.session_state["ora_result_df"] = df
                st.session_state["ora_last_sql"]  = sql
                st.session_state["ora_xl_bytes"]  = None  # invalidate cached Excel
                st.session_state["ora_xl_key"]    = None
                st.caption(f"Executed in {elapsed_ms}ms — {len(df):,} rows fetched")
                log("Oracle SELECT", f"{len(df):,} rows fetched — {sql[:80]}")
            except Exception as exc:
                st.error(_ora_error(exc), icon="✖️")
                _log_ora_error(exc)
            finally:
                if cursor is not None:
                    cursor.close()
        else:
            cursor = None
            try:
                t0 = time.perf_counter()
                cursor = conn.cursor()
                cursor.execute(sql)
                conn.commit()
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                affected   = cursor.rowcount
                st.success(
                    f"Executed in {elapsed_ms}ms — {affected:,} rows affected.",
                    icon="✔️",
                )
                st.session_state["ora_result_df"] = None
                log("Oracle DML", f"{affected:,} rows affected — {sql[:80]}")
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                st.error(f"{_ora_error(exc)} — Transaction rolled back.", icon="✖️")
                _log_ora_error(exc)
            finally:
                if cursor is not None:
                    cursor.close()

    df = st.session_state.get("ora_result_df")
    if df is not None:
        st.divider()
        sec_label(f"Results — {len(df):,} rows × {len(df.columns)} columns")

        st.dataframe(df, use_container_width=True, height=400)
        st.caption(f"Showing {len(df):,} rows × {len(df.columns)} columns")

        if len(df) == fetch_limit:
            st.warning(
                "Result capped at fetch limit. Increase limit or narrow query with WHERE clause.",
                icon="⚠️",
            )

        st.divider()
        sec_label("Send to Transform Pipeline")

        if st.button("Send result to Transform →", use_container_width=True):
            fname = "oracle_query_result"
            st.session_state.setdefault("files", {})
            st.session_state["files"][fname] = {
                "original_df": df.copy(),
                "active_df":   df.copy(),
                "pipeline":    [],
                "meta": {
                    "delimiter": None,
                    "encoding":  "utf-8",
                    "rows":      len(df),
                    "cols":      len(df.columns),
                },
            }
            log(
                "Oracle result → Transform pipeline",
                f"{len(df):,} rows × {len(df.columns)} cols",
            )
            st.success(
                "Result loaded into Transform. Switch to the Transform page to continue."
            )

        st.divider()
        sec_label("Export")

        exp_c1, exp_c2 = st.columns(2)
        with exp_c1:
            fname_stem = st.text_input("Filename", value="oracle_result")
        with exp_c2:
            delim_label = st.selectbox(
                "Delimiter (CSV / TXT)", ["Comma", "Semicolon", "Pipe", "Tab"],
            )

        delim_char = {"Comma": ",", "Semicolon": ";", "Pipe": "|", "Tab": "\t"}[delim_label]

        # Compute once — shared by CSV and TXT download buttons
        delim_bytes = df.to_csv(index=False, sep=delim_char).encode("utf-8")

        # Excel: build once per result set, cache in session state
        xl_key = (id(df), len(df), tuple(df.columns))
        if st.session_state["ora_xl_key"] != xl_key:
            try:
                st.session_state["ora_xl_bytes"] = build_excel(df, sheet_name="oracle_result")
                st.session_state["ora_xl_key"]   = xl_key
            except Exception as e:
                st.error(f"Excel build failed: {e}", icon="✖️")

        dl_c1, dl_c2, dl_c3, dl_c4 = st.columns(4)

        with dl_c1:
            if st.download_button(
                "Download CSV",
                data=delim_bytes,
                file_name=f"{fname_stem}.csv",
                mime="text/csv",
                use_container_width=True,
            ):
                log("Oracle export", f"{fname_stem}.csv")

        with dl_c2:
            if st.download_button(
                "Download TXT",
                data=delim_bytes,
                file_name=f"{fname_stem}.txt",
                mime="text/plain",
                use_container_width=True,
            ):
                log("Oracle export", f"{fname_stem}.txt")

        with dl_c3:
            xl_bytes = st.session_state.get("ora_xl_bytes")
            if xl_bytes and st.download_button(
                "Download Excel",
                data=xl_bytes,
                file_name=f"{fname_stem}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            ):
                log("Oracle export", f"{fname_stem}.xlsx")

        with dl_c4:
            if st.button("View SQL", use_container_width=True):
                st.session_state["ora_show_sql"] = not st.session_state.get(
                    "ora_show_sql", False
                )

        last_sql = st.session_state.get("ora_last_sql", "")
        if st.session_state.get("ora_show_sql") and last_sql:
            st.code(last_sql, language="sql")

# ── Audit log ──────────────────────────────────────────────────────────────────

render_audit_log()
