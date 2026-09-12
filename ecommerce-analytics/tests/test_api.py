import pytest
from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def get(path, **params):
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_health():
    body = get("/health")
    assert body == {"status": "ok", "orders": 96211, "customers": 93104}


def test_filters():
    body = get("/filters")
    assert body["years"] == [2017, 2018]
    assert body["states"][0] == "SP"
    assert body["payments"][0] == "credit_card"


def test_kpis_unfiltered_match_notebooks():
    k = get("/kpis")
    assert k["revenue"] == pytest.approx(13_181_027.13, abs=0.01)
    assert k["orders"] == 96211
    assert k["customers"] == 93104
    assert k["aov_median"] == pytest.approx(86.50)
    assert k["aov_mean"] == pytest.approx(137.00, abs=0.01)
    assert k["late_rate"] == pytest.approx(0.0813, abs=0.0005)
    assert k["one_star_rate"] == pytest.approx(0.0975, abs=0.0005)
    assert k["repeat_rate"] == pytest.approx(0.030, abs=0.0005)


@pytest.mark.parametrize("params, revenue, aov", [
    ({"year": 2018}, 7_218_125.12, None),
    ({"state": "SP"}, 5_055_587.13, 125.12),
    ({"payment": "boleto"}, 2_323_387.90, 121.39),
])
def test_kpis_filters(params, revenue, aov):
    k = get("/kpis", **params)
    assert k["revenue"] == pytest.approx(revenue, abs=0.01)
    if aov is not None:
        assert k["aov_mean"] == pytest.approx(aov, abs=0.01)


@pytest.mark.parametrize("params", [{"state": "XX"}, {"payment": "bitcoin"}, {"year": 2016}])
def test_invalid_filters_rejected(params):
    assert client.get("/kpis", params=params).status_code == 422


def test_monthly_revenue_flags_partial_august():
    months = {m["month"]: m for m in get("/revenue/monthly")}
    assert len(months) == 20
    assert months["2017-11"]["revenue"] == pytest.approx(987_765.37, abs=0.01)
    assert months["2018-08"]["partial_month"] is True
    assert months["2018-08"]["mom_pct"] is None


def test_category_revenue_reconciles_with_orders():
    cats = get("/revenue/by-category", limit=80)
    assert sum(c["revenue"] for c in cats) == pytest.approx(13_181_027.13, abs=1)
    assert cats[0]["category"] == "health_beauty"


def test_segments_match_notebook_05():
    rfm = {s["segment"]: s for s in get("/customers/segments", by="rfm")}
    assert rfm["Potential Loyalists"]["revenue_pct"] == pytest.approx(31.16, abs=0.01)
    assert rfm["Champions"]["customers"] == 113
    km = {s["segment"]: s for s in get("/customers/segments", by="kmeans")}
    assert km["High-value single buyers"]["revenue_pct"] == pytest.approx(69.82, abs=0.01)


def test_retention_curve_is_not_flat():
    curve = {r["month"]: r["retention_pct"] for r in get("/customers/retention")}
    assert curve[1] == pytest.approx(0.476, abs=0.01)
    assert curve[3] == pytest.approx(0.251, abs=0.01)


def test_pareto():
    p = get("/products/pareto")
    assert p["products_for_80pct"] == 8310
    assert p["sold_once_pct"] == pytest.approx(55.0, abs=0.1)
    assert len(p["curve"]) == 100


def test_experiments_match_notebook_09():
    t1, t2, t3 = get("/experiments")["tests"]
    assert t1["difference"] == pytest.approx(21.80, abs=0.01)
    assert t1["ci_95"] == pytest.approx([18.56, 25.05], abs=0.01)
    assert t1["effect_size"]["cohens_d"] == pytest.approx(0.1035, abs=0.001)
    assert t2["groups"]["late"]["one_star_rate"] == pytest.approx(0.4620, abs=0.0005)
    assert t2["effect_size"]["cramers_v"] == pytest.approx(0.3627, abs=0.001)
    assert t3["p_value"] == pytest.approx(0.0100, abs=0.0005)
    assert all(t["decision"] == "reject H0" for t in (t1, t2, t3))


def test_forecast():
    f = get("/forecast")
    assert f["next_month"]["forecast"] == pytest.approx(845_820.75, abs=0.01)
    assert f["next_month"]["lower_95"] == pytest.approx(598_069.17, abs=0.01)
    assert f["model_comparison"][0]["model"] == "Moving average (3)"


def test_recommendations():
    assert "Business Recommendations" in get("/recommendations")["markdown"]


def test_multi_value_filters_combine():
    both = get("/kpis", state=["SP", "RJ"])
    assert both["revenue"] == pytest.approx(5_055_587.13 + 1_751_433.85, abs=0.02)


def test_date_range_filter():
    nov = get("/kpis", date_from="2017-11-01", date_to="2017-11-30")
    assert nov["revenue"] == pytest.approx(987_765.37, abs=0.01)
    assert nov["orders"] == 7289
    assert client.get("/kpis", params={"date_from": "2018-02-01", "date_to": "2018-01-01"}).status_code == 422


def test_customer_filters():
    assert get("/customers/summary", rfm="Champions")["customers"] == 113
    sp = get("/customers/summary", state="SP")
    assert 0 < sp["customers"] < 93104
    top = get("/customers/top", kmeans="Multi-category buyers", limit=5)
    assert len(top) == 5 and all(t["kmeans_segment"] == "Multi-category buyers" for t in top)


def test_live_cohorts_match_notebook_06():
    cohorts = [c for c in get("/customers/cohorts") if c["repeat_rate_3mo_pct"] is not None]
    assert len(cohorts) == 17
    mean = sum(c["repeat_rate_3mo_pct"] for c in cohorts) / len(cohorts)
    assert mean == pytest.approx(1.036, abs=0.005)


def test_retention_responds_to_filters():
    everyone = {r["month"]: r["retention_pct"] for r in get("/customers/retention")}
    repeaters = {r["month"]: r["retention_pct"] for r in get("/customers/retention", rfm="Champions")}
    assert repeaters[1] > everyone[1]


def test_product_filters():
    s = get("/products/summary")
    assert s["revenue"] == pytest.approx(13_181_027.13, abs=0.01)
    assert s["products_for_80pct"] == 8310
    hb = get("/products/summary", category="health_beauty")
    assert hb["revenue"] == pytest.approx(1_229_557.50, abs=0.01)
    cats = {c["category"]: c for c in get("/products/categories")}
    assert cats["health_beauty"]["momentum_change_brl"] == pytest.approx(59_579.5, abs=1)
    quad = get("/products/categories", quadrant="Premium + high volume")
    assert quad and all(c["quadrant"] == "Premium + high volume" for c in quad)


def test_live_marketing_matches_power_bi_tables():
    regions = {r["customer_state"]: r for r in get("/marketing/regions")}
    assert regions["SP"]["aov"] == pytest.approx(125.12, abs=0.01)
    assert regions["SP"]["late_rate_pct"] == pytest.approx(5.90, abs=0.01)
    sellers = get("/marketing/sellers", limit=1)
    assert sellers[0]["revenue"] == pytest.approx(226_987.93, abs=0.01)


def test_experiments_rerun_on_subset():
    sp = get("/experiments", state="SP")
    assert sp["orders_used"] == 40406
    t1 = sp["tests"][0]
    assert not t1["insufficient_data"] and t1["groups"]["credit_card"]["n"] < 72619


@pytest.mark.parametrize("params", [{"category": "not_a_category"}, {"quadrant": "Mega"}, {"rfm": "VIP"}])
def test_invalid_list_filters_rejected(params):
    path = "/customers/summary" if "rfm" in params else "/products/summary"
    assert client.get(path, params=params).status_code == 422
