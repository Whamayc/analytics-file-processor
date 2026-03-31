# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the app:**
```bash
cd app && streamlit run app.py
```

**Install dependencies:**
```bash
pip install -r app/requirements.txt
```

**Update password (for secrets.toml):**
```bash
python -c "import hashlib; print(hashlib.sha256('yourpassword'.encode()).hexdigest())"
```

No test or lint framework is configured.

## Architecture

A multi-page Streamlit app for the Eagle Pace mutual fund analytics team. It processes uploaded tabular files through a transform → export pipeline.

### Data flow

```
Upload (pages/1_upload.py)
  → st.session_state["files"][filename] = {original_df, active_df, pipeline, meta}
Transform (pages/2_transform.py)
  → mutates active_df, appends steps to pipeline[]
Export (pages/3_export.py)
  → CSV / Excel / Power BI / Oracle INSERT / PDF
Templates (pages/4_templates.py)
  → persists pipelines to ~/.analytics_processor_templates.json
```

### Session state shape

All per-file data is nested under `st.session_state["files"][filename]`. There are no flat top-level keys like `active_df` or `original_df`.

```python
st.session_state = {
    "authenticated": bool,
    "audit_log": [{"timestamp", "action", "detail"}],
    "files": {
        "<filename>": {
            # Core data
            "original_df": DataFrame,       # immutable source — never mutated
            "active_df":   DataFrame,       # rendered output: base → sort → col ops
            "pipeline":    [],              # serialisable step dicts (for templates)
            "meta": {"delimiter", "encoding", "rows", "cols"},

            # Transform working state (set by ensure_state on first visit to Transform)
            "_initialized":       bool,
            "_col_order":         list[str],
            "_typed_df":          DataFrame,  # after type conversions
            "_base_df":           DataFrame,  # after filters (input to sort + col ops)

            # Filter state
            "_filter_conditions": list[{"id"}],   # live UI rows
            "_filter_logic":      "AND" | "OR",
            "_applied_filters":   list[{"col","op","val"}],  # last applied snapshot
            "_applied_logic":     "AND" | "OR",

            # Sort state
            "_sort_levels":       list[{"id"}],   # live UI rows
            "_applied_sort":      list[{"col","asc"}],  # applied snapshot (non-destructive)

            # Error / result flags (transient, consumed on next render)
            "_col_dup_error":     list[str] | None,   # duplicate rename names
            "_type_conv_result":  {"failures": {col: {"count","target","samples"}}} | None,
        }
    },
}
```

`recompute_active` applies the chain: `_base_df` → sort (`_applied_sort`) → column filter/rename (`_col_order` + widget state) → `active_df`. It never mutates `_base_df`.

### Utils

| Module | Purpose |
|---|---|
| `utils/auth.py` | SHA256 password login; `require_auth()` must be called at top of every page |
| `utils/theme.py` | CSS injection (dark/amber theme), badge helpers, `status_bar()`, `sec_label()` |
| `utils/transforms.py` | `apply_step()`, `replay_pipeline()`, `cast_series()`, `build_filter_mask()` — the core transform engine |
| `utils/audit.py` | `log(action, detail)` appends to session audit_log; `render_audit_log()` shows it in an expander |
| `utils/dq.py` | Data quality sidebar panel: null counts, duplicate detection, 3-sigma outliers |

### Key implementation patterns

- **Stable widget keys:** MD5 hash of filename/column name used as Streamlit widget key to survive reruns.
- **Lazy init:** `_initialized` flag on each file entry prevents duplicate state setup on page rerender.
- **Pipeline replay:** Transforms are stored as serializable step dicts; `replay_pipeline()` re-applies them from `original_df`, enabling undo and template reuse.
- **Auth gate:** Every page must call `require_auth()` at the top before rendering any content.

### Configuration

- `app/.streamlit/config.toml` — dark base theme, amber `#F59E0B` primary, monospace font
- `app/.streamlit/secrets.toml` — `APP_PASSWORD_HASH` (SHA256 hex digest)

## UI / Styling

Theme is defined in `app/.streamlit/config.toml`:

```toml
[theme]
base = "dark"
primaryColor = "#F59E0B"
backgroundColor = "#0F1117"
secondaryBackgroundColor = "#1A1D27"
textColor = "#E2E8F0"
font = "monospace"
```

Additional conventions enforced via `st.markdown(..., unsafe_allow_html=True)` in `utils/theme.py`:

- **Page title:** small monospaced label + version in top-left (e.g. `AFP v1.0`)
- **Buttons:** always pass `use_container_width=True`
- **Download buttons:** amber border styling to distinguish from action buttons
- **Status messages:** use `st.error` / `st.warning` — never `st.write` for status or feedback
- **Section breaks:** use `st.divider()` between major sections
- **Column operation table (Page 2):** `st.columns([0.4, 0.4, 0.1, 0.1])` — name / include / up / down

## Dependencies

`app/requirements.txt` — key choices:

| Package | Purpose |
|---|---|
| `streamlit>=1.35.0` | Web UI framework |
| `pandas>=2.2.0` | DataFrame operations |
| `openpyxl>=3.1.0` | Excel read/write |
| `reportlab>=4.0.0` | PDF generation (`build_pdf` in `3_export.py`) — **not** fpdf2 |
| `chardet>=5.0.0` | Encoding detection in `detect_encoding()` (`1_upload.py`) |
