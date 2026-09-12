from __future__ import annotations

from datetime import date
from functools import lru_cache

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api import stats
from app.api.data import (REPORTS_DIR, CustomerFilter, ItemFilter, OrderFilter, cohort_summary,
                          filter_customers, filter_items, filter_orders, get_store, records,
                          retention_curve)

app = FastAPI(
    title="Olist Customer & Revenue Intelligence API",
    version="2.0.0",
    description=(
        "Analytics API over the Olist Brazilian e-commerce dataset: delivered orders, "
        "Jan 2017 - Aug 2018. Revenue is item price and excludes freight. Every list filter accepts "
        "several values (`?state=SP&state=RJ`). There is no cost data (so no margin), no marketing "
        "channel data (so no attribution), and no experiment (so every statistical test is observational)."
    ),
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


# ---------------------------------------------------------------- filters

@lru_cache(maxsize=1)
def allowed() -> dict[str, set]:
    s = get_store()
    return {
        "year": set(s.orders["order_year"].astype(int)),
        "state": set(s.orders["customer_state"]),
        "payment": set(s.orders["payment_type"].dropna()),
        "category": set(s.items["category"]),
        "quadrant": set(s.categories["quadrant"]),
        "seller_state": set(s.items["seller_state"]),
        "rfm": set(s.customers["rfm_segment"]),
        "kmeans": set(s.customers["kmeans_segment"]),
        "risk": set(s.customers["risk_tier"]),
    }


def _check(name: str, values: list | None) -> tuple:
    if not values:
        return ()
    unknown = [v for v in values if v not in allowed()[name]]
    if unknown:
        raise HTTPException(422, f"Unknown {name}: {', '.join(map(str, unknown))}")
    return tuple(values)


def order_filter(
    year: list[int] | None = Query(None, description="Order year(s)"),
    state: list[str] | None = Query(None, description="Customer state(s), e.g. SP"),
    payment: list[str] | None = Query(None, description="Payment method(s), e.g. credit_card"),
    date_from: date | None = Query(None, description="First purchase date to include"),
    date_to: date | None = Query(None, description="Last purchase date to include"),
) -> OrderFilter:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from is after date_to")
    return OrderFilter(years=_check("year", year), states=_check("state", [s.upper() for s in state or []]),
                       payments=_check("payment", payment), date_from=date_from, date_to=date_to)


def item_filter(
    category: list[str] | None = Query(None, description="Product category(ies)"),
    quadrant: list[str] | None = Query(None, description="Price-volume quadrant(s)"),
    seller_state: list[str] | None = Query(None, description="Seller state(s)"),
) -> ItemFilter:
    cats = set(_check("category", category))
    quads = _check("quadrant", quadrant)
    if quads:
        c = get_store().categories
        in_quadrant = set(c.loc[c["quadrant"].isin(quads), "category"])
        cats = cats & in_quadrant if cats else in_quadrant
    return ItemFilter(categories=tuple(sorted(cats)) or (("__none__",) if quads or category else ()),
                      seller_states=_check("seller_state", [s.upper() for s in seller_state or []]))


def customer_filter(
    state: list[str] | None = Query(None, description="Customer state(s)"),
    rfm: list[str] | None = Query(None, description="RFM segment(s)"),
    kmeans: list[str] | None = Query(None, description="K-Means segment(s)"),
    risk: list[str] | None = Query(None, description="Risk tier(s)"),
) -> CustomerFilter:
    return CustomerFilter(states=_check("state", [s.upper() for s in state or []]), rfm=_check("rfm", rfm),
                          kmeans=_check("kmeans", kmeans), risk=_check("risk", risk))


def _orders(f: OrderFilter) -> pd.DataFrame:
    df = filter_orders(get_store(), f)
    if df.empty:
        raise HTTPException(404, "No orders match these filters")
    return df


def _items(f: OrderFilter, i: ItemFilter) -> pd.DataFrame:
    df = filter_items(get_store(), f, i)
    if df.empty:
        raise HTTPException(404, "No order lines match these filters")
    return df


def _customers(c: CustomerFilter) -> pd.DataFrame:
    df = filter_customers(get_store(), c)
    if df.empty:
        raise HTTPException(404, "No customers match these filters")
    return df


# ---------------------------------------------------------------- meta

@app.get("/health", tags=["meta"])
def health() -> dict:
    store = get_store()
    return {"status": "ok", "orders": len(store.orders), "customers": len(store.customers)}


@app.get("/filters", tags=["meta"], summary="Every value each filter accepts, ordered by revenue")
def filters() -> dict:
    s = get_store()

    def by_revenue(df, col, value="revenue"):
        return df.groupby(col)[value].sum().sort_values(ascending=False).index.tolist()

    return {
        "years": sorted(int(y) for y in s.orders["order_year"].unique()),
        "date_min": s.orders["order_timestamp"].min().date().isoformat(),
        "date_max": s.orders["order_timestamp"].max().date().isoformat(),
        "states": by_revenue(s.orders, "customer_state"),
        "payments": by_revenue(s.orders, "payment_type"),
        "categories": by_revenue(s.items, "category"),
        "quadrants": sorted(s.categories["quadrant"].unique()),
        "seller_states": by_revenue(s.items, "seller_state"),
        "rfm_segments": by_revenue(s.customers, "rfm_segment", "monetary_revenue"),
        "kmeans_segments": by_revenue(s.customers, "kmeans_segment", "monetary_revenue"),
        "risk_tiers": sorted(s.customers["risk_tier"].unique()),
    }


# ---------------------------------------------------------------- overview

class Kpis(BaseModel):
    revenue: float
    orders: int
    customers: int
    aov_mean: float
    aov_median: float
    freight: float
    items_per_order: float
    late_rate: float
    avg_review: float | None
    one_star_rate: float | None
    repeat_rate: float


@app.get("/kpis", response_model=Kpis, tags=["overview"])
def kpis(f: OrderFilter = Depends(order_filter)) -> Kpis:
    df = _orders(f)
    reviewed = df["review_score"].dropna()
    per_customer = df.groupby("customer_unique_id").size()
    return Kpis(
        revenue=float(df["revenue"].sum()), orders=int(df["order_id"].nunique()),
        customers=int(df["customer_unique_id"].nunique()), aov_mean=float(df["revenue"].mean()),
        aov_median=float(df["revenue"].median()), freight=float(df["freight"].sum()),
        items_per_order=float(df["items_in_order"].mean()), late_rate=float(df["is_late"].mean()),
        avg_review=float(reviewed.mean()) if len(reviewed) else None,
        one_star_rate=float((reviewed == 1).mean()) if len(reviewed) else None,
        repeat_rate=float((per_customer > 1).mean()),
    )


@app.get("/revenue/monthly", tags=["overview"])
def revenue_monthly(f: OrderFilter = Depends(order_filter)) -> list[dict]:
    df = _orders(f)
    df = df[~df["is_truncated_period"]]
    if df.empty:
        return []
    m = (df.groupby("order_month")
           .agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"),
                customers=("customer_unique_id", "nunique"))
           .reset_index().rename(columns={"order_month": "month"}))
    m["aov"] = m["revenue"] / m["orders"]
    m["mom_pct"] = m["revenue"].pct_change() * 100
    m["partial_month"] = m["month"] == "2018-08"
    m.loc[m["partial_month"], "mom_pct"] = None
    return records(m)


@app.get("/revenue/by-state", tags=["overview"])
def revenue_by_state(f: OrderFilter = Depends(order_filter)) -> list[dict]:
    df = _orders(f)
    s = (df.groupby("customer_state")
           .agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"), aov=("revenue", "mean"),
                late_rate=("is_late", "mean"), avg_review=("review_score", "mean"))
           .reset_index().rename(columns={"customer_state": "state"})
           .sort_values("revenue", ascending=False))
    s["revenue_pct"] = s["revenue"] / s["revenue"].sum() * 100
    return records(s)


@app.get("/revenue/by-category", tags=["overview"])
def revenue_by_category(f: OrderFilter = Depends(order_filter), i: ItemFilter = Depends(item_filter),
                        limit: int = Query(15, ge=1, le=80)) -> list[dict]:
    items = _items(f, i)
    c = (items.groupby("category")
              .agg(revenue=("revenue", "sum"), items=("order_id", "size"), orders=("order_id", "nunique"))
              .reset_index().sort_values("revenue", ascending=False))
    c["avg_price"] = c["revenue"] / c["items"]
    c["revenue_pct"] = c["revenue"] / c["revenue"].sum() * 100
    return records(c.head(limit))


# ---------------------------------------------------------------- customers

@app.get("/customers/summary", tags=["customers"])
def customers_summary(c: CustomerFilter = Depends(customer_filter)) -> dict:
    df = _customers(c)
    return {"customers": len(df), "repeat_customers": int(df["is_repeat_customer"].sum()),
            "repeat_rate": float(df["is_repeat_customer"].mean()),
            "revenue": float(df["monetary_revenue"].sum()),
            "avg_value": float(df["monetary_revenue"].mean()),
            "median_value": float(df["monetary_revenue"].median()),
            "avg_recency_days": float(df["recency_days"].mean())}


@app.get("/customers/segments", tags=["customers"])
def customer_segments(by: str = Query("rfm", pattern="^(rfm|kmeans)$"),
                      c: CustomerFilter = Depends(customer_filter)) -> list[dict]:
    df = _customers(c)
    col = "rfm_segment" if by == "rfm" else "kmeans_segment"
    s = (df.groupby(col)
           .agg(customers=("customer_unique_id", "size"), revenue=("monetary_revenue", "sum"),
                avg_recency_days=("recency_days", "mean"), avg_orders=("frequency_orders", "mean"),
                avg_value=("monetary_revenue", "mean"))
           .reset_index().rename(columns={col: "segment"})
           .sort_values("revenue", ascending=False))
    s["customer_pct"] = s["customers"] / s["customers"].sum() * 100
    s["revenue_pct"] = s["revenue"] / s["revenue"].sum() * 100
    return records(s)


@app.get("/customers/retention", tags=["customers"],
         summary="Average retention by months since first purchase, computed live for the filtered customers")
def customer_retention(c: CustomerFilter = Depends(customer_filter)) -> list[dict]:
    ids = _customers(c)["customer_unique_id"]
    orders = get_store().orders
    return records(retention_curve(orders[orders["customer_unique_id"].isin(ids)]))


@app.get("/customers/cohorts", tags=["customers"],
         summary="Cohort sizes and repeat rates, computed live for the filtered customers")
def customer_cohorts(c: CustomerFilter = Depends(customer_filter)) -> list[dict]:
    ids = _customers(c)["customer_unique_id"]
    orders = get_store().orders
    return records(cohort_summary(orders[orders["customer_unique_id"].isin(ids)]))


@app.get("/customers/top", tags=["customers"])
def top_customers(c: CustomerFilter = Depends(customer_filter),
                  limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    cols = ["customer_state", "rfm_segment", "kmeans_segment", "risk_tier", "frequency_orders",
            "monetary_revenue", "avg_order_value", "recency_days", "distinct_categories"]
    df = _customers(c).sort_values("monetary_revenue", ascending=False).head(limit)
    return records(df[cols])


# ---------------------------------------------------------------- products

def _pareto(product_revenue: pd.Series, units: pd.Series) -> dict:
    share = product_revenue.cumsum() / product_revenue.sum() * 100
    n80 = int((share <= 80).sum()) + 1
    n = len(product_revenue)
    idx = [max(int(n * q / 100) - 1, 0) for q in range(1, 101)]
    once = units == 1
    return {
        "products": n,
        "products_for_80pct": min(n80, n),
        "pct_of_products_for_80pct": min(n80, n) / n * 100,
        "top_1pct_revenue_share": float(share.iloc[idx[0]]),
        "sold_once_pct": float(once.mean() * 100),
        "sold_once_revenue_pct": float(product_revenue[once].sum() / product_revenue.sum() * 100),
        "curve": [{"pct_products": q, "pct_revenue": round(float(share.iloc[i]), 3)}
                  for q, i in zip(range(1, 101), idx)],
    }


@app.get("/products/summary", tags=["products"],
         summary="Product KPIs and Pareto concentration for the filtered order lines")
def product_summary(f: OrderFilter = Depends(order_filter), i: ItemFilter = Depends(item_filter)) -> dict:
    items = _items(f, i)
    per_product = (items.groupby("product_id").agg(revenue=("revenue", "sum"), units=("order_id", "size"))
                   .sort_values("revenue", ascending=False))
    return {"revenue": float(items["revenue"].sum()), "products_sold": len(per_product),
            "items_sold": len(items), "avg_item_price": float(items["revenue"].mean()),
            "categories": int(items["category"].nunique()),
            **_pareto(per_product["revenue"], per_product["units"])}


@app.get("/products/pareto", tags=["products"])
def product_pareto(f: OrderFilter = Depends(order_filter), i: ItemFilter = Depends(item_filter)) -> dict:
    summary = product_summary(f, i)
    return {k: v for k, v in summary.items()
            if k not in ("revenue", "products_sold", "items_sold", "avg_item_price", "categories")}


@app.get("/products/categories", tags=["products"],
         summary="Category revenue, volume, price and Mar-May vs Jun-Aug 2018 momentum")
def product_categories(f: OrderFilter = Depends(order_filter), i: ItemFilter = Depends(item_filter)) -> list[dict]:
    items = _items(f, i)
    cats = (items.groupby("category")
                 .agg(revenue=("revenue", "sum"), units=("order_id", "size"), orders=("order_id", "nunique"),
                      products=("product_id", "nunique"), freight=("freight", "sum"))
                 .reset_index())
    cats["avg_item_price"] = cats["revenue"] / cats["units"]
    cats["pct_of_revenue"] = cats["revenue"] / cats["revenue"].sum() * 100
    cats["freight_pct_of_revenue"] = cats["freight"] / cats["revenue"] * 100
    prior = items[items["order_month"].isin(["2018-03", "2018-04", "2018-05"])].groupby("category")["revenue"].sum()
    recent = items[items["order_month"].isin(["2018-06", "2018-07", "2018-08"])].groupby("category")["revenue"].sum()
    cats["revenue_mar_may_2018"] = cats["category"].map(prior).fillna(0)
    cats["revenue_jun_aug_2018"] = cats["category"].map(recent).fillna(0)
    cats["momentum_change_brl"] = cats["revenue_jun_aug_2018"] - cats["revenue_mar_may_2018"]
    cats["momentum_change_pct"] = (cats["momentum_change_brl"] / cats["revenue_mar_may_2018"].where(
        cats["revenue_mar_may_2018"] > 0) * 100)
    cats = cats.merge(get_store().categories[["category", "quadrant"]], on="category", how="left")
    return records(cats.drop(columns="freight").sort_values("revenue", ascending=False))


@app.get("/products/top", tags=["products"])
def top_products(f: OrderFilter = Depends(order_filter), i: ItemFilter = Depends(item_filter),
                 limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    items = _items(f, i)
    p = (items.groupby(["product_id", "category"])
              .agg(units=("order_id", "size"), revenue=("revenue", "sum"), sellers=("seller_id", "nunique"))
              .reset_index().sort_values("revenue", ascending=False))
    p["avg_item_price"] = p["revenue"] / p["units"]
    p["revenue_rank"] = range(1, len(p) + 1)
    p["cumulative_pct_of_revenue"] = p["revenue"].cumsum() / p["revenue"].sum() * 100
    return records(p.head(limit))


# ---------------------------------------------------------------- marketing

@app.get("/marketing/payments", tags=["marketing"])
def marketing_payments(f: OrderFilter = Depends(order_filter)) -> list[dict]:
    df = _orders(f).dropna(subset=["payment_type"])
    p = (df.groupby("payment_type")
           .agg(orders=("order_id", "nunique"), revenue=("revenue", "sum"), aov=("revenue", "mean"),
                avg_review=("review_score", "mean"), avg_installments=("max_installments", "mean"))
           .reset_index().sort_values("revenue", ascending=False))
    p["order_pct"] = p["orders"] / p["orders"].sum() * 100
    p["revenue_pct"] = p["revenue"] / p["revenue"].sum() * 100
    return records(p)


@app.get("/marketing/installments", tags=["marketing"], summary="Credit-card order value by instalment count")
def marketing_installments(f: OrderFilter = Depends(order_filter)) -> list[dict]:
    df = _orders(f)
    df = df[df["payment_type"] == "credit_card"]
    i = (df.groupby("max_installments")
           .agg(orders=("order_id", "nunique"), aov=("revenue", "mean"), avg_review=("review_score", "mean"))
           .reset_index().rename(columns={"max_installments": "installments"}))
    return records(i[i["orders"] >= 30])


@app.get("/marketing/regions", tags=["marketing"], summary="State scorecard, computed live")
def marketing_regions(f: OrderFilter = Depends(order_filter), min_orders: int = Query(0, ge=0)) -> list[dict]:
    df = _orders(f)
    r = (df.groupby("customer_state")
           .agg(orders=("order_id", "nunique"), customers=("customer_unique_id", "nunique"),
                revenue=("revenue", "sum"), aov=("revenue", "mean"), freight=("freight", "sum"),
                avg_delivery_days=("delivery_days", "mean"), late_rate=("is_late", "mean"),
                avg_review_score=("review_score", "mean"))
           .reset_index())
    r["late_rate_pct"] = r["late_rate"] * 100
    r["freight_pct_of_revenue"] = r["freight"] / r["revenue"] * 100
    r["pct_of_revenue"] = r["revenue"] / r["revenue"].sum() * 100
    r = r[r["orders"] >= min_orders].drop(columns=["late_rate", "freight"])
    return records(r.sort_values("revenue", ascending=False))


@app.get("/marketing/sellers", tags=["marketing"], summary="Seller revenue and service quality, computed live")
def marketing_sellers(f: OrderFilter = Depends(order_filter), limit: int = Query(20, ge=1, le=500),
                      min_orders: int = Query(0, ge=0)) -> list[dict]:
    items = _items(f, ItemFilter())
    s = (items.groupby(["seller_id", "seller_state"])
              .agg(revenue=("revenue", "sum"), items_sold=("order_id", "size"), orders_n=("order_id", "nunique"),
                   products=("product_id", "nunique"))
              .reset_index())
    pairs = items[["seller_id", "order_id"]].drop_duplicates().merge(
        get_store().orders[["order_id", "delivery_days", "is_late", "review_score"]], on="order_id")
    service = pairs.groupby("seller_id").agg(avg_delivery_days=("delivery_days", "mean"),
                                             late_rate_pct=("is_late", "mean"),
                                             avg_review_score=("review_score", "mean"))
    service["late_rate_pct"] *= 100
    s = s.merge(service, on="seller_id", how="left")
    s["pct_of_revenue"] = s["revenue"] / s["revenue"].sum() * 100
    s = s[s["orders_n"] >= min_orders].sort_values("revenue", ascending=False)
    return records(s.head(limit))


# ---------------------------------------------------------------- statistics

@app.get("/experiments", tags=["statistics"], summary="The three observational tests, rerun on the filtered orders")
def experiments(year: list[int] | None = Query(None), state: list[str] | None = Query(None)) -> dict:
    f = OrderFilter(years=_check("year", year), states=_check("state", [s.upper() for s in state or []]))
    return {"alpha": stats.ALPHA, "min_group": stats.MIN_GROUP, "orders_used": len(_orders(f)),
            "note": "Observational comparisons, not randomised experiments: there is no treatment "
                    "assignment or control group, so none of these results establishes causation.",
            "tests": _cached_tests(f)}


@lru_cache(maxsize=64)
def _cached_tests(f: OrderFilter) -> list[dict]:
    return stats.all_tests(filter_orders(get_store(), f))


# ---------------------------------------------------------------- forecast & report

@app.get("/forecast", tags=["forecast"])
def forecast() -> dict:
    store = get_store()
    f = store.forecast.drop(columns=["value"])
    f["period"] = f["period"].dt.strftime("%Y-%m-%d")
    nxt = store.forecast[store.forecast["type"] == "forecast"].iloc[0]
    return {"model": "ARIMA(0,1,1)",
            "next_month": {"period": nxt["period_label"], "forecast": float(nxt["forecast"]),
                           "lower_95": float(nxt["lower_95"]), "upper_95": float(nxt["upper_95"])},
            "series": records(f),
            "model_comparison": records(store.models.sort_values("MAE"))}


@app.get("/recommendations", tags=["report"])
def recommendations() -> dict:
    path = REPORTS_DIR / "business_recommendations.md"
    if not path.exists():
        raise HTTPException(404, "business_recommendations.md not found")
    return {"markdown": path.read_text(encoding="utf-8")}
