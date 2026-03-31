import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
import streamlit as st
import pandas as pd
from utils.auth import require_auth
from utils.theme import inject_css, status_bar, sec_label, type_badge, page_header
from utils.transforms import cast_series, build_filter_mask
from utils.dq import render_dq_sidebar
from utils.audit import log, render_audit_log
from utils.keys import _fh, _ch, _col_keys, _type_keys, _flt_keys

st.set_page_config(
    page_title="Transform — Analytics File Processor",
    page_icon="▪",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()
require_auth()
render_dq_sidebar()

# ── Constants ──────────────────────────────────────────────────────────────────

FILTER_OPS   = ["==", "!=", ">", "<", ">=", "<=",
                "contains", "not contains", "is null", "is not null"]
TYPE_OPTIONS = ["auto", "string", "float", "integer", "date", "boolean"]
NULL_OPTIONS = ["keep as-is", "fill with 0", "fill with empty string",
                "fill with value", "drop rows with null"]
DATE_PRESETS = ["%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%d-%b-%Y"]

_DTYPE_LABEL = {
    "object":          "string",
    "string":          "string",
    "int64":           "integer",
    "Int64":           "integer",
    "float64":         "float",
    "bool":            "boolean",
    "datetime64[ns]":  "date",
}

MAX_UNDO = 10


def _snapshot_widgets(fname: str) -> dict:
    """Capture column-op and type-conversion widget values for undo."""
    state = st.session_state["files"][fname]
    snap: dict = {}
    for col in state["original_df"].columns:
        for k in (*_col_keys(fname, col), *_type_keys(fname, col)):
            if k in st.session_state:
                snap[k] = st.session_state[k]
    return snap


def _push_undo(fname: str) -> None:
    """Save current transform state to the per-file undo stack."""
    state = st.session_state["files"][fname]
    stack = state.setdefault("_undo_stack", [])
    stack.append({
        "typed_df":        state["_typed_df"].copy(),
        "base_df":         state["_base_df"].copy(),
        "applied_filters": list(state.get("_applied_filters", [])),
        "applied_logic":   state.get("_applied_logic", "AND"),
        "applied_sort":    list(state.get("_applied_sort", [])),
        "col_order":       list(state.get("_col_order", [])),
        "widgets":         _snapshot_widgets(fname),
    })
    if len(stack) > MAX_UNDO:
        stack.pop(0)


def _pop_undo(fname: str) -> bool:
    """Restore the last undo snapshot. Returns True on success."""
    state = st.session_state["files"][fname]
    stack = state.get("_undo_stack", [])
    if not stack:
        return False
    snap = stack.pop()
    state["_typed_df"]        = snap["typed_df"]
    state["_base_df"]         = snap["base_df"]
    state["_applied_filters"] = snap["applied_filters"]
    state["_applied_logic"]   = snap["applied_logic"]
    state["_applied_sort"]    = snap["applied_sort"]
    state["_col_order"]       = snap["col_order"]
    st.session_state.update(snap["widgets"])
    recompute_active(fname)
    return True


# ── State management ───────────────────────────────────────────────────────────

def ensure_state(fname: str) -> None:
    state = st.session_state["files"][fname]
    if state.get("_initialized"):
        return
    orig = state["original_df"]
    state["_col_order"]        = list(orig.columns)
    state["_filter_conditions"]= []   # [{id: str}]
    state["_filter_logic"]     = "AND"
    state["_applied_filters"]  = []   # [{col, op, val}] snapshot
    state["_applied_logic"]    = "AND"
    state["_sort_levels"]      = []   # [{id: str}]
    state["_applied_sort"]     = []   # [{col, asc}] snapshot
    state["_typed_df"]         = orig.copy()
    state["_base_df"]          = orig.copy()
    state["_initialized"]      = True


def recompute_active(fname: str) -> None:
    """Recompute active_df from _base_df + current col-op widget state."""
    state   = st.session_state["files"][fname]
    base    = state["_base_df"]

    # Apply sort (non-destructive — _base_df is never mutated)
    applied_sort = state.get("_applied_sort", [])
    if applied_sort:
        sort_cols = [s["col"] for s in applied_sort if s["col"] in base.columns]
        sort_ascs = [s["asc"] for s in applied_sort if s["col"] in base.columns]
        if sort_cols:
            base = base.sort_values(by=sort_cols, ascending=sort_ascs).reset_index(drop=True)

    order   = [c for c in state["_col_order"] if c in base.columns]
    # Append any base cols that fell out of order list
    for c in base.columns:
        if c not in order:
            order.append(c)
    state["_col_order"] = order

    includes, renames = {}, {}
    for c in order:
        rn_k, inc_k = _col_keys(fname, c)
        includes[c] = st.session_state.get(inc_k, True)
        renames[c]  = st.session_state.get(rn_k, c) or c

    included = [c for c in order if includes.get(c, True)]

    # Block on duplicate final column names
    final_names = [renames[c] for c in included]
    seen_names: dict[str, str] = {}
    dupes: list[str] = []
    for orig, final in zip(included, final_names):
        if final in seen_names:
            dupes.append(final)
        seen_names[final] = orig
    if dupes:
        state["_col_dup_error"] = sorted(set(dupes))
        return  # leave active_df unchanged
    state.pop("_col_dup_error", None)

    df = base[included].copy()
    rm = {c: renames[c] for c in included if renames.get(c, c) != c}
    if rm:
        df = df.rename(columns=rm)
    state["active_df"] = df


# ── Filter application ─────────────────────────────────────────────────────────

def _read_filter_conds(conditions: list, fhash: str) -> list[dict]:
    """Read current widget values for all conditions."""
    out = []
    for cond in conditions:
        cid = cond["id"]
        c_k, o_k, v_k = _flt_keys(fhash, cid)
        col = st.session_state.get(c_k, "")
        op  = st.session_state.get(o_k, "==")
        val = st.session_state.get(v_k, "")
        if col:
            out.append({"col": col, "op": op, "val": val})
    return out


def _apply_filter_snapshot(df: pd.DataFrame, snapshot: list, logic: str) -> pd.DataFrame:
    """Apply a saved conditions snapshot (no widget reads)."""
    if not snapshot:
        return df.copy()
    masks = [build_filter_mask(df, c["col"], c["op"], c["val"]) for c in snapshot]
    combined = masks[0]
    for m in masks[1:]:
        combined = (combined & m) if logic == "AND" else (combined | m)
    return df[combined].reset_index(drop=True)


def _apply_filter_widgets(df: pd.DataFrame, conditions: list, logic: str, fhash: str) -> pd.DataFrame:
    """Apply conditions by reading live widget values."""
    snapshot = _read_filter_conds(conditions, fhash)
    return _apply_filter_snapshot(df, snapshot, logic), snapshot


# ── Type application ───────────────────────────────────────────────────────────

def _apply_type_ops(df: pd.DataFrame, col_list: list, fname: str) -> tuple[pd.DataFrame, dict]:
    """Apply type conversions + null handling by reading widget state.
    Returns (converted_df, failures) where failures maps col → {count, target, samples}.
    """
    df = df.copy()
    drop_cols: list[str] = []
    failures: dict = {}

    for col in col_list:
        if col not in df.columns:
            continue
        t_k, f_k, n_k, v_k = _type_keys(fname, col)
        target  = st.session_state.get(t_k, "auto")
        fmt     = st.session_state.get(f_k, "%Y-%m-%d") or "%Y-%m-%d"
        null_h  = st.session_state.get(n_k, "keep as-is")
        fill_v  = st.session_state.get(v_k, "")

        # Snapshot original non-empty values for failure detection
        if target not in ("auto", "string"):
            orig_series = df[col].copy()
            was_nonnull = orig_series.notna() & (orig_series.astype(str).str.strip() != "")

        if target != "auto":
            df[col] = cast_series(
                df[col],
                target_type=target,
                date_fmt=fmt if target == "date" else None,
                null_handling=null_h,
                fill_value=fill_v,
            )
        elif null_h != "keep as-is":
            df[col] = cast_series(
                df[col],
                target_type="auto",
                null_handling=null_h,
                fill_value=fill_v,
            )

        # Detect values that failed conversion (became null from a non-null original)
        if target not in ("auto", "string"):
            coerced_check = cast_series(
                orig_series, target_type=target,
                date_fmt=fmt if target == "date" else None,
                null_handling="keep as-is",
            )
            failed_mask = was_nonnull & coerced_check.isna()
            n_failed = int(failed_mask.sum())
            if n_failed > 0:
                samples = orig_series[failed_mask].astype(str).unique()[:5].tolist()
                failures[col] = {"count": n_failed, "target": target, "samples": samples}

        if null_h == "drop rows with null":
            drop_cols.append(col)

    if drop_cols:
        df = df.dropna(subset=[c for c in drop_cols if c in df.columns])

    return df.reset_index(drop=True), failures


# ── Dtype detection ────────────────────────────────────────────────────────────

def _detect_type(series: pd.Series) -> str:
    dtype = str(series.dtype)
    return _DTYPE_LABEL.get(dtype, "string")


# ── Section 3a — Column Operations ────────────────────────────────────────────

def render_col_ops(fname: str) -> None:
    state = st.session_state["files"][fname]
    base  = state["_base_df"]
    order = state["_col_order"]

    # Sync order with base columns
    order = [c for c in order if c in base.columns]
    for c in base.columns:
        if c not in order:
            order.append(c)
    state["_col_order"] = order

    # Initialize missing widget state
    for c in order:
        rn_k, inc_k = _col_keys(fname, c)
        if rn_k  not in st.session_state: st.session_state[rn_k]  = c
        if inc_k not in st.session_state: st.session_state[inc_k] = True

    # Duplicate rename error
    dup_error = state.get("_col_dup_error")
    if dup_error:
        st.error(
            f"Duplicate column names: {', '.join(dup_error)} — rename to unique names before proceeding.",
            icon="✖️",
        )

    # Header row
    h = st.columns([0.4, 0.4, 0.1, 0.1])
    for col, lbl in zip(h, ["Column name", "Include", "", ""]):
        col.markdown(
            f'<span style="font-size:0.65rem;color:#525252;letter-spacing:.1em">{lbl}</span>',
            unsafe_allow_html=True,
        )

    fhash = _fh(fname)
    for i, c in enumerate(order):
        rn_k, inc_k = _col_keys(fname, c)
        r = st.columns([0.4, 0.4, 0.1, 0.1])

        with r[0]:
            st.text_input(
                "n", key=rn_k, label_visibility="collapsed",
                on_change=recompute_active, args=(fname,),
            )
        with r[1]:
            st.checkbox(
                "i", key=inc_k, label_visibility="collapsed",
                on_change=recompute_active, args=(fname,),
            )
        with r[2]:
            if i > 0 and st.button("↑", key=f"co_up_{fhash}_{i}",
                                    use_container_width=True):
                _push_undo(fname)
                order[i-1], order[i] = order[i], order[i-1]
                state["_col_order"] = order
                recompute_active(fname)
                st.rerun()
        with r[3]:
            if i < len(order)-1 and st.button("↓", key=f"co_dn_{fhash}_{i}",
                                               use_container_width=True):
                _push_undo(fname)
                order[i], order[i+1] = order[i+1], order[i]
                state["_col_order"] = order
                recompute_active(fname)
                st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Reset columns", key=f"co_reset_{fhash}", use_container_width=True):
        _push_undo(fname)
        orig_cols = list(state["original_df"].columns)
        state["_col_order"] = orig_cols[:]
        for c in orig_cols:
            rn_k, inc_k = _col_keys(fname, c)
            st.session_state.pop(rn_k,  None)
            st.session_state.pop(inc_k, None)
        recompute_active(fname)
        log("Reset columns", fname)
        st.rerun()


# ── Section 3b — Row Sort ─────────────────────────────────────────────────────

def _sort_widget_keys(fhash: str, cid: str) -> tuple[str, str]:
    return f"so_c_{fhash}_{cid}", f"so_o_{fhash}_{cid}"


def _read_sort_levels(levels: list, fhash: str) -> list[dict]:
    out = []
    for lvl in levels:
        cid = lvl["id"]
        c_k, o_k = _sort_widget_keys(fhash, cid)
        col = st.session_state.get(c_k, "")
        asc = st.session_state.get(o_k, "Ascending") == "Ascending"
        if col:
            out.append({"col": col, "asc": asc})
    return out


def render_row_sort(fname: str) -> None:
    state      = st.session_state["files"][fname]
    fhash      = _fh(fname)
    levels     = state.setdefault("_sort_levels", [])
    base_cols  = list(state["_base_df"].columns)

    if not base_cols:
        st.caption("No columns available.")
        return

    # ── Level rows ────────────────────────────────────────────────
    for i, lvl in enumerate(levels):
        cid = lvl["id"]
        c_k, o_k = _sort_widget_keys(fhash, cid)

        if c_k not in st.session_state or st.session_state[c_k] not in base_cols:
            st.session_state[c_k] = base_cols[0]

        c0, c1, c2, c3 = st.columns([0.35, 2.5, 1.4, 0.4])
        with c0:
            st.markdown(
                f'<span style="font-size:0.72rem;color:#525252;font-family:monospace">'
                f'{"1st" if i == 0 else ("2nd" if i == 1 else ("3rd" if i == 2 else f"{i+1}th"))}</span>',
                unsafe_allow_html=True,
            )
        with c1:
            st.selectbox("col", base_cols, key=c_k, label_visibility="collapsed")
        with c2:
            st.selectbox("order", ["Ascending", "Descending"], key=o_k,
                         label_visibility="collapsed")
        with c3:
            if st.button("✕", key=f"so_rm_{fhash}_{cid}", use_container_width=True):
                for k in [c_k, o_k]:
                    st.session_state.pop(k, None)
                levels.pop(i)
                state["_sort_levels"] = levels
                st.rerun()

    # ── Action buttons ────────────────────────────────────────────
    b0, b1, b2, b3 = st.columns([1, 1, 1.2, 1.5])
    with b0:
        if st.button("+ Add level", key=f"so_add_{fhash}", use_container_width=True):
            cid = f"{len(levels)}_{int(time.time()*1000) % 100000}"
            levels.append({"id": cid})
            state["_sort_levels"] = levels
            st.rerun()
    with b1:
        apply_clicked = st.button(
            "Apply", type="primary", key=f"so_apply_{fhash}",
            disabled=not levels, use_container_width=True,
        )
    with b2:
        if st.button("Clear sort", key=f"so_clear_{fhash}",
                     disabled=not state.get("_applied_sort"), use_container_width=True):
            for lvl in levels:
                for k in _sort_widget_keys(fhash, lvl["id"]):
                    st.session_state.pop(k, None)
            state["_sort_levels"]  = []
            state["_applied_sort"] = []
            recompute_active(fname)
            log("Cleared sort", fname)
            st.rerun()

    with b3:
        sort_pending = bool(levels) and (
            _read_sort_levels(levels, fhash) != state.get("_applied_sort", [])
        )
        if sort_pending:
            st.markdown(
                '<span style="font-size:0.72rem;color:#F59E0B;font-family:monospace">'
                '⚠ Unapplied changes</span>',
                unsafe_allow_html=True,
            )

    # ── Applied sort indicator ────────────────────────────────────
    applied = state.get("_applied_sort", [])
    if applied:
        parts = " → ".join(
            f'{s["col"]} {"↑" if s["asc"] else "↓"}' for s in applied
        )
        st.markdown(
            f'<span style="font-size:0.75rem;color:#F59E0B">Sorted by: {parts}</span>',
            unsafe_allow_html=True,
        )

    if apply_clicked and levels:
        _push_undo(fname)
        snapshot = _read_sort_levels(levels, fhash)
        if snapshot:
            state["_applied_sort"] = snapshot
            recompute_active(fname)
            sort_desc = " → ".join(
                f'{s["col"]} {"ASC" if s["asc"] else "DESC"}' for s in snapshot
            )
            log("Sorted rows", f"{fname} — {sort_desc}")
            st.success(f"Sorted by: {sort_desc}", icon="✔️")
            st.rerun()


# ── Section 3c — Row Filter ────────────────────────────────────────────────────

def render_row_filter(fname: str) -> None:
    state      = st.session_state["files"][fname]
    conditions = state["_filter_conditions"]
    fhash      = _fh(fname)
    base_cols  = list(state["_typed_df"].columns)
    orig_len   = len(state["_typed_df"])
    cur_len    = len(state["_base_df"])

    # AND / OR toggle
    logic_idx = 0 if state.get("_filter_logic", "AND") == "AND" else 1
    logic = st.radio(
        "Combine with",
        ["AND", "OR"],
        index=logic_idx,
        horizontal=True,
        key=f"fl_logic_{fhash}",
        label_visibility="collapsed",
    )
    state["_filter_logic"] = logic

    if not base_cols:
        st.caption("No columns available.")
        return

    # Condition rows
    for i, cond in enumerate(conditions):
        cid = cond["id"]
        c_k, o_k, v_k = _flt_keys(fhash, cid)

        # Init defaults
        if c_k not in st.session_state:
            st.session_state[c_k] = base_cols[0]
        if o_k not in st.session_state:
            st.session_state[o_k] = "=="
        # Ensure col is still valid
        if st.session_state.get(c_k) not in base_cols:
            st.session_state[c_k] = base_cols[0]

        cur_op = st.session_state.get(o_k, "==")
        c0, c1, c2, c3 = st.columns([2, 1.6, 2.4, 0.4])

        with c0:
            st.selectbox("col", base_cols, key=c_k,
                         label_visibility="collapsed")
        with c1:
            st.selectbox("op", FILTER_OPS, key=o_k,
                         label_visibility="collapsed")
        with c2:
            if cur_op not in ("is null", "is not null"):
                st.text_input("val", key=v_k,
                              label_visibility="collapsed",
                              placeholder="value…")
            else:
                st.markdown(
                    '<span style="font-size:0.72rem;color:#525252">—</span>',
                    unsafe_allow_html=True,
                )
        with c3:
            if st.button("✕", key=f"fl_rm_{fhash}_{cid}",
                         use_container_width=True):
                for k in [c_k, o_k, v_k]:
                    st.session_state.pop(k, None)
                conditions.pop(i)
                state["_filter_conditions"] = conditions
                st.rerun()

    # Buttons row
    b0, b1, b2, b3 = st.columns([1, 1.2, 1.5, 2])

    with b0:
        if st.button("+ Add", key=f"fl_add_{fhash}", use_container_width=True):
            cid = f"{len(conditions)}_{int(time.time()*1000) % 100000}"
            conditions.append({"id": cid})
            state["_filter_conditions"] = conditions
            st.rerun()

    with b1:
        apply_clicked = st.button(
            "Apply", type="primary", key=f"fl_apply_{fhash}",
            disabled=not conditions, use_container_width=True,
        )

    with b2:
        if st.button("Clear all", key=f"fl_clear_{fhash}",
                     disabled=not conditions, use_container_width=True):
            for cond in conditions:
                cid = cond["id"]
                for k in _flt_keys(fhash, cid):
                    st.session_state.pop(k, None)
            state["_filter_conditions"] = []
            state["_applied_filters"]   = []
            state["_applied_logic"]     = "AND"
            state["_base_df"]           = state["_typed_df"].copy()
            recompute_active(fname)
            st.rerun()

    with b3:
        filter_pending = bool(conditions) and (
            _read_filter_conds(conditions, fhash) != state.get("_applied_filters", [])
            or logic != state.get("_applied_logic", "AND")
        )
        if filter_pending:
            st.markdown(
                '<span style="font-size:0.72rem;color:#F59E0B;font-family:monospace">'
                '⚠ Unapplied changes</span>',
                unsafe_allow_html=True,
            )
        elif orig_len != cur_len:
            st.markdown(
                f'<span style="font-size:0.75rem;color:#F59E0B">'
                f'{orig_len:,} → {cur_len:,} rows'
                f'&nbsp;({orig_len - cur_len:,} removed)</span>',
                unsafe_allow_html=True,
            )

    if apply_clicked and conditions:
        _push_undo(fname)
        new_base, snapshot = _apply_filter_widgets(
            state["_typed_df"], conditions, logic, fhash
        )
        pre  = len(state["_typed_df"])
        post = len(new_base)
        state["_base_df"]          = new_base
        state["_applied_filters"]  = snapshot
        state["_applied_logic"]    = logic
        recompute_active(fname)
        filter_desc = f" {logic} ".join(
            f"{c['col']} {c['op']} {c['val']}".strip() for c in snapshot
        )
        log("Applied filter", f"{fname} — {filter_desc} ({pre:,} → {post:,} rows)")
        st.success(
            f"{pre:,} → {post:,} rows  ({pre - post:,} removed)",
            icon="✔️",
        )
        st.rerun()


# ── Section 3c — Type Conversion ───────────────────────────────────────────────

def render_type_conversion(fname: str) -> None:
    state   = st.session_state["files"][fname]
    orig_df = state["original_df"]
    fhash   = _fh(fname)

    # Header
    h = st.columns([2.2, 1.4, 1.8, 1.8])
    for col, lbl in zip(h, ["Column", "Convert to", "Date format", "Null handling"]):
        col.markdown(
            f'<span style="font-size:0.65rem;color:#525252;letter-spacing:.1em">{lbl}</span>',
            unsafe_allow_html=True,
        )

    for col in orig_df.columns:
        t_k, f_k, n_k, v_k = _type_keys(fname, col)
        detected = _detect_type(orig_df[col])

        # Init defaults
        if t_k not in st.session_state: st.session_state[t_k] = "auto"
        if f_k not in st.session_state: st.session_state[f_k] = "%Y-%m-%d"
        if n_k not in st.session_state: st.session_state[n_k] = "keep as-is"
        if v_k not in st.session_state: st.session_state[v_k] = ""

        cur_type = st.session_state.get(t_k, "auto")
        cur_null = st.session_state.get(n_k, "keep as-is")

        r = st.columns([2.2, 1.4, 1.8, 1.8])

        with r[0]:
            st.markdown(
                f'<span style="font-size:0.78rem;color:#D4D4D4;font-family:monospace">'
                f'{col}</span>&nbsp;{type_badge(detected)}',
                unsafe_allow_html=True,
            )
        with r[1]:
            st.selectbox(
                "t", TYPE_OPTIONS,
                index=TYPE_OPTIONS.index(cur_type),
                key=t_k,
                label_visibility="collapsed",
            )
        with r[2]:
            if st.session_state.get(t_k) == "date":
                # Quick presets + raw input
                preset_cols = st.columns(len(DATE_PRESETS))
                for pc, fmt in zip(preset_cols, DATE_PRESETS):
                    if pc.button(
                        fmt.replace("%", ""),
                        key=f"ty_pre_{fhash}_{_ch(col)}_{fmt}",
                        use_container_width=True,
                    ):
                        st.session_state[f_k] = fmt
                        st.rerun()
                st.text_input(
                    "fmt", key=f_k,
                    label_visibility="collapsed",
                    placeholder="%Y-%m-%d",
                )
            else:
                st.markdown(
                    '<span style="font-size:0.7rem;color:#404040">—</span>',
                    unsafe_allow_html=True,
                )
        with r[3]:
            st.selectbox(
                "null", NULL_OPTIONS,
                index=NULL_OPTIONS.index(cur_null),
                key=n_k,
                label_visibility="collapsed",
            )
            if st.session_state.get(n_k) == "fill with value":
                st.text_input(
                    "fill", key=v_k,
                    label_visibility="collapsed",
                    placeholder="fill value…",
                )

    st.markdown("<br>", unsafe_allow_html=True)

    # Show result of previous Apply (stored across rerun)
    conv_result = state.pop("_type_conv_result", None)
    if conv_result is not None:
        for col, info in conv_result.get("failures", {}).items():
            samples_str = ", ".join(f'"{v}"' for v in info["samples"])
            st.warning(
                f"{col}: {info['count']:,} value(s) could not be converted to "
                f"{info['target']} — set to null. "
                f"Values: {samples_str}. Use the null handling dropdown to fill or drop.",
                icon="⚠️",
            )
        if not conv_result.get("failures"):
            st.success("Type conversions applied.", icon="✔️")

    if st.button("Apply type conversions", type="primary",
                 key=f"ty_apply_{fhash}"):
        _push_undo(fname)
        try:
            new_typed, failures = _apply_type_ops(orig_df, list(orig_df.columns), fname)
            state["_typed_df"] = new_typed
            # Re-apply previously applied filters
            state["_base_df"] = _apply_filter_snapshot(
                new_typed,
                state.get("_applied_filters", []),
                state.get("_applied_logic", "AND"),
            )
            recompute_active(fname)
            log("Applied type conversions", fname)
            if failures:
                fail_summary = ", ".join(f"{c} ({i['count']})" for c, i in failures.items())
                log("Type conversion warnings", f"{fname} — {fail_summary}")
            state["_type_conv_result"] = {"failures": failures}
            st.rerun()
        except Exception as e:
            st.error(f"Type conversion failed: {e}", icon="✖️")


# ── Per-file tab renderer ──────────────────────────────────────────────────────

def render_tab(fname: str) -> None:
    ensure_state(fname)
    state     = st.session_state["files"][fname]
    active_df = state["active_df"]

    left, right = st.columns([11, 9], gap="medium")

    # ── Right — live preview ───────────────────────────────────────────────────
    with right:
        sec_label("Live preview — 10 rows")
        st.markdown(
            f'<span style="font-size:0.72rem;color:#525252">'
            f'{len(active_df):,} rows × {len(active_df.columns)} cols</span>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            st.session_state["files"][fname]["active_df"].head(10),
            use_container_width=True,
            hide_index=True,
        )
        orig_n = len(state["original_df"])
        cur_n  = len(active_df)
        if orig_n != cur_n:
            st.caption(f"Original: {orig_n:,} rows  →  now: {cur_n:,}  ({orig_n - cur_n:,} removed)")

    # ── Left — transform sections ──────────────────────────────────────────────
    with left:
        # ── Undo ─────────────────────────────────────────────────────────────
        undo_count = len(state.get("_undo_stack", []))
        if st.button(
            f"↩  Undo  ({undo_count})",
            key=f"undo_{_fh(fname)}",
            disabled=undo_count == 0,
            use_container_width=True,
        ):
            _pop_undo(fname)
            log("Undo", fname)
            st.rerun()

        with st.expander("**3a  Column Operations** — rename · reorder · include",
                         expanded=True):
            render_col_ops(fname)

        with st.expander("**3b  Row Sort** — multi-column sort"):
            render_row_sort(fname)

        with st.expander("**3c  Row Filter** — condition builder"):
            render_row_filter(fname)

        with st.expander("**3d  Type Conversion** — cast · null handling"):
            render_type_conversion(fname)

        st.markdown(
            '<div style="background:#0F0F0F;border:1px solid #1E1E1E;padding:7px 12px;'
            'font-size:0.72rem;color:#525252;font-family:monospace;margin-top:8px">'
            'ℹ  Output delimiter is configured on the <b style="color:#737373">Export</b> page.'
            '</div>',
            unsafe_allow_html=True,
        )


# ── Page ───────────────────────────────────────────────────────────────────────

page_header("Transform")

files: dict = st.session_state.get("files", {})

if not files:
    st.warning("No files loaded.", icon="⚠️")
    st.page_link("pages/1_upload.py", label="Go to Upload", icon="📂")
    st.stop()

total_rows  = sum(v["meta"]["rows"] for v in files.values())
total_steps = sum(len(v.get("pipeline", [])) for v in files.values())

status_bar({
    "FILES":   str(len(files)),
    "ROWS":    f"{total_rows:,}",
})

fnames     = list(files.keys())
tab_labels = [fn if len(fn) <= 24 else fn[:22] + "…" for fn in fnames]
tabs       = st.tabs(tab_labels)

for idx, fname in enumerate(fnames):
    with tabs[idx]:
        render_tab(fname)

# ── Audit log ──────────────────────────────────────────────────────────────────
render_audit_log()
