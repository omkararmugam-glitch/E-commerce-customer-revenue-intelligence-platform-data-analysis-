from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.dashboard.client import API_URL, ApiError, get  # noqa: E402

PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
BLUE, ORANGE, TEAL, AMBER, MAGENTA = PALETTE[:5]
MUTED = "#9FB2CC"

st.set_page_config(page_title="Olist Intelligence", page_icon="📊", layout="wide")

st.markdown(f"""
<style>
.block-container {{padding-top: 1.6rem; padding-bottom: 2rem;}}
.hero {{background: linear-gradient(120deg, #102A4F 0%, #1E4FA8 100%); border-radius: 14px;
        padding: 1.3rem 1.6rem; margin-bottom: 1.1rem; border: 1px solid #22385E;}}
.hero h1 {{color: #FFFFFF; font-size: 1.75rem; margin: 0 0 .25rem 0; font-weight: 700;}}
.hero p {{color: #C9D6EA; margin: 0; font-size: .92rem;}}
div[data-testid="stMetric"] {{background: #13233F; border-radius: 12px; padding: .8rem 1rem;
        border: 1px solid #22385E; border-left: 4px solid var(--accent, {BLUE});}}
div[data-testid="stMetricValue"] {{color: #FFFFFF;}}
div[data-testid="stMetricLabel"] p {{color: {MUTED}; font-weight: 600;}}
div[data-testid="stColumn"]:nth-of-type(4n+1) div[data-testid="stMetric"] {{--accent: {BLUE};}}
div[data-testid="stColumn"]:nth-of-type(4n+2) div[data-testid="stMetric"] {{--accent: {TEAL};}}
div[data-testid="stColumn"]:nth-of-type(4n+3) div[data-testid="stMetric"] {{--accent: {AMBER};}}
div[data-testid="stColumn"]:nth-of-type(4n+4) div[data-testid="stMetric"] {{--accent: {MAGENTA};}}
div[class*="st-key-fbar_"] {{background: linear-gradient(180deg, #13233F 0%, #102A4F 100%);
        border: 1px solid #2D4570; border-radius: 14px; padding: .55rem .9rem .35rem .9rem;
        margin-bottom: .6rem;}}
div[class*="st-key-fbar_"] label p {{color: {MUTED}; font-weight: 600; font-size: .82rem;}}
.fbar-title {{color: #FFFFFF; font-weight: 700; font-size: .92rem; margin: .1rem 0 .15rem 0;}}
.active {{color: {MUTED}; font-size: .8rem; margin: -.2rem 0 .4rem .1rem;}}
.active b {{color: #E6EDF7;}}
.caveat {{color: {MUTED}; font-size: .85rem;}}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=600, show_spinner=False)
def api(path: str, **params):
    return get(path, **params)


def brl(x: float) -> str:
    if abs(x) >= 1e6:
        return f"R${x / 1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"R${x / 1e3:,.1f}K"
    return f"R${x:,.2f}"


def count(x: float) -> str:
    return f"{x / 1e3:,.1f}K" if x >= 1e4 else f"{x:,.0f}"


def pretty(value) -> str:
    return str(value).replace("_", " ").title() if isinstance(value, str) and "_" in value else str(value)


def chart(c: alt.Chart, height: int = 320):
    st.altair_chart(c.properties(height=height), width="stretch")


def hbar(df: pd.DataFrame, y: str, x: str, x_title: str, color: str = BLUE, fmt: str = "~s"):
    base = alt.Chart(df).encode(
        y=alt.Y(f"{y}:N", sort="-x", title=None),
        x=alt.X(f"{x}:Q", title=x_title, axis=alt.Axis(format=fmt),
                scale=alt.Scale(domain=[0, float(df[x].max()) * 1.15])),
        tooltip=[alt.Tooltip(f"{y}:N"), alt.Tooltip(f"{x}:Q", format=",.2f")],
    )
    return base.mark_bar(color=color, cornerRadiusEnd=4) + base.mark_text(
        align="left", dx=4, color=MUTED, fontSize=11).encode(text=alt.Text(f"{x}:Q", format=".3~s"))


def empty(msg: str = "Nothing matches these filters — widen or clear them."):
    st.info(msg, icon="🔎")


# ---------------------------------------------------------------- filter bars

ALL_DEFAULTS: dict[str, object] = {}


def _reset(keys: dict) -> None:
    for k, v in keys.items():
        st.session_state[k] = v


def _reset_all() -> None:
    _reset(ALL_DEFAULTS)


def filter_bar(name: str, defaults: dict, widths: list[float]):
    """A Power BI-style slicer bar: title, a row of filter columns, and a Clear button."""
    ALL_DEFAULTS.update(defaults)
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)
    box = st.container(key=f"fbar_{name}")
    head, button = box.columns([6, 1], vertical_alignment="center")
    head.markdown("<div class='fbar-title'>🔎 Filters</div>", unsafe_allow_html=True)
    button.button("Clear", key=f"clear_{name}", on_click=_reset, args=(defaults,),
                  icon=":material/filter_alt_off:", width="stretch")
    return box.columns(widths)


def active_summary(parts: dict) -> None:
    shown = [f"<b>{label}:</b> {', '.join(map(pretty, vals)) if isinstance(vals, (list, tuple)) else vals}"
             for label, vals in parts.items() if vals]
    text = " · ".join(shown) if shown else "No filters — showing everything."
    st.markdown(f"<div class='active'>{text}</div>", unsafe_allow_html=True)


def multi(col, label: str, options: list, key: str, **kw):
    return col.multiselect(label, options, key=key, placeholder="All", format_func=pretty, **kw)


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.markdown("### 📊 Olist Intelligence")
    try:
        health = api("/health")
        opts = api("/filters")
    except ApiError as exc:
        st.error(f"{exc}.\n\nStart it with:\n\n`python -m uvicorn app.api.main:app --port 8000`")
        st.stop()
    st.success(f"API connected · {health['orders']:,} orders", icon="🟢")
    st.markdown("<div class='caveat'>Every section has its own filter bar, like the pages of the "
                "Power BI dashboard. Leave a filter empty to include everything.</div>",
                unsafe_allow_html=True)
    st.button("Clear all filters", icon=":material/restart_alt:", width="stretch", on_click=_reset_all)
    st.divider()
    st.markdown(
        "<div class='caveat'><b>Scope</b><br>Delivered orders, Jan 2017 – Aug 2018. "
        "Revenue = item price, excluding freight.<br><br><b>Not in the data:</b> cost (no margin), "
        "marketing channels (no attribution), experiments (tests are observational).</div>",
        unsafe_allow_html=True)
    st.markdown(f"<div class='caveat'><br>API: <a href='{API_URL}/docs'>{API_URL}/docs</a></div>",
                unsafe_allow_html=True)

DATE_MIN, DATE_MAX = date.fromisoformat(opts["date_min"]), date.fromisoformat(opts["date_max"])

st.markdown("""
<div class="hero">
  <h1>E-Commerce Customer & Revenue Intelligence</h1>
  <p>Olist Brazilian marketplace · 96,211 delivered orders · 93,104 customers · Jan 2017 – Aug 2018</p>
</div>""", unsafe_allow_html=True)

tabs = st.tabs(["📊 Overview", "👥 Customers", "📦 Products", "📣 Marketing",
                "🧪 Experiments", "📈 Forecast", "💡 Recommendations"])

# ---------------------------------------------------------------- overview
with tabs[0]:
    c = filter_bar("overview", {"ov_year": [], "ov_dates": (DATE_MIN, DATE_MAX), "ov_state": [],
                                "ov_payment": []}, [1, 1.7, 1.4, 1.4])
    years = multi(c[0], "Year", opts["years"], "ov_year")
    dates = c[1].date_input("Order date", min_value=DATE_MIN, max_value=DATE_MAX, key="ov_dates",
                            format="DD/MM/YYYY")
    states = multi(c[2], "Customer state", opts["states"], "ov_state")
    payments = multi(c[3], "Payment method", opts["payments"], "ov_payment")
    d_from, d_to = (dates if isinstance(dates, tuple) and len(dates) == 2 else (DATE_MIN, DATE_MAX))
    date_active = (d_from, d_to) != (DATE_MIN, DATE_MAX)
    f = {"year": years, "state": states, "payment": payments,
         "date_from": d_from.isoformat() if date_active else None,
         "date_to": d_to.isoformat() if date_active else None}
    active_summary({"Year": years, "Dates": f"{d_from:%d %b %Y} – {d_to:%d %b %Y}" if date_active else None,
                    "State": states, "Payment": payments})

    k = api("/kpis", **f)
    if not k:
        empty()
    else:
        m = st.columns(4)
        m[0].metric("Total revenue", brl(k["revenue"]))
        m[1].metric("Orders", count(k["orders"]))
        m[2].metric("Customers", count(k["customers"]))
        m[3].metric("Median order value", brl(k["aov_median"]),
                    help="Order value is heavily skewed, so the median is the typical order.")
        m = st.columns(4)
        m[0].metric("Mean order value", brl(k["aov_mean"]))
        m[1].metric("Late delivery rate", f"{k['late_rate']:.1%}")
        m[2].metric("Average review", f"{k['avg_review']:.2f} ★" if k["avg_review"] else "–")
        m[3].metric("One-star rate", f"{k['one_star_rate']:.1%}" if k["one_star_rate"] is not None else "–")

        st.markdown("##### Monthly revenue")
        mon = pd.DataFrame(api("/revenue/monthly", **f))
        if mon.empty:
            empty("No complete months in this selection.")
        else:
            line = alt.Chart(mon).encode(
                x=alt.X("month:O", title=None, axis=alt.Axis(labelAngle=-45)),
                y=alt.Y("revenue:Q", title=None, axis=alt.Axis(format="~s")),
                tooltip=["month", alt.Tooltip("revenue:Q", format=",.0f"), alt.Tooltip("orders:Q", format=","),
                         alt.Tooltip("mom_pct:Q", format="+.1f", title="MoM %")])
            chart(line.mark_area(color=BLUE, opacity=0.25, line={"color": BLUE, "strokeWidth": 3})
                  + line.mark_point(color=BLUE, filled=True, size=45), 300)
            st.caption("August 2018 covers 1–23 August only: the data export thins out after that, "
                       "so it is flagged as a partial month and has no MoM change.")

        left, right = st.columns(2)
        with left:
            st.markdown("##### Revenue by category")
            cat = pd.DataFrame(api("/revenue/by-category", limit=12, **f))
            if cat.empty:
                empty()
            else:
                chart(hbar(cat, "category", "revenue", "Revenue (R$)"), 380)
        with right:
            st.markdown("##### Revenue by customer state")
            s = pd.DataFrame(api("/revenue/by-state", **f)).head(12)
            if s.empty:
                empty()
            else:
                chart(hbar(s, "state", "revenue", "Revenue (R$)", color=TEAL), 380)

# ---------------------------------------------------------------- customers
with tabs[1]:
    c = filter_bar("customers", {"cu_rfm": [], "cu_kmeans": [], "cu_state": [], "cu_risk": []}, [1, 1, 1, 1])
    cf = {"rfm": multi(c[0], "RFM segment", opts["rfm_segments"], "cu_rfm"),
          "kmeans": multi(c[1], "K-Means segment", opts["kmeans_segments"], "cu_kmeans"),
          "state": multi(c[2], "Customer state", opts["states"], "cu_state"),
          "risk": multi(c[3], "Risk tier", opts["risk_tiers"], "cu_risk")}
    active_summary({"RFM": cf["rfm"], "K-Means": cf["kmeans"], "State": cf["state"], "Risk": cf["risk"]})

    summary = api("/customers/summary", **cf)
    if not summary:
        empty()
    else:
        m = st.columns(4)
        m[0].metric("Customers", count(summary["customers"]))
        m[1].metric("Repeat purchase rate", f"{summary['repeat_rate']:.1%}")
        m[2].metric("Repeat customers", f"{summary['repeat_customers']:,}")
        m[3].metric("Average customer value", brl(summary["avg_value"]))
        st.markdown("<div class='caveat'>97% of customers buy exactly once — this is an acquisition "
                    "business, not a retention business. Every chart below, including the retention "
                    "curve and cohorts, is recomputed for the customers you select.</div>",
                    unsafe_allow_html=True)

        method = st.segmented_control("Group by", ["RFM", "K-Means"], default="RFM", key="cu_method")
        seg = pd.DataFrame(api("/customers/segments", by="kmeans" if method == "K-Means" else "rfm", **cf))
        shares = seg.melt(id_vars="segment", value_vars=["customer_pct", "revenue_pct"],
                          var_name="measure", value_name="pct")
        shares["measure"] = shares["measure"].map({"customer_pct": "% of customers", "revenue_pct": "% of revenue"})
        chart(alt.Chart(shares).mark_bar(cornerRadiusEnd=4).encode(
            y=alt.Y("segment:N", sort=seg["segment"].tolist(), title=None),
            x=alt.X("pct:Q", title="Share (%)"), yOffset="measure:N",
            color=alt.Color("measure:N", scale=alt.Scale(range=[MUTED, BLUE]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["segment", "measure", alt.Tooltip("pct:Q", format=".2f")]), max(160, 55 * len(seg)))

        left, right = st.columns(2)
        with left:
            st.markdown("##### Retention curve")
            r = pd.DataFrame(api("/customers/retention", **cf))
            if r.empty:
                empty("None of these customers ordered again.")
            else:
                chart(alt.Chart(r).mark_area(color=TEAL, opacity=0.3, line={"color": TEAL, "strokeWidth": 3}).encode(
                    x=alt.X("month:Q", title="Months since first purchase"),
                    y=alt.Y("retention_pct:Q", title="% of cohort ordering again"),
                    tooltip=["month", alt.Tooltip("retention_pct:Q", format=".2f"), "cohorts"]), 280)
        with right:
            st.markdown("##### 3-month repeat rate by cohort")
            co = pd.DataFrame(api("/customers/cohorts", **cf)).dropna(subset=["repeat_rate_3mo_pct"])
            if co.empty:
                empty("No cohorts with 3 months of history in this selection.")
            else:
                chart(alt.Chart(co).mark_bar(color=AMBER, cornerRadiusEnd=3).encode(
                    x=alt.X("cohort_month:O", title=None, axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("repeat_rate_3mo_pct:Q", title="% repeating within 3 months"),
                    tooltip=["cohort_month", "new_customers",
                             alt.Tooltip("repeat_rate_3mo_pct:Q", format=".3f")]), 280)

        st.markdown("##### Top customers")
        top = pd.DataFrame(api("/customers/top", limit=15, **cf))
        st.dataframe(top, hide_index=True, column_config={
            "customer_state": "State", "rfm_segment": "RFM segment", "kmeans_segment": "K-Means segment",
            "risk_tier": "Risk tier", "frequency_orders": "Orders",
            "monetary_revenue": st.column_config.NumberColumn("Lifetime revenue", format="R$ %.2f"),
            "avg_order_value": st.column_config.NumberColumn("AOV", format="R$ %.2f"),
            "recency_days": st.column_config.NumberColumn("Recency (days)", format="%d"),
            "distinct_categories": "Categories"})

# ---------------------------------------------------------------- products
with tabs[2]:
    c = filter_bar("products", {"pr_cat": [], "pr_quad": [], "pr_year": [], "pr_seller": [], "pr_top": 20},
                   [1.5, 1.3, 0.8, 1, 1])
    pf = {"category": multi(c[0], "Category", opts["categories"], "pr_cat"),
          "quadrant": multi(c[1], "Price-volume quadrant", opts["quadrants"], "pr_quad"),
          "year": multi(c[2], "Year", opts["years"], "pr_year"),
          "seller_state": multi(c[3], "Seller state", opts["seller_states"], "pr_seller")}
    top_n = c[4].slider("Top products shown", 5, 100, step=5, key="pr_top")
    active_summary({"Category": pf["category"], "Quadrant": pf["quadrant"], "Year": pf["year"],
                    "Seller state": pf["seller_state"]})

    p = api("/products/summary", **pf)
    if not p:
        empty()
    else:
        m = st.columns(4)
        m[0].metric("Revenue", brl(p["revenue"]))
        m[1].metric("Products sold", count(p["products_sold"]))
        m[2].metric("Products for 80% of revenue", f"{p['pct_of_products_for_80pct']:.1f}%",
                    help=f"{p['products_for_80pct']:,} of {p['products']:,} products")
        m[3].metric("Products sold once", f"{p['sold_once_pct']:.1f}%",
                    help=f"They carry {p['sold_once_revenue_pct']:.1f}% of revenue")
        st.markdown("<div class='caveat'>No cost data exists, so there is no margin analysis: "
                    "'performance' here means revenue, price and volume.</div>", unsafe_allow_html=True)

        cats = pd.DataFrame(api("/products/categories", **pf))
        left, right = st.columns(2)
        with left:
            st.markdown("##### Pareto curve")
            curve = pd.DataFrame(p["curve"])
            ref = pd.DataFrame({"x": [0, 100], "y": [0, 100]})
            chart(alt.Chart(curve).mark_line(color=BLUE, strokeWidth=3).encode(
                      x=alt.X("pct_products:Q", title="% of products (ranked by revenue)"),
                      y=alt.Y("pct_revenue:Q", title="% of revenue"))
                  + alt.Chart(ref).mark_line(color=MUTED, strokeDash=[4, 4]).encode(x="x:Q", y="y:Q")
                  + alt.Chart(pd.DataFrame({"y": [80]})).mark_rule(color=ORANGE, strokeDash=[6, 4]).encode(y="y:Q"),
                  400)
        with right:
            st.markdown("##### Category momentum: Jun–Aug vs Mar–May 2018")
            mom = cats[(cats["revenue_mar_may_2018"] > 0) | (cats["revenue_jun_aug_2018"] > 0)]
            if mom.empty:
                empty("Momentum compares two 2018 windows — include 2018 in the Year filter.")
            else:
                mom = pd.concat([mom.nlargest(8, "momentum_change_brl"),
                                 mom.nsmallest(8, "momentum_change_brl")]).drop_duplicates("category")
                chart(alt.Chart(mom).mark_bar(cornerRadiusEnd=3).encode(
                    y=alt.Y("category:N", sort="-x", title=None),
                    x=alt.X("momentum_change_brl:Q", title="Revenue change (R$)", axis=alt.Axis(format="~s")),
                    color=alt.condition("datum.momentum_change_brl > 0", alt.value(BLUE), alt.value(PALETTE[7])),
                    tooltip=["category", alt.Tooltip("momentum_change_brl:Q", format=",.0f"),
                             alt.Tooltip("momentum_change_pct:Q", format="+.1f", title="change %")]),
                      max(160, 27 * len(mom)))

        st.markdown("##### Category price vs volume  (bubble size = revenue)")
        chart(alt.Chart(cats).mark_circle(opacity=0.8, stroke="#0A1628", strokeWidth=1).encode(
            x=alt.X("units:Q", title="Units sold", scale=alt.Scale(type="log")),
            y=alt.Y("avg_item_price:Q", title="Average item price (R$)"),
            size=alt.Size("revenue:Q", legend=None, scale=alt.Scale(range=[30, 1200])),
            color=alt.Color("quadrant:N", scale=alt.Scale(range=PALETTE), legend=alt.Legend(orient="top", title=None)),
            tooltip=["category", "quadrant", alt.Tooltip("revenue:Q", format=",.0f"), "units",
                     alt.Tooltip("avg_item_price:Q", format=",.2f")]), 340)

        st.markdown(f"##### Top {top_n} products")
        top = pd.DataFrame(api("/products/top", limit=top_n, **pf))
        st.dataframe(top[["revenue_rank", "category", "units", "avg_item_price", "revenue",
                          "cumulative_pct_of_revenue"]], hide_index=True, column_config={
            "revenue_rank": "Rank", "category": "Category", "units": "Units",
            "avg_item_price": st.column_config.NumberColumn("Avg price", format="R$ %.2f"),
            "revenue": st.column_config.NumberColumn("Revenue", format="R$ %.2f"),
            "cumulative_pct_of_revenue": st.column_config.NumberColumn("Cumulative %", format="%.2f%%")})

# ---------------------------------------------------------------- marketing
with tabs[3]:
    c = filter_bar("marketing", {"mk_payment": [], "mk_state": [], "mk_year": [], "mk_min": 100},
                   [1.3, 1.3, 0.9, 1.2])
    mf = {"payment": multi(c[0], "Payment method", opts["payments"], "mk_payment"),
          "state": multi(c[1], "Customer state", opts["states"], "mk_state"),
          "year": multi(c[2], "Year", opts["years"], "mk_year")}
    min_orders = c[3].slider("Min orders (states & sellers)", 0, 500, step=25, key="mk_min")
    active_summary({"Payment": mf["payment"], "State": mf["state"], "Year": mf["year"],
                    "Min orders": min_orders or None})
    st.info("**These are performance proxies, not marketing channels.** The dataset has no campaign, "
            "spend, impression or session data, so CAC, ROAS and channel attribution cannot be computed.",
            icon="ℹ️")

    pay = pd.DataFrame(api("/marketing/payments", **mf))
    if pay.empty:
        empty()
    else:
        left, right = st.columns([2, 3])
        with left:
            st.markdown("##### Revenue by payment method")
            chart(hbar(pay, "payment_type", "revenue", "Revenue (R$)"), 220)
            st.dataframe(pay[["payment_type", "orders", "aov", "revenue_pct"]], hide_index=True, column_config={
                "payment_type": "Method", "orders": "Orders",
                "aov": st.column_config.NumberColumn("AOV", format="R$ %.2f"),
                "revenue_pct": st.column_config.NumberColumn("% revenue", format="%.1f%%")})
        with right:
            st.markdown("##### Credit-card order value by instalments")
            inst = pd.DataFrame(api("/marketing/installments", **mf))
            if inst.empty:
                empty("Instalments only exist on credit-card orders — include credit card in the Payment filter.")
            else:
                chart(alt.Chart(inst).mark_bar(color=TEAL, cornerRadiusEnd=3).encode(
                    x=alt.X("installments:O", title="Instalments"),
                    y=alt.Y("aov:Q", title="Mean order value (R$)"),
                    tooltip=["installments", alt.Tooltip("aov:Q", format=",.2f"), "orders"]), 300)
                st.caption("Order value rises with instalments. Whether instalments enable bigger baskets or "
                           "big baskets attract instalments cannot be told apart here.")

        left, right = st.columns(2)
        with left:
            st.markdown("##### State scorecard")
            reg = pd.DataFrame(api("/marketing/regions", min_orders=min_orders, **mf))
            if reg.empty:
                empty("No state reaches the minimum order count.")
            else:
                st.dataframe(reg[["customer_state", "orders", "aov", "avg_delivery_days", "late_rate_pct",
                                  "avg_review_score"]], hide_index=True, column_config={
                    "customer_state": "State", "orders": "Orders",
                    "aov": st.column_config.NumberColumn("AOV", format="R$ %.2f"),
                    "avg_delivery_days": st.column_config.NumberColumn("Delivery days", format="%.1f"),
                    "late_rate_pct": st.column_config.ProgressColumn("Late %", format="%.1f%%",
                                                                     min_value=0, max_value=25),
                    "avg_review_score": st.column_config.NumberColumn("Review", format="%.2f ★")})
        with right:
            st.markdown("##### Top sellers")
            sel = pd.DataFrame(api("/marketing/sellers", limit=20, min_orders=min_orders, **mf))
            if sel.empty:
                empty("No seller reaches the minimum order count.")
            else:
                st.dataframe(sel[["seller_state", "orders_n", "revenue", "late_rate_pct", "avg_review_score"]],
                             hide_index=True, column_config={
                    "seller_state": "State", "orders_n": "Orders",
                    "revenue": st.column_config.NumberColumn("Revenue", format="R$ %.0f"),
                    "late_rate_pct": st.column_config.ProgressColumn("Late %", format="%.1f%%",
                                                                     min_value=0, max_value=40),
                    "avg_review_score": st.column_config.NumberColumn("Review", format="%.2f ★")})

# ---------------------------------------------------------------- experiments
with tabs[4]:
    c = filter_bar("experiments", {"ex_year": [], "ex_state": []}, [1, 2])
    ef = {"year": multi(c[0], "Year", opts["years"], "ex_year"),
          "state": multi(c[1], "Customer state", opts["states"], "ex_state")}
    active_summary({"Year": ef["year"], "State": ef["state"]})

    ex = api("/experiments", **ef)
    if not ex:
        empty()
    else:
        st.warning("**Observational, not randomised.** There is no treatment assignment or control group, "
                   "so none of these results establishes causation. A p-value says how surely two groups "
                   f"differ — not whether one thing caused the difference. Significance level α = {ex['alpha']}. "
                   f"Tests rerun on **{ex['orders_used']:,} orders** matching the filters.", icon="⚠️")
        effect_names = {"cohens_d": "Cohen's d", "cramers_v": "Cramér's V", "risk_ratio": "risk ratio",
                        "cohens_h": "Cohen's h"}
        for t, colour in zip(ex["tests"], [BLUE, ORANGE, TEAL]):
            with st.container(border=True):
                st.markdown(f"#### {t['name']}")
                if t.get("insufficient_data"):
                    sizes = ", ".join(f"{pretty(g)}: {v['n']:,}" for g, v in t["groups"].items())
                    st.warning(f"{t['business_read']} Group sizes here — {sizes}.", icon="⚠️")
                    continue
                a, b = st.columns([3, 2])
                with a:
                    st.markdown(f"**H₀:** {t['h0']}  \n**H₁:** {t['h1']}  \n**Test:** {t['test']}")
                    eff = ", ".join(f"{effect_names.get(key, key)} = {v:.3f}" for key, v in t["effect_size"].items())
                    lo, hi = t["ci_95"]
                    p_text = "< 1e-300" if t["p_value"] == 0 else f"{t['p_value']:.3g}"
                    st.markdown(f"**Statistic:** {t['statistic']:,.3f} · **p-value:** {p_text} · "
                                f"**95% CI of difference:** [{lo:,.4f}, {hi:,.4f}]  \n**Effect size:** {eff}  \n"
                                f"**Decision:** {t['decision']} at α = {ex['alpha']}")
                    st.markdown(f"<div class='caveat'>💼 {t['business_read']}</div>", unsafe_allow_html=True)
                with b:
                    groups = pd.DataFrame([{"group": g.replace("_", " "), **v} for g, v in t["groups"].items()])
                    metric = [col for col in groups.columns if col not in ("group", "n")][0]
                    chart(alt.Chart(groups).mark_bar(color=colour, cornerRadiusEnd=4).encode(
                        x=alt.X("group:N", title=None, axis=alt.Axis(labelAngle=0)),
                        y=alt.Y(f"{metric}:Q", title=metric.replace("_", " ")),
                        tooltip=["group", "n", alt.Tooltip(f"{metric}:Q", format=",.4f")]), 200)

# ---------------------------------------------------------------- forecast
with tabs[5]:
    fc = api("/forecast")
    series = pd.DataFrame(fc["series"])
    months = series["period_label"].tolist()
    models = [m["model"] for m in fc["model_comparison"]]
    c = filter_bar("forecast", {"fc_start": months[0], "fc_band": True, "fc_models": []}, [2, 1, 2])
    start = c[0].select_slider("Show history from", months[:-3], key="fc_start")
    band = c[1].toggle("Show 95% interval", key="fc_band")
    chosen = multi(c[2], "Models in comparison", models, "fc_models")
    active_summary({"From": start if start != months[0] else None, "Models": chosen,
                    "Interval": None if band else "hidden"})

    nm = fc["next_month"]
    best = fc["model_comparison"][0]
    m = st.columns(4)
    m[0].metric(f"Forecast for {nm['period']}", brl(nm["forecast"]))
    m[1].metric("95% lower bound", brl(nm["lower_95"]))
    m[2].metric("95% upper bound", brl(nm["upper_95"]))
    m[3].metric("Best back-test error (MAPE)", f"{best['MAPE_pct']:.2f}%",
                help=f"{best['model']} was the most accurate model on 4 held-out months.")

    view = series[series["period_label"] >= start]
    actual = view[view["type"] == "actual"]
    future = view[view["type"] == "forecast"]
    bridge = pd.concat([actual.tail(1).assign(forecast=actual.tail(1)["actual"]), future])
    x = alt.X("period_label:O", title=None, axis=alt.Axis(labelAngle=-45))
    layers = alt.Chart(actual).mark_line(color=BLUE, strokeWidth=3, point=True).encode(
        x=x, y=alt.Y("actual:Q", title="Revenue (R$)", axis=alt.Axis(format="~s")),
        tooltip=["period_label", alt.Tooltip("actual:Q", format=",.0f")])
    if band:
        layers = alt.Chart(future).mark_area(color=MUTED, opacity=0.25).encode(
            x=x, y="lower_95:Q", y2="upper_95:Q") + layers
    layers += alt.Chart(bridge).mark_line(color=ORANGE, strokeWidth=3, strokeDash=[6, 4], point=True).encode(
        x=x, y="forecast:Q", tooltip=["period_label", alt.Tooltip("forecast:Q", format=",.0f")])
    chart(layers, 360)
    st.caption("Blue: actual. Orange: ARIMA(0,1,1) forecast. Shaded: 95% prediction interval. Only 20 months "
               "of history, so there is no annual seasonality — the forecast cannot anticipate Black Friday — "
               "and August 2018 is truncated, so the base is understated.")
    st.markdown("##### Model comparison on 4 held-out months")
    comp = pd.DataFrame(fc["model_comparison"])
    if chosen:
        comp = comp[comp["model"].isin(chosen)]
    st.dataframe(comp, hide_index=True, column_config={
        "model": "Model",
        "MAE": st.column_config.NumberColumn(format="R$ %.0f"),
        "RMSE": st.column_config.NumberColumn(format="R$ %.0f"),
        "MAPE_pct": st.column_config.NumberColumn("MAPE %", format="%.2f"),
        "vs_naive_pct": st.column_config.NumberColumn("vs naive %", format="%+.1f")})

# ---------------------------------------------------------------- recommendations
with tabs[6]:
    md = api("/recommendations")["markdown"]
    parts = re.split(r"(?m)^(?=## )", md)
    intro, sections = parts[0], parts[1:]
    titles = [s.splitlines()[0].lstrip("# ").strip() for s in sections]
    c = filter_bar("recs", {"re_section": [], "re_search": ""}, [2, 1.2])
    picked = c[0].multiselect("Sections", titles, key="re_section", placeholder="All sections")
    query = c[1].text_input("Search", key="re_search", placeholder="e.g. delivery, SP, forecast")
    active_summary({"Sections": picked, "Search": f"“{query}”" if query else None})

    shown = [s for s, t in zip(sections, titles)
             if (not picked or t in picked) and (not query or query.lower() in s.lower())]
    if not picked and not query:
        st.markdown(intro)
    st.caption(f"Showing {len(shown)} of {len(sections)} sections")
    if not shown:
        empty("No section matches — try another word.")
    for s in shown:
        with st.container(border=True):
            st.markdown(s)
