"""Data-quality sidebar panel — shown on pages 2, 3, and 4."""

import streamlit as st
import pandas as pd


def render_dq_sidebar() -> None:
    files: dict = st.session_state.get("files", {})
    if not files:
        return

    with st.sidebar:
        st.markdown(
            '<div style="font-size:0.68rem;color:#525252;text-transform:uppercase;'
            'letter-spacing:.12em;border-bottom:1px solid #1E1E1E;padding-bottom:3px;'
            'margin-bottom:10px;font-family:\'Courier New\',monospace">Data Quality</div>',
            unsafe_allow_html=True,
        )

        fname = st.selectbox(
            "dq_file",
            list(files.keys()),
            key="_dq_file_sel",
            label_visibility="collapsed",
        )

        df: pd.DataFrame = files[fname]["active_df"]
        n = max(len(df), 1)

        # ── 1. Null summary ───────────────────────────────────────────────────
        with st.expander("Nulls", expanded=True):
            null_counts = df.isnull().sum()
            any_nulls   = null_counts[null_counts > 0]

            if any_nulls.empty:
                st.markdown(
                    '<span style="font-size:0.72rem;color:#525252">No nulls found.</span>',
                    unsafe_allow_html=True,
                )
            else:
                rows_html = ""
                for col, cnt in any_nulls.items():
                    pct   = cnt / n * 100
                    color = "#F59E0B" if pct > 10 else "#A3A3A3"
                    rows_html += (
                        f'<div style="display:flex;justify-content:space-between;'
                        f'margin-bottom:2px">'
                        f'<span style="font-size:0.7rem;color:#737373;font-family:'
                        f'\'Courier New\',monospace;overflow:hidden;text-overflow:ellipsis;'
                        f'white-space:nowrap;max-width:60%">{col}</span>'
                        f'<span style="font-size:0.7rem;color:{color};font-family:'
                        f'\'Courier New\',monospace;white-space:nowrap">'
                        f'{cnt:,} &nbsp;({pct:.1f}%)</span>'
                        f'</div>'
                    )
                st.markdown(rows_html, unsafe_allow_html=True)
                if any((null_counts / n * 100) > 10):
                    st.markdown(
                        '<span style="font-size:0.65rem;color:#F59E0B">▲ amber = >10% null</span>',
                        unsafe_allow_html=True,
                    )

        # ── 2. Duplicate rows ─────────────────────────────────────────────────
        with st.expander("Duplicates"):
            dup_count = int(df.duplicated().sum())
            color     = "#F59E0B" if dup_count > 0 else "#525252"
            st.markdown(
                f'<span style="font-size:0.78rem;color:{color};font-family:'
                f'\'Courier New\',monospace"><b>{dup_count:,}</b> duplicate row(s)</span>',
                unsafe_allow_html=True,
            )
            if dup_count > 0:
                if st.button(
                    "Drop duplicates",
                    key="_dq_drop_dup",
                    use_container_width=True,
                ):
                    deduped = df.drop_duplicates().reset_index(drop=True)
                    st.session_state["files"][fname]["active_df"] = deduped
                    st.rerun()

        # ── 3. Numeric outliers ───────────────────────────────────────────────
        with st.expander("Outliers"):
            num_cols = df.select_dtypes(include="number").columns.tolist()

            # Also attempt to coerce object cols that look numeric
            if not num_cols:
                coerced = {}
                for col in df.columns:
                    s = pd.to_numeric(df[col], errors="coerce")
                    if s.notna().sum() > 0:
                        coerced[col] = s
                num_series = coerced
            else:
                num_series = {col: df[col] for col in num_cols}

            if not num_series:
                st.markdown(
                    '<span style="font-size:0.72rem;color:#525252">No numeric columns.</span>',
                    unsafe_allow_html=True,
                )
            else:
                for col, series in num_series.items():
                    s       = series.dropna()
                    if len(s) < 2:
                        continue
                    mean    = s.mean()
                    std     = s.std()
                    lo, hi  = mean - 3 * std, mean + 3 * std
                    out_ct  = int(((s < lo) | (s > hi)).sum())
                    flag    = out_ct > 0

                    col_color = "#F59E0B" if flag else "#737373"
                    st.markdown(
                        f'<div style="margin-bottom:6px">'
                        f'<div style="font-size:0.7rem;color:{col_color};font-family:'
                        f'\'Courier New\',monospace;font-weight:{"700" if flag else "400"}">'
                        f'{col}{"  ▲ " + str(out_ct) + " outlier(s)" if flag else ""}'
                        f'</div>'
                        f'<div style="font-size:0.66rem;color:#525252;font-family:'
                        f'\'Courier New\',monospace;padding-left:6px">'
                        f'min {s.min():,.3g} &nbsp;·&nbsp; '
                        f'max {s.max():,.3g} &nbsp;·&nbsp; '
                        f'mean {mean:,.3g}'
                        f'</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
