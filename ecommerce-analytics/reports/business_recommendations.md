# Business Recommendations
## Olist Brazilian E-Commerce Marketplace — Customer & Revenue Intelligence

**Analysis period:** January 2017 – August 2018 (20 months)
**Basis:** 96,211 delivered orders · R$13,181,027 revenue · 93,104 customers · 32,081 products · 74 categories
**Source:** Phases 4–12 of this project. Every recommendation cites the notebook it comes from.
Section numbers (§) refer to the section lists in the README's *Notebook guide*.

---

## Executive summary

Three findings dominate everything else, and together they overturn the strategy a conventional
e-commerce analysis would recommend.

**1. This is an acquisition business, not a retention business — and the data says so emphatically.**
97.0% of customers buy exactly once, and **98.2% of every cohort's revenue arrives in its
acquisition month**. Repeat buyers contribute 5.5% of revenue. This is not a leaky-bucket problem
to be fixed; it is the shape of the business.

**2. The usual retention playbook would waste money here.** The ceiling is measurable and it is
low. Even customers with a perfect 5-star first experience return only ~3.3% of the time. Our
statistical test (Phase 11) shows eliminating *every* late first delivery would generate roughly
**40 additional repeat customers — about R$5,000 of revenue**. A loyalty programme aimed at
"Champions" would address **156 people, 0.17% of the base**.

**3. Revenue is driven by unit price, not basket size.** Average unit price explains **87%** of the
variance in order value; basket size explains 2.4%. And larger baskets contain *cheaper* items. The
lever is category and price mix, not cross-sell.

**What follows from this:** spend on acquisition and on category mix, treat delivery quality as a
brand and marketplace-health issue rather than a retention investment, and set realistic
expectations for CRM.

**One important data correction.** An earlier reading of the monthly series suggested revenue fell
12% from May to August 2018. Phase 12 found this was an artefact — the data export thins from
22 August and stops on 29 August. On a like-for-like days 1–21 basis, **August ran 45.8% above July
and within 1.5% of May**. There is no end-of-period collapse; 2018 was flat-to-volatile, not
declining.

---

## Priority summary

| # | Recommendation | Expected impact | Confidence | Effort |
|---|---|---|---|---|
| 1 | Rebalance category investment toward growing categories | High | High | Low |
| 2 | Shift acquisition spend toward high-AOV regions and categories | High | Medium | Medium |
| 3 | Fix delivery reliability with the worst sellers | Medium (brand), Low (revenue) | High | Medium |
| 4 | Run a real second-purchase experiment in the 30-day window | Medium | Medium | Low |
| 5 | Target the 15,219 "Potential Loyalists" with a category-adjacent offer | Medium | Medium | Low |
| 6 | Plan flat, not growth — reset the forecast baseline | Planning accuracy | High | Low |
| 7 | Attack freight friction on cheap/bulky categories | Medium | Medium | Medium |
| 8 | Do **not** build a loyalty programme | Cost avoidance | High | None |
| 9 | Instrument marketing and cost data | Enables everything | High | High |

---

## 1. Rebalance category investment — the 2018 stall is a rotation, not a slowdown

**Recommendation.** Shift promotional space, homepage placement and seller recruitment toward the
six categories with positive momentum, and review the six in steep decline.

**Evidence** (Phase 9, `07_product_analytics.ipynb` §5). Comparing Jun–Aug 2018 against Mar–May 2018:

| Growing | Change | % | | Declining | Change | % |
|---|---|---|---|---|---|---|
| health_beauty | +R$59,580 | +22.1% | | computers_accessories | −R$69,789 | −36.2% |
| housewares | +R$35,019 | +24.6% | | sports_leisure | −R$56,868 | −27.5% |
| telephony | +R$25,720 | +42.9% | | watches_gifts | −R$53,690 | −17.7% |
| pet_shop | +R$20,052 | +46.2% | | baby | −R$47,623 | −39.3% |
| construction_tools | +R$17,973 | +41.7% | | cool_stuff | −R$46,503 | −45.3% |
| computers | +R$10,603 | +47.2% | | office_furniture | −R$39,586 | −55.2% |

The aggregate plateau is the **net** of these two movements. `health_beauty` — the largest category
at 9.3% of revenue — is still growing 22%.

**Actions.**
- Increase merchandising for `health_beauty`, `housewares`, `telephony` and `pet_shop` immediately;
  all four are growing >20% and three are >40%.
- Commission a review of `computers_accessories` (the single largest revenue loss) covering seller
  availability, pricing and stock — it fell R$69,789 in one quarter.
- Recruit sellers into the growing categories rather than uniformly.

**Caveat — read this before acting.** Mar–May vs Jun–Aug crosses from autumn into winter in Brazil,
and with only one year of history **seasonality cannot be separated from trend**. `sports_leisure`
and `garden_tools` declining into winter is exactly what seasonality would look like. Treat the
*growing* list as the more reliable signal — winter gains are harder to explain away than winter
losses — and re-check against a second year before cutting anything.

---

## 2. Shift acquisition toward high-value regions and categories

**Recommendation.** Move acquisition spend at the margin away from São Paulo volume and toward
higher-AOV states and premium categories.

**Evidence** (Phase 4 `03_eda.ipynb` §2.4; Phase 10 `08_marketing_analysis.ipynb` §3).

- São Paulo is **42.0% of orders and 38.4% of revenue but has the lowest AOV of any state**:
  **R$125.12** against a national R$137.00.
- High-AOV states: **PB R$218.09, CE R$171.33, PE R$157.93, BA R$151.66** — all with far lower volume.
- Growth in 2018 was **100% volume-driven**: comparing Jan–Aug 2018 to 2017, revenue +141.1%,
  orders +139.9%, **AOV +0.5%**.

The business has proven it can scale customer acquisition 8× **without diluting customer quality**
— revenue per customer held in a narrow R$131–R$160 band across all 20 cohorts (Phase 8, §1). What
it has not done is improve what each customer is worth.

**Actions.**
- Test acquisition campaigns in the north-east (BA, PE, CE, PB) where AOV runs 21–74% above SP.
- Weight acquisition creative toward premium categories (`watches_gifts` at R$198.71 average item
  price, `cool_stuff` at R$164.15) rather than budget-volume categories.
- Set an **AOV target** alongside the order-volume target. Two years of growth moved AOV 0.5%.

**Caveat.** Distance, income, category mix and freight are confounded in this data and cannot be
separated. Higher AOV in remote states may reflect customers consolidating purchases *because*
shipping is slow and expensive — in which case improving delivery there could *reduce* AOV even
while improving satisfaction. Treat the regional expansion as a **test**, not a certainty.

---

## 3. Fix delivery reliability — for the brand, not for retention

**Recommendation.** Prioritise on-time delivery with the worst-performing high-volume sellers.
Justify it on satisfaction and marketplace reputation — **not** on a retention business case.

**Evidence** (Phase 11 `09_ab_testing.ipynb` Tests 2 and 3).

- **Late delivery is the strongest relationship in the entire dataset.** One-star review rate is
  **46.20% when late vs 6.57% when on time — a 7.0× difference** (χ² = 12,573, p < 10⁻³⁰⁰,
  Cramér's V = 0.363, a large effect). Median delivery time rises monotonically as ratings fall:
  9.2 days for 5-star, 16.8 days for 1-star.
- **8.1% of orders (7,827) arrived after the promised date.**
- **But the retention value is negligible.** Repeat rate after a late first order is 2.51% vs 3.04%
  on time — statistically significant (z = −2.57, p = 0.010) but Cohen's h = 0.03. Eliminating all
  late first deliveries yields roughly **40 extra repeat customers ≈ R$5,000**.

**Actions.**
- Work the seller tail: Phase 10 (§4) identifies high-volume sellers whose late rates are multiples
  of the marketplace average, with the revenue exposure quantified.
- Address the north-east service gap: Bahia averages **19.3 days and a 14.1% late rate** against
  São Paulo's **8.7 days and 5.9%**.
- **Set expectations honestly internally.** Delivery estimates are already systematically padded —
  on-time orders arrive a mean 13.0 days *early*, while late ones are 9.6 days late. The problem is
  variance, not average optimism.

**Why this still matters despite the small retention effect.** Reviews are public. A 46% one-star
rate on late orders damages conversion for every future visitor, and in a marketplace it damages
seller quality perception. That is the business case — and it is a real one — but it should not be
sold internally as a retention play, because the retention numbers will not deliver.

---

## 4. Run a real second-purchase experiment — in the first 30 days

**Recommendation.** Test a second-purchase offer targeted at the **7–30 day** window after a first
delivery. Run it as a proper randomised experiment with a holdout.

**Evidence** (Phase 6 `04_customer_analytics.ipynb` §3).

Of the 3,107 repurchase events observed:

| within | share of repurchases |
|---|---|
| 7 days | **35.5%** |
| 30 days | **50.2%** |
| 90 days | 69.0% |
| 365 days | 97.5% |

**Half of all second orders arrive within 30 days.** Any win-back campaign firing at 60 or 90 days
is aimed at a window that has largely closed.

**Actions.**
- Trigger a category-adjacent offer at **day 7–10 after delivery confirmation**, not on a monthly
  CRM cycle.
- Randomise: hold back 20% as a control. **This dataset contains no experiment, so every
  relationship in this project is observational** — a real holdout would be the first genuinely
  causal evidence the business has.
- Measure on incremental second orders, not open rate.

**Caveat.** The 7-day cluster (35.5% of repurchases) is suspicious: it is likely to include the
*same shopping intent split across two orders* — a forgotten item, a second seller, a failed first
attempt — rather than genuine re-activation. There is no session or basket identifier to separate
them. Expect the addressable portion to be smaller than the headline.

---

## 5. Target "Potential Loyalists" — the segment that actually holds the money

**Recommendation.** Concentrate CRM effort on the 15,219 recent, high-value, single-purchase
customers, and ignore the conventional loyalty segments.

**Evidence** (Phase 6–7, `05_rfm_segmentation.ipynb`).

| Segment | Customers | % of base | % of revenue |
|---|---|---|---|
| **Potential Loyalists** (recent, high value, 1–2 orders) | 15,219 | 16.4% | **31.2%** |
| **At Risk** (lapsed, historically high value) | 14,339 | 15.4% | **30.4%** |
| Needs Attention | 18,614 | 20.0% | 18.9% |
| Lost | 22,796 | 24.5% | 9.7% |
| New Customers | 21,980 | 23.6% | 9.3% |
| **Champions + Loyal** | **156** | **0.17%** | **0.55%** |

Two segments hold **61.6% of revenue**, and both consist mainly of *one-time* high-value buyers.

K-Means (Phase 7) independently reached the same structure: its **"High-value single buyers"
cluster is 37.3% of customers and 69.8% of revenue**, and 95.0% of Potential Loyalists fall inside
it. Two different methods converging on the same group is the strongest segmentation evidence in
the project.

**Actions.**
- Use the **K-Means cluster for audience selection** (derived from the data's actual variance) and
  **RFM labels for campaign framing** (more legible to a marketing team). They measure different
  things — see the ARI of 0.36 in Phase 7.
- Build the "Potential Loyalist" offer around **category adjacency**, since these customers bought
  once in one category.
- Treat **At Risk** (30.4% of revenue, average recency 393 days) as a win-back list — but size the
  expectation using the retention ceiling in §3, not standard win-back benchmarks.

---

## 6. Plan flat — reset the forecast baseline

**Recommendation.** Budget on a flat revenue baseline of approximately **R$850,000/month**, with
explicit uncertainty bands. Do not plan on a continuation of 2017 growth.

**Evidence** (Phase 12 `10_forecasting.ipynb`).

- The best-performing monthly model is a **3-month moving average** (MAE R$62,622, MAPE 7.13%, 31%
  better than the naive baseline), implying **~R$854,000/month**.
- **Trend-extrapolating models fail badly**: Holt, Drift and the historical mean are **150–210%
  worse than naive**, and Holt's fitted trend parameter collapsed to ≈ 0. The series flattened after
  2017; models projecting the old growth rate overshoot severely. This is the clearest statistical
  evidence that the 2017 growth rate is over.
- The 95% prediction interval spans **±29% in month 1, widening to ±44% by month 3**.

**Actions.**
- Set the planning baseline at R$850k/month and **plan against the interval**, not the point.
- **Add a manual November uplift.** The model structurally cannot anticipate Black Friday — there is
  only one year of history, so annual seasonality is not estimable and no SARIMA(m=12) was fitted.
  November 2017 ran **52% above October**, and 24 November 2017 alone was **7.8× a median day**.
- Re-baseline once 24+ months of history exist, at which point seasonal models become legitimate.

**Caveat.** 20 monthly observations is far below what ARIMA normally requires (~50), and model
ranking rests on only four held-out months. The robust conclusion is *"flat beats trending"*; the
precise ordering of the middle of the model table is not robust.

---

## 7. Attack freight friction on cheap, bulky categories

**Recommendation.** Introduce free-shipping thresholds or bundling for low-price, high-freight
categories.

**Evidence** (Phase 9 `07_product_analytics.ipynb` §6). Freight is **16.6% of revenue** overall, but
the burden is strongly regressive: the correlation between average selling price and freight-as-%-of-
revenue is **r = −0.75**. In cheap, bulky categories freight approaches a third of item value. By
region it ranges from **13.9% in São Paulo to 19.8% in Bahia** (Phase 5, `revenue_analysis.sql`).

Because freight is paid by the customer, a high ratio is **conversion friction** — the part of the
price that delivers no product value.

**Actions.**
- Pilot a free-shipping threshold on the worst-affected categories and measure conversion and AOV.
- Consider regional fulfilment for the north-east, where both freight burden and delivery time are
  worst.

**Caveat — important.** **This dataset has no cost data**, so whether absorbing freight is
affordable **cannot be determined here**. This recommendation identifies where friction is highest;
the finance decision needs cost inputs the data does not contain.

---

## 8. Do **not** build a loyalty programme

**Recommendation.** Decline any proposal for a points-based or tiered loyalty scheme. Revisit only
if the repeat rate structurally changes.

**Evidence.**
- **97.0% of customers buy exactly once** (Phase 6).
- **98.2% of cohort revenue arrives in the acquisition month**; only 1.8% — R$234,882 of R$13.18M —
  ever arrives later (Phase 8 §5).
- **Month-1 retention averages 0.48%**, falling to 0.25% by month 3 (Phase 8 §3). The cohort
  heatmap requires a **0–1% colour scale** to show anything at all.
- **Champions + Loyal = 156 customers.** A tiered programme would be designed for 0.17% of the base.
- Repeat buyers have a **lower AOV** than one-time buyers (R$123 vs R$138) — they are not the
  premium customers loyalty schemes assume.

**A genuine cohort check, because this is a strong claim.** Newer cohorts *appear* to repeat far
less than older ones (7.2% → 0.6%), which might suggest a worsening problem worth fixing. That is an
artefact: the naive series correlates **r = 0.92** with how long each cohort has been observed. On
an equal 3-month window, 2017 H1 cohorts repeat at **0.978%** and 2018 cohorts at **0.976%** — a
difference of −0.001 pp (Phase 8 §4). **Retention is not deteriorating. It has always been
near-zero, and it is structural.**

**What to do instead.** Redirect the budget to acquisition (§2) and category mix (§1), where the
same spend addresses 100% of revenue rather than 5.5%.

---

## 9. Instrument the data you do not have

The single highest-leverage action is not analytical — it is **collecting three missing datasets**.
Each currently blocks a class of decision entirely.

### a. Cost of goods → unlocks profitability
**Currently impossible:** gross margin, contribution per product/category, the standard
margin-vs-volume quadrant, and any statement about which products *make money*. Phase 9 substituted
a price-vs-volume quadrant and could only define "worst performer" as *"sells little"*, never
*"loses money"*.

**The specific question this blocks:** 55.0% of products sold exactly once, and they carry **21.5%
of revenue** at an above-average price. Is that profitable marketplace breadth or dead inventory?
**That is a R$2.8M question and it cannot be answered without a cost field.**

### b. Marketing channel and spend → unlocks attribution
**Currently impossible:** CAC, ROAS, channel mix, first/last-touch attribution, conversion rate,
campaign lift. There is no campaign, channel, session, referrer or spend field anywhere in the data.

**Minimum needed** (Phase 10 §6): a session log with channel/source/campaign, a visitor→customer
mapping, and a campaign spend table. Until then, §2's regional recommendation cannot be costed.

### c. Experiment infrastructure → unlocks causality
**Every finding in this project is observational.** Phase 11 was run as a genuine quasi-experiment
with full statistical rigour, and it still cannot establish cause. The instalment finding is the
sharpest example: AOV rises from **R$82.89 (paid in full) to R$322.07 (11+ instalments)** — nearly
4×. But there are two equally consistent readings: instalments *enable* larger baskets, or expensive
purchases *attract* instalments. **The first implies a major revenue lever; the second implies
none.** No analysis of this dataset can tell them apart. A randomised test of instalment prominence
would settle it in weeks.

---

## What this analysis cannot tell you

Stated plainly, so these recommendations are not over-read:

1. **Nothing about profit.** No cost data exists. Every "performance" figure is revenue, price or
   volume.
2. **Nothing about marketing effectiveness.** No channel, campaign or spend data exists. Section 2
   identifies *where* value is, not *how to buy it*.
3. **No causal claims.** No experiment, no randomisation, no control group. Phase 11's tests are
   observational and labelled as such.
4. **Nothing about customers beyond geography.** No age, gender, income or demographics.
5. **Seasonality is largely unidentified.** One year of usable history means no category decline or
   monthly dip can be separated from a seasonal pattern.
6. **The data ends in August 2018.** This is a historical dataset; none of it describes current
   conditions.

---

## Recommendation-to-evidence index

| # | Recommendation | Source |
|---|---|---|
| 1 | Rebalance category investment | `07_product_analytics.ipynb` §5 |
| 2 | Shift acquisition to high-AOV regions | `03_eda.ipynb` §2.4, §3; `08_marketing_analysis.ipynb` §3 |
| 3 | Fix delivery reliability | `09_ab_testing.ipynb` Tests 2–3; `08_marketing_analysis.ipynb` §4 |
| 4 | Second-purchase experiment | `04_customer_analytics.ipynb` §3–4 |
| 5 | Target Potential Loyalists | `05_rfm_segmentation.ipynb` §2–4 |
| 6 | Plan flat | `10_forecasting.ipynb` §3–5 |
| 7 | Freight friction | `07_product_analytics.ipynb` §6; `sql/revenue_analysis.sql` |
| 8 | No loyalty programme | `06_cohort_analysis.ipynb` §3–5; `04_customer_analytics.ipynb` §3 |
| 9 | Instrument missing data | `07_product_analytics.ipynb` §2; `08_marketing_analysis.ipynb` §6; `09_ab_testing.ipynb` §6 |
