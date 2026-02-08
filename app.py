# app.py
# Run: streamlit run app.py
from __future__ import annotations

from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from streamlit_plotly_events2 import plotly_events
import plotly.express as px


DATA_PATH = Path("instance") / "categorised.csv"


# -----------------------------
# Data loading / normalisation
# -----------------------------
@st.cache_data(show_spinner=False)
def load_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path.resolve()}")

    df = pd.read_csv(path)

    required = {"date", "account", "narration", "debit", "credit", "balance", "category"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"categorised.csv missing columns: {sorted(missing)}. Found: {list(df.columns)}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    for c in ["debit", "credit", "balance"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    for c in ["account", "narration", "category"]:
        df[c] = df[c].astype(str).fillna("").str.strip()

    df = df[df["date"].notna()].copy()

    # Assumption per your message: expenses (debit) are already NEGATIVE.
    # So signed amount per txn is credit + debit.
    df["debit"] = df["debit"].fillna(0.0)   # negative numbers
    df["credit"] = df["credit"].fillna(0.0) # positive numbers
    df["amount"] = df["credit"] + df["debit"]

    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    return df


def currency(x: float) -> str:
    if pd.isna(x):
        return "—"
    return f"${x:,.2f}"


# -----------------------------
# Aggregations
# -----------------------------
def make_monthly_series(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("month", as_index=False).agg(
        income=("credit", "sum"),       # positive
        expenses=("debit", "sum"),      # negative
        net=("amount", "sum"),          # income + expenses
        txns=("amount", "count"),
    )
    return g.sort_values("month")

def make_monthly_networth(df: pd.DataFrame) -> pd.DataFrame:
    # monthly income/expenses/net (your sign convention: expenses are negative)
    monthly = df.groupby("month", as_index=False).agg(
        income=("credit", "sum"),
        expenses=("debit", "sum"),   # negative
        net=("amount", "sum"),       # income + expenses
        txns=("amount", "count"),
    )

    # networth = sum of last balance per account each month
    b = df.dropna(subset=["balance"]).copy()
    if b.empty:
        monthly["networth"] = pd.NA
        return monthly.sort_values("month")

    b = b.sort_values(["account", "date"])
    last_per_acct_month = b.groupby(["month", "account"], as_index=False).tail(1)
    networth = last_per_acct_month.groupby("month", as_index=False).agg(
        networth=("balance", "sum")
    )

    out = monthly.merge(networth, on="month", how="left").sort_values("month")
    return out



# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Finance Tracker", layout="wide")

# Sidebar stays (nav only for now)
page = st.sidebar.radio("Navigation", ["Dashboard", "Transactions (placeholder)", "Categories (placeholder)"])

# Load data
try:
    df_all = load_data(DATA_PATH)
except Exception as e:
    st.error(str(e))
    st.stop()

# --- Dashboard page (replace your current month selector block) ---

if page == "Dashboard":
    if df_all.empty:
        st.warning("No transactions found.")
        st.stop()

    monthly = make_monthly_series(df_all)

    # ✅ Remove dashboard month filter + normalise month display everywhere
    # Use most recent month as the "focus" month for the stats panel.
    focus_month = monthly["month"].max()
    focus_month_label = focus_month.strftime("%b %Y")  # e.g., "Jan 2024"

    df_month = df_all[df_all["month"] == focus_month].copy()

    # Focus month metrics
    income_m = float(df_month["credit"].sum())
    expenses_m = float(df_month["debit"].sum())   # negative
    net_m = float(df_month["amount"].sum())
    txns_m = int(df_month.shape[0])

    # Average monthly stats (across whole dataset)
    avg_income = float(monthly["income"].mean()) if not monthly.empty else 0.0
    avg_expenses = float(monthly["expenses"].mean()) if not monthly.empty else 0.0  # negative
    avg_net = float(monthly["net"].mean()) if not monthly.empty else 0.0
    avg_txns = float(monthly["txns"].mean()) if not monthly.empty else 0.0

    # ---- Focus month (shared state for chart + stats) ----
    month_labels = monthly["month"].dt.strftime("%b %Y").tolist()

    if "month_idx" not in st.session_state:
        st.session_state.month_idx = len(month_labels) - 1

    st.session_state.month_idx = max(
        0, min(st.session_state.month_idx, len(month_labels) - 1)
    )

    def prev_month():
        if st.session_state.month_idx > 0:
            st.session_state.month_idx -= 1

    def next_month():
        if st.session_state.month_idx < len(month_labels) - 1:
            st.session_state.month_idx += 1

    # Current focus month (GLOBAL for this page)
    sel_month_label = month_labels[st.session_state.month_idx]
    sel_month = pd.to_datetime(sel_month_label, format="%b %Y")


    left, right = st.columns([2.2, 1])

    
    with left:
        st.subheader("Net worth over time")

        # -------------------------
        # Net worth time series
        # -------------------------
        monthly_nw = make_monthly_networth(df_all).sort_values("month").copy()
        monthly_nw["x_label"] = monthly_nw["month"].dt.strftime("%b %Y")
        monthly_nw["x_pos"] = range(len(monthly_nw))

        fig_nw = go.Figure()

        fig_nw.add_trace(
            go.Scatter(
                x=monthly_nw["x_pos"],
                y=monthly_nw["networth"],
                mode="lines+markers",
                fill="tozeroy",
                customdata=monthly_nw[["income", "expenses", "net", "x_label"]].to_numpy(),
                hovertemplate=(
                    "<b>%{customdata[3]}</b><br>"
                    "Net worth: %{y:,.2f}<br>"
                    "Income: %{customdata[0]:,.2f}<br>"
                    "Expenses: %{customdata[1]:,.2f}<br>"
                    "Net: %{customdata[2]:,.2f}<br>"
                    "<extra></extra>"
                ),
            )
        )

        # Highlight focused month
        focus_label = sel_month.strftime("%b %Y")
        focus_idx = monthly_nw.index[monthly_nw["x_label"] == focus_label]
        if len(focus_idx) > 0:
            i = int(focus_idx[0])
            fig_nw.add_vrect(
                x0=i - 0.5,
                x1=i + 0.5,
                fillcolor="rgba(80, 120, 255, 0.15)",
                line_width=0,
                layer="below",
            )

        fig_nw.update_layout(
            height=200,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(
                tickmode="array",
                tickvals=monthly_nw["x_pos"].tolist(),
                ticktext=monthly_nw["x_label"].tolist(),
                tickangle=-30,
            ),
            yaxis=dict(title="Net worth", fixedrange=True),
            dragmode="pan",
            showlegend=False,
        )

        st.plotly_chart(fig_nw, width="stretch")

        # -------------------------
        # Category breakdown + dropdown-to-filter tables (pie + dedicated side legend)
        # -------------------------
        st.subheader("Category breakdown")

        # persistent (does NOT reset on month change)
        if "selected_expense_category" not in st.session_state:
            st.session_state.selected_expense_category = None
        if "selected_income_category" not in st.session_state:
            st.session_state.selected_income_category = None

        df_focus = df_all[df_all["month"] == sel_month].copy()

        # Expenses (negative debit)
        exp = df_focus[df_focus["debit"] < 0].copy()
        exp_g = (
            exp.groupby("category", as_index=False)
            .agg(amount=("debit", "sum"))
            .assign(amount=lambda d: d["amount"].abs())
            .sort_values("amount", ascending=False)
        )
        exp_g["amount"] = pd.to_numeric(exp_g["amount"], errors="coerce").fillna(0.0).astype(float)
        exp_g = exp_g[exp_g["amount"] > 0].copy()
        exp_total = float(exp_g["amount"].sum()) if not exp_g.empty else 0.0
        exp_g["pct"] = (exp_g["amount"] / exp_total) if exp_total > 0 else 0.0

        # Income (positive credit)
        inc = df_focus[df_focus["credit"] > 0].copy()
        inc_g = (
            inc.groupby("category", as_index=False)
            .agg(amount=("credit", "sum"))
            .sort_values("amount", ascending=False)
        )
        inc_g["amount"] = pd.to_numeric(inc_g["amount"], errors="coerce").fillna(0.0).astype(float)
        inc_g = inc_g[inc_g["amount"] > 0].copy()
        inc_total = float(inc_g["amount"].sum()) if not inc_g.empty else 0.0
        inc_g["pct"] = (inc_g["amount"] / inc_total) if inc_total > 0 else 0.0

        # fixed sizing
        PIE_H = 380
        palette = px.colors.qualitative.Plotly

        def _simple_legend(categories, palette, max_height_px=260):
            rows = []

            for i, cat in enumerate(categories):
                col = palette[i % len(palette)]

                rows.append(
                    "<div style='display:flex;align-items:center;gap:5px;padding:0;'>"
                    f"<span style='width:12px;height:12px;border-radius:3px;background:{col};display:inline-block;'></span>"
                    f"<span style='white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>{cat}</span>"
                    "</div>"
                )

            st.markdown(
                "<div style='border:1px solid rgba(0,0,0,0.10);border-radius:12px;padding:8px 10px;"
                f"max-height:{max_height_px}px;overflow:auto;background:rgba(255,255,255,0.65);'>"
                + "".join(rows)
                + "</div>",
                unsafe_allow_html=True,
            )


        c1, c2 = st.columns(2)

        # -------------------------
        # Expenses pie + legend + dropdown + transactions table
        # -------------------------
        with c1:
            st.caption("Expenses")

            if exp_g.empty:
                st.info("No expenses this month.")
            else:
                pie_col, leg_col = st.columns([3, 1], gap="small")

                with pie_col:
                    fig_exp = go.Figure(
                        data=[
                            go.Pie(
                                labels=exp_g["category"],
                                values=exp_g["amount"],
                                hole=0.45,
                                domain=dict(x=[0.0, 1.0], y=[0.0, 1.0]),
                                marker=dict(colors=[palette[i % len(palette)] for i in range(len(exp_g))]),
                                textinfo="percent",
                                textposition="inside",
                                insidetextorientation="radial",
                                sort=False,
                                hovertemplate="<b>%{label}</b><br>%{value:,.2f}<extra></extra>",
                            )
                        ]
                    )
                    fig_exp.update_layout(
                        template="plotly",
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        height=PIE_H,
                        margin=dict(l=10, r=10, t=10, b=10),
                        showlegend=False,  # legend is external
                    )
                    st.plotly_chart(fig_exp, width="stretch")

                with leg_col:
                    _simple_legend(exp_g["category"].tolist(), palette, max_height_px=PIE_H - 20)

                # dropdown options with amount + %
                exp_opts = exp_g.copy()
                exp_opts["label"] = exp_opts.apply(
                    lambda r: f"{r['category']} — {currency(float(r['amount']))} ({float(r['pct']) * 100:.1f}%)",
                    axis=1,
                )
                exp_choices = exp_opts["label"].tolist()
                exp_label_to_cat = dict(zip(exp_opts["label"], exp_opts["category"]))

                # keep selection stable; allow "None" = hidden table
                exp_default = None
                if st.session_state.selected_expense_category is not None:
                    m = exp_opts.loc[exp_opts["category"] == st.session_state.selected_expense_category, "label"]
                    exp_default = m.iloc[0] if not m.empty else None

                picked_exp = st.selectbox(
                    "Expense category",
                    options=[None] + exp_choices,
                    index=0 if exp_default is None else ([None] + exp_choices).index(exp_default),
                    format_func=lambda x: "None" if x is None else x,
                    key="expense_category_select",
                )

                st.session_state.selected_expense_category = (
                    None if picked_exp is None else exp_label_to_cat[picked_exp]
                )

                sel_exp = st.session_state.selected_expense_category
                if sel_exp is not None:
                    exp_rows = exp[exp["category"] == sel_exp].sort_values("date", ascending=False)
                    if exp_rows.empty:
                        st.info("No matching expense transactions for this month/category.")
                    else:
                        st.dataframe(
                            exp_rows[["date", "account", "narration", "debit", "credit", "balance", "category"]]
                            .assign(
                                debit=lambda d: d["debit"].map(currency),
                                credit=lambda d: d["credit"].map(currency),
                                balance=lambda d: d["balance"].map(currency),
                            ),
                            width="stretch",
                            hide_index=True,
                        )

        # -------------------------
        # Income pie + legend + dropdown + transactions table
        # -------------------------
        with c2:
            st.caption("Income")

            if inc_g.empty:
                st.info("No income this month.")
            else:
                pie_col, leg_col = st.columns([3, 1], gap="small")

                with pie_col:
                    fig_inc = go.Figure(
                        data=[
                            go.Pie(
                                labels=inc_g["category"],
                                values=inc_g["amount"],
                                hole=0.45,
                                domain=dict(x=[0.0, 1.0], y=[0.0, 1.0]),
                                marker=dict(colors=[palette[i % len(palette)] for i in range(len(inc_g))]),
                                textinfo="percent",
                                textposition="inside",
                                insidetextorientation="radial",
                                sort=False,
                                hovertemplate="<b>%{label}</b><br>%{value:,.2f}<extra></extra>",
                            )
                        ]
                    )
                    fig_inc.update_layout(
                        template="plotly",
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        height=PIE_H,
                        margin=dict(l=10, r=10, t=10, b=10),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_inc, width="stretch")

                with leg_col:
                    _simple_legend(inc_g["category"].tolist(), palette, max_height_px=PIE_H - 20)

                inc_opts = inc_g.copy()
                inc_opts["label"] = inc_opts.apply(
                    lambda r: f"{r['category']} — {currency(float(r['amount']))} ({float(r['pct']) * 100:.1f}%)",
                    axis=1,
                )
                inc_choices = inc_opts["label"].tolist()
                inc_label_to_cat = dict(zip(inc_opts["label"], inc_opts["category"]))

                inc_default = None
                if st.session_state.selected_income_category is not None:
                    m = inc_opts.loc[inc_opts["category"] == st.session_state.selected_income_category, "label"]
                    inc_default = m.iloc[0] if not m.empty else None

                picked_inc = st.selectbox(
                    "Income category",
                    options=[None] + inc_choices,
                    index=0 if inc_default is None else ([None] + inc_choices).index(inc_default),
                    format_func=lambda x: "None" if x is None else x,
                    key="income_category_select",
                )

                st.session_state.selected_income_category = (
                    None if picked_inc is None else inc_label_to_cat[picked_inc]
                )

                sel_inc = st.session_state.selected_income_category
                if sel_inc is not None:
                    inc_rows = inc[inc["category"] == sel_inc].sort_values("date", ascending=False)
                    if inc_rows.empty:
                        st.info("No matching income transactions for this month/category.")
                    else:
                        st.dataframe(
                            inc_rows[["date", "account", "narration", "debit", "credit", "balance", "category"]]
                            .assign(
                                debit=lambda d: d["debit"].map(currency),
                                credit=lambda d: d["credit"].map(currency),
                                balance=lambda d: d["balance"].map(currency),
                            ),
                            width="stretch",
                            hide_index=True,
                        )

    with right:
        st.subheader("Monthly stats")

        # Month selection row (selector + prev/next buttons)
        month_labels = monthly["month"].dt.strftime("%b %Y").tolist()

        # single source of truth
        if "month_idx" not in st.session_state:
            st.session_state.month_idx = len(month_labels) - 1

        # clamp in case data changes
        st.session_state.month_idx = max(0, min(st.session_state.month_idx, len(month_labels) - 1))

        def prev_month():
            if st.session_state.month_idx > 0:
                st.session_state.month_idx -= 1

        def next_month():
            if st.session_state.month_idx < len(month_labels) - 1:
                st.session_state.month_idx += 1

        # ---- Month selector UI ----
        m1, m2, m3 = st.columns([8, 1, 1])

        with m1:
            picked = st.selectbox(
                "Focus month",
                month_labels,
                index=st.session_state.month_idx,
                key=f"focus_month_select_{st.session_state.month_idx}",
            )

            picked_idx = month_labels.index(picked)
            if picked_idx != st.session_state.month_idx:
                st.session_state.month_idx = picked_idx
                st.rerun()

        with m2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("‹", disabled=(st.session_state.month_idx == 0), use_container_width=True):
                prev_month()
                st.rerun()

        with m3:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("›", disabled=(st.session_state.month_idx == len(month_labels) - 1), use_container_width=True):
                next_month()
                st.rerun()
        
        df_month = df_all[df_all["month"] == sel_month].copy()

        # Focus month metrics
        income_m = float(df_month["credit"].sum())
        expenses_m = float(df_month["debit"].sum())   # negative
        net_m = float(df_month["amount"].sum())
        txns_m = int(df_month.shape[0])

        # Average monthly stats (across whole dataset)
        avg_income = float(monthly["income"].mean()) if not monthly.empty else 0.0
        avg_expenses = float(monthly["expenses"].mean()) if not monthly.empty else 0.0  # negative
        avg_net = float(monthly["net"].mean()) if not monthly.empty else 0.0
        avg_txns = float(monthly["txns"].mean()) if not monthly.empty else 0.0

        r1, r2 = st.columns(2)
        r1.metric("Net", currency(net_m))
        r2.metric("Transactions", f"{txns_m:,}")

        r3, r4 = st.columns(2)
        r3.metric("Income", currency(income_m))
        r4.metric("Expenses", currency(expenses_m))

        st.divider()

        st.markdown("**Averages (per month)**")
        a1, a2 = st.columns(2)
        a1.metric("Avg net", currency(avg_net))
        a2.metric("Avg txns", f"{avg_txns:,.1f}")

        a3, a4 = st.columns(2)
        a3.metric("Avg income", currency(avg_income))
        a4.metric("Avg expenses", currency(avg_expenses))

        st.divider()
        st.markdown("**This month vs avg**")
        compare = pd.DataFrame(
            {
                "Metric": ["Income", "Expenses", "Net", "Txns"],
                "This month": [income_m, expenses_m, net_m, txns_m],
                "Avg / month": [avg_income, avg_expenses, avg_net, avg_txns],
            }
        )
        compare["This month"] = compare["This month"].map(lambda v: currency(v) if isinstance(v, (int, float)) else v)
        compare["Avg / month"] = compare["Avg / month"].map(lambda v: currency(v) if isinstance(v, (int, float)) else v)
        st.dataframe(compare, width="stretch", hide_index=True)

elif page == "Transactions (placeholder)":
    st.subheader("Transactions")
    st.caption("Placeholder (filters/search will live here).")
    st.write(f"Rows: **{len(df_all):,}**")
    st.dataframe(df_all.sort_values("date", ascending=False).head(200), width="stretch", hide_index=True)

elif page == "Categories (placeholder)":
    st.subheader("Categories")
    st.caption("Placeholder (rule editing + review).")
    exp = df_all[df_all["debit"] < 0].copy()
    if exp.empty:
        st.info("No expenses found (expected debit < 0).")
    else:
        cat = exp.groupby("category", as_index=False).agg(
            spent=("debit", "sum"),
            txns=("debit", "count"),
        ).sort_values("spent")  # most negative at top
        cat["spent"] = cat["spent"].map(currency)
        st.dataframe(cat, width="stretch", hide_index=True)
