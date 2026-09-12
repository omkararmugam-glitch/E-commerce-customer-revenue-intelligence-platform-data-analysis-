-- name: payment_method_performance
WITH order_payment AS (
    SELECT
        p.order_id,
        p.payment_type,
        p.payment_installments,
        ROW_NUMBER() OVER (PARTITION BY p.order_id ORDER BY p.payment_value DESC) AS rn
    FROM payments AS p
    WHERE p.is_valid_payment = 1
),
order_revenue AS (
    SELECT order_id, SUM(revenue) AS revenue FROM v_analysis_items GROUP BY order_id
)
SELECT
    op.payment_type,
    COUNT(*)                                                      AS orders,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)            AS pct_of_orders,
    ROUND(SUM(orv.revenue), 2)                                    AS revenue,
    ROUND(100.0 * SUM(orv.revenue) / SUM(SUM(orv.revenue)) OVER (), 2) AS pct_of_revenue,
    ROUND(AVG(orv.revenue), 2)                                    AS aov,
    ROUND(AVG(op.payment_installments), 2)                        AS avg_installments,
    ROUND(AVG(r.review_score), 3)                                 AS avg_review_score,
    RANK() OVER (ORDER BY AVG(orv.revenue) DESC)                  AS aov_rank
FROM order_payment  AS op
JOIN order_revenue  AS orv ON orv.order_id = op.order_id
LEFT JOIN reviews   AS r   ON r.order_id   = op.order_id
WHERE op.rn = 1
GROUP BY op.payment_type
ORDER BY revenue DESC;

-- name: installment_behaviour
WITH order_payment AS (
    SELECT
        p.order_id,
        p.payment_type,
        MAX(p.payment_installments) AS installments
    FROM payments AS p
    WHERE p.is_valid_payment = 1
    GROUP BY p.order_id, p.payment_type
    HAVING p.payment_type = 'credit_card'
),
order_revenue AS (
    SELECT order_id, SUM(revenue) AS revenue FROM v_analysis_items GROUP BY order_id
)
SELECT
    CASE
        WHEN op.installments = 1            THEN 'a. paid in full (1x)'
        WHEN op.installments BETWEEN 2 AND 3 THEN 'b. 2-3x'
        WHEN op.installments BETWEEN 4 AND 6 THEN 'c. 4-6x'
        WHEN op.installments BETWEEN 7 AND 10 THEN 'd. 7-10x'
        ELSE                                     'e. 11x or more'
    END AS installment_band,
    COUNT(*)                                           AS orders,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_orders,
    ROUND(AVG(orv.revenue), 2)                         AS aov,
    ROUND(SUM(orv.revenue), 2)                         AS revenue,
    ROUND(AVG(r.review_score), 3)                      AS avg_review_score
FROM order_payment AS op
JOIN order_revenue AS orv ON orv.order_id = op.order_id
LEFT JOIN reviews  AS r   ON r.order_id   = op.order_id
GROUP BY installment_band
ORDER BY installment_band;

-- name: regional_performance_scorecard
WITH state_orders AS (
    SELECT
        v.customer_state,
        v.order_id,
        v.delivery_days,
        v.is_late,
        r.review_score
    FROM v_analysis_orders AS v
    LEFT JOIN reviews AS r ON r.order_id = v.order_id
),
state_revenue AS (
    SELECT customer_state, SUM(revenue) AS revenue, SUM(freight_value) AS freight
    FROM v_analysis_items
    GROUP BY customer_state
)
SELECT
    so.customer_state,
    COUNT(*)                                              AS orders,
    ROUND(sr.revenue, 2)                                  AS revenue,
    ROUND(sr.revenue / COUNT(*), 2)                       AS aov,
    ROUND(100.0 * sr.freight / sr.revenue, 2)             AS freight_pct_of_revenue,
    ROUND(AVG(so.delivery_days), 1)                       AS avg_delivery_days,
    ROUND(100.0 * AVG(so.is_late), 2)                     AS late_rate_pct,
    ROUND(AVG(so.review_score), 3)                        AS avg_review_score,
    RANK() OVER (ORDER BY sr.revenue DESC)                AS revenue_rank,
    RANK() OVER (ORDER BY sr.revenue / COUNT(*) DESC)     AS aov_rank,
    RANK() OVER (ORDER BY AVG(so.delivery_days) ASC)      AS speed_rank
FROM state_orders  AS so
JOIN state_revenue AS sr ON sr.customer_state = so.customer_state
GROUP BY so.customer_state
HAVING COUNT(*) >= 500
ORDER BY revenue DESC;

-- name: seller_performance_proxy
WITH seller_orders AS (
    SELECT DISTINCT i.seller_id, i.order_id
    FROM v_analysis_items AS i
),
seller_service AS (
    SELECT
        so.seller_id,
        AVG(v.delivery_days) AS avg_delivery_days,
        AVG(v.is_late)       AS late_rate,
        AVG(r.review_score)  AS avg_review
    FROM seller_orders AS so
    JOIN v_analysis_orders AS v ON v.order_id = so.order_id
    LEFT JOIN reviews AS r      ON r.order_id = so.order_id
    GROUP BY so.seller_id
),
seller_rev AS (
    SELECT
        seller_id,
        seller_state,
        COUNT(*)                   AS items,
        COUNT(DISTINCT order_id)   AS orders,
        COUNT(DISTINCT product_id) AS products,
        SUM(revenue)               AS revenue,
        AVG(revenue)               AS avg_item_price
    FROM v_analysis_items
    GROUP BY seller_id, seller_state
)
SELECT
    ROW_NUMBER() OVER (ORDER BY sr.revenue DESC)      AS rank,
    sr.seller_id,
    sr.seller_state,
    sr.orders,
    sr.products,
    ROUND(sr.revenue, 2)                              AS revenue,
    ROUND(sr.avg_item_price, 2)                       AS avg_item_price,
    ROUND(100.0 * sr.revenue / SUM(sr.revenue) OVER (), 3) AS pct_of_revenue,
    ROUND(ss.avg_delivery_days, 1)                    AS avg_delivery_days,
    ROUND(100.0 * ss.late_rate, 2)                    AS late_rate_pct,
    ROUND(ss.avg_review, 3)                           AS avg_review_score
FROM seller_rev     AS sr
JOIN seller_service AS ss ON ss.seller_id = sr.seller_id
ORDER BY sr.revenue DESC
LIMIT 20;

-- name: category_mix_by_region
WITH state_category AS (
    SELECT
        customer_state,
        category,
        SUM(revenue)              AS revenue,
        COUNT(DISTINCT order_id)  AS orders
    FROM v_analysis_items
    GROUP BY customer_state, category
),
ranked AS (
    SELECT
        customer_state,
        category,
        revenue,
        orders,
        ROW_NUMBER() OVER (PARTITION BY customer_state ORDER BY revenue DESC) AS rank_in_state,
        SUM(revenue) OVER (PARTITION BY customer_state) AS state_total
    FROM state_category
)
SELECT
    customer_state,
    category AS top_category,
    ROUND(revenue, 2)                              AS category_revenue,
    orders,
    ROUND(100.0 * revenue / state_total, 2)        AS pct_of_state_revenue,
    ROUND(state_total, 2)                          AS state_total_revenue
FROM ranked
WHERE rank_in_state = 1
  AND state_total > 100000
ORDER BY state_total DESC;

-- name: delivery_experience_vs_repeat
WITH first_orders AS (
    SELECT
        v.customer_unique_id,
        v.order_id,
        v.is_late,
        v.delivery_days,
        r.review_score,
        ROW_NUMBER() OVER (PARTITION BY v.customer_unique_id ORDER BY v.order_date) AS seq,
        COUNT(*)     OVER (PARTITION BY v.customer_unique_id) AS total_orders
    FROM v_analysis_orders AS v
    LEFT JOIN reviews AS r ON r.order_id = v.order_id
)
SELECT
    CASE WHEN is_late = 1 THEN 'first order was LATE' ELSE 'first order on time' END AS first_experience,
    COUNT(*)                                                  AS customers,
    SUM(CASE WHEN total_orders > 1 THEN 1 ELSE 0 END)         AS came_back,
    ROUND(100.0 * SUM(CASE WHEN total_orders > 1 THEN 1 ELSE 0 END) / COUNT(*), 3)
                                                              AS repeat_rate_pct,
    ROUND(AVG(review_score), 3)                               AS avg_review_score,
    ROUND(AVG(delivery_days), 1)                              AS avg_delivery_days
FROM first_orders
WHERE seq = 1
GROUP BY first_experience;
