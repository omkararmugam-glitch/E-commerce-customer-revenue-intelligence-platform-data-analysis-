"""
Build the Power BI export set in ``data/powerbi/``.

Produces flat, well-named, dashboard-ready tables — one file per dashboard
concern, each at a single stated grain. Every file is written as **both** CSV
(universally readable by Power BI Desktop) and Parquet (smaller, typed).

Design rules
------------
- **One row = one clearly stated thing.** The grain is documented per table in
  ``reports/powerbi_data_dictionary.md`` and repeated in this module.
- **No cost or margin columns.** The source data contains no cost of goods, so
  no margin field is exported. Any such column would have to be invented.
- **Analysis base is fixed**: delivered orders, 2017-01-01 .. 2018-08-31, keyed
  on ``customer_unique_id`` — identical to every notebook.
- **Truncation flag included.** Orders after 2018-08-23 fall in the thin tail of
  the export (Phase 12); ``is_truncated_period`` marks them so time-series
  visuals can exclude them rather than show a false cliff.

Run::

    python src/export_powerbi.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_ROOT / "data" / "processed"
POWERBI = PROJECT_ROOT / "data" / "powerbi"

#: Last day before the export's order flow thins out (see notebook 10 §1).
TRUNCATION_CUTOFF = pd.Timestamp("2018-08-23")

#: Analysis tables written by the notebooks, which must run before this export.
NOTEBOOK_OUTPUTS = {
    "customer_segments": "05_rfm_segmentation",
    "cohort_retention_matrix": "06_cohort_analysis",
    "cohort_summary": "06_cohort_analysis",
    "product_performance": "07_product_analytics",
    "category_performance": "07_product_analytics",
    "marketing_payment_performance": "08_marketing_analysis",
    "marketing_region_performance": "08_marketing_analysis",
    "marketing_seller_performance": "08_marketing_analysis",
    "revenue_forecast": "10_forecasting",
    "forecast_model_comparison": "10_forecasting",
}


def check_inputs() -> None:
    """Fail early, naming the notebooks to run, if any input table is missing."""
    missing = {name: nb for name, nb in NOTEBOOK_OUTPUTS.items()
               if not (PROCESSED / f"{name}.parquet").exists()}
    if not (PROCESSED / "fct_orders.parquet").exists():
        raise SystemExit("data/processed/ is empty - run `python src/data_cleaning.py` first.")
    if missing:
        notebooks = ", ".join(sorted(set(missing.values())))
        raise SystemExit(f"Missing {len(missing)} analysis tables in data/processed/ "
                         f"({', '.join(missing)}). Run notebooks 01-10 first: {notebooks}.")


def _write(df: pd.DataFrame, name: str) -> dict:
    """Write one table as CSV + Parquet and return a summary row."""
    POWERBI.mkdir(parents=True, exist_ok=True)
    # Categoricals become Parquet dictionary columns; plain text is safer for
    # Power Query and every other consumer.
    df = df.copy()
    for col in df.columns:
        if isinstance(df[col].dtype, pd.CategoricalDtype):
            df[col] = df[col].astype(str)
    csv_path = POWERBI / f"{name}.csv"
    pq_path = POWERBI / f"{name}.parquet"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_parquet(pq_path, index=False)
    return {
        "table": name,
        "rows": len(df),
        "columns": df.shape[1],
        "csv_kb": round(csv_path.stat().st_size / 1024, 1),
        "parquet_kb": round(pq_path.stat().st_size / 1024, 1),
    }


def build_exports() -> pd.DataFrame:
    fct_orders = pd.read_parquet(PROCESSED / "fct_orders.parquet")
    fct_items = pd.read_parquet(PROCESSED / "fct_order_items.parquet")

    orders = fct_orders[fct_orders.is_delivered & fct_orders.in_window].copy()
    items = fct_items[(fct_items.is_delivered == True)
                      & (fct_items.in_window == True)].copy()

    summaries = []

    # ---------------------------------------------------------------- 1. orders
    # Grain: one row per delivered order in the analysis window.
    fact_orders = pd.DataFrame({
        "order_id": orders.order_id,
        "customer_unique_id": orders.customer_unique_id,
        "order_date": pd.to_datetime(orders.order_purchase_timestamp).dt.date,
        "order_timestamp": pd.to_datetime(orders.order_purchase_timestamp),
        "order_year": orders.order_year,
        "order_month": orders.order_month,
        "order_quarter": orders.order_quarter,
        "order_weekday": orders.order_dow,
        "order_hour": orders.order_hour,
        "revenue": orders.order_revenue.round(2),
        "freight": orders.order_freight.round(2),
        "items_in_order": orders.n_items.astype(int),
        "distinct_products": orders.n_distinct_products.astype(int),
        "distinct_sellers": orders.n_sellers.astype(int),
        "avg_item_price": orders.avg_item_price.round(2),
        "is_multi_item": orders.is_multi_item,
        "payment_type": orders.payment_type.astype(str),
        "max_installments": orders.max_installments,
        "review_score": orders.review_score,
        "delivery_days": orders.delivery_days.round(2),
        "estimated_days": orders.estimated_days.round(2),
        "delivery_vs_estimate_days": orders.delivery_vs_estimate_days.round(2),
        "is_late": orders.is_late,
        "customer_state": orders.customer_state.astype(str),
        "customer_city": orders.customer_city,
    })
    fact_orders["is_truncated_period"] = (
        pd.to_datetime(fact_orders.order_timestamp) > TRUNCATION_CUTOFF)
    summaries.append(_write(fact_orders, "fact_orders"))

    # ------------------------------------------------------------- 2. order items
    # Grain: one row per product line on a delivered order.
    fact_items = pd.DataFrame({
        "order_id": items.order_id,
        "order_item_id": items.order_item_id,
        "product_id": items.product_id,
        "seller_id": items.seller_id,
        "customer_unique_id": items.customer_unique_id,
        "order_date": pd.to_datetime(items.order_purchase_timestamp).dt.date,
        "order_month": items.order_month,
        "order_quarter": items.order_quarter,
        "category": items.product_category_name_english,
        "revenue": items.revenue.round(2),
        "freight": items.freight.round(2),
        "customer_state": items.customer_state.astype(str),
        "seller_state": items.seller_state.astype(str),
        "same_state_delivery": items.same_state,
    })
    summaries.append(_write(fact_items, "fact_order_items"))

    # ------------------------------------------------------------- 3. customers
    # Grain: one row per customer (customer_unique_id), with RFM + K-Means.
    seg_path = PROCESSED / "customer_segments.parquet"
    segments = pd.read_parquet(seg_path)
    dim_customers = pd.DataFrame({
        "customer_unique_id": segments.customer_unique_id,
        "customer_state": segments.state.astype(str),
        "first_order_date": pd.to_datetime(segments.first_order).dt.date,
        "last_order_date": pd.to_datetime(segments.last_order).dt.date,
        "recency_days": segments.recency,
        "frequency_orders": segments.frequency,
        "monetary_revenue": segments.monetary.round(2),
        "avg_order_value": segments.aov.round(2),
        "total_items": segments.total_items.astype(int),
        "distinct_categories": segments.n_categories,
        "distinct_sellers": segments.n_sellers,
        "tenure_days": segments.tenure,
        "avg_review_score": segments.avg_review.round(3),
        "late_orders": segments.late_orders,
        "is_repeat_customer": segments.is_repeat,
        "r_score": segments.r_score,
        "f_score": segments.f_score,
        "m_score": segments.m_score,
        "rfm_cell": segments.rfm_cell,
        "rfm_segment": segments.rfm_segment,
        "kmeans_cluster": segments.cluster,
        "kmeans_segment": segments.cluster_name,
        "value_decile": segments.value_decile.astype(int),
        "risk_tier": segments.risk_tier,
    })
    summaries.append(_write(dim_customers, "dim_customers_segmented"))

    # --------------------------------------------------------- 4. product/category
    # Grain: one row per category.
    cat = pd.read_parquet(PROCESSED / "category_performance.parquet")
    dim_category = cat.rename(columns={
        "product_category_name_english": "category",
        "units_sold": "units",
        "avg_selling_price": "avg_item_price",
        "revenue_pct": "pct_of_revenue",
        "cum_pct": "cumulative_pct_of_revenue",
        "momentum_change": "momentum_change_brl",
        "momentum_pct": "momentum_change_pct",
    })
    for col in ["revenue", "avg_item_price", "median_price", "freight",
                "revenue_mar_may_2018", "revenue_jun_aug_2018", "momentum_change_brl"]:
        if col in dim_category:
            dim_category[col] = dim_category[col].round(2)
    dim_category["freight_pct_of_revenue"] = (
        dim_category.freight / dim_category.revenue * 100).round(2)
    # the quadrant is only computed for categories with 100+ units; label the rest
    dim_category["quadrant"] = dim_category["quadrant"].fillna("Low volume (<100 units)")
    summaries.append(_write(dim_category, "dim_category_performance"))

    # Grain: one row per product.
    prod = pd.read_parquet(PROCESSED / "product_performance.parquet")
    prod = prod.rename(columns={"avg_selling_price": "avg_item_price",
                                "units_sold": "units"})
    prod["revenue"] = prod.revenue.round(2)
    prod["avg_item_price"] = prod.avg_item_price.round(2)
    prod = prod.sort_values("revenue", ascending=False)
    prod["revenue_rank"] = np.arange(1, len(prod) + 1)
    prod["cumulative_pct_of_revenue"] = (
        prod.revenue.cumsum() / prod.revenue.sum() * 100).round(3)
    prod["sold_once_only"] = prod.units == 1
    summaries.append(_write(prod, "dim_product_performance"))

    # ------------------------------------------------------------- 5. cohorts
    # Long format: one row per (cohort, months_since_first_purchase).
    retention = pd.read_parquet(PROCESSED / "cohort_retention_matrix.parquet")
    retention.index = retention.index.astype(str)
    cohort_long = (retention.reset_index()
                   .melt(id_vars=retention.index.name or "cohort",
                         var_name="months_since_first_purchase",
                         value_name="retention_pct"))
    cohort_long.columns = ["cohort_month", "months_since_first_purchase", "retention_pct"]
    cohort_long = cohort_long.dropna(subset=["retention_pct"])
    cohort_long["months_since_first_purchase"] = (
        cohort_long.months_since_first_purchase.astype(int))
    cohort_long["retention_pct"] = cohort_long.retention_pct.round(4)

    cohort_summary = pd.read_parquet(PROCESSED / "cohort_summary.parquet")
    cohort_long = cohort_long.merge(
        cohort_summary[["cohort", "new_customers"]].rename(
            columns={"cohort": "cohort_month", "new_customers": "cohort_size"}),
        on="cohort_month", how="left")
    cohort_long["retained_customers"] = (
        cohort_long.retention_pct / 100 * cohort_long.cohort_size).round(0).astype(int)
    summaries.append(_write(cohort_long, "fact_cohort_retention"))

    cs = cohort_summary.rename(columns={"cohort": "cohort_month",
                                        "revenue_per_customer": "revenue_per_customer"})
    for col in ["revenue", "revenue_per_customer", "ever_repeated_pct", "repeat_rate_3mo_pct"]:
        if col in cs:
            cs[col] = cs[col].round(3)
    summaries.append(_write(cs, "dim_cohort_summary"))

    # ------------------------------------------------------------ 6. forecast
    # Grain: one row per month — actuals then forecast, in one continuous column.
    fcst = pd.read_parquet(PROCESSED / "revenue_forecast.parquet")
    fcst["period"] = pd.to_datetime(fcst.period)
    fcst["period_label"] = fcst.period.dt.strftime("%Y-%m")
    fcst["value"] = fcst.actual.fillna(fcst.forecast)
    for col in ["actual", "forecast", "lower_95", "upper_95", "value"]:
        fcst[col] = fcst[col].round(2)
    fcst = fcst[["period", "period_label", "type", "actual", "forecast",
                 "lower_95", "upper_95", "value"]]
    summaries.append(_write(fcst, "fact_revenue_forecast"))

    models = pd.read_parquet(PROCESSED / "forecast_model_comparison.parquet")
    for col in ["MAE", "RMSE", "MAPE_pct", "vs_naive_pct"]:
        if col in models:
            models[col] = models[col].round(3)
    summaries.append(_write(models, "dim_forecast_model_comparison"))

    # ----------------------------------------------------- 7. marketing proxies
    seller = pd.read_parquet(PROCESSED / "marketing_seller_performance.parquet")
    for col in ["revenue", "avg_item_price", "pct_of_revenue", "cum_pct",
                "avg_delivery", "late_rate", "avg_review"]:
        if col in seller:
            seller[col] = seller[col].round(3)
    seller = seller.rename(columns={"avg_delivery": "avg_delivery_days",
                                    "late_rate": "late_rate_pct",
                                    "avg_review": "avg_review_score",
                                    "cum_pct": "cumulative_pct_of_revenue"})
    summaries.append(_write(seller, "dim_seller_performance"))

    region = pd.read_parquet(PROCESSED / "marketing_region_performance.parquet")
    region = region.rename(columns={"orders_n": "orders", "avg_delivery": "avg_delivery_days",
                                    "late_rate": "late_rate_pct",
                                    "avg_review": "avg_review_score",
                                    "freight_pct": "freight_pct_of_revenue"})
    for col in region.select_dtypes("number").columns:
        region[col] = region[col].round(3)
    summaries.append(_write(region, "dim_region_performance"))

    payment = pd.read_parquet(PROCESSED / "marketing_payment_performance.parquet")
    for col in payment.select_dtypes("number").columns:
        payment[col] = payment[col].round(3)
    summaries.append(_write(payment, "dim_payment_performance"))

    # ------------------------------------------------------------- 8. date dim
    span = pd.date_range(fact_orders.order_timestamp.min().normalize(),
                         fact_orders.order_timestamp.max().normalize(), freq="D")
    dim_date = pd.DataFrame({"date": span})
    dim_date["year"] = dim_date.date.dt.year
    dim_date["quarter"] = dim_date.date.dt.to_period("Q").astype(str)
    dim_date["month"] = dim_date.date.dt.to_period("M").astype(str)
    dim_date["month_name"] = dim_date.date.dt.strftime("%b %Y")
    dim_date["day_of_month"] = dim_date.date.dt.day
    dim_date["weekday"] = dim_date.date.dt.day_name()
    dim_date["weekday_number"] = dim_date.date.dt.dayofweek + 1
    dim_date["is_weekend"] = dim_date.date.dt.dayofweek >= 5
    dim_date["is_truncated_period"] = dim_date.date > TRUNCATION_CUTOFF
    summaries.append(_write(dim_date, "dim_date"))

    return pd.DataFrame(summaries)


if __name__ == "__main__":
    check_inputs()
    summary = build_exports()
    print(f"Power BI exports written to {POWERBI}\n")
    print(summary.to_string(index=False))
    print(f"\n{len(summary)} tables | {summary.rows.sum():,} total rows | "
          f"{summary.csv_kb.sum()/1024:.1f} MB CSV + {summary.parquet_kb.sum()/1024:.1f} MB Parquet")
