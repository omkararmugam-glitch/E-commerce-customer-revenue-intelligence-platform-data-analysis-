# Olist Intelligence — Power BI Dashboard

A Power BI **project** (`.pbip`): the semantic model and report are stored as plain-text files
rather than a single binary `.pbix`, so the whole dashboard is version-controllable and can be
regenerated from code.

![Executive Overview page](../docs/screenshots/powerbi_overview.png)

Screenshots of all five pages are in the main [README](../README.md#screenshots).

```
dashboard/
├── OlistIntelligence.pbip              <- open this
├── OlistIntelligence.SemanticModel/
│   ├── definition.pbism
│   └── model.bim                       13 tables, 9 relationships, 38 measures
└── OlistIntelligence.Report/
    ├── definition.pbir
    ├── StaticResources/                base theme + custom project theme
    └── definition/pages/               5 pages, 65 visuals
```

## Opening it — first time

1. Double-click **`OlistIntelligence.pbip`** (opens in Power BI Desktop).
2. A yellow banner says *"Some of the tables have incomplete or no data"*. Click **Refresh now**.
   The project ships without cached data, so the first refresh loads the 13 Parquet files from
   `data/powerbi/` (about a minute).
3. After that, **File → Save** keeps a local cache so later opens are instant.

If Desktop refuses to open or save the project, enable these under
**File → Options and settings → Options → Preview features** and restart:
- *Power BI Project (.pbip) save option*
- *Store reports using enhanced metadata format (PBIR)*

### If you move the project

Every table loads through a single parameter, `DataFolder`. If the data lives somewhere else, go to
**Home → Transform data → Edit parameters** and point `DataFolder` at the new `data\powerbi\`
folder (keep the trailing backslash).

### OneDrive note

This project sits inside a OneDrive-synced folder. Microsoft notes that saving `.pbip` projects
directly into synced folders can cause sync conflicts. If a save fails, pause OneDrive sync while
working, or copy the `dashboard/` folder to a local path such as `C:\PowerBI\`.

## Pages

| Page | What it answers | Filters |
|---|---|---|
| **Overview** | Revenue, orders, customers, median vs mean order value, monthly trend, revenue by state and category, delivery and satisfaction KPIs | Year, order date range, customer state, payment method |
| **Customers** | Repeat rate, revenue by RFM and K-Means segment, retention curve, fair 3-month cohort comparison | RFM segment, K-Means segment, customer state, risk tier |
| **Products** | Category momentum (Jun–Aug vs Mar–May 2018), price-vs-volume scatter, product revenue ranking | Category, price-volume quadrant, year, seller state |
| **Marketing** | Revenue by payment method, credit-card AOV by instalment count, state scorecard, seller table — **explicitly not channel attribution** | Payment method, customer state, year |
| **Forecast** | Actual vs forecast with 95% interval, next-month forecast and bounds, model comparison | — (forecast data is not linked to the other tables) |

Each page carries a header stating its caveats, so the dashboard can be shared without the notebooks.

Two notes on the filters:
- The retention curve (Customers) and the forecast page read pre-aggregated tables, so the
  customer and date filters don't change them.
- The Category Momentum chart compares two fixed 2018 windows, so the Year filter doesn't
  change it either.

## Design

All formatting lives in one theme file,
`OlistIntelligence.Report/StaticResources/RegisteredResources/OlistTheme.json`, validated against
Microsoft's report-theme schema for Desktop 2.157.

- **Layout:** a navy header band on every page, holding the title, a caveat line and a page
  navigator, then a filter bar, a KPI row and two rows of charts. Everything sits on a
  1280 × 720 grid with 16 px margins and 12 px gutters.
- **Colour — "midnight" dark theme:** a deep navy canvas `#0A1628`, lighter navy cards `#13233F`
  with rounded corners and a soft shadow, and a `#102A4F` header band. Text is light (`#E6EDF7`
  titles, `#9FB2CC` labels), and KPI values are white. Each page's headline KPI row has coloured
  borders — blue, teal, amber, magenta, left to right. Table headers are a bright blue `#1E4FA8`
  over striped dark rows.
- **Chart colours:** the dark-surface steps of the same hues, in the same order, as the notebook
  charts. They were checked against the card colour with the dataviz palette validator, and all
  five checks pass: lightness, chroma, colour-blind separation, and 3:1 contrast.
- **Type:** Segoe UI Semibold for titles and KPI values, Segoe UI for labels and axes. Bar labels
  sit outside the bars so they stay readable on the dark cards.
- **Filters:** dark dropdown slicers with rounded borders and blue chevrons, a blue date-range
  slider, and a dark filter pane that highlights applied filters in blue.
- **Navigation:** the header buttons switch pages. In Power BI Desktop's editing view, hold
  **Ctrl** while clicking; in reading view or the Power BI service, a plain click works.

To restyle the whole dashboard, edit `custom_theme()` in `src/build_pbip.py` and rebuild. Colours
and fonts are set there once, not per visual.

## What was verified

This project was opened in Power BI Desktop 2.157, refreshed, and queried directly through the
Desktop's Analysis Services engine:

- **All 77 files validate:** 76 report files against Microsoft's PBIR JSON schemas (the
  versions Desktop 2.157 accepts without preview switches), and the theme against the 2.157
  report-theme schema.
- **All five pages rendered with live data** and were checked in screenshots. Every KPI matched
  the notebooks: revenue R$13,181,027, 96,211 orders, 93,104 customers, median order R$86.50,
  mean R$137.00, late rate 8.1%, one-star rate 9.7%.
- **Every measure was executed.** Order-grain and item-grain revenue reconcile to the cent
  (R$13,181,027.13 both ways), and RFM/K-Means shares match notebook 05 exactly.
- **Every filter was tested.** Each slicer's filter path was queried on the live model: São Paulo
  gives R$5,055,587 at a R$125.12 AOV, boleto R$121.39, and November 2017 R$987,765 from 7,289
  orders — all matching the notebooks.

Verification found and fixed four defects before hand-off:

| Defect | Fix |
|---|---|
| Retention curve showed the **same value (0.26%) for every month** — the `> 0` filter overwrote the chart's own axis | `KEEPFILTERS`; month 1 is now 0.48%, month 2 0.34%, month 3 0.25% |
| Forecast cards **summed the 95% bounds across three months**, which is not a valid interval | Replaced with next-month bounds: R$598k – R$1.09M |
| MoM % compared **August's 23 clean days against July's 31 days**, producing a fake −7.8% | Returns blank for partial months |
| Instalment chart **mixed boleto orders (always 1x) into the 1x bar** | Credit-card-only measure; 1x is now R$82.49 |

Both of the last two fixes are confirmed on screen: the retention curve falls from about 0.48%
instead of sitting flat, and the credit-card instalment chart starts near R$82 at 1x.

## Regenerating

The whole project is generated by [`src/build_pbip.py`](../src/build_pbip.py):

```bash
python src/export_powerbi.py          # refresh data/powerbi/
python src/build_pbip.py --validate   # rebuild the project and schema-check every file
```

Rebuilding **overwrites the definition files**. Edits made in Power BI Desktop are saved to those
same files, so if you customise the report in Desktop, do not rerun the generator afterwards
without copying your changes first. Desktop's local cache in `.pbi/` is preserved across rebuilds.

## Built-in caveats

These are properties of the source data, repeated here because the dashboard is the most likely
thing to be shared on its own:

- **No margin or profit anywhere** — the dataset has no cost data. Revenue is item price.
- **Marketing page is proxies, not channels** — no campaign, spend or session data exists.
- **Two revenue measures, two grains.** `Total Revenue` (orders) and `Item Revenue` (lines) both
  total R$13,181,027. Use `Item Revenue` whenever a visual is sliced by product, category or seller,
  because those dimensions filter the line table, not the order table.
- **August 2018 is partial** — the export thins from 22 August. Trend visuals use
  `Revenue (Trend)`, which excludes the truncated tail.
- **Forecast has no Black Friday** — 20 months is too short to estimate annual seasonality.
