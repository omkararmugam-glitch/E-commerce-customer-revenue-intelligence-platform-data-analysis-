from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

ALPHA = 0.05
MIN_GROUP = 30


def _verdict(p: float) -> str:
    return "reject H0" if p < ALPHA else "fail to reject H0"


def _too_small(name: str, groups: dict) -> dict:
    return {"name": name, "insufficient_data": True, "groups": groups,
            "business_read": f"Not enough data in this filter (each group needs at least {MIN_GROUP})."}


def payment_vs_order_value(orders: pd.DataFrame) -> dict:
    name = "Credit card vs boleto: order value"
    cc = orders.loc[orders["payment_type"] == "credit_card", "revenue"].dropna()
    bo = orders.loc[orders["payment_type"] == "boleto", "revenue"].dropna()
    groups = {"credit_card": {"n": len(cc), "mean": float(cc.mean()) if len(cc) else None},
              "boleto": {"n": len(bo), "mean": float(bo.mean()) if len(bo) else None}}
    if min(len(cc), len(bo)) < MIN_GROUP:
        return _too_small(name, groups)
    t_stat, p = stats.ttest_ind(cc, bo, equal_var=False)
    n1, n2 = len(cc), len(bo)
    v1, v2 = cc.var(ddof=1), bo.var(ddof=1)
    se = np.sqrt(v1 / n1 + v2 / n2)
    dof = (v1 / n1 + v2 / n2) ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    diff = cc.mean() - bo.mean()
    crit = stats.t.ppf(1 - ALPHA / 2, dof)
    pooled = np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    _, p_mw = stats.mannwhitneyu(cc, bo, alternative="two-sided")
    d = diff / pooled
    return {
        "name": name, "insufficient_data": False,
        "h0": "Mean order value is equal for credit-card and boleto orders",
        "h1": "Mean order value differs",
        "test": "Welch two-sample t-test (Mann-Whitney U as a check)",
        "groups": groups, "statistic": float(t_stat), "p_value": float(p),
        "p_value_mann_whitney": float(p_mw), "difference": float(diff),
        "ci_95": [float(diff - crit * se), float(diff + crit * se)],
        "effect_size": {"cohens_d": float(d)}, "decision": _verdict(p),
        "business_read": f"Cohen's d = {d:.2f}: {'small' if abs(d) < 0.5 else 'meaningful'}, and "
                         "self-selected - it describes who buys, not a lever.",
    }


def late_delivery_vs_one_star(orders: pd.DataFrame) -> dict:
    name = "Late vs on-time delivery: 1-star reviews"
    reviewed = orders.dropna(subset=["review_score"])
    one_star = reviewed["review_score"] == 1
    late = reviewed["is_late"].astype(bool)
    table = np.array([[int((~late & ~one_star).sum()), int((~late & one_star).sum())],
                      [int((late & ~one_star).sum()), int((late & one_star).sum())]])
    n_late, n_on = int(table[1].sum()), int(table[0].sum())
    groups = {"late": {"n": n_late, "one_star_rate": table[1, 1] / n_late if n_late else None},
              "on_time": {"n": n_on, "one_star_rate": table[0, 1] / n_on if n_on else None}}
    if min(n_late, n_on) < MIN_GROUP or (table == 0).any():
        return _too_small(name, groups)
    chi2, p, _, _ = stats.chi2_contingency(table)
    p_late, p_on = table[1, 1] / n_late, table[0, 1] / n_on
    se = np.sqrt(p_late * (1 - p_late) / n_late + p_on * (1 - p_on) / n_on)
    return {
        "name": name, "insufficient_data": False,
        "h0": "The 1-star review rate is independent of late delivery",
        "h1": "The two are associated",
        "test": "Pearson chi-square test of independence",
        "groups": groups, "statistic": float(chi2), "p_value": float(p),
        "difference": float(p_late - p_on),
        "ci_95": [float(p_late - p_on - 1.96 * se), float(p_late - p_on + 1.96 * se)],
        "effect_size": {"cramers_v": float(np.sqrt(chi2 / table.sum())), "risk_ratio": float(p_late / p_on)},
        "decision": _verdict(p),
        "business_read": f"Late orders are {p_late / p_on:.1f}x as likely to get 1 star.",
    }


def late_first_order_vs_repeat(orders: pd.DataFrame) -> dict:
    name = "Late first order: repeat purchase"
    ordered = orders.sort_values(["customer_unique_id", "order_timestamp"])
    first = ordered.groupby("customer_unique_id").first()
    repeated = ordered.groupby("customer_unique_id").size() > 1
    late = first["is_late"].astype(bool)
    k1, n1 = int(repeated[late].sum()), int(late.sum())
    k0, n0 = int(repeated[~late].sum()), int((~late).sum())
    groups = {"late_first_order": {"n": n1, "repeat_rate": k1 / n1 if n1 else None},
              "on_time_first_order": {"n": n0, "repeat_rate": k0 / n0 if n0 else None}}
    if min(n1, n0) < MIN_GROUP or k1 + k0 == 0:
        return _too_small(name, groups)
    p1, p0 = k1 / n1, k0 / n0
    pooled = (k1 + k0) / (n1 + n0)
    z = (p1 - p0) / np.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n0))
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    se = np.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
    h = 2 * np.arcsin(np.sqrt(p1)) - 2 * np.arcsin(np.sqrt(p0))
    return {
        "name": name, "insufficient_data": False,
        "h0": "The repeat rate is the same after a late and an on-time first order",
        "h1": "The repeat rates differ",
        "test": "Two-proportion z-test",
        "groups": groups, "statistic": float(z), "p_value": float(p),
        "difference": float(p1 - p0),
        "ci_95": [float(p1 - p0 - 1.96 * se), float(p1 - p0 + 1.96 * se)],
        "effect_size": {"cohens_h": float(h)}, "decision": _verdict(p),
        "business_read": f"Cohen's h = {h:.3f}: even when significant, the effect is "
                         f"{'negligible' if abs(h) < 0.2 else 'noticeable'} in business terms.",
    }


def all_tests(orders: pd.DataFrame) -> list[dict]:
    return [payment_vs_order_value(orders), late_delivery_vs_one_star(orders),
            late_first_order_vs_repeat(orders)]
