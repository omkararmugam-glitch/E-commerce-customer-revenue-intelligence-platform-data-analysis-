"""
Feature engineering for the customer- and cohort-level analyses.

These are the derivations used by notebooks 04–06, factored out so the RFM
scoring, clustering features and cohort assignment are defined once. The
cleaning rules and fact tables they build on live in :mod:`src.data_cleaning`.

Two definitions are load-bearing and are fixed here:

- **Reference date** (:data:`REFERENCE_DATE`) is 2018-09-01, the day after the
  analysis window closes. Recency is measured against it so no customer has a
  negative recency.
- **Frequency scoring is rule-based, not quantile-based.** 97% of customers in
  this dataset have exactly one order, so ``pd.qcut`` collapses to a single bin
  and cannot separate anyone. :func:`score_frequency` states the cut points
  explicitly instead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Day after the analysis window closes (2018-08-31). See module docstring.
REFERENCE_DATE = pd.Timestamp("2018-09-01")

#: Features used for K-Means in notebook 05.
CLUSTER_FEATURES = ["recency", "frequency", "monetary", "aov", "n_categories"]

#: Cluster features that need a log transform before scaling (recency does not —
#: it is roughly symmetric; the rest have skew between 7 and 11).
LOG_FEATURES = ["frequency", "monetary", "aov", "n_categories"]


# --------------------------------------------------------------------------
# Customer-level features
# --------------------------------------------------------------------------

def build_customer_features(
    orders: pd.DataFrame,
    items: pd.DataFrame,
    reference_date: pd.Timestamp = REFERENCE_DATE,
) -> pd.DataFrame:
    """Aggregate the analysis base to one row per ``customer_unique_id``.

    Parameters
    ----------
    orders
        Order-grain rows from the analysis base (delivered, in-window).
    items
        Item-grain rows from the same base, used for breadth measures.
    """
    customers = orders.groupby("customer_unique_id").agg(
        first_order=("order_purchase_timestamp", "min"),
        last_order=("order_purchase_timestamp", "max"),
        frequency=("order_id", "nunique"),
        monetary=("order_revenue", "sum"),
        total_freight=("order_freight", "sum"),
        total_items=("n_items", "sum"),
        avg_review=("review_score", "mean"),
        late_orders=("is_late", "sum"),
        avg_delivery_days=("delivery_days", "mean"),
        state=("customer_state", "first"),
    )

    breadth = items.groupby("customer_unique_id").agg(
        n_distinct_products=("product_id", "nunique"),
        n_categories=("product_category_name_english", "nunique"),
        n_sellers=("seller_id", "nunique"),
    )
    customers = customers.join(breadth)

    customers["recency"] = (reference_date - customers.last_order).dt.days
    customers["tenure"] = (reference_date - customers.first_order).dt.days
    customers["aov"] = customers.monetary / customers.frequency
    customers["is_repeat"] = customers.frequency > 1
    customers["late_rate"] = customers.late_orders / customers.frequency
    return customers


# --------------------------------------------------------------------------
# RFM scoring
# --------------------------------------------------------------------------

def score_recency(recency: pd.Series, bins: int = 5) -> pd.Series:
    """Quintile score where **lower recency scores higher** (5 = most recent)."""
    return pd.qcut(recency, bins, labels=list(range(bins, 0, -1))).astype(int)


def score_monetary(monetary: pd.Series, bins: int = 5) -> pd.Series:
    """Quintile score where higher spend scores higher."""
    return pd.qcut(monetary, bins, labels=list(range(1, bins + 1))).astype(int)


def score_frequency(frequency: pd.Series) -> pd.Series:
    """Rule-based frequency score.

    Quantile scoring is impossible here: 97% of customers have ``frequency == 1``,
    so every quintile boundary lands on the same value and ``qcut`` returns one
    bin. The cut points are therefore stated explicitly:

    ===============  =====
    orders           score
    ===============  =====
    3 or more            5
    exactly 2            3
    exactly 1            1
    ===============  =====

    The gap between 5 and 3 is deliberate — three or more orders in 20 months is
    qualitatively different behaviour in this dataset, and a linear 1-2-3 scale
    would understate it.
    """
    return pd.Series(
        np.where(frequency >= 3, 5, np.where(frequency == 2, 3, 1)),
        index=frequency.index,
        dtype=int,
    )


def add_rfm_scores(customers: pd.DataFrame) -> pd.DataFrame:
    """Attach ``r_score``, ``f_score``, ``m_score``, ``rfm_cell`` and ``rfm_sum``."""
    out = customers.copy()
    out["r_score"] = score_recency(out.recency)
    out["f_score"] = score_frequency(out.frequency)
    out["m_score"] = score_monetary(out.monetary)
    out["rfm_cell"] = (out.r_score.astype(str) + "-" + out.f_score.astype(str)
                       + "-" + out.m_score.astype(str))
    out["rfm_sum"] = out.r_score + out.f_score + out.m_score
    return out


def assign_rfm_segment(row) -> str:
    """Map one customer's R/F/M scores to a named segment.

    Rules are applied in order, first match wins, so every customer lands in
    exactly one segment. Because F is 1 for 97% of customers, the effective
    segmentation for most of the base is an R x M grid — see notebook 05 §1.4.
    """
    R, F, M = row.r_score, row.f_score, row.m_score
    if F >= 5 and R >= 4 and M >= 4:
        return "Champions"
    if F >= 5 and R >= 3:
        return "Loyal"
    if F >= 5:
        return "At Risk"
    if R >= 4 and M >= 4:
        return "Potential Loyalists"
    if R >= 4:
        return "New Customers"
    if R == 3:
        return "Needs Attention"
    if M >= 4:
        return "At Risk"
    return "Lost"


def add_rfm_segments(customers: pd.DataFrame) -> pd.DataFrame:
    """Attach ``rfm_segment`` (assumes :func:`add_rfm_scores` has run)."""
    out = customers.copy()
    out["rfm_segment"] = out.apply(assign_rfm_segment, axis=1)
    return out


# --------------------------------------------------------------------------
# Clustering features
# --------------------------------------------------------------------------

def build_cluster_matrix(
    customers: pd.DataFrame,
    features: list[str] | None = None,
    log_features: list[str] | None = None,
) -> pd.DataFrame:
    """Log-transform the skewed features ready for scaling.

    K-Means minimises squared Euclidean distance, so untransformed skew lets a
    handful of extreme spenders dictate every centroid. Note that ``frequency``
    and ``n_categories`` stay skewed even after ``log1p`` — no transform fixes a
    variable that is constant for 97% of rows, which is a property of the
    business rather than a modelling failure.
    """
    features = features or CLUSTER_FEATURES
    log_features = log_features or LOG_FEATURES
    matrix = customers[features].copy()
    for col in log_features:
        if col in matrix:
            matrix[col] = np.log1p(matrix[col])
    return matrix


# --------------------------------------------------------------------------
# Cohort features
# --------------------------------------------------------------------------

def add_cohort_features(orders: pd.DataFrame) -> pd.DataFrame:
    """Attach ``order_period``, ``cohort`` and ``cohort_age`` (months since first order)."""
    out = orders.copy()
    out["order_period"] = pd.to_datetime(out.order_purchase_timestamp).dt.to_period("M")
    cohort = out.groupby("customer_unique_id").order_period.min().rename("cohort")
    out = out.join(cohort, on="customer_unique_id")
    out["cohort_age"] = (out.order_period - out.cohort).apply(lambda x: x.n)
    return out


def cohort_retention_matrix(orders_with_cohort: pd.DataFrame) -> pd.DataFrame:
    """Retention percentages: rows are cohorts, columns are months since acquisition."""
    size = orders_with_cohort.groupby("cohort").customer_unique_id.nunique()
    counts = orders_with_cohort.pivot_table(
        index="cohort", columns="cohort_age",
        values="customer_unique_id", aggfunc="nunique")
    return counts.div(size, axis=0) * 100


def fair_cohort_comparison(
    orders_with_cohort: pd.DataFrame,
    window_end: pd.Period,
    horizon: int = 3,
) -> pd.DataFrame:
    """Repeat rate within a **fixed** horizon, for cohorts old enough to have one.

    Comparing "ever repeated" across cohorts measures how long each has been
    observed, not cohort quality — in this dataset those two correlate at
    r = 0.92. Holding the horizon constant removes the censoring.
    """
    size = orders_with_cohort.groupby("cohort").customer_unique_id.nunique()
    eligible = [c for c in size.index if (window_end - c).n >= horizon]
    repeated = (orders_with_cohort[orders_with_cohort.cohort_age.between(1, horizon)]
                .groupby("cohort").customer_unique_id.nunique())
    out = pd.DataFrame({
        "cohort_size": size.loc[eligible],
        "repeated_within_horizon": repeated.reindex(eligible).fillna(0).astype(int),
    })
    out["repeat_rate_pct"] = out.repeated_within_horizon / out.cohort_size * 100
    return out
