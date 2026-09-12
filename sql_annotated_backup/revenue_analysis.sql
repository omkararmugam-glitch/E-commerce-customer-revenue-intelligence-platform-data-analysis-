-- ============================================================================
-- revenue_analysis.sql — revenue trend, growth and contribution
--
-- Analysis base: delivered orders, 2017-01-01..2018-08-31 (v_analysis_orders).
-- Revenue = order_items.price. Freight is reported separately, never summed in.
--
-- Queries are separated by "-- name:" markers, which sql/build_db.py uses to
-- run and label each one.
-- ============================================================================


-- name: monthly_revenue_and_growth
-- Monthly revenue with MoM growth (LAG), a 3-month moving average
-- (AVG OVER a sliding frame) and a running cumulative total (SUM OVER).
WITH monthly AS (
    SELECT
        v.order_month,
        COUNT(DISTINCT v.order_id)          AS orders,
        COUNT(DISTINCT v.customer_unique_id) AS customers,
        ROUND(SUM(i.revenue), 2)            AS revenue
    FROM v_analysis_items AS i
    JOIN v_analysis_orders AS v ON v.order_id = i.order_id
    GROUP BY v.order_month
)
SELECT
    order_month,
    orders,
    customers,
    revenue,
    ROUND(revenue / orders, 2)                                   AS aov,
    LAG(revenue) OVER (ORDER BY order_month)                     AS prev_month_revenue,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY order_month))
          / LAG(revenue) OVER (ORDER BY order_month), 2)         AS mom_growth_pct,
    ROUND(AVG(revenue) OVER (ORDER BY order_month
                             ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2)
                                                                 AS revenue_3mo_moving_avg,
    ROUND(SUM(revenue) OVER (ORDER BY order_month
                             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 2)
                                                                 AS cumulative_revenue,
    ROUND(100.0 * revenue / SUM(revenue) OVER (), 2)             AS pct_of_total_revenue
FROM monthly
ORDER BY order_month;


-- name: yoy_growth_comparable_window
-- Year-on-year growth on a LIKE-FOR-LIKE Jan-Aug window. Comparing full years
-- would be invalid: 2017 has 12 months of data, 2018 only 8.
WITH jan_aug AS (
    SELECT
        v.order_year,
        v.order_id,
        v.customer_unique_id,
        i.revenue
    FROM v_analysis_items AS i
    JOIN v_analysis_orders AS v ON v.order_id = i.order_id
    WHERE CAST(substr(v.order_month, 6, 2) AS INTEGER) <= 8
),
by_year AS (
    SELECT
        order_year,
        COUNT(DISTINCT order_id)           AS orders,
        COUNT(DISTINCT customer_unique_id) AS customers,
        ROUND(SUM(revenue), 2)             AS revenue
    FROM jan_aug
    GROUP BY order_year
)
SELECT
    order_year,
    orders,
    customers,
    revenue,
    ROUND(revenue / orders, 2)                                          AS aov,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY order_year))
          / LAG(revenue) OVER (ORDER BY order_year), 2)                 AS revenue_yoy_pct,
    ROUND(100.0 * (orders - LAG(orders) OVER (ORDER BY order_year))
          / LAG(orders) OVER (ORDER BY order_year), 2)                  AS orders_yoy_pct,
    ROUND(100.0 * ((revenue / orders) - LAG(revenue / orders) OVER (ORDER BY order_year))
          / LAG(revenue / orders) OVER (ORDER BY order_year), 2)        AS aov_yoy_pct
FROM by_year
ORDER BY order_year;


-- name: quarterly_revenue_with_lead
-- Quarterly revenue using both LAG and LEAD, so each row can see the quarter
-- behind and ahead. 2018Q3 holds only July+August — flagged, not silently compared.
WITH quarterly AS (
    SELECT
        v.order_quarter,
        COUNT(DISTINCT v.order_id) AS orders,
        ROUND(SUM(i.revenue), 2)   AS revenue
    FROM v_analysis_items AS i
    JOIN v_analysis_orders AS v ON v.order_id = i.order_id
    GROUP BY v.order_quarter
)
SELECT
    order_quarter,
    orders,
    revenue,
    LAG(revenue)  OVER (ORDER BY order_quarter) AS prev_quarter,
    LEAD(revenue) OVER (ORDER BY order_quarter) AS next_quarter,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY order_quarter))
          / LAG(revenue) OVER (ORDER BY order_quarter), 2) AS qoq_growth_pct,
    CASE WHEN order_quarter = '2018Q3'
         THEN 'PARTIAL - Jul+Aug only, QoQ not comparable'
         ELSE 'complete' END AS data_completeness
FROM quarterly
ORDER BY order_quarter;


-- name: revenue_contribution_by_category
-- Revenue contribution and Pareto position per category, using RANK,
-- a window SUM for the share, and a running cumulative share.
WITH category_revenue AS (
    SELECT
        category,
        COUNT(*)                          AS items_sold,
        COUNT(DISTINCT order_id)          AS orders,
        ROUND(SUM(revenue), 2)            AS revenue,
        ROUND(AVG(revenue), 2)            AS avg_item_price
    FROM v_analysis_items
    GROUP BY category
)
SELECT
    RANK() OVER (ORDER BY revenue DESC)                       AS revenue_rank,
    category,
    orders,
    items_sold,
    revenue,
    avg_item_price,
    ROUND(100.0 * revenue / SUM(revenue) OVER (), 2)          AS pct_of_revenue,
    ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue DESC
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / SUM(revenue) OVER (), 2)                          AS cumulative_pct,
    CASE
        WHEN 100.0 * SUM(revenue) OVER (ORDER BY revenue DESC
                                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             / SUM(revenue) OVER () <= 50 THEN 'top 50% of revenue'
        WHEN 100.0 * SUM(revenue) OVER (ORDER BY revenue DESC
                                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             / SUM(revenue) OVER () <= 80 THEN 'next 30%'
        ELSE 'long tail'
    END                                                       AS pareto_band
FROM category_revenue
ORDER BY revenue DESC
LIMIT 20;


-- name: revenue_by_region
-- Revenue by state with each state's share, its rank, and its AOV compared to
-- the national average — the comparison that shows the biggest market is the
-- cheapest one.
WITH state_revenue AS (
    SELECT
        v.customer_state,
        COUNT(DISTINCT v.order_id)           AS orders,
        COUNT(DISTINCT v.customer_unique_id) AS customers,
        ROUND(SUM(i.revenue), 2)             AS revenue
    FROM v_analysis_items AS i
    JOIN v_analysis_orders AS v ON v.order_id = i.order_id
    GROUP BY v.customer_state
),
national AS (
    SELECT SUM(revenue) AS total_revenue, SUM(orders) AS total_orders
    FROM state_revenue
)
SELECT
    ROW_NUMBER() OVER (ORDER BY sr.revenue DESC)              AS revenue_rank,
    sr.customer_state,
    sr.orders,
    sr.customers,
    sr.revenue,
    ROUND(100.0 * sr.revenue / n.total_revenue, 2)            AS pct_of_revenue,
    ROUND(sr.revenue / sr.orders, 2)                          AS state_aov,
    ROUND(n.total_revenue / n.total_orders, 2)                AS national_aov,
    ROUND(sr.revenue / sr.orders - n.total_revenue / n.total_orders, 2)
                                                              AS aov_vs_national,
    DENSE_RANK() OVER (ORDER BY sr.revenue / sr.orders DESC)  AS aov_rank
FROM state_revenue AS sr
CROSS JOIN national AS n
ORDER BY sr.revenue DESC
LIMIT 15;


-- name: monthly_revenue_by_top_category
-- Trend per category for the top 5 categories, with each category's own MoM
-- growth (PARTITION BY keeps the LAG inside the category).
--
-- Written so the base view is scanned ONCE: aggregate first, then rank the
-- aggregate. A "JOIN (SELECT ... ORDER BY SUM(revenue) DESC LIMIT 5)" instead
-- makes SQLite re-evaluate the subquery per row and turns this into a
-- multi-minute query.
WITH monthly_cat AS (
    SELECT
        category,
        order_month,
        ROUND(SUM(revenue), 2) AS revenue
    FROM v_analysis_items
    GROUP BY category, order_month
),
category_rank AS (
    SELECT
        category,
        RANK() OVER (ORDER BY SUM(revenue) DESC) AS category_rank
    FROM monthly_cat
    GROUP BY category
)
SELECT
    m.category,
    m.order_month,
    m.revenue,
    LAG(m.revenue) OVER (PARTITION BY m.category ORDER BY m.order_month) AS prev_month,
    ROUND(100.0 * (m.revenue - LAG(m.revenue) OVER (PARTITION BY m.category ORDER BY m.order_month))
          / LAG(m.revenue) OVER (PARTITION BY m.category ORDER BY m.order_month), 2) AS mom_pct,
    ROUND(AVG(m.revenue) OVER (PARTITION BY m.category ORDER BY m.order_month
                               ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS moving_avg_3mo
FROM monthly_cat   AS m
JOIN category_rank AS cr ON cr.category = m.category
WHERE cr.category_rank <= 5
  AND m.order_month >= '2018-03'
ORDER BY m.category, m.order_month;


-- name: freight_burden_by_region
-- Freight as a share of item value by state. Freight is a cost to the customer,
-- so this is a friction measure, not a margin measure — there is no cost data
-- in this dataset, so true margin cannot be computed.
SELECT
    customer_state,
    COUNT(*)                                               AS item_lines,
    ROUND(SUM(revenue), 2)                                 AS revenue,
    ROUND(SUM(freight_value), 2)                           AS freight,
    ROUND(100.0 * SUM(freight_value) / SUM(revenue), 2)    AS freight_pct_of_revenue,
    ROUND(AVG(freight_value), 2)                           AS avg_freight_per_item,
    RANK() OVER (ORDER BY SUM(freight_value) / SUM(revenue) DESC) AS freight_burden_rank
FROM v_analysis_items
GROUP BY customer_state
HAVING COUNT(*) >= 500
ORDER BY freight_pct_of_revenue DESC;
