import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import io
import re
import hashlib
import datetime
from pathlib import Path
import streamlit as st
import pandas as pd
from utils.auth import require_auth
from utils.theme import inject_css, status_bar, sec_label, page_header
from utils.dq import render_dq_sidebar
from utils.audit import log, render_audit_log
from utils.export import build_excel, build_oracle_sql, build_pdf, open_outlook_draft

st.set_page_config(
    page_title="Export — Analytics File Processor",
    page_icon="▪",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()
require_auth()
render_dq_sidebar()

# ── Helpers ────────────────────────────────────────────────────────────────────

def _fh(fname: str) -> str:
    return hashlib.md5(fname.encode()).hexdigest()[:8]


def _default_export_dir() -> str:
    return str(Path.home() / "Downloads")


def _save_to_disk(directory: str, filename: str, data: bytes) -> str:
    """Write data to directory/filename. Returns the full path string."""
    dest = Path(directory) / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return str(dest)


TODAY = datetime.date.today().strftime("%Y%m%d")

DELIM_MAP = {
    "Comma  ,":    ",",
    "Pipe   |":    "|",
    "Tab    \\t":  "\t",
    "Semicolon ;": ";",
    "Custom":      None,
}

# ── Power BI column cleaner ────────────────────────────────────────────────────

def clean_col_pbi(col: str) -> str:
    c = col.strip().lower()
    c = re.sub(r"[^\w]", "_", c)
    c = re.sub(r"_+", "_", c)
    c = c.strip("_")
    return c or "col"


# ── Tab renderers ──────────────────────────────────────────────────────────────

def render_csv_tab(df: pd.DataFrame, fname: str) -> None:
    fh = _fh(fname)
    base = os.path.splitext(fname)[0]

    c1, c2, c3 = st.columns(3)
    with c1:
        sec_label("Delimiter")
        delim_keys = list(DELIM_MAP.keys())
        delim_lbl = st.selectbox(
            "d", delim_keys, index=delim_keys.index("Pipe   |"),
            key=f"{fh}_csv_delim", label_visibility="collapsed",
        )
        if delim_lbl == "Custom":
            custom = st.text_input("Custom delimiter", key=f"{fh}_csv_custom",
                                   max_chars=5, placeholder="|")
            delim = custom or ","
        else:
            delim = DELIM_MAP[delim_lbl]

    with c2:
        sec_label("Encoding")
        enc = st.selectbox(
            "e", ["utf-8", "utf-8-sig  (BOM — Excel compatible)", "cp1252"],
            key=f"{fh}_csv_enc", label_visibility="collapsed",
        )
        enc_val = enc.split()[0]  # strip description

    with c3:
        sec_label("Extension")
        ext = st.selectbox("x", [".txt", ".csv"], key=f"{fh}_csv_ext",
                           label_visibility="collapsed")

    inc_header = st.checkbox("Include header row", value=False, key=f"{fh}_csv_hdr")

    fname_out = st.text_input(
        "Output filename (no extension)",
        value=f"{base}_{TODAY}",
        key=f"{fh}_csv_fname",
    )

    try:
        csv_bytes = df.to_csv(index=False, sep=delim, header=inc_header).encode(enc_val)
        if st.download_button(
            f"Download  {fname_out}{ext}",
            data=csv_bytes,
            file_name=f"{fname_out}{ext}",
            mime="text/plain",
            type="primary",
            use_container_width=True,
            key=f"{fh}_dl_csv",
        ):
            log("Exported", f"CSV — {len(df):,} rows → {fname_out}{ext}")
        export_dir = st.session_state.get(f"{fh}_export_dir", _default_export_dir())
        if st.button(f"Save to disk", key=f"{fh}_save_csv", use_container_width=True):
            try:
                full = _save_to_disk(export_dir, f"{fname_out}{ext}", csv_bytes)
                log("Saved to disk", f"CSV — {len(df):,} rows → {full}")
                st.success(f"Saved: {full}", icon="✔️")
            except Exception as se:
                st.error(
                    f"Save failed: {se} — verify the directory path exists and you have write permissions.",
                    icon="✖️",
                )
        st.caption(f"{len(csv_bytes):,} bytes  ·  {len(df):,} rows")
    except Exception as e:
        st.error(
            f"CSV build failed: {e} — check that the chosen delimiter does not appear "
            "in column values, or try a different encoding.",
            icon="✖️",
        )


def render_excel_tab(df: pd.DataFrame, fname: str) -> None:
    fh   = _fh(fname)
    base = os.path.splitext(fname)[0]

    c1, c2 = st.columns(2)
    with c1:
        sheet = st.text_input("Sheet name", value="Sheet1", key=f"{fh}_xl_sheet")
        fname_out = st.text_input(
            "Output filename (no extension)",
            value=f"{base}_{TODAY}",
            key=f"{fh}_xl_fname",
        )
    with c2:
        sec_label("Options")
        inc_hdr = st.checkbox("Include header row", value=True, key=f"{fh}_xl_hdr")
        freeze  = st.checkbox("Freeze header row", value=True, key=f"{fh}_xl_freeze",
                              disabled=not inc_hdr)
        autofit = st.checkbox("Auto-fit column widths", value=True, key=f"{fh}_xl_autofit")
        fmt_hdr = st.checkbox("Apply header formatting", value=True, key=f"{fh}_xl_fmthdr",
                              disabled=not inc_hdr)

    try:
        xl = build_excel(df, sheet_name=sheet, freeze_header=freeze,
                         autofit=autofit, format_header=fmt_hdr,
                         include_header=inc_hdr)
        if st.download_button(
            f"Download  {fname_out}.xlsx",
            data=xl,
            file_name=f"{fname_out}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
            key=f"{fh}_dl_xl",
        ):
            log("Exported", f"Excel — {len(df):,} rows × {len(df.columns)} cols → {fname_out}.xlsx")
        export_dir = st.session_state.get(f"{fh}_export_dir", _default_export_dir())
        if st.button("Save to disk", key=f"{fh}_save_xl", use_container_width=True):
            try:
                full = _save_to_disk(export_dir, f"{fname_out}.xlsx", xl)
                log("Saved to disk", f"Excel — {len(df):,} rows → {full}")
                st.success(f"Saved: {full}", icon="✔️")
            except Exception as se:
                st.error(
                    f"Save failed: {se} — verify the directory path exists and you have write permissions.",
                    icon="✖️",
                )
        st.caption(f"{len(xl):,} bytes  ·  {len(df):,} rows  ·  {len(df.columns)} cols")
    except Exception as e:
        st.error(
            f"Excel build failed: {e} — try disabling 'Auto-fit column widths' "
            "or reducing the number of rows.",
            icon="✖️",
        )


def render_pbi_tab(df: pd.DataFrame, fname: str) -> None:
    fh   = _fh(fname)
    base = os.path.splitext(fname)[0]

    st.markdown(
        '<div style="background:#0F0F0F;border:1px solid #1E3A1E;padding:7px 12px;'
        'font-size:0.72rem;color:#34D399;font-family:monospace;margin-bottom:12px">'
        'This format is optimized for direct import into Power BI Desktop.'
        '</div>',
        unsafe_allow_html=True,
    )

    # Build cleaned name mapping
    mapping = {c: clean_col_pbi(c) for c in df.columns}
    # Deduplicate: if two cols map to same name, append _2, _3 etc.
    seen: dict[str, int] = {}
    deduped: dict[str, str] = {}
    for orig, cleaned in mapping.items():
        if cleaned in seen:
            seen[cleaned] += 1
            deduped[orig] = f"{cleaned}_{seen[cleaned]}"
        else:
            seen[cleaned] = 1
            deduped[orig] = cleaned

    # Show mapping preview
    changed = {k: v for k, v in deduped.items() if k != v}
    if changed:
        sec_label(f"Column name mapping — {len(changed)} column(s) renamed")
        map_df = pd.DataFrame(
            [(k, v) for k, v in deduped.items()],
            columns=["Original", "Power BI name"],
        )
        st.dataframe(
            map_df.style.apply(
                lambda row: [
                    "color:#F59E0B" if row["Original"] != row["Power BI name"] else ""
                ] * 2,
                axis=1,
            ),
            use_container_width=True,
            hide_index=True,
            height=min(200, (len(map_df) + 1) * 35 + 10),
        )
    else:
        st.caption("All column names are already Power BI compatible — no renaming needed.")

    inc_hdr = st.checkbox("Include header row", value=True, key=f"{fh}_pbi_hdr")

    fname_out = st.text_input(
        "Output filename (no extension)",
        value=f"{base}_powerbi_{TODAY}",
        key=f"{fh}_pbi_fname",
    )

    pbi_df = df.rename(columns=deduped)
    try:
        csv_bytes = pbi_df.to_csv(index=False, header=inc_hdr).encode("utf-8")
        if st.download_button(
            f"Download  {fname_out}.csv",
            data=csv_bytes,
            file_name=f"{fname_out}.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True,
            key=f"{fh}_dl_pbi",
        ):
            log("Exported", f"Power BI CSV — {len(pbi_df):,} rows → {fname_out}.csv")
        export_dir = st.session_state.get(f"{fh}_export_dir", _default_export_dir())
        if st.button("Save to disk", key=f"{fh}_save_pbi", use_container_width=True):
            try:
                full = _save_to_disk(export_dir, f"{fname_out}.csv", csv_bytes)
                log("Saved to disk", f"Power BI CSV — {len(pbi_df):,} rows → {full}")
                st.success(f"Saved: {full}", icon="✔️")
            except Exception as se:
                st.error(
                    f"Save failed: {se} — verify the directory path exists and you have write permissions.",
                    icon="✖️",
                )
        st.caption(f"{len(csv_bytes):,} bytes  ·  {len(pbi_df):,} rows  ·  {len(pbi_df.columns)} cols")
    except Exception as e:
        st.error(
            f"Power BI export failed: {e} — check for unsupported data types in the active dataset.",
            icon="✖️",
        )


def render_sql_tab(df: pd.DataFrame, fname: str) -> None:
    fh   = _fh(fname)
    base = os.path.splitext(fname)[0]

    c1, c2, c3 = st.columns(3)
    with c1:
        schema = st.text_input("Schema", value="PERF_ANALYTICS", key=f"{fh}_sql_schema",
                               placeholder="PERF_ANALYTICS")
    with c2:
        tbl = st.text_input(
            "Table name",
            value=re.sub(r"[^\w]", "_", base.upper())[:30],
            key=f"{fh}_sql_tbl",
            placeholder="FUND_RETURNS",
        )
    with c3:
        batch = st.number_input(
            "Batch size (rows per /)",
            min_value=1, max_value=10000, value=500, step=100,
            key=f"{fh}_sql_batch",
        )

    inc_commit = st.checkbox("Include COMMIT;", value=True, key=f"{fh}_sql_commit")
    fname_out  = st.text_input(
        "Output filename (no extension)",
        value=f"{base}_{TODAY}",
        key=f"{fh}_sql_fname",
    )

    # Preview: first 3 INSERT statements
    sec_label("Preview — first 3 rows")
    try:
        preview_sql = build_oracle_sql(
            df.head(3), schema=schema or "SCHEMA",
            table=tbl or "TABLE_NAME",
            batch_size=int(batch), include_commit=False,
        )
        st.code(preview_sql, language="sql")
    except Exception as e:
        st.error(
            f"SQL preview failed: {e} — check that schema and table names contain only letters, digits, and underscores.",
            icon="✖️",
        )

    if st.button("Generate SQL", type="primary", key=f"{fh}_sql_gen",
                 use_container_width=True):
        with st.spinner(f"Generating {len(df):,} INSERT statements…"):
            try:
                sql_content = build_oracle_sql(
                    df,
                    schema=schema or "SCHEMA",
                    table=tbl or "TABLE_NAME",
                    batch_size=int(batch),
                    include_commit=inc_commit,
                )
                st.session_state[f"{fh}_sql_bytes"] = sql_content.encode("utf-8")
                st.session_state[f"{fh}_sql_out"]   = fname_out
            except Exception as e:
                st.error(
                    f"SQL generation failed: {e} — reduce batch size or check for unsupported value types in the data.",
                    icon="✖️",
                )

    if st.session_state.get(f"{fh}_sql_bytes"):
        sql_bytes  = st.session_state[f"{fh}_sql_bytes"]
        out_name   = st.session_state.get(f"{fh}_sql_out", fname_out)
        size_kb    = len(sql_bytes) / 1024
        st.caption(
            f"{len(df):,} rows  ·  {int(batch):,} rows/batch  ·  "
            f"~{size_kb:.1f} KB"
        )
        if st.download_button(
            f"Download  {out_name}.sql",
            data=sql_bytes,
            file_name=f"{out_name}.sql",
            mime="text/plain",
            use_container_width=True,
            key=f"{fh}_dl_sql",
        ):
            log("Exported", f"Oracle SQL — {len(df):,} rows → {out_name}.sql")
        export_dir = st.session_state.get(f"{fh}_export_dir", _default_export_dir())
        if st.button("Save to disk", key=f"{fh}_save_sql", use_container_width=True):
            try:
                full = _save_to_disk(export_dir, f"{out_name}.sql", sql_bytes)
                log("Saved to disk", f"Oracle SQL — {len(df):,} rows → {full}")
                st.success(f"Saved: {full}", icon="✔️")
            except Exception as se:
                st.error(
                    f"Save failed: {se} — verify the directory path exists and you have write permissions.",
                    icon="✖️",
                )


def render_pdf_tab(df: pd.DataFrame, fname: str) -> None:
    fh   = _fh(fname)
    base = os.path.splitext(fname)[0]

    c1, c2 = st.columns(2)
    with c1:
        max_rows = st.number_input(
            "Max rows in table", min_value=10, max_value=10000, value=2000, step=100,
            key=f"{fh}_pdf_maxrows",
        )
    with c2:
        fname_out = st.text_input(
            "Output filename (no extension)",
            value=f"{base}_{TODAY}",
            key=f"{fh}_pdf_fname",
        )

    if len(df) > max_rows:
        st.warning(
            f"Table will be truncated to first {int(max_rows):,} of {len(df):,} rows.",
            icon="⚠️",
        )

    st.markdown(
        '<div style="background:#0F0F0F;border:1px solid #1E1E1E;padding:7px 12px;'
        'font-size:0.72rem;color:#525252;font-family:monospace;margin-bottom:8px">'
        'Report includes: data table · page numbers · source filename.'
        '</div>',
        unsafe_allow_html=True,
    )

    if st.button("Build PDF", type="primary", key=f"{fh}_pdf_build",
                 use_container_width=True):
        with st.spinner("Generating PDF report…"):
            try:
                pdf_bytes = build_pdf(df, source_fname=fname, max_rows=int(max_rows))
                st.session_state[f"{fh}_pdf_bytes"] = pdf_bytes
                st.session_state[f"{fh}_pdf_out"]   = fname_out
            except Exception as e:
                st.error(
                    f"PDF generation failed: {e} — ensure ReportLab is installed "
                    "(`pip install reportlab`) and try reducing 'Max rows in table'.",
                    icon="✖️",
                )

    if st.session_state.get(f"{fh}_pdf_bytes"):
        pdf_bytes  = st.session_state[f"{fh}_pdf_bytes"]
        out_name   = st.session_state.get(f"{fh}_pdf_out", fname_out)
        st.caption(f"~{len(pdf_bytes) / 1024:.1f} KB  ·  {len(df):,} rows")
        if st.download_button(
            f"Download  {out_name}.pdf",
            data=pdf_bytes,
            file_name=f"{out_name}.pdf",
            mime="application/pdf",
            use_container_width=True,
            key=f"{fh}_dl_pdf",
        ):
            log("Exported", f"PDF — {len(df):,} rows → {out_name}.pdf")
        export_dir = st.session_state.get(f"{fh}_export_dir", _default_export_dir())
        if st.button("Save to disk", key=f"{fh}_save_pdf", use_container_width=True):
            try:
                full = _save_to_disk(export_dir, f"{out_name}.pdf", pdf_bytes)
                log("Saved to disk", f"PDF — {len(df):,} rows → {full}")
                st.success(f"Saved: {full}", icon="✔️")
            except Exception as se:
                st.error(
                    f"Save failed: {se} — verify the directory path exists and you have write permissions.",
                    icon="✖️",
                )


def render_email_tab(df: pd.DataFrame, fname: str) -> None:
    fh   = _fh(fname)
    base = os.path.splitext(fname)[0]

    # ── Message ───────────────────────────────────────────────────────────────
    sec_label("Message")
    recipients_raw = st.text_input(
        "To (comma-separated)",
        key=f"{fh}_email_to",
        placeholder="analyst@eaglepace.com, manager@eaglepace.com",
    )
    subject = st.text_input(
        "Subject",
        value=f"Analytics export — {base}",
        key=f"{fh}_email_subject",
    )
    body = st.text_area(
        "Body",
        value="Please find the exported file attached.",
        key=f"{fh}_email_body",
        height=90,
    )

    st.divider()

    # ── Attachment format ─────────────────────────────────────────────────────
    sec_label("Attachment format")
    fmt = st.selectbox(
        "Format", ["CSV", "Excel", "PDF"],
        key=f"{fh}_email_fmt",
        label_visibility="collapsed",
    )

    if fmt == "CSV":
        attachment = df.to_csv(index=False).encode("utf-8")
        attach_name = f"{base}_{TODAY}.csv"
    elif fmt == "Excel":
        attachment = build_excel(df)
        attach_name = f"{base}_{TODAY}.xlsx"
    else:
        attachment = build_pdf(df, source_fname=fname)
        attach_name = f"{base}_{TODAY}.pdf"

    st.caption(f"Attachment: {attach_name}  ·  {len(df):,} rows  ·  {len(attachment):,} bytes")

    # ── Open draft ────────────────────────────────────────────────────────────
    if st.button("Open draft in Outlook", type="primary", key=f"{fh}_email_send",
                 use_container_width=True):
        if not recipients_raw.strip():
            st.error("At least one recipient address is required.", icon="✖️")
        else:
            recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
            try:
                open_outlook_draft(
                    recipients=recipients,
                    subject=subject,
                    body=body,
                    attachment_bytes=attachment,
                    attachment_filename=attach_name,
                )
                log("Email draft opened", f"{fname} — {fmt} → {', '.join(recipients)}")
                st.success(
                    "Draft opened in Outlook — review and click Send when ready.",
                    icon="✔️",
                )
            except Exception as e:
                st.error(
                    f"Could not open Outlook: {e} — ensure Outlook is installed and running.",
                    icon="✖️",
                )


# ── Per-file tab ───────────────────────────────────────────────────────────────

def render_file_tab(fname: str) -> None:
    state     = st.session_state["files"][fname]
    active_df = state["active_df"]
    fh        = _fh(fname)

    # Shape + preview
    sec_label(f"Active data — {len(active_df):,} rows × {len(active_df.columns)} cols")
    st.dataframe(active_df.head(5), use_container_width=True, hide_index=True)

    if len(active_df) == 0:
        st.warning(
            "Active dataset has 0 rows — clear or adjust the row filter on the Transform page before exporting.",
            icon="⚠️",
        )
        return

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Export directory ──────────────────────────────────────────────
    sec_label("Export directory")
    if f"{fh}_export_dir" not in st.session_state:
        st.session_state[f"{fh}_export_dir"] = _default_export_dir()
    st.text_input(
        "Save files to",
        key=f"{fh}_export_dir",
        label_visibility="collapsed",
        placeholder=_default_export_dir(),
    )

    st.markdown("<br>", unsafe_allow_html=True)

    csv_tab, xl_tab, pbi_tab, sql_tab, pdf_tab, email_tab = st.tabs(
        ["CSV / TXT", "Excel", "Power BI", "Oracle SQL", "PDF", "Email"]
    )

    with csv_tab:
        render_csv_tab(active_df, fname)

    with xl_tab:
        render_excel_tab(active_df, fname)

    with pbi_tab:
        render_pbi_tab(active_df, fname)

    with sql_tab:
        render_sql_tab(active_df, fname)

    with pdf_tab:
        render_pdf_tab(active_df, fname)

    with email_tab:
        render_email_tab(active_df, fname)


# ── Page ───────────────────────────────────────────────────────────────────────

page_header("Export")

files: dict = st.session_state.get("files", {})

if not files:
    st.warning("No files loaded.", icon="⚠️")
    st.page_link("pages/1_upload.py", label="Go to Upload", icon="📂")
    st.stop()

total_rows = sum(v["meta"]["rows"] for v in files.values())
status_bar({
    "FILES": str(len(files)),
    "TOTAL ROWS": f"{total_rows:,}",
})

fnames     = list(files.keys())
tab_labels = [fn if len(fn) <= 24 else fn[:22] + "…" for fn in fnames]
file_tabs  = st.tabs(tab_labels)

for idx, fname in enumerate(fnames):
    with file_tabs[idx]:
        render_file_tab(fname)

# ── Audit log ──────────────────────────────────────────────────────────────────
render_audit_log()
