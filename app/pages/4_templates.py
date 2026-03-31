import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import datetime
import streamlit as st
from pathlib import Path
from utils.auth import require_auth
from utils.theme import inject_css, status_bar, sec_label, page_header
from utils.dq import render_dq_sidebar
from utils.audit import log, render_audit_log
from utils.keys import _fh, _ch, _col_keys

st.set_page_config(
    page_title="Templates — Analytics File Processor",
    page_icon="▪",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()
require_auth()
render_dq_sidebar()

# ── Template store (local filesystem) ─────────────────────────────────────────

TEMPLATES_PATH = Path.home() / ".analytics_processor_templates.json"


def load_templates() -> dict:
    if TEMPLATES_PATH.exists():
        try:
            return json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_templates(templates: dict) -> None:
    TEMPLATES_PATH.write_text(json.dumps(templates, indent=2), encoding="utf-8")


# ── Read current column config from session state ─────────────────────────────

def read_col_config(fname: str) -> list[dict]:
    """Return list of column dicts reflecting current widget state for fname."""
    state = st.session_state["files"][fname]
    order = state.get("_col_order", list(state["original_df"].columns))
    result = []
    for col in order:
        rn_k, inc_k = _col_keys(fname, col)
        result.append({
            "original_name": col,
            "display_name":  st.session_state.get(rn_k, col) or col,
            "include":       bool(st.session_state.get(inc_k, True)),
        })
    return result


# ── Apply template column config to a file ────────────────────────────────────

def _recompute_active(fname: str) -> None:
    state = st.session_state["files"][fname]
    base  = state.get("_base_df", state["original_df"])
    order = [c for c in state["_col_order"] if c in base.columns]
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
    df = base[included].copy()
    rm = {c: renames[c] for c in included if renames.get(c, c) != c}
    if rm:
        df = df.rename(columns=rm)
    state["active_df"] = df


def apply_template_to_file(fname: str, tmpl_columns: list[dict]) -> list[str]:
    """
    Apply template column config to fname.
    Matches template original_name values case-insensitively.
    Returns list of warning strings for unmatched columns.
    """
    state     = st.session_state["files"][fname]
    orig_cols = list(state["original_df"].columns)
    lower_map = {c.lower(): c for c in orig_cols}
    warnings  = []
    new_order = []
    applied   = set()

    for tcol in tmpl_columns:
        orig   = tcol["original_name"]
        actual = lower_map.get(orig.lower())
        if actual is None:
            warnings.append(f"Column '{orig}' not found in current file — skipped")
            continue
        new_order.append(actual)
        applied.add(actual)
        rn_k, inc_k = _col_keys(fname, actual)
        st.session_state[rn_k]  = tcol.get("display_name", actual)
        st.session_state[inc_k] = tcol.get("include", True)

    # Columns in file not in template: append at end with default settings
    for c in orig_cols:
        if c not in applied:
            new_order.append(c)
            rn_k, inc_k = _col_keys(fname, c)
            if rn_k  not in st.session_state: st.session_state[rn_k]  = c
            if inc_k not in st.session_state: st.session_state[inc_k] = True

    state["_col_order"] = new_order

    # Ensure enough state exists for recompute
    if not state.get("_initialized"):
        state["_base_df"]           = state["original_df"].copy()
        state["_typed_df"]          = state["original_df"].copy()
        state["_filter_conditions"] = []
        state["_filter_logic"]      = "AND"
        state["_applied_filters"]   = []
        state["_applied_logic"]     = "AND"
        state["_initialized"]       = True

    _recompute_active(fname)
    return warnings


# ── Page ───────────────────────────────────────────────────────────────────────

page_header("Templates")

templates = load_templates()
files: dict = st.session_state.get("files", {})

status_bar({
    "SAVED TEMPLATES": str(len(templates)),
    "FILES LOADED":    str(len(files)),
})

st.caption(
    "Save a file's column configuration (order, display names, include/exclude) as a named template, "
    "then apply it to other files in one click. "
    "Filter conditions and type conversions are not saved."
)

left, right = st.columns([1, 2], gap="medium")

# ══════════════════════════════════════════════════════════════════════
# LEFT — Save + Import / Export
# ══════════════════════════════════════════════════════════════════════
with left:

    # ── Save current column config ────────────────────────────────────
    sec_label("Save current config as template")

    initialized_files = {fn: v for fn, v in files.items() if v.get("_initialized")}

    if not files:
        st.markdown(
            '<span style="font-size:0.75rem;color:#525252">No files loaded.</span>',
            unsafe_allow_html=True,
        )
    elif not initialized_files:
        st.markdown(
            '<span style="font-size:0.75rem;color:#525252">'
            "Open the Transform page first to configure column settings."
            "</span>",
            unsafe_allow_html=True,
        )
    else:
        src_fname = st.selectbox(
            "Source file",
            list(initialized_files.keys()),
            key="tmpl_src",
        )
        t_name = st.text_input(
            "Template name",
            key="t_name",
            placeholder="e.g. Eagle Monthly Standard",
        )

        pending_ow = st.session_state.get("_pending_overwrite")

        if pending_ow and pending_ow == t_name.strip():
            st.warning(f"Template '{pending_ow}' already exists. Overwrite?", icon="⚠️")
            ow1, ow2 = st.columns(2)
            with ow1:
                if st.button("Yes, overwrite", type="primary",
                             use_container_width=True, key="ow_yes"):
                    cols = read_col_config(src_fname)
                    templates[pending_ow] = {
                        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
                        "columns":  cols,
                    }
                    save_templates(templates)
                    log("Saved template (overwrite)", f"'{pending_ow}' ({len(cols)} columns) from {src_fname}")
                    st.session_state.pop("_pending_overwrite", None)
                    st.success(f"Saved '{pending_ow}' ({len(cols)} columns)", icon="✔️")
                    st.rerun()
            with ow2:
                if st.button("Cancel", use_container_width=True, key="ow_no"):
                    st.session_state.pop("_pending_overwrite", None)
                    st.rerun()
        else:
            if st.button("Save", type="primary", use_container_width=True,
                         key="tmpl_save_btn"):
                name = t_name.strip()
                if not name:
                    st.error("Name is required.", icon="✖️")
                elif name in templates:
                    st.session_state["_pending_overwrite"] = name
                    st.rerun()
                else:
                    cols = read_col_config(src_fname)
                    templates[name] = {
                        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
                        "columns":  cols,
                    }
                    save_templates(templates)
                    log("Saved template", f"'{name}' ({len(cols)} columns) from {src_fname}")
                    st.success(f"Saved '{name}' ({len(cols)} columns)", icon="✔️")
                    st.rerun()

    # ── Import templates ──────────────────────────────────────────────
    st.divider()
    sec_label("Import templates from JSON")
    import_file = st.file_uploader(
        "Load templates JSON", type=["json"], key="tmpl_import"
    )

    if import_file:
        try:
            loaded: dict = json.loads(import_file.read())
            if not isinstance(loaded, dict):
                st.error("Unrecognized format — expected a JSON object.", icon="✖️")
            else:
                conflicts    = [k for k in loaded if k in templates]
                n_new        = sum(1 for k in loaded if k not in templates)

                st.markdown(
                    f'<span style="font-size:0.75rem;color:#A3A3A3">'
                    f'{len(loaded)} template(s) found &nbsp;·&nbsp; '
                    f'{n_new} new &nbsp;·&nbsp; {len(conflicts)} conflict(s)</span>',
                    unsafe_allow_html=True,
                )

                resolved: dict[str, str] = {}
                for cname in conflicts:
                    action = st.radio(
                        f"`{cname}`",
                        ["Keep existing", "Overwrite"],
                        key=f"_imp_res_{cname}",
                        horizontal=True,
                    )
                    resolved[cname] = action

                if st.button("Import", type="primary",
                             use_container_width=True, key="do_import"):
                    merged = {**templates}
                    count  = 0
                    for k, v in loaded.items():
                        if k in conflicts:
                            if resolved.get(k) == "Overwrite":
                                merged[k] = v
                                count += 1
                        else:
                            merged[k] = v
                            count += 1
                    save_templates(merged)
                    st.success(f"Imported {count} template(s).", icon="✔️")
                    st.rerun()

        except Exception as e:
            st.error(f"Import failed: {e}", icon="✖️")

    # ── Export all ────────────────────────────────────────────────────
    if templates:
        st.divider()
        sec_label("Export all templates")
        st.download_button(
            "Export all templates",
            data=json.dumps(templates, indent=2),
            file_name="analytics_templates.json",
            mime="application/json",
            use_container_width=True,
        )

# ══════════════════════════════════════════════════════════════════════
# RIGHT — Template library
# ══════════════════════════════════════════════════════════════════════
with right:
    sec_label(f"Template library — {len(templates)} saved")

    if not templates:
        st.markdown(
            '<div style="color:#525252;font-size:0.8rem;font-family:monospace;padding:20px 0">'
            "No templates saved yet.</div>",
            unsafe_allow_html=True,
        )
    else:
        for tname, tmpl in list(templates.items()):
            cols_list = tmpl.get("columns", [])
            saved_at  = tmpl.get("saved_at", "—")
            n_inc     = sum(1 for c in cols_list if c.get("include", True))

            with st.expander(tname, expanded=False):
                st.markdown(
                    f'<span style="font-size:0.72rem;color:#737373">'
                    f'Saved: {saved_at} &nbsp;·&nbsp; '
                    f'{len(cols_list)} columns ({n_inc} included)</span>',
                    unsafe_allow_html=True,
                )

                # Column preview
                if cols_list:
                    st.markdown("<br>", unsafe_allow_html=True)
                    sec_label("Column configuration")
                    hdr = st.columns([2.5, 2.5, 0.7])
                    for hcol, lbl in zip(hdr, ["Original name", "Display name", "Incl."]):
                        hcol.markdown(
                            f'<span style="font-size:0.62rem;color:#525252;'
                            f'letter-spacing:.08em">{lbl}</span>',
                            unsafe_allow_html=True,
                        )
                    for tc in cols_list:
                        r = st.columns([2.5, 2.5, 0.7])
                        r[0].markdown(
                            f'<span style="font-size:0.72rem;color:#737373;'
                            f'font-family:monospace">{tc["original_name"]}</span>',
                            unsafe_allow_html=True,
                        )
                        r[1].markdown(
                            f'<span style="font-size:0.72rem;color:#D4D4D4;'
                            f'font-family:monospace">{tc["display_name"]}</span>',
                            unsafe_allow_html=True,
                        )
                        inc_color = "#22C55E" if tc.get("include", True) else "#525252"
                        inc_mark  = "✓"       if tc.get("include", True) else "✕"
                        r[2].markdown(
                            f'<span style="font-size:0.72rem;color:{inc_color}">'
                            f'{inc_mark}</span>',
                            unsafe_allow_html=True,
                        )

                # ── Apply to file ─────────────────────────────────────
                st.markdown("<br>", unsafe_allow_html=True)
                if files:
                    sec_label("Apply to current file")
                    apply_target = st.selectbox(
                        "Select file",
                        list(files.keys()),
                        key=f"apply_tgt_{tname}",
                        label_visibility="collapsed",
                    )
                    result_key = f"_tmpl_apply_result_{tname}"

                    # Show result of previous apply (stored across rerun)
                    apply_result = st.session_state.pop(result_key, None)
                    if apply_result is not None:
                        for w in apply_result["warns"]:
                            st.warning(w, icon="⚠️")
                        st.success(
                            f"Applied '{tname}' to '{apply_result['target']}' "
                            f"({apply_result['matched']} columns matched).",
                            icon="✔️",
                        )

                    # Pre-apply match preview
                    target_lower = {
                        c.lower()
                        for c in files[apply_target]["original_df"].columns
                    }
                    tmpl_names     = [c["original_name"] for c in cols_list]
                    matched_prev   = sum(1 for n in tmpl_names if n.lower() in target_lower)
                    total_tmpl     = len(tmpl_names)
                    match_pct      = matched_prev / total_tmpl if total_tmpl else 1.0
                    match_color    = (
                        "#22C55E" if match_pct >= 0.8
                        else "#F59E0B" if match_pct >= 0.5
                        else "#EF4444"
                    )
                    st.markdown(
                        f'<span style="font-size:0.72rem;color:{match_color};'
                        f'font-family:monospace">'
                        f'Match: {matched_prev} / {total_tmpl} columns found '
                        f'in {apply_target}</span>',
                        unsafe_allow_html=True,
                    )
                    if match_pct < 0.5:
                        st.warning(
                            f"Only {matched_prev} of {total_tmpl} template columns exist "
                            "in the selected file — check you're applying to the correct file.",
                            icon="⚠️",
                        )

                    if st.button(
                        "Apply to current file",
                        key=f"apply_{tname}",
                        type="primary",
                        use_container_width=True,
                    ):
                        warns = apply_template_to_file(apply_target, cols_list)
                        matched = len(cols_list) - len(warns)
                        log("Applied template",
                            f"'{tname}' → '{apply_target}' ({matched} columns matched)")
                        st.session_state[result_key] = {
                            "warns": warns,
                            "matched": matched,
                            "target": apply_target,
                        }
                        st.rerun()
                else:
                    st.caption("No files loaded — upload files first to apply this template.")

                # ── Delete ────────────────────────────────────────────
                st.markdown("<br>", unsafe_allow_html=True)
                del_key = f"_confirm_del_{tname}"

                if st.session_state.get(del_key):
                    st.warning(
                        f"Delete '{tname}'? This cannot be undone.", icon="⚠️"
                    )
                    d1, d2 = st.columns(2)
                    with d1:
                        if st.button(
                            "Yes, delete",
                            key=f"del_yes_{tname}",
                            type="primary",
                            use_container_width=True,
                        ):
                            templates.pop(tname, None)
                            save_templates(templates)
                            log("Deleted template", f"'{tname}'")
                            st.session_state.pop(del_key, None)
                            st.rerun()
                    with d2:
                        if st.button(
                            "Cancel",
                            key=f"del_no_{tname}",
                            use_container_width=True,
                        ):
                            st.session_state.pop(del_key, None)
                            st.rerun()
                else:
                    if st.button(
                        "Delete", key=f"del_{tname}", use_container_width=True
                    ):
                        st.session_state[del_key] = True
                        st.rerun()

# ── Audit log ──────────────────────────────────────────────────────────────────
render_audit_log()
