-- name: top_products_by_revenue
WITH product_perf AS (
    SELECT
        i.product_id,
        i.category,
        COUNT(*)                          AS units_sold,
        COUNT(DISTINCT i.order_id)        AS orders,
        ROUND(SUM(i.revenue), 2)          AS revenue,
        ROUND(AVG(i.revenue), 2)          AS avg_selling_price,
        ROUND(MIN(i.revenue), 2)          AS min_price,
        ROUND(MAX(i.revenue), 2)          AS max_price
    FROM v_analysis_items AS i
    GROUP BY i.product_id, i.category
)
SELECT
    ROW_NUMBER() OVER (ORDER BY revenue DESC)                              AS overall_rank,
    DENSE_RANK() OVER (PARTITION BY category ORDER BY revenue DESC)        AS rank_in_category,
    product_id,
    category,
    units_sold,
    revenue,
    avg_selling_price,
    min_price,
    max_price,
    ROUND(100.0 * revenue / SUM(revenue) OVER (), 3)                       AS pct_of_total_revenue
FROM product_perf
ORDER BY revenue DESC
LIMIT 20;

-- name: worst_performing_products
WITH product_perf AS (
    SELECT
        i.product_id,
        i.category,
        COUNT(*)               AS units_sold,
        ROUND(SUM(i.revenue), 2) AS revenue,
        ROUND(AVG(i.revenue), 2) AS avg_selling_price
    FROM v_analysis_items AS i
    GROUP BY i.product_id, i.category
)
SELECT
    category,
    COUNT(*)                                              AS products_sold_once,
    ROUND(SUM(revenue), 2)                                AS revenue_from_them,
    ROUND(AVG(avg_selling_price), 2)                      AS avg_price,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)    AS pct_of_all_single_sale_products
FROM product_perf
WHERE units_sold = 1
GROUP BY category
ORDER BY products_sold_once DESC
LIMIT 15;

-- name: category_pareto_80_20
WITH category_revenue AS (
    SELECT
        category,
        COUNT(*)                   AS items_sold,
        COUNT(DISTINCT order_id)   AS orders,
        COUNT(DISTINCT product_id) AS products,
        ROUND(SUM(revenue), 2)     AS revenue
    FROM v_analysis_items
    GROUP BY category
),
ranked AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY revenue DESC) AS rank,
        category,
        products,
        items_sold,
        orders,
        revenue,
        ROUND(100.0 * revenue / SUM(revenue) OVER (), 2) AS pct_of_revenue,
        ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue DESC
                                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
              / SUM(revenue) OVER (), 2) AS cumulative_pct,
        ROUND(100.0 * ROW_NUMBER() OVER (ORDER BY revenue DESC)
              / COUNT(*) OVER (), 2)     AS pct_of_categories
    FROM category_revenue
)
SELECT
    rank,
    category,
    products,
    items_sold,
    revenue,
    pct_of_revenue,
    cumulative_pct,
    pct_of_categories,
    CASE WHEN cumulative_pct <= 80 THEN 'within first 80% of revenue'
         ELSE 'tail' END AS pareto_side
FROM ranked
WHERE rank <= 25
ORDER BY rank;

-- name: category_price_and_volume_quadrant
WITH category_stats AS (
    SELECT
        category,
        COUNT(DISTINCT order_id)  AS orders,
        COUNT(*)                  AS units,
        ROUND(SUM(revenue), 2)    AS revenue,
        ROUND(AVG(revenue), 2)    AS avg_price
    FROM v_analysis_items
    GROUP BY category
    HAVING COUNT(*) >= 100
),
positioned AS (
    SELECT
        avg_price,
        units,
        ROW_NUMBER() OVER (ORDER BY avg_price) AS price_pos,
        ROW_NUMBER() OVER (ORDER BY units)     AS units_pos,
        COUNT(*)     OVER ()                   AS n
    FROM category_stats
),
medians AS (
    SELECT
        AVG(CASE WHEN price_pos IN ((n + 1) / 2, (n + 2) / 2) THEN avg_price END) AS med_price,
        AVG(CASE WHEN units_pos IN ((n + 1) / 2, (n + 2) / 2) THEN units     END) AS med_units
    FROM positioned
)
SELECT
    cs.category,
    cs.units,
    cs.revenue,
    cs.avg_price,
    ROUND(m.med_price, 2) AS median_category_price,
    ROUND(m.med_units, 0) AS median_category_units,
    CASE
        WHEN cs.avg_price >= m.med_price AND cs.units >= m.med_units THEN 'premium + high volume (protect)'
        WHEN cs.avg_price >= m.med_price AND cs.units <  m.med_units THEN 'premium + low volume (grow reach)'
        WHEN cs.avg_price <  m.med_price AND cs.units >= m.med_units THEN 'budget + high volume (traffic driver)'
        ELSE 'budget + low volume (review)'
    END AS quadrant
FROM category_stats AS cs
CROSS JOIN medians AS m
ORDER BY cs.revenue DESC
LIMIT 25;

-- name: price_band_analysis
SELECT
    CASE
        WHEN revenue <  25  THEN 'a. under R$25'
        WHEN revenue <  50  THEN 'b. R$25-50'
        WHEN revenue < 100  THEN 'c. R$50-100'
        WHEN revenue < 200  THEN 'd. R$100-200'
        WHEN revenue < 500  THEN 'e. R$200-500'
        WHEN revenue < 1000 THEN 'f. R$500-1000'
        ELSE                     'g. R$1000+'
    END AS price_band,
    COUNT(*)                                                    AS item_lines,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)          AS pct_of_lines,
    ROUND(SUM(revenue), 2)                                      AS revenue,
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2)  AS pct_of_revenue,
    ROUND(AVG(revenue), 2)                                      AS avg_price
FROM v_analysis_items
GROUP BY price_band
ORDER BY price_band;

-- name: category_monthly_momentum
WITH recent AS (
    SELECT
        category,
        SUM(CASE WHEN order_month IN ('2018-06','2018-07','2018-08') THEN revenue ELSE 0 END) AS last_3mo,
        SUM(CASE WHEN order_month IN ('2018-03','2018-04','2018-05') THEN revenue ELSE 0 END) AS prior_3mo
    FROM v_analysis_items
    GROUP BY category
)
SELECT
    category,
    ROUND(prior_3mo, 2) AS revenue_mar_may_2018,
    ROUND(last_3mo, 2)  AS revenue_jun_aug_2018,
    ROUND(last_3mo - prior_3mo, 2) AS change_brl,
    ROUND(100.0 * (last_3mo - prior_3mo) / prior_3mo, 2) AS change_pct,
    RANK() OVER (ORDER BY last_3mo - prior_3mo DESC) AS momentum_rank
FROM recent
WHERE prior_3mo > 20000
ORDER BY change_brl DESC;

-- name: seller_concentration
WITH seller_perf AS (
    SELECT
        seller_id,
        seller_state,
        COUNT(DISTINCT order_id)   AS orders,
        COUNT(*)                   AS items,
        COUNT(DISTINCT product_id) AS products,
        ROUND(SUM(revenue), 2)     AS revenue
    FROM v_analysis_items
    GROUP BY seller_id, seller_state
)
SELECT
    ROW_NUMBER() OVER (ORDER BY revenue DESC) AS seller_rank,
    seller_id,
    seller_state,
    orders,
    items,
    products,
    revenue,
    ROUND(100.0 * revenue / SUM(revenue) OVER (), 3) AS pct_of_revenue,
    ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue DESC
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / SUM(revenue) OVER (), 2) AS cumulative_pct
FROM seller_perf
ORDER BY revenue DESC
LIMIT 20;
