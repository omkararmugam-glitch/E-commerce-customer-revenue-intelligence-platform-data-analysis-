from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "powerbi"
REPORTS_DIR = PROJECT_ROOT / "reports"
LAST_MONTH = pd.Period("2018-08", freq="M")


@dataclass(frozen=True)
class Store:
    orders: pd.DataFrame
    items: pd.DataFrame
    customers: pd.DataFrame
    categories: pd.DataFrame
    forecast: pd.DataFrame
    models: pd.DataFrame


@dataclass(frozen=True)
class OrderFilter:
    years: tuple[int, ...] = ()
    states: tuple[str, ...] = ()
    payments: tuple[str, ...] = ()
    date_from: date | None = None
    date_to: date | None = None


@dataclass(frozen=True)
class ItemFilter:
    categories: tuple[str, ...] = ()
    seller_states: tuple[str, ...] = ()


@dataclass(frozen=True)
class CustomerFilter:
    states: tuple[str, ...] = ()
    rfm: tuple[str, ...] = ()
    kmeans: tuple[str, ...] = ()
    risk: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def get_store() -> Store:
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"{DATA_DIR} not found - run `python src/export_powerbi.py` first")

    def read(name: str) -> pd.DataFrame:
        return pd.read_parquet(DATA_DIR / f"{name}.parquet")

    orders = read("fact_orders")
    orders["month_index"] = orders["order_timestamp"].dt.year * 12 + orders["order_timestamp"].dt.month
    items = read("fact_order_items").merge(
        orders[["order_id", "order_year", "order_timestamp", "payment_type"]], on="order_id", how="left")
    forecast = read("fact_revenue_forecast")
    forecast["period"] = pd.to_datetime(forecast["period"])
    return Store(orders=orders, items=items, customers=read("dim_customers_segmented"),
                 categories=read("dim_category_performance"), forecast=forecast,
                 models=read("dim_forecast_model_comparison"))


def _in_dates(ts: pd.Series, f: OrderFilter) -> pd.Series:
    mask = pd.Series(True, index=ts.index)
    if f.date_from:
        mask &= ts >= pd.Timestamp(f.date_from.isoformat())
    if f.date_to:
        mask &= ts < pd.Timestamp((f.date_to + timedelta(days=1)).isoformat())
    return mask


def filter_orders(store: Store, f: OrderFilter) -> pd.DataFrame:
    df = store.orders
    if f.years:
        df = df[df["order_year"].isin(f.years)]
    if f.states:
        df = df[df["customer_state"].isin(f.states)]
    if f.payments:
        df = df[df["payment_type"].isin(f.payments)]
    if f.date_from or f.date_to:
        df = df[_in_dates(df["order_timestamp"], f)]
    return df


def filter_items(store: Store, f: OrderFilter, i: ItemFilter = ItemFilter()) -> pd.DataFrame:
    df = store.items
    if f.years:
        df = df[df["order_year"].isin(f.years)]
    if f.states:
        df = df[df["customer_state"].isin(f.states)]
    if f.payments:
        df = df[df["payment_type"].isin(f.payments)]
    if f.date_from or f.date_to:
        df = df[_in_dates(df["order_timestamp"], f)]
    if i.categories:
        df = df[df["category"].isin(i.categories)]
    if i.seller_states:
        df = df[df["seller_state"].isin(i.seller_states)]
    return df


def filter_customers(store: Store, c: CustomerFilter) -> pd.DataFrame:
    df = store.customers
    for column, values in (("customer_state", c.states), ("rfm_segment", c.rfm),
                           ("kmeans_segment", c.kmeans), ("risk_tier", c.risk)):
        if values:
            df = df[df[column].isin(values)]
    return df


def cohort_frame(orders: pd.DataFrame) -> pd.DataFrame:
    """Per (cohort, age in months) distinct customers, from the orders given."""
    first = orders.groupby("customer_unique_id")["month_index"].transform("min")
    frame = pd.DataFrame({"customer": orders["customer_unique_id"], "cohort": first,
                          "age": orders["month_index"] - first, "revenue": orders["revenue"]})
    return frame


def retention_curve(orders: pd.DataFrame) -> pd.DataFrame:
    frame = cohort_frame(orders)
    counts = frame.groupby(["cohort", "age"])["customer"].nunique()
    size = counts.xs(0, level="age")
    retention = (counts / size.reindex(counts.index.get_level_values("cohort")).values * 100).rename("pct")
    later = retention[retention.index.get_level_values("age") > 0]
    curve = later.groupby(level="age").agg(["mean", "size"]).reset_index()
    curve.columns = ["month", "retention_pct", "cohorts"]
    return curve


def cohort_summary(orders: pd.DataFrame) -> pd.DataFrame:
    frame = cohort_frame(orders)
    size = frame[frame["age"] == 0].groupby("cohort")["customer"].nunique()
    revenue = frame.groupby("cohort")["revenue"].sum()
    repeat_3 = frame[frame["age"].between(1, 3)].groupby("cohort")["customer"].nunique()
    ever = frame[frame["age"] > 0].groupby("cohort")["customer"].nunique()
    out = pd.DataFrame({"new_customers": size, "revenue": revenue})
    out["revenue_per_customer"] = out["revenue"] / out["new_customers"]
    out["repeat_rate_3mo_pct"] = repeat_3.reindex(out.index).fillna(0) / out["new_customers"] * 100
    out["ever_repeated_pct"] = ever.reindex(out.index).fillna(0) / out["new_customers"] * 100
    last = LAST_MONTH.year * 12 + LAST_MONTH.month
    out["months_observed"] = last - out.index
    out.loc[out["months_observed"] < 3, "repeat_rate_3mo_pct"] = np.nan
    out.index = [f"{(m - 1) // 12}-{(m - 1) % 12 + 1:02d}" for m in out.index]
    return out.rename_axis("cohort_month").reset_index()


def records(df: pd.DataFrame, decimals: int = 4) -> list[dict]:
    """DataFrame -> JSON-safe list of dicts (numpy types and NaN handled)."""
    return json.loads(df.round(decimals).to_json(orient="records", date_format="iso"))
