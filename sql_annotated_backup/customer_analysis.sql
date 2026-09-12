-- ============================================================================
-- customer_analysis.sql — customer value, frequency, retention and lifecycle
--
-- Every query keys on customer_unique_id, never customer_id: customer_id is
-- issued per order and would force a 0% repeat rate by construction.
-- ============================================================================


-- name: top_customers_ranked
-- Top customers by lifetime spend, with three ranking functions side by side so
-- the difference is visible: ROW_NUMBER always unique, RANK skips after ties,
-- DENSE_RANK does not. Also shows each customer's share of total revenue.
WITH customer_value AS (
    SELECT
        v.customer_unique_id,
        v.customer_state,
        COUNT(DISTINCT v.order_id)  AS orders,
        ROUND(SUM(i.revenue), 2)    AS lifetime_spend,
        ROUND(AVG(i.revenue), 2)    AS avg_item_price,
        MIN(v.order_date)           AS first_purchase,
        MAX(v.order_date)           AS last_purchase
    FROM v_analysis_items  AS i
    JOIN v_analysis_orders AS v ON v.order_id = i.order_id
    GROUP BY v.customer_unique_id, v.customer_state
)
SELECT
    ROW_NUMBER() OVER (ORDER BY lifetime_spend DESC) AS row_number_rank,
    RANK()       OVER (ORDER BY orders DESC)         AS rank_by_orders,
    DENSE_RANK() OVER (ORDER BY orders DESC)         AS dense_rank_by_orders,
    customer_unique_id,
    customer_state,
    orders,
    lifetime_spend,
    ROUND(lifetime_spend / orders, 2)                AS aov,
    first_purchase,
    last_purchase,
    ROUND(100.0 * lifetime_spend / SUM(lifetime_spend) OVER (), 4) AS pct_of_total_revenue
FROM customer_value
ORDER BY lifetime_spend DESC
LIMIT 20;


-- name: repeat_vs_one_time
-- The central customer fact of this dataset: one-time buyers dominate both the
-- customer base and revenue. Includes the counter-intuitive AOV comparison.
WITH customer_orders AS (
    SELECT
        v.customer_unique_id,
        COUNT(DISTINCT v.order_id) AS orders,
        SUM(i.revenue)             AS lifetime_spend
    FROM v_analysis_items  AS i
    JOIN v_analysis_orders AS v ON v.order_id = i.order_id
    GROUP BY v.customer_unique_id
)
SELECT
    CASE WHEN orders = 1 THEN 'one-time buyer' ELSE 'repeat buyer' END AS customer_type,
    COUNT(*)                                                    AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)          AS pct_of_customers,
    SUM(orders)                                                 AS total_orders,
    ROUND(SUM(lifetime_spend), 2)                               AS total_revenue,
    ROUND(100.0 * SUM(lifetime_spend) / SUM(SUM(lifetime_spend)) OVER (), 2)
                                                                AS pct_of_revenue,
    ROUND(AVG(lifetime_spend), 2)                               AS avg_lifetime_spend,
    ROUND(SUM(lifetime_spend) / SUM(orders), 2)                 AS aov
FROM customer_orders
GROUP BY customer_type
ORDER BY total_revenue DESC;


-- name: order_frequency_distribution
-- How many customers placed exactly N orders, with a running share so the
-- concentration of the base is visible.
WITH customer_orders AS (
    SELECT customer_unique_id, COUNT(DISTINCT order_id) AS orders
    FROM v_analysis_orders
    GROUP BY customer_unique_id
)
SELECT
    orders AS orders_placed,
    COUNT(*) AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 3) AS pct_of_customers,
    SUM(COUNT(*)) OVER (ORDER BY orders
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_customers,
    ROUND(100.0 * SUM(COUNT(*)) OVER (ORDER BY orders
                                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / SUM(COUNT(*)) OVER (), 3) AS cumulative_pct
FROM customer_orders
GROUP BY orders
ORDER BY orders;


-- name: first_and_last_purchase_per_customer
-- Lifecycle view for repeat customers: first purchase, last purchase, the gap
-- between consecutive orders (LAG over each customer's own order sequence),
-- and days since their last order relative to the end of the analysis window.
WITH ordered_purchases AS (
    SELECT
        v.customer_unique_id,
        v.order_id,
        v.order_date,
        ROW_NUMBER() OVER (PARTITION BY v.customer_unique_id ORDER BY v.order_date) AS purchase_seq,
        LAG(v.order_date) OVER (PARTITION BY v.customer_unique_id ORDER BY v.order_date) AS prev_order_date,
        COUNT(*)  OVER (PARTITION BY v.customer_unique_id) AS total_orders,
        FIRST_VALUE(v.order_date) OVER (PARTITION BY v.customer_unique_id
                                        ORDER BY v.order_date) AS first_purchase,
        LAST_VALUE(v.order_date)  OVER (PARTITION BY v.customer_unique_id
                                        ORDER BY v.order_date
                                        ROWS BETWEEN UNBOUNDED PRECEDING
                                                 AND UNBOUNDED FOLLOWING) AS last_purchase
    FROM v_analysis_orders AS v
)
SELECT
    customer_unique_id,
    purchase_seq,
    order_date,
    prev_order_date,
    CAST(julianday(order_date) - julianday(prev_order_date) AS INTEGER) AS days_since_prev_order,
    total_orders,
    first_purchase,
    last_purchase,
    CAST(julianday('2018-08-31') - julianday(last_purchase) AS INTEGER)  AS recency_days
FROM ordered_purchases
WHERE total_orders >= 3
ORDER BY total_orders DESC, customer_unique_id, purchase_seq
LIMIT 25;


-- name: repurchase_gap_summary
-- How long repeat customers wait before buying again — the operative number for
-- timing a second-purchase campaign.
WITH gaps AS (
    SELECT
        customer_unique_id,
        julianday(order_date)
          - julianday(LAG(order_date) OVER (PARTITION BY customer_unique_id
                                            ORDER BY order_date)) AS gap_days
    FROM v_analysis_orders
)
SELECT
    COUNT(*)                     AS repurchase_events,
    ROUND(AVG(gap_days), 1)      AS mean_gap_days,
    ROUND(MIN(gap_days), 1)      AS min_gap_days,
    ROUND(MAX(gap_days), 1)      AS max_gap_days,
    SUM(CASE WHEN gap_days <= 30  THEN 1 ELSE 0 END) AS within_30_days,
    SUM(CASE WHEN gap_days <= 90  THEN 1 ELSE 0 END) AS within_90_days,
    SUM(CASE WHEN gap_days <= 180 THEN 1 ELSE 0 END) AS within_180_days,
    ROUND(100.0 * SUM(CASE WHEN gap_days <= 90 THEN 1 ELSE 0 END) / COUNT(*), 2)
                                 AS pct_within_90_days
FROM gaps
WHERE gap_days IS NOT NULL;


-- name: customer_rfm_scores
-- RFM computed entirely in SQL with NTILE, as a cross-check on the pandas
-- implementation in notebook 05. Reference date is the day after the window
-- closes, so recency is never negative.
WITH customer_base AS (
    SELECT
        v.customer_unique_id,
        CAST(julianday('2018-09-01') - julianday(MAX(v.order_date)) AS INTEGER) AS recency_days,
        COUNT(DISTINCT v.order_id) AS frequency,
        ROUND(SUM(i.revenue), 2)   AS monetary
    FROM v_analysis_items  AS i
    JOIN v_analysis_orders AS v ON v.order_id = i.order_id
    GROUP BY v.customer_unique_id
),
scored AS (
    SELECT
        customer_unique_id,
        recency_days,
        frequency,
        monetary,
        -- recency: lower is better, so the quintile order is inverted
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,
        NTILE(5) OVER (ORDER BY monetary ASC)      AS m_score
    FROM customer_base
)
SELECT
    customer_unique_id,
    recency_days,
    frequency,
    monetary,
    r_score,
    -- frequency is scored by rule, not by quintile: 97% of customers have
    -- frequency = 1, so NTILE would cut an essentially constant column
    CASE WHEN frequency >= 3 THEN 5
         WHEN frequency  = 2 THEN 3
         ELSE 1 END AS f_score,
    m_score,
    r_score || '-' ||
    CASE WHEN frequency >= 3 THEN 5 WHEN frequency = 2 THEN 3 ELSE 1 END || '-' ||
    m_score AS rfm_cell
FROM scored
ORDER BY monetary DESC
LIMIT 20;


-- name: revenue_concentration_by_customer_decile
-- What share of revenue each customer decile holds — the SQL form of the
-- concentration curve in notebook 03.
WITH customer_value AS (
    SELECT
        v.customer_unique_id,
        SUM(i.revenue) AS spend
    FROM v_analysis_items  AS i
    JOIN v_analysis_orders AS v ON v.order_id = i.order_id
    GROUP BY v.customer_unique_id
),
deciled AS (
    SELECT
        customer_unique_id,
        spend,
        NTILE(10) OVER (ORDER BY spend DESC) AS spend_decile
    FROM customer_value
)
SELECT
    spend_decile,
    COUNT(*)                                                  AS customers,
    ROUND(SUM(spend), 2)                                      AS revenue,
    ROUND(100.0 * SUM(spend) / SUM(SUM(spend)) OVER (), 2)    AS pct_of_revenue,
    ROUND(100.0 * SUM(SUM(spend)) OVER (ORDER BY spend_decile
                                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / SUM(SUM(spend)) OVER (), 2)                       AS cumulative_pct,
    ROUND(AVG(spend), 2)                                      AS avg_spend,
    ROUND(MIN(spend), 2)                                      AS min_spend
FROM deciled
GROUP BY spend_decile
ORDER BY spend_decile;


-- name: new_vs_returning_by_month
-- Monthly split of acquisition vs returning demand. With a 3% repeat rate the
-- returning line is expected to be very thin — quantifying it is the point.
WITH first_order AS (
    SELECT
        customer_unique_id,
        MIN(order_month) AS cohort_month
    FROM v_analysis_orders
    GROUP BY customer_unique_id
),
tagged AS (
    SELECT
        v.order_month,
        v.order_id,
        i_rev.revenue,
        CASE WHEN v.order_month = f.cohort_month THEN 'new' ELSE 'returning' END AS customer_type
    FROM v_analysis_orders AS v
    JOIN first_order AS f ON f.customer_unique_id = v.customer_unique_id
    JOIN (SELECT order_id, SUM(revenue) AS revenue
          FROM v_analysis_items GROUP BY order_id) AS i_rev ON i_rev.order_id = v.order_id
)
SELECT
    order_month,
    SUM(CASE WHEN customer_type = 'new'       THEN 1 ELSE 0 END) AS new_customer_orders,
    SUM(CASE WHEN customer_type = 'returning' THEN 1 ELSE 0 END) AS returning_orders,
    ROUND(SUM(CASE WHEN customer_type = 'new'       THEN revenue ELSE 0 END), 2) AS new_revenue,
    ROUND(SUM(CASE WHEN customer_type = 'returning' THEN revenue ELSE 0 END), 2) AS returning_revenue,
    ROUND(100.0 * SUM(CASE WHEN customer_type = 'returning' THEN revenue ELSE 0 END)
          / SUM(revenue), 2) AS returning_revenue_pct
FROM tagged
GROUP BY order_month
ORDER BY order_month;
