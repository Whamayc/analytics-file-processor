"""Stable Streamlit widget-key helpers shared across pages."""

import hashlib


def _fh(fname: str) -> str:
    return hashlib.md5(fname.encode()).hexdigest()[:10]


def _ch(col: str) -> str:
    return hashlib.md5(col.encode()).hexdigest()[:8]


def _col_keys(fname: str, col: str) -> tuple[str, str]:
    """(rename_key, include_key) — stable across reruns."""
    return f"co_rn_{_fh(fname)}_{_ch(col)}", f"co_inc_{_fh(fname)}_{_ch(col)}"


def _type_keys(fname: str, col: str) -> tuple[str, str, str, str]:
    """(type_key, fmt_key, null_key, fill_key)"""
    fh, ch = _fh(fname), _ch(col)
    return (f"ty_t_{fh}_{ch}", f"ty_f_{fh}_{ch}",
            f"ty_n_{fh}_{ch}", f"ty_v_{fh}_{ch}")


def _flt_keys(fhash: str, cid: str) -> tuple[str, str, str]:
    """(col_key, op_key, val_key) for a filter condition."""
    return f"fl_c_{fhash}_{cid}", f"fl_o_{fhash}_{cid}", f"fl_v_{fhash}_{cid}"
