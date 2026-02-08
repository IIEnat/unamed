# app.py
from __future__ import annotations

from pathlib import Path
import pandas as pd
import streamlit as st

from views.dashboard import render as render_dashboard
from views.categories import render as render_categories

DATA_PATH = Path("instance") / "categorised.csv"


@st.cache_data(show_spinner=False)
def load_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path.resolve()}")

    df = pd.read_csv(path)

    required = {"date", "account", "narration", "debit", "credit", "balance", "category"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"categorised.csv missing columns: {sorted(missing)}. Found: {list(df.columns)}"
        )

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    for c in ["debit", "credit", "balance"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    for c in ["account", "narration", "category"]:
        df[c] = df[c].astype(str).fillna("").str.strip()

    df = df[df["date"].notna()].copy()

    # Assumption: expenses (debit) are already NEGATIVE.
    df["debit"] = df["debit"].fillna(0.0)
    df["credit"] = df["credit"].fillna(0.0)
    df["amount"] = df["credit"] + df["debit"]

    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    return df


def currency(x: float) -> str:
    if pd.isna(x):
        return "—"
    return f"${x:,.2f}"


st.set_page_config(page_title="Finance Tracker", layout="wide")

# Sidebar = router
page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Categories"],
)

# Load data once here, pass to pages
try:
    df_all = load_data(DATA_PATH)
except Exception as e:
    st.error(str(e))
    st.stop()

if page == "Dashboard":
    render_dashboard(df_all=df_all, currency=currency)
elif page == "Categories":
    render_categories(df_all=df_all, currency=currency)
