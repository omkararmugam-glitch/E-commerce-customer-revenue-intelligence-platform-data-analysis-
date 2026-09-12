"""
Generate the Power BI project (``dashboard/OlistIntelligence.pbip``).

Builds a complete Power BI Desktop project from the tables in ``data/powerbi/``:

- **Semantic model** (``model.bim``, TMSL JSON): 13 tables loaded from Parquet
  through a single ``DataFolder`` parameter, 9 relationships, 38 DAX measures,
  a marked date table, and auto date/time disabled.
- **Report** (PBIR ``definition/`` folder): five pages — Executive Overview,
  Customer Intelligence, Product Intelligence, Marketing Proxies, Revenue
  Forecast.

Column data types are read from the Parquet files themselves, so the model
cannot drift out of step with the exports.

Why these formats
-----------------
- ``model.bim`` (TMSL) rather than TMDL: TMDL is whitespace-sensitive and needs a
  preview switch; TMSL is plain JSON and accepted by ``definition.pbism`` 4.0.
- PBIR rather than PBIR-Legacy: PBIR is the publicly documented, externally
  editable report format; ``report.json`` (legacy) is not.
- Schema versions are the ones Power BI Desktop 2.157 accepts *unconditionally*
  (not behind feature switches): report 1.3.0, page 1.4.0, pagesMetadata 1.0.0,
  versionMetadata 1.0.0, visualContainer 2.4.0.

Usage::

    python src/build_pbip.py              # build
    python src/build_pbip.py --validate   # build, then validate every report
                                          # file against Microsoft's schemas
"""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path

import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "powerbi"
OUT_DIR = PROJECT_ROOT / "dashboard"
NAME = "OlistIntelligence"

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
S_PBIP = f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json"
S_PBIR = f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json"
S_PBISM = f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json"
S_VERSION = f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json"
S_REPORT = f"{SCHEMA}/item/report/definition/report/1.3.0/schema.json"
S_PAGES = f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json"
S_PAGE = f"{SCHEMA}/item/report/definition/page/1.4.0/schema.json"
S_VISUAL = f"{SCHEMA}/item/report/definition/visualContainer/2.4.0/schema.json"

#: Report theme schema matching the installed Desktop build (2.157).
S_THEME = ("https://raw.githubusercontent.com/microsoft/powerbi-desktop-samples/main/"
           "Report%20Theme%20JSON%20Schema/reportThemeSchema-2.157.json")

BASE_THEME = "CY24SU10"
DESKTOP_THEMES = Path(
    r"C:\Program Files\WindowsApps\Microsoft.MicrosoftPowerBIDesktop_2.157.1354.0_x64__8wekyb3d8bbwe"
    r"\bin\WebView2Resources\minerva\sharedresources\BaseThemes"
)

# Dark-surface steps of the same hues, in the same fixed order, as src/viz.py, so the dashboard
# matches the notebooks. Validated against the card surface (#13233F) with the dataviz palette
# validator: lightness band, chroma, colour-blind separation and 3:1 contrast all pass.
PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]

PAGE_W, PAGE_H = 1280, 720
NS = uuid.UUID("6f1c2d4e-0b7a-4c1e-9a55-3b8e2f0d7c11")  # stable ids across rebuilds


def _uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


# ==========================================================================
# Semantic model
# ==========================================================================

TABLES = [
    "fact_orders", "fact_order_items", "dim_customers_segmented", "dim_date",
    "dim_product_performance", "dim_category_performance", "dim_seller_performance",
    "dim_region_performance", "dim_payment_performance", "fact_cohort_retention",
    "dim_cohort_summary", "fact_revenue_forecast", "dim_forecast_model_comparison",
]

#: Columns that are genuinely additive; everything else defaults to "don't summarize"
#: so ids, scores and pre-computed rates are never accidentally summed.
ADDITIVE = {
    "revenue", "freight", "items_in_order", "units", "orders", "orders_n", "items_sold",
    "customers", "products", "new_customers", "retained_customers", "monetary_revenue",
    "total_items", "late_orders", "actual", "forecast", "value",
}

#: Columns loaded as `date` (not datetime) so relationship keys line up.
DATE_ONLY = {("dim_date", "date"), ("fact_revenue_forecast", "period")}

RELATIONSHIPS = [
    ("fact_order_items", "order_id", "fact_orders", "order_id"),
    ("fact_orders", "customer_unique_id", "dim_customers_segmented", "customer_unique_id"),
    ("fact_orders", "order_date", "dim_date", "date"),
    ("fact_orders", "customer_state", "dim_region_performance", "customer_state"),
    ("fact_orders", "payment_type", "dim_payment_performance", "payment_type"),
    ("fact_order_items", "product_id", "dim_product_performance", "product_id"),
    ("fact_order_items", "category", "dim_category_performance", "category"),
    ("fact_order_items", "seller_id", "dim_seller_performance", "seller_id"),
    ("fact_cohort_retention", "cohort_month", "dim_cohort_summary", "cohort_month"),
]

BRL = '"R$"#,0'
BRL2 = '"R$"#,0.00'
INT = "#,0"
PCT = "0.0%"
PCT2 = "0.00%"
DEC2 = "0.00"
DEC1 = "0.0"

#: table -> [(name, DAX, formatString, displayFolder, description)]
MEASURES = {
    "fact_orders": [
        ("Total Revenue", "SUM ( fact_orders[revenue] )", BRL, "Revenue",
         "Item price on delivered orders. Excludes freight. Use for order-level analysis."),
        ("Revenue (Trend)",
         "CALCULATE ( [Total Revenue], dim_date[is_truncated_period] = FALSE () )", BRL, "Revenue",
         "Total Revenue excluding the truncated export tail after 2018-08-23. Use on time-series visuals."),
        ("Total Freight", "SUM ( fact_orders[freight] )", BRL, "Revenue",
         "Customer-paid shipping. Never added into revenue."),
        ("Freight % of Revenue", "DIVIDE ( [Total Freight], [Total Revenue] )", PCT, "Revenue", ""),
        ("Revenue MoM %",
         "VAR isPartial =\n    CALCULATE ( COUNTROWS ( dim_date ), dim_date[is_truncated_period] = TRUE () ) > 0\n"
         "VAR cur = [Revenue (Trend)]\n"
         "VAR prev = CALCULATE ( [Revenue (Trend)], DATEADD ( dim_date[date], -1, MONTH ) )\n"
         "RETURN IF ( isPartial, BLANK (), DIVIDE ( cur - prev, prev ) )", PCT, "Revenue",
         "Month-on-month change in trend revenue. Blank for Aug 2018, which is a partial month."),
        ("Orders", "DISTINCTCOUNT ( fact_orders[order_id] )", INT, "Volume", ""),
        ("Customers", "DISTINCTCOUNT ( fact_orders[customer_unique_id] )", INT, "Volume",
         "Distinct people (customer_unique_id)."),
        ("AOV (Mean)", "DIVIDE ( [Total Revenue], [Orders] )", BRL2, "Order Value",
         "Mean order value. Skewed by large orders - show beside the median."),
        ("AOV (Median)", "MEDIAN ( fact_orders[revenue] )", BRL2, "Order Value",
         "Median order value - the typical order. Prefer this headline."),
        ("AOV (Credit Card)",
         "CALCULATE ( [AOV (Mean)], KEEPFILTERS ( fact_orders[payment_type] = \"credit_card\" ) )", BRL2,
         "Order Value", "Mean order value on credit-card orders only - the only method with instalments."),
        ("Multi-Item Order %",
         "DIVIDE ( CALCULATE ( [Orders], KEEPFILTERS ( fact_orders[is_multi_item] = TRUE () ) ), [Orders] )",
         PCT, "Order Value", ""),
        ("Late Rate %",
         "DIVIDE ( CALCULATE ( [Orders], KEEPFILTERS ( fact_orders[is_late] = TRUE () ) ), [Orders] )",
         PCT, "Delivery",
         "Share of orders delivered after the promised date."),
        ("Avg Delivery Days", "AVERAGE ( fact_orders[delivery_days] )", DEC1, "Delivery", ""),
        ("Avg Review Score", "AVERAGE ( fact_orders[review_score] )", DEC2, "Satisfaction",
         "Mean of non-blank review scores."),
        ("One-Star Rate %",
         "DIVIDE (\n    CALCULATE ( COUNTROWS ( fact_orders ), KEEPFILTERS ( fact_orders[review_score] = 1 ) ),\n"
         "    CALCULATE ( COUNTROWS ( fact_orders ), NOT ISBLANK ( fact_orders[review_score] ) )\n)",
         PCT, "Satisfaction", ""),
    ],
    "fact_order_items": [
        ("Item Revenue", "SUM ( fact_order_items[revenue] )", BRL, "Revenue",
         "Revenue at line level. Use for product, category and seller visuals."),
        ("Items Sold", "COUNTROWS ( fact_order_items )", INT, "Volume", ""),
        ("Products Sold", "DISTINCTCOUNT ( fact_order_items[product_id] )", INT, "Volume", ""),
        ("Avg Item Price", "DIVIDE ( [Item Revenue], [Items Sold] )", BRL2, "Order Value", ""),
    ],
    "dim_customers_segmented": [
        ("Segment Customers", "COUNTROWS ( dim_customers_segmented )", INT, "Segments", ""),
        ("Segment Revenue", "SUM ( dim_customers_segmented[monetary_revenue] )", BRL, "Segments", ""),
        ("Segment Revenue %",
         "DIVIDE ( [Segment Revenue], CALCULATE ( [Segment Revenue], ALL ( dim_customers_segmented ) ) )",
         PCT, "Segments", ""),
        ("Repeat Customers",
         "CALCULATE ( COUNTROWS ( dim_customers_segmented ),"
         " KEEPFILTERS ( dim_customers_segmented[is_repeat_customer] = TRUE () ) )",
         INT, "Segments", ""),
        ("Repeat Rate %", "DIVIDE ( [Repeat Customers], [Segment Customers] )", PCT, "Segments",
         "Share of customers with more than one order (~3%)."),
        ("Avg Customer Value", "AVERAGE ( dim_customers_segmented[monetary_revenue] )", BRL2, "Segments", ""),
    ],
    "fact_cohort_retention": [
        ("Avg Retention %", "DIVIDE ( AVERAGE ( fact_cohort_retention[retention_pct] ), 100 )", PCT2,
         "Cohorts", ""),
        ("Retention % After Month 0",
         # KEEPFILTERS matters: without it the > 0 filter overwrites the chart's own
         # month axis and every point shows the same overall average.
         "CALCULATE ( [Avg Retention %],"
         " KEEPFILTERS ( fact_cohort_retention[months_since_first_purchase] > 0 ) )", PCT2,
         "Cohorts", "Excludes month 0, which is always 100%."),
    ],
    "dim_cohort_summary": [
        ("3-Month Repeat Rate %",
         "DIVIDE ( AVERAGE ( dim_cohort_summary[repeat_rate_3mo_pct] ), 100 )", PCT2, "Cohorts",
         "Fair cross-cohort comparison (equal 3-month window)."),
    ],
    "dim_category_performance": [
        ("Category Momentum", "SUM ( dim_category_performance[momentum_change_brl] )", BRL, "Category",
         "Jun-Aug 2018 vs Mar-May 2018 revenue change. Seasonality not separable."),
        ("Category Units", "SUM ( dim_category_performance[units] )", INT, "Category", ""),
        ("Category Avg Price", "AVERAGE ( dim_category_performance[avg_item_price] )", BRL2, "Category", ""),
    ],
    "fact_revenue_forecast": [
        ("Actual Revenue", "SUM ( fact_revenue_forecast[actual] )", BRL, "Forecast", ""),
        ("Forecast Revenue", "SUM ( fact_revenue_forecast[forecast] )", BRL, "Forecast",
         "ARIMA(0,1,1) point forecast."),
        ("Forecast Lower 95", "SUM ( fact_revenue_forecast[lower_95] )", BRL, "Forecast",
         "Per-month bound. Do not total across months: summed bounds are not a valid interval."),
        ("Forecast Upper 95", "SUM ( fact_revenue_forecast[upper_95] )", BRL, "Forecast",
         "Per-month bound. Do not total across months: summed bounds are not a valid interval."),
        ("Next Month Lower 95",
         "VAR firstPeriod =\n    CALCULATE ( MIN ( fact_revenue_forecast[period] ),"
         " fact_revenue_forecast[type] = \"forecast\" )\n"
         "RETURN CALCULATE ( SUM ( fact_revenue_forecast[lower_95] ), fact_revenue_forecast[period] = firstPeriod )",
         BRL, "Forecast", "Lower 95% bound for the first forecast month."),
        ("Next Month Upper 95",
         "VAR firstPeriod =\n    CALCULATE ( MIN ( fact_revenue_forecast[period] ),"
         " fact_revenue_forecast[type] = \"forecast\" )\n"
         "RETURN CALCULATE ( SUM ( fact_revenue_forecast[upper_95] ), fact_revenue_forecast[period] = firstPeriod )",
         BRL, "Forecast", "Upper 95% bound for the first forecast month."),
        ("Next Month Forecast",
         "VAR firstPeriod =\n    CALCULATE ( MIN ( fact_revenue_forecast[period] ),"
         " fact_revenue_forecast[type] = \"forecast\" )\n"
         "RETURN CALCULATE ( [Forecast Revenue], fact_revenue_forecast[period] = firstPeriod )",
         BRL, "Forecast", "First forecast month."),
    ],
}


def _arrow_to_types(table: str, column: str, arrow_type) -> tuple[str, str]:
    """Map a Parquet/Arrow type to (TMSL dataType, Power Query type)."""
    t = str(arrow_type)
    if (table, column) in DATE_ONLY or t.startswith("date32"):
        return "dateTime", "type date"
    if t.startswith("timestamp"):
        return "dateTime", "type datetime"
    if t in ("int64", "int32", "int16", "int8"):
        return "int64", "Int64.Type"
    if t in ("double", "float", "float64"):
        return "double", "type number"
    if t == "bool":
        return "boolean", "type logical"
    return "string", "type text"


def build_table(table: str) -> dict:
    schema = pq.read_schema(DATA_DIR / f"{table}.parquet")
    columns, m_types = [], []
    for name, arrow_type in zip(schema.names, schema.types):
        dtype, mtype = _arrow_to_types(table, name, arrow_type)
        col = {
            "name": name,
            "dataType": dtype,
            "sourceColumn": name,
            "summarizeBy": "sum" if (name in ADDITIVE and dtype in ("int64", "double")) else "none",
        }
        if dtype == "dateTime":
            col["formatString"] = "yyyy-mm-dd" if mtype == "type date" else "yyyy-mm-dd hh:nn"
        if table == "dim_date" and name == "date":
            col["isKey"] = True
        if table == "dim_date" and name == "month_name":
            col["sortByColumn"] = "month"
        columns.append(col)
        m_types.append(f'{{"{name}", {mtype}}}')

    expression = [
        "let",
        f'    Source = Parquet.Document(File.Contents(DataFolder & "{table}.parquet")),',
        "    Typed = Table.TransformColumnTypes(Source, {" + ", ".join(m_types) + "})",
        "in",
        "    Typed",
    ]

    out = {
        "name": table,
        "columns": columns,
        "partitions": [{"name": table, "mode": "import", "source": {"type": "m", "expression": expression}}],
    }
    if table == "dim_date":
        out["dataCategory"] = "Time"
    if table in MEASURES:
        out["measures"] = [
            {k: v for k, v in {
                "name": n,
                "expression": [line for line in dax.split("\n")] if "\n" in dax else dax,
                "formatString": fmt,
                "displayFolder": folder,
                "description": desc or None,
            }.items() if v is not None}
            for n, dax, fmt, folder, desc in MEASURES[table]
        ]
    return out


def build_model() -> dict:
    folder = str(DATA_DIR).rstrip("\\") + "\\"
    folder_m = folder.replace('"', '""')
    tables = [build_table(t) for t in TABLES]

    # structural self-check before anything is written
    cols = {t["name"]: {c["name"] for c in t["columns"]} for t in tables}
    for ft, fc, tt, tc in RELATIONSHIPS:
        assert fc in cols[ft], f"relationship column missing: {ft}[{fc}]"
        assert tc in cols[tt], f"relationship column missing: {tt}[{tc}]"
    names = [m["name"] for t in tables for m in t.get("measures", [])]
    assert len(names) == len(set(names)), "duplicate measure names"

    return {
        "name": NAME,
        "compatibilityLevel": 1550,
        "model": {
            "culture": "en-US",
            "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-US",
            "tables": tables,
            "relationships": [
                {"name": _uid("rel", ft, fc, tt, tc), "fromTable": ft, "fromColumn": fc,
                 "toTable": tt, "toColumn": tc}
                for ft, fc, tt, tc in RELATIONSHIPS
            ],
            "expressions": [{
                "name": "DataFolder",
                "kind": "m",
                "expression": f'"{folder_m}" meta [IsParameterQuery=true, Type="Text", '
                              f'IsParameterQueryRequired=true]',
                "annotations": [{"name": "PBI_ResultType", "value": "Text"}],
            }],
            "annotations": [
                {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
                {"name": "PBI_QueryOrder", "value": json.dumps(["DataFolder"] + TABLES)},
            ],
        },
    }


# ==========================================================================
# Report helpers
# ==========================================================================

def lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def text(s: str) -> dict:
    return lit("'" + s.replace("'", "''") + "'")


def col(table: str, column: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}}


def meas(table: str, name: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def proj(field: dict, display: str | None = None) -> dict:
    kind = "Column" if "Column" in field else "Measure"
    entity = field[kind]["Expression"]["SourceRef"]["Entity"]
    prop = field[kind]["Property"]
    p = {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    return p


def visual(name, vtype, x, y, w, h, roles=None, title=None, sort=None, objects=None, z=0):
    v = {"visualType": vtype}
    if roles:
        v["query"] = {"queryState": {r: {"projections": ps} for r, ps in roles.items()}}
        if sort is not None:
            field, direction = sort
            v["query"]["sortDefinition"] = {
                "sort": [{"field": field, "direction": direction}], "isDefaultSort": True}
    if objects:
        v["objects"] = objects
    container = {}
    if title:
        container["title"] = [{"properties": {"show": lit("true"), "text": text(title)}}]
    if container:
        v["visualContainerObjects"] = container
    if vtype not in ("textbox",):
        v["drillFilterOtherVisuals"] = True
    return {
        "$schema": S_VISUAL,
        "name": name,
        "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z},
        "visual": v,
    }


def textbox(name, x, y, w, h, runs, z=0, container=None):
    """A text box. ``runs`` is a list of (text, font_size, bold, color)."""
    paragraphs = [{
        "textRuns": [{
            "value": t,
            "textStyle": {"fontFamily": FONT_BOLD if bold else FONT, "fontSize": f"{size}pt",
                          "fontWeight": "bold" if bold else "normal", "color": color},
        }]
    } for t, size, bold, color in runs]
    v = visual(name, "textbox", x, y, w, h, z=z, objects={
        "general": [{"properties": {"paragraphs": paragraphs}}]})
    if container:
        v["visual"]["visualContainerObjects"] = container
    return v


def card(name, x, y, w, h, table, measure, label, z=0, precision=None, units=None):
    """A KPI card. ``precision`` sets decimals shown; ``units`` fixes the display unit (1000 = K)."""
    labels = {}
    if precision is not None:
        labels["labelPrecision"] = lit(f"{precision}L")
    if units is not None:
        labels["labelDisplayUnits"] = lit(f"{units}D")
    objects = {"categoryLabels": [{"properties": {"show": lit("false")}}]}
    if labels:
        objects["labels"] = [{"properties": labels}]
    # the container title names the metric; the theme hides the card's duplicate label
    return visual(name, "card", x, y, w, h, z=z, title=label,
                  roles={"Values": [proj(meas(table, measure))]}, objects=objects)


def table_visual(name, x, y, w, h, columns, title, sort, z=0):
    """A table whose columns share the card width. ``columns`` is a list of (table, column, label, weight)."""
    usable = w - 44  # card padding + vertical scrollbar
    total = sum(c[3] for c in columns)
    widths = [{"properties": {"value": lit(f"{usable * wt / total:.1f}D")},
               "selector": {"metadata": f"{t}.{c}"}} for t, c, _, wt in columns]
    return visual(name, "tableEx", x, y, w, h, z=z, title=title, sort=sort,
                  roles={"Values": [proj(col(t, c), label) for t, c, label, _ in columns]},
                  objects={"columnWidth": widths})


def slicer(name, x, y, w, h, table, column, label, mode="Dropdown", z=0):
    """A slicer. ``mode`` is 'Dropdown' (list) or 'Between' (range slider)."""
    return visual(name, "slicer", x, y, w, h, z=z,
                  roles={"Values": [proj(col(table, column), label)]},
                  objects={"data": [{"properties": {"mode": text(mode)}}],
                           "header": [{"properties": {"text": text(label)}}]})


# --------------------------------------------------------------------------
# Design system — shared by the theme and the page layouts
# --------------------------------------------------------------------------

# "Midnight" dark theme
NAVY = "#102A4F"        # header band and navigator buttons
NAVY_HOVER = "#1B3A66"
ACCENT = PALETTE[0]     # selected nav pill, slicer accents, series 1
CANVAS = "#0A1628"      # page background
CARD_BG = "#13233F"     # visual cards
LINE = "#22385E"        # card borders
GRID_LINE = "#22385E"
TEXT = "#E6EDF7"        # titles and values
TEXT_2 = "#9FB2CC"      # secondary text, axis labels
ON_NAVY = "#9FB2CC"     # secondary text on the header band
ZEBRA = "#172B4D"       # alternate table rows, input fields
TABLE_HEAD = "#1E4FA8"
KPI_VALUE = "#FFFFFF"
SHADOW = "#000000"
FILTER_APPLIED = "#1E3A66"
PANE_BG = "#0F1E36"     # filter pane
INPUT_BG = "#0A1628"
BOUND = "#9FB2CC"       # forecast interval lines
#: coloured borders for the headline KPI row, left to right
KPI_ACCENTS = [PALETTE[0], PALETTE[2], PALETTE[3], PALETTE[4]]
FONT, FONT_BOLD = "Segoe UI", "Segoe UI Semibold"

M, G = 16, 12                     # page margin, gutter
HEADER_H = 60
FILTER_Y, FILTER_H = 70, 56
KPI_Y, KPI_H = 136, 88
ROW1_Y, ROW2_Y, ROW_H = 236, 480, 232


def grid(y, h, weights, x0=M, width=PAGE_W - 2 * M, gap=G):
    """Split a horizontal band into cells proportional to ``weights``."""
    usable = width - gap * (len(weights) - 1)
    cells, x = [], x0
    for wgt in weights:
        w = round(usable * wgt / sum(weights))
        cells.append((x, y, w, h))
        x += w + gap
    return cells


def header(page_title: str, subtitle: str) -> list[dict]:
    """Navy band across the top: title + caveat line on the left, page navigator on the right."""
    band = {"background": [{"properties": {"show": lit("true"), "color": _solid(NAVY),
                                           "transparency": lit("0D")}}],
            "border": [{"properties": {"show": lit("false")}}],
            "dropShadow": [{"properties": {"show": lit("false")}}]}
    nav_w = 560
    title = textbox("header", 0, 0, PAGE_W - nav_w, HEADER_H, [
        (page_title, 15, True, "#FFFFFF"),
        (subtitle, 8, False, ON_NAVY),
    ], container=band)
    nav = visual("nav", "pageNavigator", PAGE_W - nav_w, 0, nav_w, HEADER_H, z=1)
    nav["visual"]["visualContainerObjects"] = band
    nav["visual"].pop("drillFilterOtherVisuals", None)
    return [title, nav]


def _solid(hex_color: str) -> dict:
    return {"solid": {"color": lit(f"'{hex_color}'")}}


# ==========================================================================
# Pages
# ==========================================================================

def page_executive() -> list[dict]:
    fo, fi, cat, dd = "fact_orders", "fact_order_items", "dim_category_performance", "dim_date"
    rg, pm = "dim_region_performance", "dim_payment_performance"
    f = grid(FILTER_Y, FILTER_H, [1, 1.7, 1, 1])
    k = grid(KPI_Y, KPI_H, [1, 1, 1, 1])
    r1 = grid(ROW1_Y, ROW_H, [2, 1])
    r2 = grid(ROW2_Y, ROW_H, [1, 1])
    rx, ry, rw, rh = r2[1]
    small = [(x, y, w, (rh - G) // 2) for (x, y, w, _) in grid(ry, rh, [1, 1], x0=rx, width=rw)]
    small += [(x, y + (rh - G) // 2 + G, w, h) for (x, y, w, h) in small]
    return [
        *header("Executive Overview",
                "Delivered orders, Jan 2017 – Aug 2018 · Revenue = item price, excl. freight · "
                "Trends exclude the truncated export tail"),
        slicer("f_year", *f[0], dd, "year", "Year", z=2),
        slicer("f_dates", *f[1], dd, "date", "Order Date", mode="Between", z=3),
        slicer("f_state", *f[2], rg, "customer_state", "Customer State", z=4),
        slicer("f_payment", *f[3], pm, "payment_type", "Payment Method", z=5),
        card("kpi_revenue", *k[0], fo, "Total Revenue", "Total Revenue", 6, precision=2),
        card("kpi_orders", *k[1], fo, "Orders", "Orders", 7, precision=1),
        card("kpi_customers", *k[2], fo, "Customers", "Customers", 8, precision=1),
        card("kpi_aov", *k[3], fo, "AOV (Median)", "Median Order Value", 9),
        visual("trend_revenue", "lineChart", *r1[0], z=10,
               title="Monthly Revenue  (Aug 2018 = 1–23 Aug only)",
               roles={"Category": [proj(col(dd, "month"), "Month")],
                      "Y": [proj(meas(fo, "Revenue (Trend)"), "Revenue")]},
               sort=(col(dd, "month"), "Ascending")),
        visual("rev_by_state", "clusteredColumnChart", *r1[1], z=11,
               title="Revenue by Customer State",
               roles={"Category": [proj(col(fo, "customer_state"), "State")],
                      "Y": [proj(meas(fo, "Total Revenue"), "Revenue")]},
               sort=(meas(fo, "Total Revenue"), "Descending")),
        visual("rev_by_category", "clusteredBarChart", *r2[0], z=12,
               title="Revenue by Category",
               roles={"Category": [proj(col(cat, "category"), "Category")],
                      "Y": [proj(meas(fi, "Item Revenue"), "Revenue")]},
               sort=(meas(fi, "Item Revenue"), "Descending")),
        card("kpi_late", *small[0], fo, "Late Rate %", "Late Delivery Rate", 13),
        card("kpi_review", *small[1], fo, "Avg Review Score", "Avg Review Score", 14),
        card("kpi_aov_mean", *small[2], fo, "AOV (Mean)", "Mean Order Value (skewed)", 15),
        card("kpi_onestar", *small[3], fo, "One-Star Rate %", "One-Star Review Rate", 16),
    ]


def page_customers() -> list[dict]:
    cs, cr, sm = "dim_customers_segmented", "fact_cohort_retention", "dim_cohort_summary"
    f = grid(FILTER_Y, FILTER_H, [1, 1, 1, 1])
    k = grid(KPI_Y, KPI_H, [1, 1, 1, 1])
    r1 = grid(ROW1_Y, ROW_H, [1, 1])
    r2 = grid(ROW2_Y, ROW_H, [1, 1])
    return [
        *header("Customer Intelligence",
                "97% of customers buy once · 98.2% of cohort revenue arrives in the first month · "
                "Segments are descriptive, not predictive"),
        slicer("f_rfm", *f[0], cs, "rfm_segment", "RFM Segment", z=2),
        slicer("f_kmeans", *f[1], cs, "kmeans_segment", "K-Means Segment", z=3),
        slicer("f_state", *f[2], cs, "customer_state", "Customer State", z=4),
        slicer("f_risk", *f[3], cs, "risk_tier", "Risk Tier", z=5),
        card("kpi_customers", *k[0], cs, "Segment Customers", "Customers", 6, precision=1),
        card("kpi_repeat", *k[1], cs, "Repeat Rate %", "Repeat Purchase Rate", 7),
        card("kpi_repeat_n", *k[2], cs, "Repeat Customers", "Repeat Customers", 8),
        card("kpi_value", *k[3], cs, "Avg Customer Value", "Avg Customer Value", 9),
        visual("rfm_revenue", "clusteredBarChart", *r1[0], z=10,
               title="Revenue by RFM Segment",
               roles={"Category": [proj(col(cs, "rfm_segment"), "RFM Segment")],
                      "Y": [proj(meas(cs, "Segment Revenue"), "Revenue")]},
               sort=(meas(cs, "Segment Revenue"), "Descending")),
        visual("kmeans_revenue", "clusteredBarChart", *r1[1], z=11,
               title="Revenue by K-Means Segment",
               roles={"Category": [proj(col(cs, "kmeans_segment"), "K-Means Segment")],
                      "Y": [proj(meas(cs, "Segment Revenue"), "Revenue")]},
               sort=(meas(cs, "Segment Revenue"), "Descending")),
        visual("retention_curve", "lineChart", *r2[0], z=12,
               title="Retention by Months Since First Purchase  (all cohorts, month 0 excluded)",
               roles={"Category": [proj(col(cr, "months_since_first_purchase"), "Months Since First Purchase")],
                      "Y": [proj(meas(cr, "Retention % After Month 0"), "Retention")]},
               sort=(col(cr, "months_since_first_purchase"), "Ascending")),
        visual("cohort_fair", "clusteredColumnChart", *r2[1], z=13,
               title="3-Month Repeat Rate by Cohort  (fair comparison)",
               roles={"Category": [proj(col(sm, "cohort_month"), "Cohort")],
                      "Y": [proj(meas(sm, "3-Month Repeat Rate %"), "3-Month Repeat Rate")]},
               sort=(col(sm, "cohort_month"), "Ascending")),
    ]


def page_products() -> list[dict]:
    fi, cat, pp, dd = "fact_order_items", "dim_category_performance", "dim_product_performance", "dim_date"
    sl = "dim_seller_performance"
    f = grid(FILTER_Y, FILTER_H, [1.3, 1.3, 1, 1])
    k = grid(KPI_Y, KPI_H, [1, 1, 1, 1])
    left, right = grid(ROW1_Y, ROW2_Y + ROW_H - ROW1_Y, [1, 1])
    rx, _, rw, _ = right
    return [
        *header("Product Intelligence",
                "No cost data → no margin analysis · The quadrant is price vs volume · "
                "Momentum cannot separate seasonality from trend"),
        slicer("f_category", *f[0], cat, "category", "Category", z=2),
        slicer("f_quadrant", *f[1], cat, "quadrant", "Price-Volume Quadrant", z=3),
        slicer("f_year", *f[2], dd, "year", "Year", z=4),
        slicer("f_seller_state", *f[3], sl, "seller_state", "Seller State", z=5),
        card("kpi_item_rev", *k[0], fi, "Item Revenue", "Revenue", 6, precision=2),
        card("kpi_products", *k[1], fi, "Products Sold", "Products Sold", 7, precision=1),
        card("kpi_items", *k[2], fi, "Items Sold", "Items Sold", 8, precision=1),
        card("kpi_item_price", *k[3], fi, "Avg Item Price", "Avg Item Price", 9),
        visual("momentum", "clusteredBarChart", *left, z=10,
               title="Category Momentum: Jun–Aug vs Mar–May 2018",
               roles={"Category": [proj(col(cat, "category"), "Category")],
                      "Y": [proj(meas(cat, "Category Momentum"), "Revenue Change")]},
               sort=(meas(cat, "Category Momentum"), "Descending")),
        visual("price_volume", "scatterChart", rx, ROW1_Y, rw, ROW_H, z=11,
               title="Category Price vs Volume  (bubble = revenue)",
               roles={"Category": [proj(col(cat, "category"), "Category")],
                      "X": [proj(meas(cat, "Category Units"), "Units Sold")],
                      "Y": [proj(meas(cat, "Category Avg Price"), "Avg Price")],
                      "Size": [proj(meas(fi, "Item Revenue"), "Revenue")]}),
        table_visual("top_products", rx, ROW2_Y, rw, ROW_H, z=12, title="Products by Revenue",
                     columns=[(pp, "revenue_rank", "Rank", 0.7), (pp, "category", "Category", 2.2),
                              (pp, "units", "Units", 0.9), (pp, "avg_item_price", "Avg Price", 1.1),
                              (pp, "revenue", "Revenue", 1.2),
                              (pp, "cumulative_pct_of_revenue", "Cumulative %", 1.2)],
                     sort=(col(pp, "revenue_rank"), "Ascending")),
    ]


def page_marketing() -> list[dict]:
    fo, rg, sl, pm, dd = ("fact_orders", "dim_region_performance", "dim_seller_performance",
                          "dim_payment_performance", "dim_date")
    f = grid(FILTER_Y, FILTER_H, [1, 1, 1])
    k = grid(KPI_Y, KPI_H, [1, 1, 1, 1])
    r1 = grid(ROW1_Y, ROW_H, [1, 2])
    r2 = grid(ROW2_Y, ROW_H, [1, 1])
    return [
        *header("Marketing Proxies",
                "Performance segments, NOT channel attribution · No campaign, spend or session data · "
                "CAC and ROAS cannot be computed"),
        slicer("f_payment", *f[0], pm, "payment_type", "Payment Method", z=2),
        slicer("f_state", *f[1], rg, "customer_state", "Customer State", z=3),
        slicer("f_year", *f[2], dd, "year", "Year", z=4),
        card("kpi_revenue", *k[0], fo, "Total Revenue", "Total Revenue", 5, precision=2),
        card("kpi_aov", *k[1], fo, "AOV (Mean)", "Mean Order Value", 6),
        card("kpi_late", *k[2], fo, "Late Rate %", "Late Delivery Rate", 7),
        card("kpi_review", *k[3], fo, "Avg Review Score", "Avg Review Score", 8),
        visual("rev_by_payment", "clusteredColumnChart", *r1[0], z=9,
               title="Revenue by Payment Method",
               roles={"Category": [proj(col(fo, "payment_type"), "Payment Method")],
                      "Y": [proj(meas(fo, "Total Revenue"), "Revenue")]},
               sort=(meas(fo, "Total Revenue"), "Descending")),
        visual("aov_by_installments", "clusteredColumnChart", *r1[1], z=10,
               title="Credit-Card Order Value by Instalment Count  (causation unknown)",
               roles={"Category": [proj(col(fo, "max_installments"), "Instalments")],
                      "Y": [proj(meas(fo, "AOV (Credit Card)"), "Mean Order Value")]},
               sort=(col(fo, "max_installments"), "Ascending")),
        table_visual("region_table", *r2[0], z=11, title="State Scorecard",
                     columns=[(rg, "customer_state", "State", 0.8), (rg, "orders", "Orders", 1),
                              (rg, "aov", "AOV", 1), (rg, "avg_delivery_days", "Delivery Days", 1.2),
                              (rg, "late_rate_pct", "Late %", 1), (rg, "avg_review_score", "Review", 1)],
                     sort=(col(rg, "orders"), "Descending")),
        table_visual("seller_table", *r2[1], z=12, title="Sellers by Revenue",
                     columns=[(sl, "seller_state", "Seller State", 1.1), (sl, "orders_n", "Orders", 1),
                              (sl, "revenue", "Revenue", 1.3), (sl, "late_rate_pct", "Late %", 1),
                              (sl, "avg_review_score", "Review", 1)],
                     sort=(col(sl, "revenue"), "Descending")),
    ]


def _forecast_series_styles(table: str) -> dict:
    """Actual in blue, forecast in orange, the 95% bounds as grey dashed lines, no area fill."""
    colours = {"Actual Revenue": ACCENT, "Forecast Revenue": PALETTE[1],
               "Forecast Lower 95": BOUND, "Forecast Upper 95": BOUND}
    data_points = [{"properties": {"fill": _solid(c)}, "selector": {"metadata": f"{table}.{m}"}}
                   for m, c in colours.items()]
    line_styles = [{"properties": {"areaShow": lit("false")}}]
    line_styles += [{"properties": {"lineStyle": text("dashed"), "strokeWidth": lit("2D"),
                                    "showMarker": lit("false")},
                     "selector": {"metadata": f"{table}.{m}"}}
                    for m in ("Forecast Lower 95", "Forecast Upper 95")]
    return {"dataPoint": data_points, "lineStyles": line_styles}


def page_forecast() -> list[dict]:
    fc, mc = "fact_revenue_forecast", "dim_forecast_model_comparison"
    k = grid(FILTER_Y, KPI_H, [1, 1, 1, 1.25])
    chart_y = FILTER_Y + KPI_H + G
    table_y = 482
    note_card = {"background": [{"properties": {"show": lit("true"), "color": _solid(FILTER_APPLIED),
                                                "transparency": lit("0D")}}],
                 "border": [{"properties": {"show": lit("true"), "color": _solid(ACCENT),
                                            "radius": lit("10D")}}]}
    return [
        *header("Revenue Forecast",
                "20 months of history · No annual seasonality, so no Black Friday · "
                "Aug 2018 is truncated, so the base is understated"),
        card("kpi_next", *k[0], fc, "Next Month Forecast", "Next Month Forecast", 2, precision=0, units=1000),
        card("kpi_lower", *k[1], fc, "Next Month Lower 95", "95% Lower Bound", 3, precision=0, units=1000),
        card("kpi_upper", *k[2], fc, "Next Month Upper 95", "95% Upper Bound", 4, precision=0, units=1000),
        textbox("note", *k[3], [
            ("Plan flat", 11, True, KPI_VALUE),
            ("A 3-month moving average beat every model. Trend models were 150–210% "
             "worse than naive.", 9, False, TEXT_2),
        ], z=5, container=note_card),
        visual("forecast_chart", "lineChart", M, chart_y, PAGE_W - 2 * M, table_y - chart_y - G, z=6,
               title="Monthly Revenue: Actual, Forecast and 95% Prediction Interval",
               objects=_forecast_series_styles(fc),
               roles={"Category": [proj(col(fc, "period_label"), "Month")],
                      "Y": [proj(meas(fc, "Actual Revenue"), "Actual"),
                            proj(meas(fc, "Forecast Revenue"), "Forecast"),
                            proj(meas(fc, "Forecast Lower 95"), "Lower 95%"),
                            proj(meas(fc, "Forecast Upper 95"), "Upper 95%")]},
               sort=(col(fc, "period_label"), "Ascending")),
        table_visual("model_table", M, table_y, PAGE_W - 2 * M, PAGE_H - table_y - M, z=7,
                     title="Model Comparison on 4 Held-Out Months  (negative = better than naive)",
                     columns=[(mc, "model", "Model", 2), (mc, "MAE", "MAE", 1), (mc, "RMSE", "RMSE", 1),
                              (mc, "MAPE_pct", "MAPE %", 1), (mc, "vs_naive_pct", "vs Naive %", 1)],
                     sort=(col(mc, "MAE"), "Ascending")),
    ]


# Short display names: they label the header navigator buttons.
PAGES = [
    ("exec", "Overview", page_executive),
    ("customers", "Customers", page_customers),
    ("products", "Products", page_products),
    ("marketing", "Marketing", page_marketing),
    ("forecast", "Forecast", page_forecast),
]


# ==========================================================================
# Writers
# ==========================================================================

def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # PBIP files must be UTF-8 without BOM
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def custom_theme() -> dict:
    """Report theme: colours, fonts and default formatting for every visual type."""
    def sc(c):
        return {"solid": {"color": c}}

    no_chrome = {"background": [{"show": False}], "border": [{"show": False}],
                 "dropShadow": [{"show": False}], "title": [{"show": False}]}
    return {
        "name": "Olist Intelligence",
        "dataColors": PALETTE + [BOUND, "#6da7ec", "#86b6ef", "#b7d3f6"],
        "background": CARD_BG,
        "foreground": TEXT,
        "backgroundLight": ZEBRA,
        "backgroundNeutral": LINE,
        "foregroundNeutralSecondary": TEXT_2,
        "tableAccent": ACCENT,
        "good": PALETTE[2],
        "neutral": PALETTE[3],
        "bad": PALETTE[7],
        "maximum": "#86b6ef",
        "center": "#3987e5",
        "minimum": "#184f95",
        "textClasses": {
            "callout": {"fontSize": 24, "fontFace": FONT_BOLD, "color": KPI_VALUE},
            "title": {"fontSize": 11, "fontFace": FONT_BOLD, "color": TEXT},
            "header": {"fontSize": 10, "fontFace": FONT_BOLD, "color": TEXT},
            "label": {"fontSize": 9, "fontFace": FONT, "color": TEXT_2},
            "largeTitle": {"fontSize": 16, "fontFace": FONT_BOLD, "color": TEXT},
        },
        "visualStyles": {
            "*": {"*": {
                "background": [{"show": True, "color": sc(CARD_BG), "transparency": 0}],
                "border": [{"show": True, "color": sc(LINE), "radius": 10, "width": 1}],
                "dropShadow": [{"show": True, "color": sc(SHADOW), "position": "Outer", "preset": "Custom",
                                "shadowSpread": 0, "shadowBlur": 14, "angle": 90, "shadowDistance": 3,
                                "transparency": 55}],
                "title": [{"show": True, "fontColor": sc(TEXT), "fontSize": 11, "fontFamily": FONT_BOLD,
                           "alignment": "left"}],
                "padding": [{"top": 8, "bottom": 8, "left": 12, "right": 12}],
                "categoryAxis": [{"labelColor": sc(TEXT_2), "fontFamily": FONT, "fontSize": 9,
                                  "showAxisTitle": False, "gridlineShow": False}],
                "valueAxis": [{"labelColor": sc(TEXT_2), "fontFamily": FONT, "fontSize": 9,
                               "showAxisTitle": False, "gridlineColor": sc(GRID_LINE),
                               "gridlineStyle": "dotted"}],
                "legend": [{"labelColor": sc(TEXT_2), "fontFamily": FONT, "fontSize": 9, "position": "Top"}],
            }},
            "page": {"*": {
                "background": [{"color": sc(CANVAS), "transparency": 0}],
                "outspace": [{"color": sc(CANVAS), "transparency": 0}],
                "outspacePane": [{"backgroundColor": sc(PANE_BG), "foregroundColor": sc(TEXT),
                                  "border": True, "borderColor": sc(LINE), "fontFamily": FONT,
                                  "titleSize": 13, "headerSize": 10, "searchTextSize": 10,
                                  "checkboxAndApplyColor": sc(ACCENT), "inputBoxColor": sc(INPUT_BG),
                                  "transparency": 0}],
                "filterCard": [
                    {"$id": "Applied", "backgroundColor": sc(FILTER_APPLIED), "foregroundColor": sc(TEXT),
                     "border": True, "borderColor": sc(ACCENT), "fontFamily": FONT, "textSize": 10,
                     "inputBoxColor": sc(INPUT_BG), "transparency": 0},
                    {"$id": "Available", "backgroundColor": sc(CARD_BG), "foregroundColor": sc(TEXT),
                     "border": True, "borderColor": sc(LINE), "fontFamily": FONT, "textSize": 10,
                     "inputBoxColor": sc(INPUT_BG), "transparency": 0},
                ],
            }},
            "card": {"*": {
                "labels": [{"color": sc(KPI_VALUE), "fontSize": 24, "fontFamily": FONT_BOLD}],
                "categoryLabels": [{"show": False}],
                "title": [{"show": True, "fontColor": sc(TEXT_2), "fontSize": 10, "fontFamily": FONT_BOLD,
                           "alignment": "left"}],
            }},
            "slicer": {"*": {
                "title": [{"show": False}],
                "dropShadow": [{"show": False}],
                "border": [{"show": True, "color": sc(LINE), "radius": 10, "width": 1}],
                "padding": [{"top": 4, "bottom": 4, "left": 10, "right": 10}],
                "header": [{"show": True, "fontColor": sc(TEXT_2), "fontFamily": FONT_BOLD, "textSize": 9,
                            "outlineStyle": 0}],
                "items": [{"fontColor": sc(TEXT), "fontFamily": FONT, "textSize": 10,
                           "background": sc(CARD_BG), "outlineStyle": 0}],
                "dropdown": [{"borderRadius": 6, "borderColor": sc("#2D4570"), "iconColor": sc(ACCENT)}],
                "slider": [{"show": True, "color": sc(ACCENT), "handleFillColor": sc(ACCENT),
                            "handleBorderColor": sc(KPI_VALUE)}],
                "date": [{"fontColor": sc(TEXT), "fontFamily": FONT, "textSize": 9, "background": sc(ZEBRA)}],
            }},
            "tableEx": {"*": {
                "columnHeaders": [{"backColor": sc(TABLE_HEAD), "fontColor": sc("#FFFFFF"), "fontFamily": FONT_BOLD,
                                   "fontSize": 10, "outlineStyle": 0}],
                "values": [{"backColorPrimary": sc(CARD_BG), "backColorSecondary": sc(ZEBRA),
                            "fontColorPrimary": sc(TEXT), "fontColorSecondary": sc(TEXT),
                            "fontFamily": FONT, "fontSize": 10, "outlineStyle": 0}],
                "grid": [{"gridHorizontal": True, "gridHorizontalColor": sc(GRID_LINE),
                          "gridVertical": False, "rowPadding": 4, "outlineStyle": 0}],
            }},
            "clusteredBarChart": {"*": {
                # outside the bar: inside-end labels are unreadable on a same-colour bar
                "labels": [{"show": True, "color": sc(TEXT_2), "fontFamily": FONT, "fontSize": 9,
                            "labelDisplayUnits": 0, "labelPosition": "OutsideEnd"}],
            }},
            "lineChart": {"*": {
                "lineStyles": [{"strokeWidth": 3, "showMarker": True, "markerSize": 5, "areaShow": True}],
            }},
            "textbox": {"*": {**no_chrome,
                              "padding": [{"top": 6, "bottom": 2, "left": 14, "right": 8}]}},
            "pageNavigator": {"*": {
                **no_chrome,
                "layout": [{"orientation": 0, "cellPadding": 6}],
                "shape": [{"tileShape": "rectangleRounded", "rectangleRoundedCurve": 14}],
                "fill": [{"$id": "default", "show": True, "fillColor": sc(NAVY), "transparency": 0},
                         {"$id": "hover", "show": True, "fillColor": sc(NAVY_HOVER), "transparency": 0},
                         {"$id": "selected", "show": True, "fillColor": sc(ACCENT), "transparency": 0}],
                "text": [{"$id": "default", "show": True, "fontColor": sc(ON_NAVY), "fontFamily": FONT_BOLD,
                          "fontSize": 10},
                         {"$id": "hover", "fontColor": sc("#FFFFFF")},
                         {"$id": "selected", "fontColor": sc("#FFFFFF")}],
                "outline": [{"$id": "default", "show": False}],
            }},
        },
    }


def accent_kpis(visuals: list[dict]) -> list[dict]:
    """Give the headline KPI row a coloured border each, left to right in KPI_ACCENTS order."""
    top = sorted((v for v in visuals if v["visual"]["visualType"] == "card"
                  and v["position"]["y"] in (KPI_Y, FILTER_Y)), key=lambda v: v["position"]["x"])
    for i, v in enumerate(top):
        v["visual"].setdefault("visualContainerObjects", {})["border"] = [{"properties": {
            "show": lit("true"), "color": _solid(KPI_ACCENTS[i % len(KPI_ACCENTS)]),
            "radius": lit("10D"), "width": lit("2D")}}]
    return visuals


def build(out_dir: Path = OUT_DIR) -> list[Path]:
    model_dir = out_dir / f"{NAME}.SemanticModel"
    report_dir = out_dir / f"{NAME}.Report"
    for d in (model_dir, report_dir):
        if d.exists():
            # keep Desktop's local cache/settings if present, replace definitions
            for child in d.iterdir():
                if child.name != ".pbi":
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
    written: list[Path] = []

    def w(path: Path, obj) -> None:
        _dump(path, obj)
        written.append(path)

    # project + semantic model
    w(out_dir / f"{NAME}.pbip", {
        "$schema": S_PBIP, "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })
    w(model_dir / "definition.pbism", {"$schema": S_PBISM, "version": "4.0", "settings": {}})
    w(model_dir / "model.bim", build_model())

    # report shell
    w(report_dir / "definition.pbir", {
        "$schema": S_PBIR, "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}},
    })
    base_src = DESKTOP_THEMES / f"{BASE_THEME}.json"
    base_dst = report_dir / "StaticResources" / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json"
    base_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base_src, base_dst)
    written.append(base_dst)
    w(report_dir / "StaticResources" / "RegisteredResources" / "OlistTheme.json", custom_theme())

    defn = report_dir / "definition"
    w(defn / "version.json", {"$schema": S_VERSION, "version": "2.0.0"})
    w(defn / "report.json", {
        "$schema": S_REPORT,
        "themeCollection": {
            "baseTheme": {"name": BASE_THEME, "reportVersionAtImport": "5.61", "type": "SharedResources"},
            "customTheme": {"name": "OlistTheme.json", "reportVersionAtImport": "5.61",
                            "type": "RegisteredResources"},
        },
        "layoutOptimization": "None",
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "OlistTheme.json", "path": "OlistTheme.json", "type": "CustomTheme"}]},
        ],
    })
    w(defn / "pages" / "pages.json", {
        "$schema": S_PAGES, "pageOrder": [p[0] for p in PAGES], "activePageName": PAGES[0][0]})
    for page_id, display, builder in PAGES:
        pdir = defn / "pages" / page_id
        w(pdir / "page.json", {
            "$schema": S_PAGE, "name": page_id, "displayName": display,
            "displayOption": "FitToPage", "height": PAGE_H, "width": PAGE_W,
        })
        for vis in accent_kpis(builder()):
            w(pdir / "visuals" / vis["name"] / "visual.json", vis)

    # Desktop's per-user settings and data cache should never be committed
    (out_dir / ".gitignore").write_text(
        "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")
    return written


# ==========================================================================
# Validation against Microsoft's published JSON schemas
# ==========================================================================

def validate(paths: list[Path]) -> int:
    """Validate every PBIR/PBIP JSON file against the schema it declares."""
    import os
    import tempfile
    import urllib.request

    from jsonschema import Draft7Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7

    cache = Path(tempfile.gettempdir()) / "pbir-schema-cache"
    cache.mkdir(exist_ok=True)

    def fetch(uri: str) -> dict:
        raw = uri.replace("https://developer.microsoft.com/json-schemas/",
                          "https://raw.githubusercontent.com/microsoft/json-schemas/main/")
        f = cache / (raw.split("json-schemas/main/")[-1].replace("/", "__"))
        if not f.exists():
            with urllib.request.urlopen(raw, timeout=30) as r:
                f.write_bytes(r.read())
        return json.loads(f.read_text(encoding="utf-8-sig"))

    registry = Registry(retrieve=lambda uri: Resource.from_contents(fetch(uri), default_specification=DRAFT7))
    failures = 0
    checked = 0

    # the custom theme carries no $schema, so check it against the Desktop-matched theme schema
    for p in paths:
        if p.name == "OlistTheme.json":
            doc = json.loads(p.read_text(encoding="utf-8"))
            errors = list(Draft7Validator(fetch(S_THEME)).iter_errors(doc))
            checked += 1
            if errors:
                failures += 1
                for e in errors[:8]:
                    print(f"  INVALID theme: {'/'.join(map(str, e.absolute_path))} -> {e.message[:200]}")
    for p in paths:
        if p.suffix not in (".json", ".pbir", ".pbism", ".pbip") or "BaseThemes" in str(p) \
                or "RegisteredResources" in str(p):
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        url = doc.get("$schema")
        if not url:
            continue
        schema = fetch(url)
        errors = sorted(Draft7Validator(schema, registry=registry).iter_errors(doc), key=lambda e: e.path)
        checked += 1
        if errors:
            failures += 1
            rel = os.path.relpath(p, OUT_DIR)
            for e in errors[:5]:
                print(f"  INVALID {rel}: {'/'.join(map(str, e.absolute_path))} -> {e.message[:200]}")
    print(f"validated {checked} files, {failures} with errors")
    return failures


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    paths = build()
    model = json.loads((OUT_DIR / f"{NAME}.SemanticModel" / "model.bim").read_text(encoding="utf-8"))
    n_meas = sum(len(t.get("measures", [])) for t in model["model"]["tables"])
    n_vis = sum(1 for p in paths if p.name == "visual.json")
    print(f"built {OUT_DIR / (NAME + '.pbip')}")
    print(f"  model : {len(model['model']['tables'])} tables, "
          f"{len(model['model']['relationships'])} relationships, {n_meas} measures")
    print(f"  report: {len(PAGES)} pages, {n_vis} visuals")
    if args.validate:
        raise SystemExit(1 if validate(paths) else 0)


if __name__ == "__main__":
    main()
