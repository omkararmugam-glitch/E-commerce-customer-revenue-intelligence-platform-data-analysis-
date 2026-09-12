-- ============================================================================
-- schema.sql — analytical schema for the Olist e-commerce warehouse
--
-- Engine: SQLite 3.50+ (see sql/build_db.py for why SQLite rather than
--         PostgreSQL, and for the ANSI-compatibility note).
--
-- Loaded from the Phase 3 cleaned tables in data/processed/, so every
-- definition established there (revenue rule, customer key, analysis window)
-- carries through unchanged.
--
-- Grain of each table is stated in its comment. Star-ish layout: orders and
-- order_items are the facts; customers, products, sellers, geolocation are
-- the dimensions; payments and reviews are order-level satellites.
-- ============================================================================

DROP VIEW  IF EXISTS v_analysis_items;
DROP VIEW  IF EXISTS v_analysis_orders;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS sellers;
DROP TABLE IF EXISTS geolocation;

-- ---------------------------------------------------------------- dimensions

-- One row per order-scoped customer account.
-- NOTE: customer_id is issued per order. customer_unique_id is the person and
-- is the key used for every customer-level analysis.
CREATE TABLE customers (
    customer_id              TEXT PRIMARY KEY,
    customer_unique_id       TEXT NOT NULL,
    customer_zip_code_prefix INTEGER,
    customer_city            TEXT,          -- accent/punctuation-normalised
    customer_state           TEXT NOT NULL, -- 27 Brazilian states, clean
    customer_city_raw        TEXT
);

-- One row per product.
CREATE TABLE products (
    product_id                    TEXT PRIMARY KEY,
    product_category_name         TEXT,     -- 'unknown' where the source was null
    product_category_name_english TEXT,     -- includes 2 manually added translations
    product_name_length           REAL,
    product_description_length    REAL,
    product_photos_qty            REAL,
    product_weight_g              REAL,     -- 0 g values nulled (impossible)
    product_length_cm             REAL,
    product_height_cm             REAL,
    product_width_cm              REAL,
    product_volume_cm3            REAL,
    category_missing              INTEGER,  -- 0/1
    invalid_dimensions            INTEGER   -- 0/1
);

-- One row per seller.
CREATE TABLE sellers (
    seller_id              TEXT PRIMARY KEY,
    seller_zip_code_prefix INTEGER,
    seller_city            TEXT,
    seller_state           TEXT NOT NULL,
    seller_city_raw        TEXT
);

-- One row per zip code prefix (collapsed from 1,000,163 raw observations).
CREATE TABLE geolocation (
    geolocation_zip_code_prefix INTEGER PRIMARY KEY,
    geolocation_lat             REAL,
    geolocation_lng             REAL,
    geolocation_city            TEXT,
    geolocation_state           TEXT,
    n_observations              INTEGER
);

-- ---------------------------------------------------------------- facts

-- One row per order.
CREATE TABLE orders (
    order_id                      TEXT PRIMARY KEY,
    customer_id                   TEXT NOT NULL,
    order_status                  TEXT NOT NULL,
    order_purchase_timestamp      TEXT,     -- ISO-8601
    order_approved_at             TEXT,
    order_delivered_carrier_date  TEXT,
    order_delivered_customer_date TEXT,
    order_estimated_delivery_date TEXT,
    order_date                    TEXT,
    order_year                    INTEGER,
    order_month                   TEXT,     -- 'YYYY-MM'
    order_quarter                 TEXT,     -- 'YYYYQn'
    order_dow                     TEXT,
    order_hour                    INTEGER,
    approval_days                 REAL,
    carrier_days                  REAL,
    shipping_days                 REAL,
    delivery_days                 REAL,
    estimated_days                REAL,
    delivery_vs_estimate_days     REAL,
    is_delivered                  INTEGER NOT NULL,  -- revenue rule
    in_window                     INTEGER NOT NULL,  -- 2017-01-01..2018-08-31
    is_late                       INTEGER,
    timeline_valid                INTEGER,
    status_date_conflict          INTEGER,
    FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
);

-- One row per product line on an order. price is THE revenue measure;
-- freight_value is a separate cost-to-customer and is never summed into it.
CREATE TABLE order_items (
    order_id               TEXT NOT NULL,
    order_item_id          INTEGER NOT NULL,
    product_id             TEXT NOT NULL,
    seller_id              TEXT NOT NULL,
    shipping_limit_date    TEXT,
    price                  REAL NOT NULL,
    freight_value          REAL NOT NULL,
    item_total             REAL,
    invalid_shipping_limit INTEGER,
    free_freight           INTEGER,
    PRIMARY KEY (order_id, order_item_id),
    FOREIGN KEY (order_id)   REFERENCES orders (order_id),
    FOREIGN KEY (product_id) REFERENCES products (product_id),
    FOREIGN KEY (seller_id)  REFERENCES sellers (seller_id)
);

-- One row per payment record (an order may split across methods/instalments).
CREATE TABLE payments (
    order_id                   TEXT NOT NULL,
    payment_sequential         INTEGER NOT NULL,
    payment_type               TEXT,
    payment_installments       INTEGER,
    payment_value              REAL,
    is_valid_payment           INTEGER,
    zero_value                 INTEGER,
    undefined_type             INTEGER,
    installments_imputed       INTEGER,
    order_has_no_payment_value INTEGER,
    PRIMARY KEY (order_id, payment_sequential),
    FOREIGN KEY (order_id) REFERENCES orders (order_id)
);

-- One row per order (deduplicated in Phase 3: raw review_id was not unique).
CREATE TABLE reviews (
    review_id               TEXT,
    order_id                TEXT PRIMARY KEY,
    review_score            INTEGER NOT NULL,
    review_comment_title    TEXT,
    review_comment_message  TEXT,
    review_creation_date    TEXT,
    review_answer_timestamp TEXT,
    has_comment             INTEGER,
    response_days           REAL,
    had_multiple_reviews    INTEGER,
    FOREIGN KEY (order_id) REFERENCES orders (order_id)
);

-- ---------------------------------------------------------------- indexes

CREATE INDEX idx_orders_customer   ON orders (customer_id);
CREATE INDEX idx_orders_month      ON orders (order_month);
CREATE INDEX idx_orders_analysis   ON orders (is_delivered, in_window);
CREATE INDEX idx_items_order       ON order_items (order_id);
CREATE INDEX idx_items_product     ON order_items (product_id);
CREATE INDEX idx_items_seller      ON order_items (seller_id);
CREATE INDEX idx_customers_unique  ON customers (customer_unique_id);
CREATE INDEX idx_customers_state   ON customers (customer_state);
CREATE INDEX idx_payments_order    ON payments (order_id);
CREATE INDEX idx_products_category ON products (product_category_name_english);

-- ---------------------------------------------------------------- views
--
-- Encoding the analysis base once, so no query can accidentally include
-- cancelled orders or the unusable edges of the date range.

-- One row per order in the analysis base.
CREATE VIEW v_analysis_orders AS
SELECT
    o.order_id,
    o.order_month,
    o.order_quarter,
    o.order_year,
    o.order_date,
    o.order_dow,
    o.delivery_days,
    o.is_late,
    c.customer_id,
    c.customer_unique_id,
    c.customer_state,
    c.customer_city
FROM orders AS o
JOIN customers AS c ON c.customer_id = o.customer_id
WHERE o.is_delivered = 1
  AND o.in_window    = 1;

-- One row per item line in the analysis base, enriched with product and seller.
CREATE VIEW v_analysis_items AS
SELECT
    i.order_id,
    i.order_item_id,
    i.price        AS revenue,
    i.freight_value,
    i.product_id,
    i.seller_id,
    p.product_category_name_english AS category,
    s.seller_state,
    v.order_month,
    v.order_quarter,
    v.customer_unique_id,
    v.customer_state
FROM order_items      AS i
JOIN v_analysis_orders AS v ON v.order_id   = i.order_id
JOIN products          AS p ON p.product_id = i.product_id
JOIN sellers           AS s ON s.seller_id  = i.seller_id;
