"""
Data cleaning pipeline for the Olist e-commerce dataset.

Implements every decision recorded in the Phase 2 audit
(``notebooks/01_data_understanding.ipynb``) and writes analysis-ready tables to
``data/processed/``.

Design rules this module follows
--------------------------------
1. **Nothing is silently dropped.** Rows that fail a quality rule are *flagged*
   with a boolean column so downstream phases can include or exclude them
   deliberately. The only rows physically removed are exact duplicates and
   records that would corrupt a join (duplicate review rows, the geolocation
   fan-out, out-of-Brazil coordinates).
2. **Outliers are preserved.** High prices, heavy products, long deliveries and
   large baskets were checked individually and are real business events, not
   data errors. See ``docs`` in :func:`clean_order_items` and the notebook.
3. **Definitions are centralised here**, so every later phase inherits the same
   revenue rule, analysis window and customer key.

Key definitions
---------------
- **Revenue**  = ``order_items.price`` (freight tracked separately, never summed
  into revenue). ``payment_value`` is not used because it cannot be attributed
  below order level.
- **Customer** = ``customer_unique_id`` (``customer_id`` is order-scoped).
- **Analysis window** = 2017-01-01 .. 2018-08-31 inclusive. The 2016 pilot and
  the truncated Sep/Oct 2018 tail are extract artefacts.

Run standalone::

    python src/data_cleaning.py
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "olist"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

RAW_FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

#: Analysis window — see module docstring.
WINDOW_START = pd.Timestamp("2017-01-01")
WINDOW_END = pd.Timestamp("2018-08-31 23:59:59")

#: Order statuses that represent realised revenue.
REVENUE_STATUSES = ("delivered",)

#: The two categories present in ``products`` but absent from Olist's
#: translation table. Translated manually so they are not lost from English
#: reporting; without this an inner join would delete them entirely.
MISSING_TRANSLATIONS = {
    "pc_gamer": "pc_gamer",
    "portateis_cozinha_e_preparadores_de_alimentos": "kitchen_portables_and_food_preparers",
}

#: Brazil bounding box, used to reject corrupt geolocation coordinates.
BR_LAT_MIN, BR_LAT_MAX = -33.75, 5.27
BR_LNG_MIN, BR_LNG_MAX = -73.99, -34.79

ORDER_DATE_COLS = [
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def normalize_text(value):
    """Lower-case, strip accents and collapse punctuation/whitespace.

    Used for city names, where the raw data carries accent and spacing variants
    of the same place (``sao paulo`` / ``são paulo`` / ``sãopaulo``). This
    collapses encoding and punctuation variants only — it does **not** correct
    genuine misspellings, so the result is cleaner but not a canonical gazetteer.
    """
    if pd.isna(value):
        return value
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def load_raw(raw_dir: Path = RAW_DIR) -> dict[str, pd.DataFrame]:
    """Read the nine source CSVs exactly as they are on disk."""
    raw_dir = Path(raw_dir)
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw data directory not found: {raw_dir}")
    return {name: pd.read_csv(raw_dir / fname) for name, fname in RAW_FILES.items()}


# --------------------------------------------------------------------------
# Per-table cleaners
# --------------------------------------------------------------------------

def clean_orders(orders: pd.DataFrame) -> pd.DataFrame:
    """Parse order timestamps, derive stage durations and flag quality issues.

    No orders are removed. Non-delivered orders are kept and flagged, because
    cancellation and unavailability rates are themselves findings; the revenue
    rule excludes them at aggregation time instead.

    Flags added
    -----------
    ``is_delivered``           status == 'delivered'
    ``in_window``              purchased inside the usable analysis window
    ``timeline_valid``         no stage duration is negative
    ``status_date_conflict``   status and timestamps disagree
    ``is_late``                delivered after the estimated date
    """
    df = orders.copy()
    for col in ORDER_DATE_COLS:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    df["order_status"] = df["order_status"].astype("category")
    df["is_delivered"] = df["order_status"].eq("delivered")
    df["in_window"] = df["order_purchase_timestamp"].between(WINDOW_START, WINDOW_END)

    # Calendar helpers used throughout later phases
    ts = df["order_purchase_timestamp"]
    df["order_date"] = ts.dt.date
    df["order_year"] = ts.dt.year
    df["order_month"] = ts.dt.to_period("M").astype(str)
    df["order_quarter"] = ts.dt.to_period("Q").astype(str)
    df["order_dow"] = ts.dt.day_name()
    df["order_hour"] = ts.dt.hour

    # Stage durations, in days
    day = 86_400
    df["approval_days"] = (df.order_approved_at - ts).dt.total_seconds() / day
    df["carrier_days"] = (
        df.order_delivered_carrier_date - df.order_approved_at
    ).dt.total_seconds() / day
    df["shipping_days"] = (
        df.order_delivered_customer_date - df.order_delivered_carrier_date
    ).dt.total_seconds() / day
    df["delivery_days"] = (
        df.order_delivered_customer_date - ts
    ).dt.total_seconds() / day
    df["estimated_days"] = (df.order_estimated_delivery_date - ts).dt.total_seconds() / day
    df["delivery_vs_estimate_days"] = (
        df.order_delivered_customer_date - df.order_estimated_delivery_date
    ).dt.total_seconds() / day
    df["is_late"] = df["delivery_vs_estimate_days"] > 0

    # Quality flags — negative stage durations are impossible in reality
    stage_cols = ["approval_days", "carrier_days", "shipping_days", "delivery_days"]
    negative = pd.concat([df[c].lt(0) for c in stage_cols], axis=1).any(axis=1)
    df["timeline_valid"] = ~negative

    # Status/timestamp disagreement (delivered with no date, or the reverse)
    df["status_date_conflict"] = (
        df.is_delivered & df.order_delivered_customer_date.isna()
    ) | (~df.is_delivered & df.order_delivered_customer_date.notna())

    # Negative durations are set to NaN so that means/medians are not corrupted.
    # The raw timestamps are untouched, so the issue remains auditable.
    for col in stage_cols:
        df.loc[df[col] < 0, col] = np.nan

    return df


def clean_order_items(items: pd.DataFrame) -> pd.DataFrame:
    """Clean the item lines.

    **Outliers are deliberately retained.** The IQR rule would flag 8,427 item
    rows (7.5%) as high-price outliers, but those rows carry 35.6% of all
    revenue, span 3,715 distinct products, and the expensive products recur
    across many orders (the top one sells 195 times). They are a genuine
    high-value product tier, not data error — removing them would delete a third
    of the revenue this project exists to explain.

    Flags added
    -----------
    ``invalid_shipping_limit``  shipping_limit_date falls outside the data window
    ``free_freight``            freight_value == 0 (real free-shipping offers)
    """
    df = items.copy()
    df["shipping_limit_date"] = pd.to_datetime(df["shipping_limit_date"], errors="coerce")
    df["invalid_shipping_limit"] = ~df["shipping_limit_date"].between(
        pd.Timestamp("2016-09-01"), pd.Timestamp("2018-12-31")
    )
    df["free_freight"] = df["freight_value"].eq(0)
    df["item_total"] = df["price"] + df["freight_value"]
    return df


def clean_customers(customers: pd.DataFrame) -> pd.DataFrame:
    """Normalise city names and keep both customer keys side by side."""
    df = customers.copy()
    df["customer_city_raw"] = df["customer_city"]
    df["customer_city"] = df["customer_city"].map(normalize_text)
    df["customer_state"] = df["customer_state"].str.upper().str.strip().astype("category")
    return df


def clean_products(products: pd.DataFrame, translation: pd.DataFrame) -> pd.DataFrame:
    """Attach English category names and repair impossible physical attributes.

    Uses a **left** join to the translation table plus manual entries for the two
    untranslated categories, so no product is lost. Products with no category at
    all become the explicit bucket ``'unknown'`` rather than being dropped —
    they carry real revenue (R$179,535 gross) and deleting them would understate
    every category total.
    """
    df = products.copy()

    # Olist ships two columns with a typo in the source file ('lenght').
    df = df.rename(
        columns={
            "product_name_lenght": "product_name_length",
            "product_description_lenght": "product_description_length",
        }
    )

    trans = translation.copy()
    extra = pd.DataFrame(
        {
            "product_category_name": list(MISSING_TRANSLATIONS),
            "product_category_name_english": list(MISSING_TRANSLATIONS.values()),
        }
    )
    trans = pd.concat([trans, extra], ignore_index=True).drop_duplicates(
        "product_category_name"
    )

    df["category_missing"] = df["product_category_name"].isna()
    df = df.merge(trans, on="product_category_name", how="left")
    df["product_category_name"] = df["product_category_name"].fillna("unknown")
    df["product_category_name_english"] = df["product_category_name_english"].fillna("unknown")

    # A physical good cannot weigh zero — treat as missing, do not guess a value.
    dim_cols = ["product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"]
    df["invalid_dimensions"] = df[dim_cols].le(0).any(axis=1) | df[dim_cols].isna().any(axis=1)
    for col in dim_cols:
        df.loc[df[col] <= 0, col] = np.nan

    df["product_volume_cm3"] = (
        df.product_length_cm * df.product_height_cm * df.product_width_cm
    )
    return df


def clean_payments(payments: pd.DataFrame) -> pd.DataFrame:
    """Flag invalid payment records without deleting them.

    Three distinct anomalies, each treated on its own merits:

    - 6 zero-value ``voucher`` rows are trailing records on orders whose other
      payment rows already cover the full amount — harmless, flagged only.
    - 3 ``not_defined`` rows are the *only* payment record for their order and
      total R$0.00, so those orders have no recoverable payment value. Revenue
      for them still comes from ``order_items``.
    - 2 rows record 0 instalments, which is not a valid count. Set to 1, since
      a single up-front payment is the only reading consistent with the value.
    """
    df = payments.copy()
    df["payment_type"] = df["payment_type"].str.strip()

    order_totals = df.groupby("order_id").payment_value.transform("sum")
    df["zero_value"] = df["payment_value"].eq(0)
    df["order_has_no_payment_value"] = order_totals.eq(0)
    df["undefined_type"] = df["payment_type"].eq("not_defined")

    df["installments_imputed"] = df["payment_installments"].eq(0)
    df.loc[df["payment_installments"] == 0, "payment_installments"] = 1

    df["is_valid_payment"] = ~(df.zero_value | df.undefined_type)
    df["payment_type"] = df["payment_type"].astype("category")
    return df


def clean_reviews(reviews: pd.DataFrame) -> pd.DataFrame:
    """Reduce reviews to exactly one row per order.

    ``review_id`` is not unique (789 ids repeat) and 547 orders carry more than
    one review, 202 of them with conflicting scores (mean spread 2.04 points).
    Left unhandled, the fan-out on an order join would duplicate order revenue.

    **Rule: keep the most recent review per order**, ordered by
    ``review_answer_timestamp`` then ``review_creation_date`` — the latest
    response is the customer's settled view. Measured impact: mean review score
    moves by less than 0.0001 and no score band shifts by more than 0.01pp, so
    the rule does not bias the satisfaction distribution.
    """
    df = reviews.copy()
    df["review_creation_date"] = pd.to_datetime(df["review_creation_date"], errors="coerce")
    df["review_answer_timestamp"] = pd.to_datetime(df["review_answer_timestamp"], errors="coerce")

    df["has_comment"] = df["review_comment_message"].notna()
    df["response_days"] = (
        df.review_answer_timestamp - df.review_creation_date
    ).dt.total_seconds() / 86_400

    dup_counts = df.order_id.map(df.order_id.value_counts())
    df["had_multiple_reviews"] = dup_counts.gt(1)

    df = (
        df.sort_values(["order_id", "review_answer_timestamp", "review_creation_date"])
        .drop_duplicates("order_id", keep="last")
        .reset_index(drop=True)
    )
    return df


def clean_sellers(sellers: pd.DataFrame) -> pd.DataFrame:
    """Normalise seller city/state to match the customer-side treatment."""
    df = sellers.copy()
    df["seller_city_raw"] = df["seller_city"]
    df["seller_city"] = df["seller_city"].map(normalize_text)
    df["seller_state"] = df["seller_state"].str.upper().str.strip().astype("category")
    return df


def clean_geolocation(geolocation: pd.DataFrame) -> pd.DataFrame:
    """Collapse the geolocation fan-out to one row per zip prefix.

    The raw table holds 1,000,163 observation rows (26% of them exact
    duplicates) for 19,015 zip prefixes. Joined as-is it would multiply any
    customer table enormously. Coordinates outside Brazil's bounding box (42
    rows) are corrupt and removed before aggregation; the **median** lat/lng is
    used rather than the mean so remaining local noise cannot drag a centroid.
    """
    df = geolocation.copy()
    in_brazil = df.geolocation_lat.between(BR_LAT_MIN, BR_LAT_MAX) & df.geolocation_lng.between(
        BR_LNG_MIN, BR_LNG_MAX
    )
    df = df[in_brazil].copy()
    df["geolocation_city"] = df["geolocation_city"].map(normalize_text)

    out = (
        df.groupby("geolocation_zip_code_prefix")
        .agg(
            geolocation_lat=("geolocation_lat", "median"),
            geolocation_lng=("geolocation_lng", "median"),
            geolocation_city=("geolocation_city", lambda s: s.mode().iat[0] if len(s.mode()) else np.nan),
            geolocation_state=("geolocation_state", lambda s: s.mode().iat[0] if len(s.mode()) else np.nan),
            n_observations=("geolocation_lat", "size"),
        )
        .reset_index()
    )
    return out


# --------------------------------------------------------------------------
# Fact-table builders
# --------------------------------------------------------------------------

def build_order_items_fact(
    orders: pd.DataFrame,
    items: pd.DataFrame,
    customers: pd.DataFrame,
    products: pd.DataFrame,
    sellers: pd.DataFrame,
) -> pd.DataFrame:
    """Item-grain fact table: one row per product line on an order.

    This is the analytical backbone for product, category and seller work.
    All joins are left joins from ``order_items``, so no line is lost.
    """
    fact = items.merge(
        orders[
            [
                "order_id", "customer_id", "order_status", "is_delivered", "in_window",
                "order_purchase_timestamp", "order_date", "order_year", "order_month",
                "order_quarter", "order_dow", "delivery_days", "is_late",
            ]
        ],
        on="order_id",
        how="left",
    )
    fact = fact.merge(
        customers[["customer_id", "customer_unique_id", "customer_city", "customer_state", "customer_zip_code_prefix"]],
        on="customer_id",
        how="left",
    )
    fact = fact.merge(
        products[
            [
                "product_id", "product_category_name", "product_category_name_english",
                "product_weight_g", "product_volume_cm3", "product_photos_qty",
            ]
        ],
        on="product_id",
        how="left",
    )
    fact = fact.merge(
        sellers[["seller_id", "seller_city", "seller_state"]], on="seller_id", how="left"
    )
    fact = fact.rename(columns={"price": "revenue", "freight_value": "freight"})
    fact["same_state"] = fact.customer_state.astype(str).eq(fact.seller_state.astype(str))
    return fact


def build_orders_fact(
    orders: pd.DataFrame,
    items: pd.DataFrame,
    customers: pd.DataFrame,
    payments: pd.DataFrame,
    reviews: pd.DataFrame,
) -> pd.DataFrame:
    """Order-grain fact table: one row per order, with revenue rolled up.

    Orders with no item lines (775 of them, almost all ``unavailable`` or
    ``canceled``) are kept with zero revenue and ``n_items = 0`` so that
    cancellation analysis remains possible.
    """
    item_agg = items.groupby("order_id").agg(
        order_revenue=("price", "sum"),
        order_freight=("freight_value", "sum"),
        n_items=("order_item_id", "count"),
        n_distinct_products=("product_id", "nunique"),
        n_sellers=("seller_id", "nunique"),
        max_item_price=("price", "max"),
    )

    # Payment mix: the dominant type is the one carrying the most value.
    valid_pay = payments[payments.is_valid_payment]
    pay_agg = valid_pay.groupby("order_id").agg(
        payment_total=("payment_value", "sum"),
        n_payment_records=("payment_sequential", "count"),
        max_installments=("payment_installments", "max"),
    )
    dominant = (
        valid_pay.sort_values("payment_value", ascending=False)
        .drop_duplicates("order_id")
        .set_index("order_id")["payment_type"]
        .rename("payment_type")
    )

    rev_agg = reviews.set_index("order_id")[["review_score", "has_comment", "response_days"]]

    fact = (
        orders.merge(item_agg, on="order_id", how="left")
        .merge(pay_agg, on="order_id", how="left")
        .merge(dominant, on="order_id", how="left")
        .merge(rev_agg, on="order_id", how="left")
        .merge(
            customers[["customer_id", "customer_unique_id", "customer_city", "customer_state", "customer_zip_code_prefix"]],
            on="customer_id",
            how="left",
        )
    )

    for col in ["order_revenue", "order_freight", "n_items", "n_distinct_products", "n_sellers"]:
        fact[col] = fact[col].fillna(0)
    fact["has_items"] = fact["n_items"] > 0
    fact["is_multi_item"] = fact["n_items"] > 1
    fact["avg_item_price"] = np.where(
        fact.n_items > 0, fact.order_revenue / fact.n_items.replace(0, np.nan), np.nan
    )
    return fact


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def run_pipeline(
    raw_dir: Path = RAW_DIR,
    out_dir: Path = PROCESSED_DIR,
    write: bool = True,
) -> dict[str, pd.DataFrame]:
    """Run every cleaner, build both fact tables and optionally write to disk."""
    raw = load_raw(raw_dir)

    orders = clean_orders(raw["orders"])
    items = clean_order_items(raw["order_items"])
    customers = clean_customers(raw["customers"])
    products = clean_products(raw["products"], raw["category_translation"])
    payments = clean_payments(raw["payments"])
    reviews = clean_reviews(raw["reviews"])
    sellers = clean_sellers(raw["sellers"])
    geolocation = clean_geolocation(raw["geolocation"])

    out = {
        "orders_clean": orders,
        "order_items_clean": items,
        "customers_clean": customers,
        "products_clean": products,
        "payments_clean": payments,
        "reviews_clean": reviews,
        "sellers_clean": sellers,
        "geolocation_clean": geolocation,
        "fct_order_items": build_order_items_fact(orders, items, customers, products, sellers),
        "fct_orders": build_orders_fact(orders, items, customers, payments, reviews),
    }

    if write:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, df in out.items():
            df.to_parquet(out_dir / f"{name}.parquet", index=False)

    return out


if __name__ == "__main__":
    tables = run_pipeline()
    print(f"Cleaned tables written to {PROCESSED_DIR}\n")
    for name, df in tables.items():
        print(f"  {name:22s} {len(df):>9,} rows x {df.shape[1]:>3} cols")
