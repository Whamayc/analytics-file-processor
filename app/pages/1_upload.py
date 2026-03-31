import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import io
import csv
import streamlit as st
import pandas as pd
from utils.auth import require_auth
from utils.theme import inject_css, status_bar, sec_label, type_badge, delim_badge, enc_badge, page_header
from utils.audit import log, render_audit_log

st.set_page_config(
    page_title="Upload — Analytics File Processor",
    page_icon="▪",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()
require_auth()

# ── Helpers ────────────────────────────────────────────────────────────────────

_ENC_CANDIDATES = [
    "utf-8", "cp1252", "latin-1", "iso-8859-2", "utf-16",
    "shift_jis", "gb2312", "big5", "windows-1250", "windows-1251",
]


def detect_encoding(raw: bytes) -> tuple[str, float]:
    """Detect encoding via chardet. Returns (encoding, confidence).
    confidence is 1.0 for UTF-8/ASCII. Values below 0.7 are unreliable.
    """
    import chardet
    result     = chardet.detect(raw)
    enc        = (result.get("encoding") or "utf-8").strip()
    confidence = float(result.get("confidence") or 0.0)
    if enc.lower().replace("-", "") in ("utf8", "ascii"):
        return "utf-8", 1.0
    return enc, confidence


def detect_delimiter(text: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",|\t;")
        return dialect.delimiter
    except Exception:
        counts = {",": text.count(","), "|": text.count("|"),
                  "\t": text.count("\t"), ";": text.count(";")}
        return max(counts, key=counts.get)


def infer_col_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):      return "boolean"
    if pd.api.types.is_integer_dtype(series):   return "integer"
    if pd.api.types.is_float_dtype(series):     return "float"
    if pd.api.types.is_datetime64_any_dtype(series): return "date"
    if series.dtype == object:
        sample = series.dropna().head(20).astype(str)
        if sample.str.lower().isin({"true","false","yes","no","1","0"}).all():
            return "boolean"
        try:
            pd.to_datetime(sample, infer_datetime_format=True)
            return "date"
        except Exception:
            pass
    return "string"


def get_excel_sheets(raw: bytes) -> list[str]:
    xf = pd.ExcelFile(io.BytesIO(raw), engine="openpyxl")
    return xf.sheet_names


def load_excel_sheet(raw: bytes, sheet_name) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(raw), dtype=str, engine="openpyxl",
                       sheet_name=sheet_name)
    df.columns = [str(c) for c in df.columns]
    return df


def load_file(uploaded_file, delimiter_override=None, encoding_override=None):
    """Returns (df, delim, enc, enc_confidence, raw_bytes, warnings).
    raw_bytes is non-None only when enc_confidence < 0.7 and no override was given,
    so the UI can offer re-encoding without requiring a re-upload.
    """
    load_warnings: list[str] = []
    raw  = uploaded_file.read()
    uploaded_file.seek(0)
    name = uploaded_file.name.lower()
    if name.endswith(".xlsx"):
        df = load_excel_sheet(raw, 0)
        return df, "n/a", "utf-8", 1.0, None, load_warnings

    enc, confidence = detect_encoding(raw)

    if encoding_override:
        enc        = encoding_override
        confidence = 1.0  # explicit user choice — treat as authoritative
    elif confidence < 0.7:
        load_warnings.append(
            f"**{uploaded_file.name}**: encoding detected as **{enc.upper()}** "
            f"with low confidence ({confidence:.0%}). "
            "Select an encoding below if characters appear garbled."
        )
    elif enc != "utf-8":
        load_warnings.append(
            f"**{uploaded_file.name}**: loaded as {enc.upper()} — "
            "check accented characters for display errors."
        )

    text  = raw.decode(enc, errors="replace")
    delim = delimiter_override if delimiter_override else detect_delimiter(text)
    df    = pd.read_csv(io.StringIO(text), sep=delim, engine="python", dtype=str)

    # Keep raw bytes only for low-confidence files so the user can re-encode without re-upload
    raw_bytes = raw if (confidence < 0.7 and not encoding_override) else None
    return df, delim, enc, confidence, raw_bytes, load_warnings


def _excel_file_key(workbook_name: str, sheet_name: str, total_sheets: int) -> str:
    if total_sheets == 1:
        return workbook_name
    return f"{os.path.splitext(workbook_name)[0]} [{sheet_name}]"


def _register_file(
    key: str,
    df: pd.DataFrame,
    delim: str,
    enc: str,
    enc_confidence: float = 1.0,
    raw_bytes: bytes | None = None,
) -> None:
    entry: dict = {
        "original_df": df,
        "active_df":   df.copy(),
        "pipeline":    [],
        "meta": {
            "delimiter":      delim,
            "encoding":       enc,
            "enc_confidence": enc_confidence,
            "rows":           len(df),
            "cols":           len(df.columns),
            "col_types":      {col: infer_col_type(df[col]) for col in df.columns},
        },
    }
    if raw_bytes is not None:
        entry["_raw_bytes"] = raw_bytes
    st.session_state["files"][key] = entry
    log("Uploaded file", f"{key} ({len(df):,} rows × {len(df.columns)} cols)")


def tab_label(fname: str) -> str:
    return fname if len(fname) <= 22 else fname[:20] + "…"


DELIM_OPTIONS  = [("Auto", None), ("Comma ,", ","), ("Pipe |", "|"), ("Tab \\t", "\t"), ("Semicolon ;", ";")]
DELIM_LABELS   = [d[0] for d in DELIM_OPTIONS]
DELIM_VALUES   = [d[1] for d in DELIM_OPTIONS]

_SIZE_WARN_MB  = 50
_SIZE_HARD_MB  = 200

# ── Session state init ─────────────────────────────────────────────────────────
# st.session_state["files"] = {
#   filename: {
#     "original_df": df,
#     "active_df":   df (transformed),
#     "pipeline":    [],
#     "meta": { delimiter, encoding, rows, cols }
#   }
# }

files: dict = st.session_state.setdefault("files", {})

# ── Page ───────────────────────────────────────────────────────────────────────

page_header("Upload & Preview")

uploaded = st.file_uploader(
    "Drop files here",
    type=["xlsx", "csv", "txt"],
    accept_multiple_files=True,
    help="Accepts Eagle PACE exports: .xlsx, .csv, .txt",
)

# ── Process new uploads ────────────────────────────────────────────────────────
_xlsx_pending: dict = st.session_state.setdefault("_xlsx_pending", {})  # fname -> {raw, sheets}

if uploaded:
    for uf in uploaded:
        size_mb = uf.size / (1024 * 1024)
        if size_mb > _SIZE_HARD_MB:
            st.error(
                f"**{uf.name}** ({size_mb:.0f} MB) exceeds the {_SIZE_HARD_MB} MB limit and was skipped.",
                icon="✖️",
            )
            continue
        if size_mb > _SIZE_WARN_MB:
            st.warning(
                f"**{uf.name}** is {size_mb:.0f} MB — large files may be slow to process.",
                icon="⚠️",
            )

        is_xlsx = uf.name.lower().endswith(".xlsx")

        if is_xlsx:
            if uf.name not in _xlsx_pending or st.session_state.get(f"_xlsx_reread_{uf.name}"):
                raw = uf.read(); uf.seek(0)
                try:
                    sheets = get_excel_sheets(raw)
                    if len(sheets) == 1:
                        # Single sheet — import directly, no picker needed
                        if uf.name not in files or st.session_state.get(f"_xlsx_reread_{uf.name}"):
                            df = load_excel_sheet(raw, sheets[0])
                            _register_file(uf.name, df, "n/a", "utf-8")
                            st.session_state[f"_xlsx_reread_{uf.name}"] = False
                    else:
                        # Multiple sheets — queue for picker
                        _xlsx_pending[uf.name] = {
                            "raw": raw,
                            "sheets": sheets,
                            "total_sheets": len(sheets),
                        }
                        st.session_state.setdefault(f"_xlsx_sel_{uf.name}", sheets)
                        st.session_state[f"_xlsx_reread_{uf.name}"] = False
                except Exception as e:
                    st.error(f"Failed to read **{uf.name}**: {e}", icon="✖️")
        else:
            override_key   = f"delim_override_{uf.name}"
            override_idx   = st.session_state.get(override_key, 0)
            delim_override = DELIM_VALUES[override_idx]
            enc_override   = st.session_state.get(f"_enc_override_{uf.name}")
            try:
                df, detected_delim, enc, enc_conf, raw_bytes, file_warnings = load_file(
                    uf, delim_override, enc_override
                )
                if uf.name not in files or st.session_state.get(f"_reimport_{uf.name}"):
                    _register_file(uf.name, df, detected_delim, enc, enc_conf, raw_bytes)
                    for w in file_warnings:
                        st.warning(w, icon="⚠️")
                    st.session_state[f"_reimport_{uf.name}"] = False
            except Exception as e:
                st.error(f"Failed to load **{uf.name}**: {e}", icon="✖️")

    st.session_state["files"] = files

# ── Excel sheet picker ─────────────────────────────────────────────────────────
for xfname, xdata in list(_xlsx_pending.items()):
    sheets  = xdata["sheets"]
    total_sheets = xdata.get("total_sheets", len(sheets))
    sel_key = f"_xlsx_sel_{xfname}"
    available_sheets = [
        sheet for sheet in sheets
        if _excel_file_key(xfname, sheet, total_sheets) not in files
    ]
    if sel_key not in st.session_state:
        st.session_state[sel_key] = available_sheets
    else:
        st.session_state[sel_key] = [
            sheet for sheet in st.session_state[sel_key]
            if sheet in available_sheets
        ]

    if not available_sheets:
        del _xlsx_pending[xfname]
        st.session_state.pop(sel_key, None)
        continue

    with st.expander(f"**{xfname}** — {len(available_sheets)} sheet(s) remaining", expanded=True):
        selected = st.multiselect(
            "Select sheets to import",
            options=available_sheets,
            default=st.session_state[sel_key],
            key=sel_key,
        )

        action_col1, action_col2 = st.columns(2)

        if action_col1.button(
            f"Import {'sheet' if len(selected) == 1 else f'{len(selected)} sheets'}",
            type="primary",
            key=f"_xlsx_import_{xfname}",
            disabled=not selected,
            use_container_width=True,
        ):
            try:
                for sheet in selected:
                    df  = load_excel_sheet(xdata["raw"], sheet)
                    key = _excel_file_key(xfname, sheet, total_sheets)
                    _register_file(key, df, "n/a", "utf-8")
                remaining_sheets = [sheet for sheet in available_sheets if sheet not in selected]
                if remaining_sheets:
                    _xlsx_pending[xfname]["sheets"] = remaining_sheets
                else:
                    del _xlsx_pending[xfname]
                st.session_state.pop(sel_key, None)
                log("Imported Excel sheets",
                    f"{xfname}: {', '.join(selected)}")
                st.success(
                    f"Imported {len(selected)} sheet(s) from **{xfname}**.", icon="✔️"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}", icon="✖️")

        if action_col2.button(
            "Remove remaining",
            key=f"_xlsx_remove_remaining_{xfname}",
            use_container_width=True,
        ):
            del _xlsx_pending[xfname]
            st.session_state.pop(sel_key, None)
            log("Dismissed remaining Excel sheets", xfname)
            st.rerun()

# ── Nothing loaded ─────────────────────────────────────────────────────────────
if not files:
    st.markdown(
        '<div style="color:#525252;font-size:0.8rem;font-family:monospace;padding:20px 0">'
        "No files uploaded yet.</div>",
        unsafe_allow_html=True,
    )
    st.stop()

# ── Status bar ─────────────────────────────────────────────────────────────────
total_rows = sum(v["meta"]["rows"] for v in files.values())
status_bar({
    "FILES": str(len(files)),
    "TOTAL ROWS": f"{total_rows:,}",
})

# ── Tabs — one per file + optional Merge tab ───────────────────────────────────
file_names = list(files.keys())
tab_labels = [tab_label(fn) for fn in file_names]
if len(files) >= 2:
    tab_labels.append("⊕  Merge")

tabs = st.tabs(tab_labels)

# ── Per-file tabs ──────────────────────────────────────────────────────────────
for idx, fname in enumerate(file_names):
    with tabs[idx]:
        state = files[fname]
        df    = state["active_df"]
        meta  = state["meta"]
        override_key = f"delim_override_{fname}"

        # Header row
        col_a, col_b, col_c, col_d = st.columns([2, 1, 1, 2])
        with col_a:
            badges = ""
            if meta["delimiter"] != "n/a":
                badges += delim_badge(meta["delimiter"]) + "&nbsp;"
            badges += enc_badge(meta["encoding"])
            st.markdown(badges, unsafe_allow_html=True)
        with col_b:
            st.markdown(
                f'<span style="font-size:0.78rem;color:#A3A3A3"><b>{meta["rows"]:,}</b> rows</span>',
                unsafe_allow_html=True,
            )
        with col_c:
            st.markdown(
                f'<span style="font-size:0.78rem;color:#A3A3A3"><b>{meta["cols"]}</b> cols</span>',
                unsafe_allow_html=True,
            )
        with col_d:
            if meta["delimiter"] != "n/a":
                new_idx = st.selectbox(
                    "Delimiter override",
                    options=range(len(DELIM_LABELS)),
                    format_func=lambda i: DELIM_LABELS[i],
                    index=st.session_state.get(override_key, 0),
                    key=f"sel_delim_{idx}",
                    label_visibility="collapsed",
                )
                if new_idx != st.session_state.get(override_key, 0):
                    st.session_state[override_key] = new_idx
                    st.session_state[f"_reimport_{fname}"] = True
                    st.rerun()

        # Encoding warning + re-encode selector (shown only for low-confidence files)
        if state.get("_raw_bytes") is not None:
            enc_conf = meta.get("enc_confidence", 0.0)
            current_enc = meta["encoding"]
            st.warning(
                f"Encoding detected as **{current_enc.upper()}** "
                f"({enc_conf:.0%} confidence) — select below if characters appear garbled.",
                icon="⚠️",
            )
            enc_sel_key = f"_enc_sel_{fname}"
            candidates  = sorted(set([current_enc] + _ENC_CANDIDATES))
            new_enc = st.selectbox(
                "Re-encode as",
                candidates,
                index=candidates.index(current_enc) if current_enc in candidates else 0,
                key=enc_sel_key,
            )
            if st.button("Apply encoding", key=f"_enc_apply_{fname}", use_container_width=True):
                if new_enc != current_enc:
                    try:
                        raw   = state["_raw_bytes"]
                        text  = raw.decode(new_enc, errors="replace")
                        delim = meta["delimiter"] if meta["delimiter"] != "n/a" \
                                else detect_delimiter(text)
                        df_re = pd.read_csv(
                            io.StringIO(text), sep=delim, engine="python", dtype=str
                        )
                        _register_file(fname, df_re, delim, new_enc, 1.0, None)
                        log("Re-encoded file", f"{fname} → {new_enc}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Re-encoding failed: {e}", icon="✖️")

        # Column type badges (cached per file; computed once at registration)
        sec_label("Column types")
        col_types = meta.get("col_types", {})
        type_html = ""
        for col in df.columns:
            ctype = col_types.get(col) or infer_col_type(df[col])
            type_html += (
                f'<span style="font-size:0.72rem;color:#737373;margin-right:4px">{col}</span>'
                f'{type_badge(ctype)}&nbsp;&nbsp;'
            )
        st.markdown(type_html, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        # Pipeline badge
        n_steps = len(state["pipeline"])
        if n_steps:
            st.markdown(
                f'<span style="font-size:0.72rem;color:#F59E0B">▸ {n_steps} transform step(s) applied</span>',
                unsafe_allow_html=True,
            )

        # Preview
        sec_label("Preview — first 20 rows")
        st.dataframe(df.head(20), use_container_width=True, hide_index=True)

        # Remove file button
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Remove file", key=f"remove_{idx}", use_container_width=True):
            log("Removed file", fname)
            del st.session_state["files"][fname]
            st.rerun()

# ── Merge tab ──────────────────────────────────────────────────────────────────
if len(files) >= 2:
    with tabs[-1]:
        st.markdown("### Merge files")
        merge_type = st.radio(
            "Strategy",
            ["Stack rows (union)", "Join on key"],
            horizontal=True,
            key="merge_strategy",
        )

        dfs = {fn: files[fn]["active_df"] for fn in file_names}

        if merge_type == "Stack rows (union)":
            all_cols   = [set(df.columns) for df in dfs.values()]
            col_union  = set().union(*all_cols)
            col_inter  = col_union.intersection(*all_cols)
            if col_union != col_inter:
                st.warning(
                    f"Column mismatch — {len(col_union - col_inter)} column(s) not in all files: "
                    + ", ".join(sorted(col_union - col_inter)),
                    icon="⚠️",
                )
            merge_name = st.text_input("Output file name", value="merged", key="merge_name_union")
            if st.button("Stack rows", type="primary", key="do_stack"):
                merged = pd.concat(list(dfs.values()), ignore_index=True)
                out_name = (merge_name.strip() or "merged") + ".csv"
                st.session_state["files"][out_name] = {
                    "original_df": merged,
                    "active_df":   merged.copy(),
                    "pipeline":    [],
                    "meta": {
                        "delimiter": "n/a",
                        "encoding":  "utf-8",
                        "rows":      len(merged),
                        "cols":      len(merged.columns),
                    },
                }
                log("Merged files (stack)",
                    f"{len(dfs)} files → {out_name} ({len(merged):,} rows)")
                st.success(f"Created '{out_name}' — {len(merged):,} rows", icon="✔️")
                st.rerun()

        else:
            all_common = sorted(
                set(list(dfs.values())[0].columns).intersection(
                    *[set(df.columns) for df in list(dfs.values())[1:]]
                )
            )
            if not all_common:
                st.error("No common columns across files.", icon="✖️")
            else:
                c1, c2, c3 = st.columns(3)
                with c1:
                    join_key = st.selectbox("Join key", all_common, key="join_key")
                with c2:
                    join_how = st.selectbox("Join type", ["inner", "left", "outer"], key="join_how")
                with c3:
                    merge_name = st.text_input("Output file name", value="merged", key="merge_name_join")

                if st.button("Join files", type="primary", key="do_join"):
                    try:
                        df_list = list(dfs.values())
                        merged = df_list[0]
                        for other in df_list[1:]:
                            merged = merged.merge(other, on=join_key, how=join_how, suffixes=("", "_dup"))
                        dup_cols = [c for c in merged.columns if c.endswith("_dup")]
                        merged = merged.drop(columns=dup_cols)
                        out_name = (merge_name.strip() or "merged") + ".csv"
                        st.session_state["files"][out_name] = {
                            "original_df": merged,
                            "active_df":   merged.copy(),
                            "pipeline":    [],
                            "meta": {
                                "delimiter": "n/a",
                                "encoding":  "utf-8",
                                "rows":      len(merged),
                                "cols":      len(merged.columns),
                            },
                        }
                        log("Merged files (join)",
                            f"{len(dfs)} files on '{join_key}' ({join_how}) → {out_name} "
                            f"({len(merged):,} rows × {len(merged.columns)} cols)")
                        st.success(f"Created '{out_name}' — {len(merged):,} rows × {len(merged.columns)} cols", icon="✔️")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Join failed: {e}", icon="✖️")

# ── Audit log ──────────────────────────────────────────────────────────────────
render_audit_log()
