# pages/categories.py
from __future__ import annotations

import pandas as pd
import streamlit as st


def render(*, df_all: pd.DataFrame, currency):
    st.subheader("Categories")
    st.caption("Placeholder (rule editing + review).")

    exp = df_all[df_all["debit"] < 0].copy()
    if exp.empty:
        st.info("No expenses found (expected debit < 0).")
        return

    cat = (
        exp.groupby("category", as_index=False)
        .agg(spent=("debit", "sum"), txns=("debit", "count"))
        .sort_values("spent")
    )
    cat["spent"] = cat["spent"].map(currency)
    st.dataframe(cat, width="stretch", hide_index=True)
