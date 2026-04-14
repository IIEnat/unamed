# views/categories.py
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st


INSTANCE_DIR = Path("instance")
CATEGORIES_JSON = INSTANCE_DIR / "categories.json"
DATA_CSV = INSTANCE_DIR / "categorised.csv"


# -----------------------------
# Normalisation (match your categoriser)
# -----------------------------
def normalise_text(s: str) -> str:
    s = "" if s is None else str(s)
    s = s.strip().lower()
    return re.sub(r"\s+", " ", s)


def load_categories(path: Path) -> dict:
    if not path.exists():
        return {"keywords": {}, "exact": {}}

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and ("keywords" in data or "exact" in data):
        kw = data.get("keywords", {}) or {}
        ex = data.get("exact", {}) or {}
        return {
            "keywords": {normalise_text(k): normalise_text(v) for k, v in kw.items()},
            "exact": {normalise_text(k): normalise_text(v) for k, v in ex.items()},
        }

    flat = {normalise_text(k): normalise_text(v) for k, v in (data or {}).items()}
    return {"keywords": flat, "exact": {}}


def save_categories(path: Path, categories: dict) -> None:
    keywords = categories.get("keywords", {}) or {}
    exact = categories.get("exact", {}) or {}

    ordered = {
        "keywords": dict(sorted(keywords.items(), key=lambda kv: (kv[1], kv[0]))),
        "exact": dict(sorted(exact.items(), key=lambda kv: (kv[1], kv[0]))),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)


# -----------------------------
# Apply rules to categorised.csv (Part 2)
# -----------------------------
def apply_rules_to_df(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    exact = rules.get("exact", {}) or {}
    keywords = rules.get("keywords", {}) or {}
    kw_items = sorted(keywords.items(), key=lambda kv: len(kv[0]), reverse=True)

    def classify(narr: str, current_cat: str) -> str:
        text = normalise_text(narr)
        if text in exact:
            return exact[text]
        for k, v in kw_items:
            if k and k in text:
                return v
        return current_cat

    out = df.copy()
    out["category"] = [
        classify(n, c) for n, c in zip(out["narration"].astype(str), out["category"].astype(str))
    ]
    return out


# -----------------------------
# Table conversions
# -----------------------------
def dict_to_df(d: dict[str, str], left_name: str) -> pd.DataFrame:
    if not d:
        return pd.DataFrame({left_name: pd.Series(dtype="string"), "category": pd.Series(dtype="string")})
    return pd.DataFrame([(k, v) for k, v in d.items()], columns=[left_name, "category"])


def df_to_dict(df: pd.DataFrame, left_name: str) -> dict[str, str]:
    """
    Converts editor df -> dict, applying normalisation + dropping blanks.
    If duplicates exist after normalisation, last row wins.
    """
    if df is None or df.empty:
        return {}

    out: dict[str, str] = {}
    for _, r in df.iterrows():
        k = normalise_text(r.get(left_name, ""))
        v = normalise_text(r.get("category", ""))
        if not k or not v:
            continue
        out[k] = v
    return out


def render(*, df_all: pd.DataFrame, currency):
    rules = load_categories(CATEGORIES_JSON)

    # Initialise draft tables once
    if "kw_table" not in st.session_state:
        st.session_state.kw_table = dict_to_df(rules.get("keywords", {}), "keyword")
    if "ex_table" not in st.session_state:
        st.session_state.ex_table = dict_to_df(rules.get("exact", {}), "narration")

    st.subheader("Keywords")
    st.caption("Matches if the keyword appears anywhere in the narration. Longest keyword wins.")
    kw_df = st.data_editor(
        st.session_state.kw_table,
        num_rows="dynamic",
        width='stretch',
        hide_index=True,
        column_config={
            "keyword": st.column_config.TextColumn("keyword", width="large"),
            "category": st.column_config.TextColumn("category", width="medium"),
        },
        key="kw_editor",
    )

    st.subheader("Exact")
    st.caption("Matches only if the full normalised narration is identical.")
    ex_df = st.data_editor(
        st.session_state.ex_table,
        num_rows="dynamic",
        width='stretch',
        hide_index=True,
        column_config={
            "narration": st.column_config.TextColumn("narration", width="large"),
            "category": st.column_config.TextColumn("category", width="medium"),
        },
        key="ex_editor",
    )

    st.divider()

    if st.button("Save changes", type="primary", width='stretch'):
        # Convert tables -> rules dict (normalised)
        new_rules = {
            "keywords": df_to_dict(kw_df, "keyword"),
            "exact": df_to_dict(ex_df, "narration"),
        }

        # Part 1: write JSON
        try:
            save_categories(CATEGORIES_JSON, new_rules)
        except Exception as e:
            st.error(f"Failed to write categories.json: {e}")
            st.stop()

        # Part 2: update categorised.csv
        if not DATA_CSV.exists():
            st.warning("Saved categories.json, but categorised.csv not found — data not updated.")
            st.cache_data.clear()
            st.rerun()
            return

        try:
            df_disk = pd.read_csv(DATA_CSV)
            required = {"date", "account", "narration", "debit", "credit", "balance", "category"}
            missing = required - set(df_disk.columns)
            if missing:
                st.error(f"categorised.csv missing columns: {sorted(missing)}")
                st.stop()

            df_updated = apply_rules_to_df(df_disk, new_rules)

            # Keep date output as YYYY-MM-DD strings
            try:
                dt = pd.to_datetime(df_updated["date"], errors="coerce")
                if dt.notna().any():
                    df_updated["date"] = dt.dt.strftime("%Y-%m-%d")
            except Exception:
                pass

            df_updated.to_csv(DATA_CSV, index=False)
        except Exception as e:
            st.error(f"Failed to update categorised.csv: {e}")
            st.stop()

        # Update session tables from what we actually saved (canonical order)
        st.session_state.kw_table = dict_to_df(new_rules["keywords"], "keyword")
        st.session_state.ex_table = dict_to_df(new_rules["exact"], "narration")

        st.success("Saved categories.json and updated categorised.csv")
        st.cache_data.clear()
        st.rerun()
