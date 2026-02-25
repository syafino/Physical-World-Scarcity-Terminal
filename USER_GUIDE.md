# PWST User Guide
## Physical World Scarcity Terminal — Operator Manual
**Version:** 0.1.0-alpha  
**Terminal Build:** Pre-Release

---

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║   ██████╗ ██╗    ██╗███████╗████████╗                                     ║
║   ██╔══██╗██║    ██║██╔════╝╚══██╔══╝                                     ║
║   ██████╔╝██║ █╗ ██║███████╗   ██║                                        ║
║   ██╔═══╝ ██║███╗██║╚════██║   ██║                                        ║
║   ██║     ╚███╔███╔╝███████║   ██║                                        ║
║   ╚═╝      ╚══╝╚══╝ ╚══════╝   ╚═╝                                        ║
║                                                                           ║
║   Physical World Scarcity Terminal                                        ║
║   "Reality has an API. Learn to query it."                                ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

---

## 1. Philosophy

### Why This Exists

Financial terminals show you what markets *think*. This terminal shows you what the physical world *is doing*. 

When an aquifer depletes, the market learns 90 days later when crop yields crash. When a port jams, the market learns 30 days later when shelves empty. PWST gives you the signal when it happens in the physical world—not when it arrives in quarterly earnings.

### Design Principles

**Information Density Over Aesthetics**  
Every pixel earns its place. No decorative gradients, no excessive padding, no "click here to learn more." Data is primary.

**Keyboard Over Mouse**  
The fastest path to any function is through your keyboard. The Command Palette (`Cmd+K`) is your interface to everything.

**Skepticism Over Prediction**  
We surface anomalies and correlations. We do not tell you what will happen. We tell you that something unusual *is* happening and show you what has historically followed.

**Open Over Proprietary**  
The code is yours. The data sources are public. The methodology is documented. You own your analysis.

---

## 2. Quick Start

### Launch Sequence

```bash
# Start the terminal
cd Physical-World-Scarcity-Terminal
docker-compose up -d
streamlit run src/ui/app.py
```

### Your First Query

1. Press `Cmd+K` to open the Command Palette
2. Type: `WATR US-CA <GO>`
3. Press `Enter`

The terminal will:
- Fetch current groundwater levels for California
- Render monitoring stations on the 3D map
- Display tabular data in the right panel
- Flag any anomalies exceeding 2σ from baseline

---

## 3. Command Syntax

### Basic Structure

```
<FUNCTION_CODE> [REGION] [MODIFIERS] <GO>
```

| Component | Required | Description |
|-----------|----------|-------------|
| `FUNCTION_CODE` | Yes | 4-letter code identifying the data type |
| `REGION` | No | ISO region code (defaults to configured home region) |
| `MODIFIERS` | No | Flags to filter or transform output |
| `<GO>` | Yes | Execution trigger (can also press Enter) |

### Examples

```
WATR <GO>                      # Water data for default region
WATR US-CA <GO>                # Water data for California
WATR US-CA -anomaly <GO>       # Only stations with anomalies
GRID ERCOT -24h <GO>           # Texas grid, last 24 hours
SHIP SUEZ -density <GO>        # Suez Canal vessel density map
CORR WATR:AGRI US-CA <GO>      # Water-to-agriculture correlation
```

---

## 4. Function Code Reference

### Water & Hydrology

| Code | Name | Description |
|------|------|-------------|
| `WATR` | Groundwater | Aquifer levels, well depths, depletion rates |
| `FLOW` | Streamflow | River discharge, watershed flow volumes |
| `LAKE` | Reservoirs | Lake/reservoir levels, storage capacity percentages |

**Example:** `WATR US-CA -30d <GO>` — California groundwater, 30-day trend

### Energy & Grid

| Code | Name | Description |
|------|------|-------------|
| `GRID` | Power Grid | Load, capacity, outages by grid operator |
| `FUEL` | Petroleum | Crude storage, refinery utilization, pipeline flows |

**Example:** `GRID ERCOT -anomaly <GO>` — Texas grid anomalies

### Agriculture & Land

| Code | Name | Description |
|------|------|-------------|
| `AGRI` | Crop Health | NDVI vegetation indices, soil moisture |
| `TEMP` | Temperature | Deviation from 30-year climate normals |
| `CLIM` | Climate Index | Drought indices, sea surface temperatures |

**Example:** `AGRI US-KS -compare:US-NE <GO>` — Kansas vs Nebraska crop health

### Logistics & Trade

| Code | Name | Description |
|------|------|-------------|
| `SHIP` | Maritime | Vessel positions, chokepoint density |
| `PORT` | Ports | Container dwell times, congestion levels |
| `RAIL` | Rail Freight | Intermodal volumes, velocity metrics |

**Example:** `SHIP SUEZ -48h <GO>` — Suez Canal traffic, 48-hour window

### Mining & Materials

| Code | Name | Description |
|------|------|-------------|
| `MINE` | Mining | Production volumes, stockpile levels |
| `CHIP` | Semiconductors | Fab utilization (data availability limited) |

**Example:** `MINE COPPER -7d <GO>` — Copper production, weekly

### Weather & Events

| Code | Name | Description |
|------|------|-------------|
| `STRM` | Storms | Active tropical systems, severe weather |

**Example:** `STRM ATLANTIC <GO>` — Active Atlantic storm tracking

### Intelligence & Analysis

| Code | Name | Description |
|------|------|-------------|
| `RISK` | Risk Dashboard | Aggregated anomaly scores, regional risk |
| `CORR` | Correlation | Cross-indicator statistical relationships |

**Example:** `RISK US-CA <GO>` — Full risk dashboard for California

---

## 5. Modifiers

Modifiers alter how data is retrieved or displayed. Append them before `<GO>`.

### Time Window

| Modifier | Effect |
|----------|--------|
| `-1h` | Last 1 hour |
| `-24h` | Last 24 hours |
| `-7d` | Last 7 days |
| `-30d` | Last 30 days |
| `-90d` | Last 90 days |
| `-ytd` | Year to date |

### Filters

| Modifier | Effect |
|----------|--------|
| `-anomaly` | Show only values exceeding 2σ threshold |
| `-critical` | Show only values exceeding 3σ threshold |
| `-stale` | Include data older than 24 hours (hidden by default) |

### Display

| Modifier | Effect |
|----------|--------|
| `-table` | Force tabular view |
| `-map` | Force map view |
| `-chart` | Force time series view |
| `-density` | Show heatmap/density visualization |

### Export

| Modifier | Effect |
|----------|--------|
| `-export` | Download results as CSV |
| `-json` | Download results as JSON |

### Comparison

| Modifier | Effect |
|----------|--------|
| `-compare:<REGION>` | Side-by-side with another region |
| `-baseline:<DATE>` | Compare against specific historical date |

---

## 6. Region Codes

PWST uses ISO 3166-2 codes for regions. Some examples:

### United States
| Code | Region |
|------|--------|
| `US` | United States (national) |
| `US-CA` | California |
| `US-TX` | Texas |
| `US-AZ` | Arizona |
| `US-CO` | Colorado |

### Grid Operators (Energy)
| Code | Region |
|------|--------|
| `ERCOT` | Texas Interconnection |
| `CAISO` | California ISO |
| `PJM` | PJM Interconnection (Mid-Atlantic) |
| `MISO` | Midcontinent ISO |

### Maritime Chokepoints
| Code | Region |
|------|--------|
| `SUEZ` | Suez Canal |
| `PANAMA` | Panama Canal |
| `HORMUZ` | Strait of Hormuz |
| `MALACCA` | Strait of Malacca |

### Watersheds
| Code | Region |
|------|--------|
| `COLORADO-BASIN` | Colorado River Basin |
| `CENTRAL-VALLEY` | California Central Valley |

---

## 7. Reading the Display

### Map Panel (Left)

The 3D map renders geospatial data using color-coded points, polygons, or heatmaps.

**Point Colors:**
- 🟢 **Green** — Normal (within 1σ)
- 🟡 **Yellow** — Watch (1-2σ deviation)
- 🟠 **Orange** — Warning (2-3σ deviation)
- 🔴 **Red** — Critical (>3σ deviation)
- ⚫ **Gray** — Stale (data >24h old)

**Interactions:**
- Scroll to zoom
- Click+drag to rotate (3D)
- Click point for details in data panel

### Data Panel (Right)

Tabular view of current query results.

```
▓ INDICATOR: GW_LEVEL
▓ REGION: California
▓ LAST UPDATE: 14:00 UTC
────────────────────────────
STATION      VALUE   DELTA   STATUS
KERN-001     -12.3m  ▼ 0.8m  [!] ANOMALY
TULARE-007   -8.7m   ▼ 0.2m  NORMAL
FRESNO-012   -15.1m  ▼ 1.1m  [!] ANOMALY
```

**Columns:**
- `STATION` — Monitoring site identifier
- `VALUE` — Current reading with unit
- `DELTA` — Change from previous period (▲ up, ▼ down)
- `STATUS` — Anomaly flag if threshold exceeded

### Time Series Panel (Bottom)

Historical trend visualization for selected indicator/station.

- Solid line: Observed values
- Dashed line: Historical baseline (30-day rolling mean)
- Shaded band: ±2σ confidence interval
- Red markers: Detected anomalies

### Status Bar (Bottom)

```
> WATR US-CA <GO>                                           [Cmd+K] HELP
```

- Left: Command input area (click or press `/` to focus)
- Right: Keyboard shortcut hints

---

## 8. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd+K` | Open Command Palette |
| `/` | Focus command input |
| `Esc` | Close palette / Clear input |
| `↑` / `↓` | Navigate command history |
| `Tab` | Autocomplete region/function |
| `Cmd+E` | Export current view |
| `Cmd+R` | Refresh data |
| `?` | Show help overlay |

---

## 9. Understanding Anomalies

### What Triggers an Anomaly?

An anomaly is flagged when an observed value deviates significantly from its historical baseline.

**Calculation:**
```
z_score = (observed_value - rolling_mean) / rolling_std
```

**Thresholds:**
| Z-Score | Severity | UI Treatment |
|---------|----------|--------------|
| 1-2σ | Watch | Yellow indicator |
| 2-3σ | Warning | Orange indicator, logged |
| >3σ | Critical | Red indicator, alert generated |

### What Anomalies Mean

An anomaly is **not** a prediction. It is a statement:

> "This value is statistically unusual compared to recent history."

The PWST does not know *why* an anomaly occurred. It surfaces the anomaly so *you* can investigate.

### False Positives

Expect false positives. A 2σ threshold will flag ~5% of values even in normal operation. Use domain knowledge to filter signal from noise.

---

## 10. Correlation Engine

### Accessing Correlations

```
CORR <SOURCE>:<TARGET> [REGION] <GO>
```

**Example:**
```
CORR WATR:AGRI US-CA <GO>
```

This computes the statistical relationship between groundwater levels and crop health in California.

### Interpreting Results

```
CORRELATION ANALYSIS: GW_LEVEL → NDVI
REGION: US-CA
WINDOW: 2024-01-01 to 2026-02-25
────────────────────────────────────────
LAG (days)   CORRELATION   P-VALUE   N
7            0.12          0.234     412
14           0.31          0.003     405
30           0.58          <0.001    388
60           0.67          <0.001    359
90           0.52          <0.001    330

INTERPRETATION: Strong lagged correlation at 60 days suggests
groundwater depletion signals appear in crop health ~2 months later.
```

**Key Metrics:**
- `LAG` — Days between physical signal and target response
- `CORRELATION` — Pearson coefficient (-1 to 1)
- `P-VALUE` — Statistical significance (<0.05 = significant)
- `N` — Sample size

### Caveats

Correlation is not causation. The correlation engine identifies statistical relationships—it does not prove that one variable causes another. Always apply domain expertise before acting on correlations.

---

## 11. Data Freshness

### Update Frequencies

| Category | Typical Refresh | Source |
|----------|-----------------|--------|
| Groundwater | 6 hours | USGS |
| Streamflow | 15-60 minutes | USGS |
| Power Grid | 5-60 minutes | EIA/ISO |
| Satellite Imagery | 1-5 days | Sentinel/MODIS |
| Weather Alerts | Real-time | NWS |
| Maritime AIS | 15 min - 24 hours | Varies |

### Staleness Indicators

Data older than its expected refresh window is marked stale (gray). The data panel shows `LAST UPDATE` timestamp for every query.

To include stale data in your query:
```
WATR US-CA -stale <GO>
```

---

## 12. Troubleshooting

### "No Data Available"

1. Check region code is valid: `HELP REGIONS <GO>`
2. Check data source status: `STATUS <GO>`
3. Expand time window: add `-30d` modifier
4. Data may not exist for requested indicator/region combination

### "Rate Limited"

Some data sources restrict request frequency. Wait and retry, or:
```
STATUS SOURCES <GO>
```
Shows current rate limit status per source.

### Map Not Rendering

1. Check browser WebGL support
2. Reduce data density: add `-limit:100` modifier
3. Switch to table view: add `-table` modifier

### Stale Data

If data appears old:
1. Check source status: `STATUS <GO>`
2. Manual refresh: `Cmd+R`
3. Source may be experiencing outage (check upstream)

---

## 13. Glossary

| Term | Definition |
|------|------------|
| **Anomaly** | A value deviating significantly (>2σ) from historical baseline |
| **Baseline** | Rolling 30-day mean used for anomaly detection |
| **Chokepoint** | Geographic bottleneck in logistics networks |
| **Correlation** | Statistical measure of relationship between two variables |
| **Function Code** | 4-letter identifier for data categories (e.g., WATR, GRID) |
| **Granger Causality** | Statistical test for predictive relationships |
| **NDVI** | Normalized Difference Vegetation Index (crop health metric) |
| **σ (Sigma)** | Standard deviation; measure of statistical dispersion |
| **Z-Score** | Number of standard deviations from the mean |

---

## 14. Support & Contribution

### Reporting Issues

File issues at: `github.com/[your-org]/Physical-World-Scarcity-Terminal/issues`

Include:
- Command that produced unexpected behavior
- Expected vs. actual result
- Screenshot if visual issue
- Browser/OS information

### Contributing

PWST is open source. Contributions welcome:
- New data source integrations
- Additional function codes
- UI/UX improvements
- Documentation fixes

See `CONTRIBUTING.md` for guidelines.

---

## 15. Legal & Data Attribution

### Data Sources

PWST aggregates publicly available data. All data remains property of its original source. Key attributions:

- **USGS** — Water data (Public Domain)
- **NOAA** — Climate data (Public Domain)
- **EIA** — Energy data (Public Domain)
- **NASA** — Satellite data (Public Domain with attribution)
- **Copernicus/ESA** — Sentinel imagery (Free for research with attribution)

### Disclaimer

PWST is an informational tool. It does not provide financial, investment, or operational advice. Anomaly detection and correlation analysis are statistical observations, not predictions. Users assume all risk for decisions made using this system.

---

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║   "The map is not the territory, but a good terminal makes the           ║
║    territory legible."                                                    ║
║                                                                           ║
║                                              — PWST Operating Manual      ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝
```
