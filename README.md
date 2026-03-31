# Analytics File Processor

A multi-page Streamlit app for the **Eagle Pace** mutual fund analytics team. Upload tabular data files, apply a replayable transform pipeline, and export to multiple formats — all in a dark, secure, browser-based interface.

---

## Features

| Page | What it does |
|---|---|
| **Upload** | Load `.xlsx`, `.csv`, or `.txt` files. Auto-detects delimiter and encoding. Supports multi-sheet Excel and merging multiple files (stack rows or join on key). |
| **Transform** | Rename columns, cast types, filter rows, sort, reorder, and compute new columns. All steps are recorded in a replayable pipeline. |
| **Export** | Download as formatted Excel, CSV (custom delimiter), Power BI-ready CSV, Oracle `INSERT` statements, or PDF. |
| **Templates** | Save named pipelines and apply them to any loaded file in future sessions. |
| **Oracle Query** | Run `SELECT` queries or DML/PL-SQL against an Oracle database and export the results. |

---

## Getting Started

### 1. Install dependencies

```bash
pip install -r app/requirements.txt
```

### 2. Set a password

Generate a SHA-256 hash of your chosen password:

```bash
python -c "import hashlib; print(hashlib.sha256('yourpassword'.encode()).hexdigest())"
```

Create `app/.streamlit/secrets.toml` (this file is git-ignored — never commit it):

```toml
APP_PASSWORD_HASH = "<paste hash here>"
```

### 3. Run the app

```bash
cd app && streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Project Structure

```
app/
├── app.py                  # Home page + session overview
├── requirements.txt
├── .streamlit/
│   ├── config.toml         # Dark/amber theme
│   └── secrets.toml        # Password hash (git-ignored)
├── pages/
│   ├── 1_upload.py
│   ├── 2_transform.py
│   ├── 3_export.py
│   ├── 4_templates.py
│   └── 5_oracle_query.py
└── utils/
    ├── auth.py             # SHA-256 login
    ├── theme.py            # CSS injection, badges, status bar
    ├── transforms.py       # Transform engine: apply_step, replay_pipeline
    ├── export.py           # Excel, PDF, Oracle SQL builders
    ├── audit.py            # Session audit log
    ├── dq.py               # Data quality sidebar (nulls, duplicates, outliers)
    └── keys.py             # Stable MD5 widget keys
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `streamlit>=1.35.0` | Web UI |
| `pandas>=2.2.0` | DataFrame operations |
| `openpyxl>=3.1.0` | Excel read/write |
| `reportlab>=4.0.0` | PDF generation |
| `chardet>=5.0.0` | Encoding detection |
| `oracledb>=2.0.0` | Oracle database connectivity |
| `pywin32>=306` | Outlook email draft integration (Windows only) |

---

## Configuration

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

---

## Security

- All pages require password authentication via `require_auth()`.
- The password is stored only as a SHA-256 hash in `secrets.toml`, which is excluded from version control.
- Session data lives in `st.session_state` and is not persisted to disk.

---

*Eagle Pace · Internal Use Only*
