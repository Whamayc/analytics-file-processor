"""
Shared transform logic used by pages/2_transform.py and pages/4_templates.py.
"""
import streamlit as st
import pandas as pd


# ── New helpers for widget-state-driven transform UI ──────────────────────────

def cast_series(
    series: pd.Series,
    target_type: str,
    date_fmt: str | None = None,
    null_handling: str = "keep as-is",
    fill_value: str = "",
) -> pd.Series:
    """Apply type conversion + null handling to a single Series."""
    s = series.copy()

    # Type conversion
    if target_type == "float":
        s = s.astype(str).str.replace(",", "").str.strip()
        s = pd.to_numeric(s, errors="coerce")
    elif target_type == "integer":
        s = s.astype(str).str.replace(",", "").str.strip()
        s = pd.to_numeric(s, errors="coerce").astype("Int64")
    elif target_type == "string":
        s = s.astype(str).str.strip()
    elif target_type == "date":
        fmt = date_fmt or None
        s = pd.to_datetime(s, format=fmt, errors="coerce", infer_datetime_format=(fmt is None))
    elif target_type == "boolean":
        s = s.astype(str).str.strip().str.lower().isin({"true", "yes", "1", "y"})

    # Null handling
    if null_handling == "fill with 0":
        s = s.fillna(0)
    elif null_handling == "fill with empty string":
        s = s.fillna("")
    elif null_handling == "fill with value":
        s = s.fillna(fill_value)
    # "drop rows with null" is handled at the DataFrame level, not here

    return s


def build_filter_mask(
    df: pd.DataFrame,
    col: str,
    op: str,
    val: str,
) -> "pd.Series[bool]":
    """Return a boolean mask for one filter condition."""
    if col not in df.columns:
        return pd.Series([True] * len(df), index=df.index)

    series = df[col]

    if op == "is null":
        return series.isna() | (series.astype(str).str.strip() == "")
    if op == "is not null":
        return series.notna() & (series.astype(str).str.strip() != "")
    if op == "contains":
        return series.astype(str).str.contains(str(val), na=False, regex=False)
    if op == "not contains":
        return ~series.astype(str).str.contains(str(val), na=False, regex=False)

    # Comparison ops — try numeric first, fall back to string
    try:
        num_val = float(val)
        sn = pd.to_numeric(series, errors="coerce")
        mapping = {
            "==": sn == num_val, "!=": sn != num_val,
            ">":  sn > num_val,  ">=": sn >= num_val,
            "<":  sn < num_val,  "<=": sn <= num_val,
        }
        if op in mapping:
            return mapping[op]
    except (ValueError, TypeError):
        pass

    ss = series.astype(str)
    str_mapping = {"==": ss == val, "!=": ss != val}
    return str_mapping.get(op, pd.Series([True] * len(df), index=df.index))


def apply_step(df: pd.DataFrame, step: dict) -> pd.DataFrame:
    op = step["op"]

    if op == "rename":
        mapping = {k: v for k, v in step["mapping"].items() if k in df.columns and v.strip()}
        df = df.rename(columns=mapping)

    elif op == "drop":
        cols = [c for c in step["columns"] if c in df.columns]
        df = df.drop(columns=cols)

    elif op == "reorder":
        ordered = [c for c in step["columns"] if c in df.columns]
        rest = [c for c in df.columns if c not in ordered]
        df = df[ordered + rest]

    elif op == "filter":
        col, oper, val = step["column"], step["operator"], step["value"]
        if col in df.columns:
            series = df[col]
            try:
                num_val = float(val)
                sn = pd.to_numeric(series, errors="coerce")
                ops = {
                    "==": sn == num_val, "!=": sn != num_val,
                    ">":  sn > num_val,  ">=": sn >= num_val,
                    "<":  sn < num_val,  "<=": sn <= num_val,
                }
                if oper in ops:
                    df = df[ops[oper]]
                elif oper == "contains":        df = df[series.astype(str).str.contains(val, na=False)]
                elif oper == "not contains":    df = df[~series.astype(str).str.contains(val, na=False)]
                elif oper == "starts with":     df = df[series.astype(str).str.startswith(val, na=False)]
                elif oper == "ends with":       df = df[series.astype(str).str.endswith(val, na=False)]
            except (ValueError, TypeError):
                if oper == "==":                df = df[series.astype(str) == val]
                elif oper == "!=":              df = df[series.astype(str) != val]
                elif oper == "contains":        df = df[series.astype(str).str.contains(val, na=False)]
                elif oper == "not contains":    df = df[~series.astype(str).str.contains(val, na=False)]
                elif oper == "starts with":     df = df[series.astype(str).str.startswith(val, na=False)]
                elif oper == "ends with":       df = df[series.astype(str).str.endswith(val, na=False)]

    elif op == "cast":
        col, target = step["column"], step["target_type"]
        if col in df.columns:
            try:
                if target == "float":    df[col] = pd.to_numeric(df[col], errors="coerce")
                elif target == "integer":df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
                elif target == "string": df[col] = df[col].astype(str)
                elif target == "date":   df[col] = pd.to_datetime(df[col], infer_datetime_format=True, errors="coerce")
                elif target == "boolean":df[col] = df[col].map(
                    lambda x: str(x).strip().lower() in {"true", "yes", "1", "y"}
                )
            except Exception:
                pass

    elif op == "add_col":
        name, expr = step["name"], step["expression"]
        try:
            df[name] = df.eval(expr)
        except Exception as e:
            st.warning(f"add_col '{name}': {e}", icon="⚠️")

    elif op == "strip_whitespace":
        cols = step.get("columns") or list(df.select_dtypes(include="object").columns)
        for c in cols:
            if c in df.columns and df[c].dtype == object:
                df[c] = df[c].str.strip()

    elif op == "string_case":
        col, case = step["column"], step["case"]
        if col in df.columns:
            if case == "upper":  df[col] = df[col].str.upper()
            elif case == "lower":df[col] = df[col].str.lower()
            elif case == "title":df[col] = df[col].str.title()

    elif op == "fill_null":
        col, val = step["column"], step["value"]
        if col in df.columns:
            df[col] = df[col].fillna(val)

    elif op == "drop_null_rows":
        cols = step.get("columns")
        df = df.dropna(subset=cols if cols else None)

    elif op == "deduplicate":
        cols = step.get("columns") or None
        df = df.drop_duplicates(subset=cols)

    return df.reset_index(drop=True)


def replay_pipeline(original_df: pd.DataFrame, pipeline: list[dict]) -> pd.DataFrame:
    df = original_df.copy()
    for step in pipeline:
        df = apply_step(df, step)
    return df


def step_label(step: dict) -> str:
    op = step["op"]
    if op == "rename":
        pairs = ", ".join(f'{k}→{v}' for k, v in step["mapping"].items())
        return f"rename  {pairs}"
    if op == "drop":
        return f"drop    {', '.join(step['columns'])}"
    if op == "reorder":
        cols = step["columns"]
        return f"reorder [{', '.join(cols[:4])}{'...' if len(cols) > 4 else ''}]"
    if op == "filter":
        return f"filter  {step['column']} {step['operator']} {step['value']}"
    if op == "cast":
        return f"cast    {step['column']} → {step['target_type']}"
    if op == "add_col":
        return f"add_col {step['name']} = {step['expression']}"
    if op == "strip_whitespace":
        return "strip whitespace"
    if op == "string_case":
        return f"case    {step['column']} → {step['case']}"
    if op == "fill_null":
        return f"fill_null {step['column']} → '{step['value']}'"
    if op == "drop_null_rows":
        return "drop null rows"
    if op == "deduplicate":
        return "deduplicate"
    return op
