"""
Revenue forecasting utilities.

Covers the Phase 12 workflow: build a clean revenue series, run stationarity and
seasonality diagnostics, fit a ladder of models from naive upward, score them on
a held-out window, and produce a forecast with prediction intervals.

Two things this module is deliberate about
------------------------------------------
1. **It trims the truncated tail.** The Olist extract thins sharply from
   2018-08-22 and stops on 2018-08-29. Monthly aggregation hides this; the daily
   series exposes it. :func:`trim_truncated_tail` removes trailing days whose
   order count falls below a fraction of the trailing median, so the model is
   not fitted to (or scored against) an artefact of the export.
2. **It does not force ARIMA.** :func:`diagnose` reports stationarity and
   seasonality, and the caller decides. On the monthly series (20 points, fewer
   than two annual cycles) seasonal ARIMA is not estimable and is not offered.
"""

from __future__ import annotations

import inspect
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import InterpolationWarning
from statsmodels.tsa.holtwinters import ExponentialSmoothing, SimpleExpSmoothing
from statsmodels.tsa.stattools import acf, adfuller, kpss
from statsmodels.tsa.statespace.sarimax import SARIMAX

# statsmodels >= 0.15 warns unless the adfuller return type is chosen explicitly.
_ADF_KW = {"result_object": False} if "result_object" in inspect.signature(adfuller).parameters else {}


# --------------------------------------------------------------------------
# Series construction
# --------------------------------------------------------------------------

def build_series(orders: pd.DataFrame, freq: str = "D") -> pd.Series:
    """Aggregate order-level revenue into a regular time series.

    Parameters
    ----------
    orders
        Order-grain frame with ``order_purchase_timestamp`` and ``order_revenue``.
    freq
        ``"D"`` for daily (missing days filled with 0) or ``"MS"`` for month-start.
    """
    ts = pd.to_datetime(orders["order_purchase_timestamp"])
    if freq == "D":
        s = orders.groupby(ts.dt.normalize())["order_revenue"].sum()
        return s.asfreq("D").fillna(0.0)
    s = orders.groupby(ts.dt.to_period("M"))["order_revenue"].sum()
    s.index = s.index.to_timestamp()
    return s.asfreq("MS")


def trim_truncated_tail(
    series: pd.Series,
    counts: pd.Series,
    min_ratio: float = 0.5,
    window: int = 28,
) -> tuple[pd.Series, pd.Timestamp | None]:
    """Drop trailing periods whose activity collapses relative to recent history.

    A data export that stops mid-period leaves a tail of artificially thin
    observations. Fitting or scoring on them teaches the model a decline that
    never happened.

    Returns the trimmed series and the cut-off date (``None`` if nothing was cut).
    """
    ratio = counts / counts.rolling(window).median()
    healthy = ratio[ratio >= min_ratio]
    if healthy.empty:
        return series, None
    last_good = healthy.index.max()
    if last_good >= series.index.max():
        return series, None
    return series.loc[:last_good], last_good


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------

@dataclass
class Diagnosis:
    """Stationarity and seasonality evidence for one series."""

    n_obs: int
    adf_stat: float
    adf_p: float
    kpss_p: float | None
    stationary: bool
    seasonal_period: int | None
    seasonal_acf: dict[int, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    kpss_bound: str = ""

    def __str__(self) -> str:
        kpss_text = f"{self.kpss_bound} {self.kpss_p:.4g}".strip() if self.kpss_p is not None else ""
        lines = [
            f"observations        : {self.n_obs}",
            f"ADF statistic       : {self.adf_stat:.4f}  (p = {self.adf_p:.4g})",
            f"KPSS p-value        : {kpss_text}" if kpss_text else "KPSS: not run",
            f"stationary (ADF)    : {self.stationary}",
            f"seasonal period     : {self.seasonal_period}",
        ]
        if self.seasonal_acf:
            lines.append("seasonal ACF (differenced series):")
            lines += [f"    lag {k:>2}: {v:+.4f}" for k, v in self.seasonal_acf.items()]
        lines += [f"  * {n}" for n in self.notes]
        return "\n".join(lines)


def adf_test(series: pd.Series) -> tuple[float, float]:
    """Augmented Dickey-Fuller test with AIC lag selection: (statistic, p-value)."""
    stat, p = adfuller(series.dropna(), autolag="AIC", **_ADF_KW)[:2]
    return float(stat), float(p)


def diagnose(series: pd.Series, candidate_period: int | None = 7) -> Diagnosis:
    """Run stationarity tests and check for seasonality at ``candidate_period``.

    Seasonality is assessed on the **first-differenced** series. The raw ACF of a
    trending series decays smoothly and will show high autocorrelation at every
    lag, which is level persistence rather than seasonality; differencing removes
    the trend so genuine seasonal spikes stand out.
    """
    notes: list[str] = []
    adf_stat, adf_p = adf_test(series)

    # KPSS p-values come from a lookup table covering 0.01-0.10; outside it,
    # statsmodels returns the table edge and warns, so report it as a bound.
    kpss_p: float | None
    kpss_bound = ""
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", InterpolationWarning)
            kpss_p = float(kpss(series.dropna(), regression="c", nlags="auto")[1])
        if any(issubclass(w.category, InterpolationWarning) for w in caught):
            kpss_bound = "<" if kpss_p <= 0.01 else ">"
    except (ValueError, np.linalg.LinAlgError):
        kpss_p = None

    stationary = adf_p < 0.05
    if kpss_p is not None and stationary and kpss_p < 0.05:
        notes.append("ADF and KPSS disagree — consistent with a trend-stationary series; "
                     "differencing is still advisable.")

    seasonal_acf: dict[int, float] = {}
    seasonal_period = None
    if candidate_period and len(series) > 4 * candidate_period:
        diffed = series.diff().dropna()
        max_lag = min(4 * candidate_period + 2, len(diffed) - 2)
        values = acf(diffed, nlags=max_lag)
        for lag in range(1, max_lag + 1):
            seasonal_acf[lag] = float(values[lag])
        at_period = [values[candidate_period * k] for k in range(1, 5)
                     if candidate_period * k <= max_lag]
        off_period = [values[l] for l in range(1, max_lag + 1) if l % candidate_period != 0]
        if at_period and np.mean(at_period) > 3 * np.mean(np.abs(off_period)):
            seasonal_period = candidate_period
            notes.append(f"Seasonality confirmed at period {candidate_period}: differenced ACF "
                         f"spikes at multiples of {candidate_period} "
                         f"(mean {np.mean(at_period):.3f}) against "
                         f"{np.mean(np.abs(off_period)):.3f} elsewhere.")
        else:
            notes.append(f"No clear seasonality at period {candidate_period}.")
        seasonal_acf = {l: seasonal_acf[l] for l in
                        sorted(set(list(range(1, 9)) + [candidate_period * k for k in range(1, 5)]))
                        if l in seasonal_acf}

    return Diagnosis(len(series), float(adf_stat), float(adf_p), kpss_p,
                     stationary, seasonal_period, seasonal_acf, notes, kpss_bound)


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def forecast_metrics(actual, predicted) -> dict[str, float]:
    """MAE, RMSE and MAPE. MAPE is omitted (NaN) if any actual value is ~0."""
    a = np.asarray(actual, dtype=float)
    f = np.asarray(predicted, dtype=float)
    err = a - f
    mape = np.nan if np.any(np.abs(a) < 1e-9) else float(np.mean(np.abs(err / a)) * 100)
    return {
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err**2))),
        "MAPE_pct": mape,
    }


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

def naive(train: pd.Series, horizon: int) -> np.ndarray:
    """Last observed value carried forward — the baseline every model must beat."""
    return np.repeat(train.iloc[-1], horizon)


def seasonal_naive(train: pd.Series, horizon: int, period: int) -> np.ndarray:
    """Repeat the last full season."""
    last = train.iloc[-period:].values
    return np.tile(last, int(np.ceil(horizon / period)))[:horizon]


def mean_forecast(train: pd.Series, horizon: int) -> np.ndarray:
    return np.repeat(train.mean(), horizon)


def moving_average(train: pd.Series, horizon: int, window: int = 3) -> np.ndarray:
    return np.repeat(train.iloc[-window:].mean(), horizon)


def drift(train: pd.Series, horizon: int) -> np.ndarray:
    slope = (train.iloc[-1] - train.iloc[0]) / (len(train) - 1)
    return train.iloc[-1] + slope * np.arange(1, horizon + 1)


def ses(train: pd.Series, horizon: int):
    fit = SimpleExpSmoothing(train, initialization_method="estimated").fit(optimized=True)
    return fit.forecast(horizon).values, fit


def holt(train: pd.Series, horizon: int, damped: bool = False):
    fit = ExponentialSmoothing(train, trend="add", damped_trend=damped, seasonal=None,
                               initialization_method="estimated").fit(optimized=True)
    return fit.forecast(horizon).values, fit


def holt_winters(train: pd.Series, horizon: int, period: int, damped: bool = True):
    fit = ExponentialSmoothing(train, trend="add", damped_trend=damped, seasonal="add",
                               seasonal_periods=period,
                               initialization_method="estimated").fit(optimized=True)
    return fit.forecast(horizon).values, fit


def sarima(train: pd.Series, horizon: int, order=(1, 1, 1), seasonal_order=(0, 0, 0, 0)):
    fit = SARIMAX(train, order=order, seasonal_order=seasonal_order).fit(disp=False)
    return fit.forecast(horizon).values, fit


def forecast_with_interval(fit, horizon: int, alpha: float = 0.05) -> pd.DataFrame:
    """Point forecast plus a prediction interval from a fitted statsmodels result."""
    res = fit.get_forecast(steps=horizon)
    mean = res.predicted_mean
    ci = res.conf_int(alpha=alpha)
    out = pd.DataFrame({"forecast": mean.values}, index=mean.index)
    out["lower"] = ci.iloc[:, 0].values
    out["upper"] = ci.iloc[:, 1].values
    return out


def evaluate_models(train: pd.Series, test: pd.Series,
                    seasonal_period: int | None = None) -> pd.DataFrame:
    """Fit the model ladder on ``train`` and score every model on ``test``."""
    h = len(test)
    preds: dict[str, np.ndarray] = {
        "Naive (last value)": naive(train, h),
        "Mean (all history)": mean_forecast(train, h),
        "Moving average (3)": moving_average(train, h, 3),
        "Drift": drift(train, h),
    }
    preds["Simple exp smoothing"] = ses(train, h)[0]
    preds["Holt (additive trend)"] = holt(train, h, damped=False)[0]
    preds["Holt (damped trend)"] = holt(train, h, damped=True)[0]

    if seasonal_period:
        preds[f"Seasonal naive ({seasonal_period})"] = seasonal_naive(train, h, seasonal_period)
        try:
            preds["Holt-Winters (seasonal)"] = holt_winters(train, h, seasonal_period)[0]
        except Exception:
            pass

    for order in [(1, 1, 0), (0, 1, 1), (1, 1, 1)]:
        try:
            preds[f"ARIMA{order}"] = sarima(train, h, order=order)[0]
        except Exception:
            pass

    if seasonal_period:
        try:
            so = (1, 0, 1, seasonal_period)
            preds[f"SARIMA(1,1,1){so}"] = sarima(train, h, (1, 1, 1), so)[0]
        except Exception:
            pass

    rows = [{"model": name, **forecast_metrics(test, p)} for name, p in preds.items()]
    out = pd.DataFrame(rows).set_index("model").sort_values("MAE")
    baseline = out.loc["Naive (last value)", "MAE"]
    out["vs_naive_pct"] = (out["MAE"] / baseline - 1) * 100
    return out
