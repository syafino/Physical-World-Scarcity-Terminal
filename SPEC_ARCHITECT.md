# PWST Technical Architecture Specification
## Physical World Scarcity Terminal — Source of Truth Document
**Version:** 0.5.0-alpha  
**Last Updated:** 2026-02-27  
**Status:** Phase 5 — The Predictive Layer

---

## 1. Project Philosophy

The Physical World Scarcity Terminal (PWST) is a **command-driven intelligence system** for monitoring physical-world signals that precede economic disruption. It rejects dashboard aesthetics in favor of **information density**, **keyboard-first interaction**, and **spatial-temporal correlation**.

### Core Tenets
1. **Free-First Infrastructure** — Zero baseline cost using open-source tools
2. **Physical Reality Over Financial Abstraction** — Data from sensors, satellites, and logistics networks
3. **Correlation, Not Prediction** — Surface anomalies and their linked industrial fates
4. **Terminal Aesthetic** — High-density, dark-mode, command-palette-driven UI

---

## 2. Technical Constraints

### 2.1 Budget Envelope
| Resource | Allocation | Status |
|----------|------------|--------|
| API Credits | $25 | Reserved for fallback only |
| Snowflake Credits | Available | Reserved for scale/marketplace |
| Compute | Local-first | Developer machine / free tier cloud |

### 2.2 Technology Stack (Mandated)

#### Backend
- **Language:** Python 3.11+
- **Database:** PostgreSQL 15+ with PostGIS 3.3+ extension
- **Caching:** Redis (local) or SQLite for session cache
- **Task Queue:** Celery with Redis backend (for scheduled ingestion)
- **Spatial Processing:** GeoPandas, Shapely, Rasterio

#### Frontend
- **Framework:** Streamlit 1.30+ (primary) with custom components
- **Geospatial Rendering:** PyDeck (Deck.gl Python bindings)
- **Map Tiles:** Mapbox GL JS (free tier: 50k loads/month) or OpenStreetMap/Stadia
- **Styling:** Custom CSS injection for terminal aesthetic

#### Infrastructure (MVP)
- **Deployment:** Local Docker Compose → Railway/Fly.io free tier
- **CI/CD:** GitHub Actions (free for public repos)

### 2.3 Snowflake Decision Matrix

| Use Case | Recommendation | Rationale |
|----------|---------------|-----------|
| MVP Development | **PostGIS** | Zero cost, sufficient for regional analysis |
| Global-scale queries (>100M rows) | Snowflake | Elastic compute, no index tuning |
| Snowflake Marketplace feeds | Snowflake | Exclusive datasets (e.g., Spire AIS) |
| Multi-TB raster storage | Snowflake | Native GEOGRAPHY + cheap storage |
| Real-time streaming | Neither | Use Kafka/Redpanda → PostGIS |

**MVP RECOMMENDATION: Start with PostGIS.** Migrate specific workloads to Snowflake only when:
1. A dataset is exclusively available on Snowflake Marketplace
2. Query latency on PostGIS exceeds 10s for core operations
3. Storage exceeds 50GB of spatial data

---

## 3. Database Schema Design

### 3.1 Core Tables (PostGIS)

```sql
-- Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;

-- Spatial reference: WGS84 (EPSG:4326) for storage, Web Mercator (3857) for display

-- ============================================
-- CORE DIMENSION TABLES
-- ============================================

CREATE TABLE regions (
    region_id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,          -- e.g., 'US-CA', 'CN-GD'
    name VARCHAR(255) NOT NULL,
    region_type VARCHAR(50) NOT NULL,          -- 'country', 'state', 'watershed', 'grid_zone'
    geometry GEOMETRY(MultiPolygon, 4326),
    parent_region_id INTEGER REFERENCES regions(region_id),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_regions_geometry ON regions USING GIST(geometry);
CREATE INDEX idx_regions_code ON regions(code);

CREATE TABLE data_sources (
    source_id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,          -- e.g., 'USGS_NWIS', 'NASA_GRACE'
    name VARCHAR(255) NOT NULL,
    base_url VARCHAR(500),
    api_type VARCHAR(50),                      -- 'REST', 'GraphQL', 'FTP', 'S3'
    rate_limit_per_hour INTEGER,
    is_free BOOLEAN DEFAULT TRUE,
    cost_per_call DECIMAL(10,6) DEFAULT 0,
    auth_method VARCHAR(50),                   -- 'API_KEY', 'OAUTH', 'NONE'
    status VARCHAR(20) DEFAULT 'active',       -- 'active', 'deprecated', 'rate_limited'
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE indicators (
    indicator_id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,          -- e.g., 'GW_LEVEL', 'NDVI', 'PORT_DWELL'
    name VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL,             -- 'water', 'energy', 'agriculture', 'logistics'
    unit VARCHAR(50),                          -- 'meters', 'index', 'days', 'MW'
    description TEXT,
    function_code VARCHAR(4) NOT NULL,         -- Links to terminal command: 'WATR', 'GRID'
    source_id INTEGER REFERENCES data_sources(source_id),
    update_frequency INTERVAL,                 -- e.g., '1 day', '1 hour'
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_indicators_function ON indicators(function_code);

-- ============================================
-- TIME-SERIES OBSERVATION TABLES
-- ============================================

CREATE TABLE observations (
    observation_id BIGSERIAL PRIMARY KEY,
    indicator_id INTEGER NOT NULL REFERENCES indicators(indicator_id),
    region_id INTEGER REFERENCES regions(region_id),
    location GEOMETRY(Point, 4326),            -- For point-based observations
    observed_at TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    value_raw JSONB,                           -- Original API response for audit
    quality_flag VARCHAR(20) DEFAULT 'valid',  -- 'valid', 'estimated', 'suspect'
    ingested_at TIMESTAMPTZ DEFAULT NOW()
);
-- Hypertable candidate if using TimescaleDB
CREATE INDEX idx_obs_indicator_time ON observations(indicator_id, observed_at DESC);
CREATE INDEX idx_obs_location ON observations USING GIST(location);
CREATE INDEX idx_obs_region ON observations(region_id, observed_at DESC);

-- Partitioning by month for large datasets
-- CREATE TABLE observations_2026_02 PARTITION OF observations
--     FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

-- ============================================
-- ANOMALY & CORRELATION TABLES
-- ============================================

CREATE TABLE anomalies (
    anomaly_id BIGSERIAL PRIMARY KEY,
    indicator_id INTEGER NOT NULL REFERENCES indicators(indicator_id),
    region_id INTEGER REFERENCES regions(region_id),
    location GEOMETRY(Point, 4326),
    detected_at TIMESTAMPTZ NOT NULL,
    anomaly_type VARCHAR(50) NOT NULL,         -- 'spike', 'drop', 'trend_break', 'seasonal_deviation'
    severity DOUBLE PRECISION,                 -- Z-score or percentile
    baseline_value DOUBLE PRECISION,
    observed_value DOUBLE PRECISION,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_anomalies_time ON anomalies(detected_at DESC);
CREATE INDEX idx_anomalies_severity ON anomalies(severity DESC);

CREATE TABLE correlations (
    correlation_id BIGSERIAL PRIMARY KEY,
    source_indicator_id INTEGER NOT NULL REFERENCES indicators(indicator_id),
    target_indicator_id INTEGER NOT NULL REFERENCES indicators(indicator_id),
    region_id INTEGER REFERENCES regions(region_id),
    lag_days INTEGER DEFAULT 0,                -- Temporal offset
    correlation_coefficient DOUBLE PRECISION,
    p_value DOUBLE PRECISION,
    sample_size INTEGER,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_corr_source ON correlations(source_indicator_id);
CREATE INDEX idx_corr_target ON correlations(target_indicator_id);

-- ============================================
-- COMMAND AUDIT & USER STATE
-- ============================================

CREATE TABLE command_log (
    log_id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    command_raw VARCHAR(500) NOT NULL,         -- e.g., 'WATR US-CA <GO>'
    function_code VARCHAR(4),
    parameters JSONB,
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    response_time_ms INTEGER,
    result_count INTEGER
);
CREATE INDEX idx_cmdlog_session ON command_log(session_id, executed_at DESC);
```

### 3.2 Schema Notes
1. **JSONB for Flexibility** — Raw API responses stored for debugging/replay
2. **Dual Spatial Columns** — `region_id` for aggregated queries, `location` for point precision
3. **Function Code Linkage** — Every indicator maps to a terminal command
4. **Audit Trail** — `command_log` enables session replay and usage analytics

### 3.3 Snowflake Schema (Future State)

When migrating to Snowflake, leverage:
- `GEOGRAPHY` type for spherical calculations
- `VARIANT` for semi-structured JSON
- `TIME TRAVEL` for historical state queries
- Clustering on `(indicator_id, observed_at)` for time-series

---

## 4. Data Ingestion Strategy

### 4.1 Free API Priority Matrix

| Priority | Source | Data Type | Free Tier Limits | Python Library | Status |
|----------|--------|-----------|------------------|----------------|--------|
| P0 | USGS NWIS | Streamflow, groundwater | Unlimited | `dataretrieval` | ✅ Verified |
| P0 | NOAA NCEI | Climate, temperature | Unlimited | `requests` | ✅ Verified |
| P0 | EIA API | Energy, petroleum | 1000/hr | `requests` | ✅ Verified |
| P0 | FRED | Economic indicators | 120/min | `fredapi` | ✅ Verified |
| P1 | NASA Earthdata | GRACE, MODIS | Requires free account | `earthaccess` | ✅ Verified |
| P1 | Copernicus/Sentinel | Satellite imagery | Free for research | `sentinelsat` | ✅ Verified |
| P1 | OpenStreetMap | Infrastructure geometry | Unlimited | `osmnx` | ✅ Verified |
| P0 | NWS API | Weather forecasts, alerts | Unlimited | `requests` | ✅ Phase 5 |
| P2 | USDA NASS | Crop statistics | Unlimited | `requests` | ✅ Verified |
| P3 | MarineTraffic | AIS vessel positions | 100/day free | `requests` | [TO BE VERIFIED] |
| P3 | UN Comtrade | Trade flows | 100/hr guest | `comtradeapicall` | [TO BE VERIFIED] |
| P1 | Yahoo Finance | Stock quotes/history | Unlimited | `yfinance` | ✅ Phase 3 |
| P1 | Google News RSS | News headlines | Unlimited | `feedparser` | ✅ Phase 4 |
| P1 | Local NLP | Sentiment scoring | N/A | `nltk` (VADER) | ✅ Phase 4 |

### 4.2 Paid Fallback Strategy ($25 Budget)

Reserve paid credits for:
1. **Spire AIS** (via Snowflake Marketplace) — If MarineTraffic free tier insufficient
2. **Planet Labs** — High-resolution imagery for specific site monitoring
3. **Precisely/SafeGraph** — POI data for infrastructure mapping

**Budget Allocation:**
- $15 reserved for emergency API overages
- $10 for one-time historical data backfills

### 4.3 Ingestion Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     INGESTION PIPELINE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Scheduler│───▶│ Fetcher  │───▶│ Parser   │───▶│ Loader   │  │
│  │ (Celery) │    │ (async)  │    │ (Pydantic)│   │ (PostGIS)│  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │                                               │         │
│       ▼                                               ▼         │
│  ┌──────────┐                                   ┌──────────┐   │
│  │ Redis    │                                   │ Anomaly  │   │
│  │ (Queue)  │                                   │ Detector │   │
│  └──────────┘                                   └──────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Scheduling Cadence:**
- Water (WATR, FLOW, LAKE): Every 6 hours
- Energy (GRID, FUEL): Every 1 hour
- Agriculture (AGRI): Daily
- Climate (CLIM, TEMP): Every 3 hours
- Logistics (SHIP, PORT, RAIL): Every 15 minutes (if API allows)

---

## 5. UI Architecture

### 5.1 Terminal Design Principles

1. **Information Density** — No whitespace > 20px between elements
2. **Keyboard-First** — All actions accessible via Command Palette
3. **Scannable** — Color-coded severity, monospace data, aligned columns
4. **Contextual** — Map and data panel always synchronized

### 5.2 Layout Structure

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [PWST v0.1.0]  │ WATR US-CA <GO>                    │ 2026-02-25 14:32 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────┐  ┌──────────────────────────────┐ │
│  │                                 │  │ ▓ INDICATOR: GW_LEVEL        │ │
│  │                                 │  │ ▓ REGION: California         │ │
│  │         3D GEOSPATIAL MAP       │  │ ▓ LAST UPDATE: 14:00 UTC     │ │
│  │           (Deck.gl/PyDeck)      │  │ ──────────────────────────── │ │
│  │                                 │  │ STATION      VALUE   DELTA   │ │
│  │                                 │  │ KERN-001     -12.3m  ▼ 0.8m  │ │
│  │                                 │  │ TULARE-007   -8.7m   ▼ 0.2m  │ │
│  │                                 │  │ FRESNO-012   -15.1m  ▼ 1.1m  │ │
│  │                                 │  │ [ANOMALY] KERN-001 > 2σ      │ │
│  │                                 │  │                              │ │
│  └─────────────────────────────────┘  └──────────────────────────────┘ │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ TIME SERIES: GW_LEVEL @ KERN-001                                │   │
│  │ ════════════════════════════════════════════════════════════════│   │
│  │  -10m ┤                              ╭─────╮                     │   │
│  │  -12m ┤                    ╭─────────╯     ╰──────╮              │   │
│  │  -14m ┤  ──────────────────╯                      ╰───▼ CURRENT │   │
│  │       └──────────────────────────────────────────────────────── │   │
│  │        Jan        Feb        Mar        Apr        May          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│ > _                                                        [Cmd+K] HELP │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Command Palette Specification

**Trigger:** `Cmd+K` (macOS) / `Ctrl+K` (Windows/Linux)

**Syntax:** `<FUNCTION_CODE> [REGION] [MODIFIERS] <GO>`

**Examples:**
```
WATR US-CA <GO>              # Water data for California
GRID ERCOT -anomaly <GO>     # Texas grid with anomaly filter
SHIP SUEZ -48h <GO>          # Suez Canal traffic, last 48 hours
CORR WATR:AGRI US-CA <GO>    # Correlate water to agriculture
RISK US-CA <GO>              # Full risk dashboard for region
FIN US-TX <GO>               # Financial correlation view (Phase 3)
NEWS US-TX <GO>              # News sentiment analysis (Phase 4)
WX US-TX <GO>                # Weather forecasts & predictive alerts (Phase 5)
```

**Modifiers:**
- `-anomaly` — Filter to anomalies only
- `-24h`, `-7d`, `-30d` — Time window
- `-export` — Download as CSV
- `-compare:<REGION>` — Side-by-side comparison

### 5.4 Color Coding (Terminal Palette)

| Severity | Hex Code | Usage |
|----------|----------|-------|
| Normal | `#00FF00` | Values within 1σ |
| Watch | `#FFFF00` | Values 1-2σ from baseline |
| Warning | `#FFA500` | Values 2-3σ from baseline |
| Critical | `#FF0000` | Values >3σ or system alerts |
| Stale | `#808080` | Data >24h old |
| Background | `#0D1117` | Primary background |
| Surface | `#161B22` | Cards, panels |
| Text | `#E6EDF3` | Primary text |
| Accent | `#58A6FF` | Links, selections |

### 5.4.1 Ticker Tray (Phase 2)

**Position:** Fixed at bottom of viewport, 40px height
**Background:** `#0D1117` with top border `#30363D`
**Content:** Horizontally scrolling alert feed from Anomaly Engine

**Display Format:**
```
[CRITICAL] GRID_STRAIN: ERCOT MARGIN 4.2% ║ [WARNING] PORT_CONGESTION: 18 VESSELS WAITING ║ [NORMAL] AQUIFER: LEVELS STABLE
```

**Behavior:**
- Auto-scroll left at 50px/second
- Pause on hover
- Click alert to jump to relevant function
- Color-coded by severity level
- Updates every 30 seconds from `/api/alerts` endpoint

### 5.5 Streamlit Component Structure

```
streamlit_app/
├── app.py                      # Main entry point
├── components/
│   ├── command_palette.py      # Cmd+K handler
│   ├── map_view.py             # PyDeck 3D map
│   ├── data_panel.py           # Right-side data grid
│   ├── time_series.py          # Altair/Plotly charts
│   └── status_bar.py           # Bottom command line
├── handlers/
│   ├── watr.py                 # WATR command logic
│   ├── grid.py                 # GRID command logic
│   ├── ship.py                 # SHIP command logic
│   └── ...                     # One per function code
├── services/
│   ├── data_fetcher.py         # API client abstraction
│   ├── anomaly_detector.py     # Statistical engine
│   └── correlation_engine.py   # Cross-indicator analysis
├── styles/
│   └── terminal.css            # Dark theme overrides
└── config/
    ├── sources.yaml            # API configurations
    └── indicators.yaml         # Indicator metadata
```

---

## 6. Anomaly Detection Engine

### 6.1 Statistical Methods

1. **Z-Score Detection** — Flag when value deviates >2σ from rolling 30-day mean
2. **Seasonal Decomposition** — STL decomposition to isolate trend/seasonal/residual
3. **Change Point Detection** — PELT algorithm for structural breaks
4. **Spatial Clustering** — DBSCAN to identify regional anomaly clusters

### 6.2 Threshold-Based Alert System (Phase 2)

**Alert Severity Levels:**
| Level | Code | Color | Meaning |
|-------|------|-------|---------|
| 0 | NORMAL | `#00FF00` | Within expected parameters |
| 1 | WATCH | `#FFFF00` | Approaching threshold |
| 2 | WARNING | `#FFA500` | Threshold breached |
| 3 | CRITICAL | `#FF0000` | Multiple thresholds / cascading risk |

**GRID Alert Thresholds (ERCOT):**
| Condition | Level | Alert Code |
|-----------|-------|------------|
| Reserve Margin > 10% | NORMAL | - |
| Reserve Margin 5-10% | WATCH | `GRID_MARGIN_LOW` |
| Reserve Margin < 5% | WARNING | `GRID_STRAIN` |
| Reserve Margin < 3% OR Demand > 95% Capacity | CRITICAL | `GRID_EMERGENCY` |

**WATR Alert Thresholds (Texas Aquifers):**
| Condition | Level | Alert Code |
|-----------|-------|------------|
| Level within 1σ of 30-day mean | NORMAL | - |
| Level 1-2σ below mean | WATCH | `AQUIFER_DECLINING` |
| Level > 2σ below mean | WARNING | `DROUGHT_RISK` |
| Level > 3σ below mean OR rate of decline > 0.5m/week | CRITICAL | `AQUIFER_CRITICAL` |

**FLOW Alert Thresholds (Port of Houston):**
| Condition | Level | Alert Code |
|-----------|-------|------------|
| Vessels Waiting < 5 | NORMAL | - |
| Vessels Waiting 5-15 | WATCH | `PORT_BUSY` |
| Vessels Waiting 15-30 | WARNING | `PORT_CONGESTION` |
| Vessels Waiting > 30 OR Dwell Time > 72h | CRITICAL | `PORT_GRIDLOCK` |

### 6.3 Linked Fate Engine (Cascading Risk)

**Multi-Signal Correlation Rules:**
```
RULE: TEXAS_SUPPLY_CHAIN_CRITICAL
  IF (GRID_STRAIN OR GRID_EMERGENCY)
  AND (PORT_CONGESTION OR PORT_GRIDLOCK)
  THEN severity = MAX(grid_severity, port_severity) + 1
  
RULE: TEXAS_INFRASTRUCTURE_STRESS
  IF (DROUGHT_RISK OR AQUIFER_CRITICAL)
  AND (GRID_STRAIN OR GRID_EMERGENCY)
  THEN severity = MAX(water_severity, grid_severity) + 1
  
RULE: PERFECT_STORM
  IF (GRID severity >= WARNING)
  AND (WATR severity >= WARNING)
  AND (FLOW severity >= WARNING)
  THEN severity = CRITICAL, alert = "TEXAS_PERFECT_STORM"
```

### 6.4 Linked Fate v2: Financial Correlation (Phase 3)

**Market-Physical Correlation Engine:**

Phase 3 introduces financial data overlays to detect market reactions to physical scarcity events in real-time.

**Data Source:** `yfinance` Python library (free, no API key required)

**Texas Proxy Watchlist:**
| Symbol | Company | Sector | Physical Exposure |
|--------|---------|--------|-------------------|
| `VST` | Vistra Corp | Energy | ERCOT power generation (39GW capacity) |
| `NRG` | NRG Energy | Energy | Integrated power, retail electricity |
| `TXN` | Texas Instruments | Technology | Semiconductor fabs (water/power intensive) |

**Correlation Rules:**
```
RULE: MARKET_REACTION_ENERGY_STRAIN
  IF (GRID_STRAIN OR GRID_EMERGENCY is ACTIVE)
  AND (VST OR NRG moving > 2% today)
  THEN alert = "MARKET REACTION: ENERGY STRAIN"
  confidence = HIGH if move > 5%, MEDIUM if move > 2%
  
RULE: MARKET_REACTION_WATER_STRESS
  IF (AQUIFER_CRITICAL OR DROUGHT_RISK is ACTIVE)
  AND (TXN moving > 2% today)
  THEN alert = "MARKET REACTION: WATER STRESS"
  confidence = MEDIUM (TXN has multiple dependencies)
  
RULE: MARKET_REACTION_SUPPLY_CHAIN
  IF (PORT_CONGESTION OR PORT_GRIDLOCK is ACTIVE)
  AND (relevant stock moving > 2% today)
  THEN alert = "MARKET REACTION: SUPPLY CHAIN"
```

**Movement Thresholds:**
| Threshold | Daily Move | Interpretation |
|-----------|------------|----------------|
| Minor | >1% | Monitor, no alert |
| Significant | >2% | Correlation check triggered |
| Major | >5% | High-confidence correlation |

**Celery Task Schedule:**
- `fetch-market-data-15m`: Fetches Texas watchlist quotes every 15 minutes
- `evaluate-market-correlation-5m`: Runs correlation analysis every 5 minutes

### 6.5 Linked Fate v3: Sentiment Correlation (Phase 4)

**Unstructured Data Layer — News & Public Sentiment:**

Phase 4 introduces news ingestion and sentiment analysis to detect public perception correlations with physical events.

**Data Sources:**
- Google News RSS feeds (free, unlimited)
- NLTK VADER lexicon for local sentiment scoring

**Texas Node Query Keywords:**
| Category | Keywords |
|----------|----------|
| `GRID` | ERCOT, Texas power grid, Texas electricity, Texas blackout |
| `WATER` | Texas drought, Texas water shortage, Texas aquifer, Edwards Aquifer |
| `LOGISTICS` | Port of Houston, Houston Ship Channel, Texas shipping |
| `EQUITY` | Vistra Energy, NRG Energy stock, Texas Instruments TXN |

**Sentiment Scoring (VADER):**
| Score Range | Label | Alert Trigger |
|-------------|-------|---------------|
| ≤ -0.5 | VERY_NEGATIVE | Critical event flag |
| -0.5 to -0.05 | NEGATIVE | Correlation check |
| -0.05 to 0.05 | NEUTRAL | No action |
| 0.05 to 0.5 | POSITIVE | No action |
| > 0.5 | VERY_POSITIVE | No action |

**Correlation Rules (v3):**
```
RULE: PHYSICAL_PUBLIC_STRAIN
  IF (Physical Alert: GRID/WATER/PORT is WARNING or CRITICAL)
  AND (News Sentiment for category < -0.5)
  THEN alert = "CRITICAL: PHYSICAL & PUBLIC STRAIN"
  confidence = STRONG
  
RULE: TRIPLE_CORRELATION
  IF (Physical Alert is ACTIVE)
  AND (News Sentiment < -0.2)
  AND (Related stock moving > 2%)
  THEN alert = "TRIPLE ALERT: Physical + Sentiment + Market"
  confidence = STRONG
```

**Celery Task Schedule:**
- `fetch-news-15m`: Fetches and scores news headlines every 15 minutes

### 6.6 Linked Fate v4: Predictive Correlation (Phase 5)

**The Predictive Layer — Weather Forecasts & Scarcity Anticipation:**

Phase 5 introduces predictive intelligence by ingesting NWS weather forecasts to anticipate grid strain and water stress **before they occur**. A true physical terminal anticipates scarcity.

**Data Source:**
- **NWS API** (api.weather.gov) — 100% free, no API key, requires User-Agent header
- 2-step process: lat/lon → gridId/gridX/gridY → forecast endpoint

**Texas Weather Monitoring Locations:**
| Location | Coordinates | Purpose |
|----------|-------------|---------|
| Dallas | 32.7767, -96.7970 | ERCOT load center, heat demand |
| Houston | 29.7604, -95.3698 | Port logistics, storm exposure |
| Austin | 30.2672, -97.7431 | Population center, grid demand |
| San Antonio | 29.4241, -98.4936 | Water stress, aquifer monitoring |

**Temperature Danger Thresholds:**
| Threshold | Temperature | Scarcity Impact |
|-----------|-------------|-----------------|
| EXTREME_HEAT | >100°F | Grid strain imminent, demand spike |
| HIGH_HEAT | >98°F | Elevated load, conservation alerts |
| MODERATE_HEAT | >95°F | Watch zone |
| FREEZE_WARNING | <32°F | Pipe/infrastructure risk |
| HARD_FREEZE | <25°F | Emergency grid conditions (2021 repeat risk) |
| EXTREME_COLD | <15°F | Critical infrastructure failure risk |

**Predictive Correlation Rules (v4):**
```
RULE: PREDICTIVE_HEAT_STRAIN
  IF (Forecast temp >100°F within 48 hours)
  AND (Current ERCOT margin <10%)
  THEN alert = "[PREDICTIVE] GRID STRAIN EXPECTED"
  tag = "48H FORECAST"
  confidence = HIGH
  
RULE: PREDICTIVE_FREEZE_EMERGENCY
  IF (Forecast temp <25°F within 48 hours)
  THEN alert = "[PREDICTIVE] FREEZE EMERGENCY RISK"
  reference = "Feb 2021 Texas Grid Collapse"
  confidence = CRITICAL

RULE: PREDICTIVE_PORT_STORM
  IF (NWS alert contains "hurricane" OR "tropical storm")
  AND (Location = Houston)
  THEN alert = "[PREDICTIVE] PORT DISRUPTION RISK"
  impact = "Supply chain 72h+ delay expected"
  confidence = HIGH
```

**WX Command Usage:**
```
WX US-TX <GO>                # Full Texas weather view
WX US-TX -danger <GO>        # Temperature danger zones only
WX US-TX -alerts <GO>        # NWS active alerts
WX US-TX -predictive <GO>    # Predictive correlation alerts
```

**Celery Task Schedule:**
- `fetch-weather-2h`: Fetches NWS forecasts every 2 hours at :00
- `evaluate-predictive-15m`: Runs Linked Fate v4 predictive analysis every 15 minutes

**Ticker Tray Integration:**
Predictive alerts appear in ticker tray with `[PREDICTIVE]` prefix and severity color coding based on confidence level.

### 6.7 Correlation Engine

**Hypothesis Testing:**
- Null: Physical indicator X has no predictive relationship with economic indicator Y
- Test: Granger causality with lag windows of 7, 14, 30, 90 days
- Output: Ranked correlation matrix with p-values

**Pre-configured Correlations:**
| Physical Signal | Economic/Industrial Target | Expected Lag |
|-----------------|---------------------------|--------------|
| Groundwater depletion | Agricultural commodity futures | 30-90 days |
| Port congestion | Retail inventory levels | 14-30 days |
| Grid strain | Industrial production index | 7-14 days |
| Shipping chokepoint density | Freight rates | 7 days |

---

## 7. Development Roadmap

### Phase 1: Foundation (Weeks 1-2)
- [ ] PostgreSQL/PostGIS local setup
- [ ] Schema migration scripts
- [ ] USGS NWIS integration (WATR, FLOW, LAKE)
- [ ] Basic Streamlit shell with command input

### Phase 2: Core Functions (Weeks 3-4)
- [ ] EIA integration (GRID, FUEL)
- [ ] NOAA integration (CLIM, TEMP, STRM)
- [ ] PyDeck map rendering
- [ ] Command palette implementation

### Phase 3: Intelligence Layer (Weeks 5-6)
- [ ] Anomaly detection pipeline
- [ ] Correlation engine MVP
- [ ] RISK command implementation
- [ ] Alert notification system

### Phase 4: Expansion (Weeks 7-8)
- [ ] Satellite imagery integration (AGRI)
- [ ] AIS vessel tracking (SHIP)
- [ ] Multi-region support
- [ ] Performance optimization

---

## 8. File Structure (Target State)

```
Physical-World-Scarcity-Terminal/
├── README.md
├── SPEC_ARCHITECT.md           # This file
├── USER_GUIDE.md               # User documentation
├── docker-compose.yml          # Local development stack
├── pyproject.toml              # Python dependencies
├── .env.example                # Environment template
├── src/
│   ├── __init__.py
│   ├── main.py                 # Application entry
│   ├── config/
│   │   ├── settings.py         # Pydantic settings
│   │   ├── sources.yaml
│   │   └── indicators.yaml
│   ├── db/
│   │   ├── connection.py       # SQLAlchemy/psycopg setup
│   │   ├── models.py           # ORM models
│   │   └── migrations/         # Alembic migrations
│   ├── ingestion/
│   │   ├── base.py             # Abstract fetcher
│   │   ├── usgs.py
│   │   ├── noaa.py
│   │   ├── eia.py
│   │   ├── weather.py          # NWS API forecasts (Phase 5)
│   │   └── scheduler.py        # Celery tasks
│   ├── analysis/
│   │   ├── anomaly.py
│   │   ├── correlation.py
│   │   ├── market_correlation.py  # Linked Fate engine (v4)
│   │   └── spatial.py
│   ├── api/                    # Optional FastAPI backend
│   │   └── routes.py
│   └── ui/
│       ├── app.py              # Streamlit entry
│       ├── components/
│       ├── handlers/
│       └── styles/
├── tests/
│   ├── test_ingestion.py
│   ├── test_anomaly.py
│   └── test_commands.py
└── scripts/
    ├── init_db.py
    └── seed_regions.py
```

---

## 9. MVP Scope — DECIDED

### 9.1 Geographic Focus: Texas (US-TX)

Texas is the ideal "Ground Zero" for the MVP:
- **Isolated Grid**: ERCOT operates independently from the national grid, providing clean signal boundaries
- **Water Stress**: Aquifer depletion and reservoir levels are critical infrastructure concerns
- **Logistics Hubs**: Houston/Dallas ports and rail interchanges
- **API Quality**: US government APIs (EIA, USGS) are free, unlimited, and well-documented for Texas

### 9.2 Primary Function Codes (MVP)

| Code | Priority | Data Source | Rationale |
|------|----------|-------------|-----------|
| `GRID` | P0 | EIA API (ERCOT) | Fast-moving (5-min intervals), high dynamism |
| `WATR` | P0 | USGS NWIS | Slow-moving, high-impact spatial data |
| `FLOW` | P0 | Simulated AIS / Port Stats | Logistics chokepoint monitoring |
| `FIN` | P1 | yfinance (Phase 3) | Market correlation with physical events |
| `NEWS` | P1 | Google News RSS (Phase 4) | News sentiment analysis |

### 9.2.1 FLOW Function Code (Phase 2)

**Command:** `FLOW HOU <GO>` — Port of Houston / Gulf Coast logistics

**Data Strategy:** Real-time AIS data requires expensive commercial APIs (MarineTraffic: $500+/mo, Spire: Enterprise only). For MVP, we use a **realistic simulation engine** based on:
- Historical Port of Houston statistics (avg 250 vessels/day, 8,000 ships/year)
- Temporal patterns (weekday peaks, seasonal variation)
- Weather/hurricane season impacts
- Random variation for realism

**Indicators:**
| Code | Name | Unit | Update Frequency |
|------|------|------|------------------|
| `PORT_VESSELS` | Vessels in Port | count | 15 min |
| `PORT_WAITING` | Vessels at Anchor | count | 15 min |
| `PORT_DWELL` | Avg Dwell Time | hours | 1 hour |
| `PORT_THROUGHPUT` | Daily Throughput | TEU | 1 hour |

**Future Migration:** When budget allows, replace simulation with:
1. Spire AIS (via Snowflake Marketplace) — $15/mo academic tier
2. MarineTraffic API — If free tier (100/day) proves sufficient for spot checks

### 9.2.2 FIN Function Code (Phase 3)

**Command:** `FIN US-TX <GO>` — Texas Financial Correlation View

**Data Strategy:** Uses `yfinance` library for free, unlimited stock data. No API key required.

**Texas Proxy Watchlist:**
| Symbol | Company | Physical Exposure | Sensitivity |
|--------|---------|-------------------|-------------|
| `VST` | Vistra Corp | ERCOT power generation | High |
| `NRG` | NRG Energy | Integrated power, retail | High |
| `TXN` | Texas Instruments | Semiconductor fabs | Medium |

**UI Layout:** Split-screen view
- **Left Panel:** Physical Status (Grid/Water/Port severity levels)
- **Right Panel:** Watchlist stocks with sparkline charts (5-day history)

**Correlation Detection:**
- Runs every 5 minutes via Celery task
- Checks if physical alert (WARNING/CRITICAL) coincides with >2% stock movement
- Generates `MARKET_REACTION` alerts visible in ticker tray

**API Endpoints:**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/finance/quotes` | GET | Current watchlist quotes |
| `/finance/history/{symbol}` | GET | Historical price data for sparklines |
| `/finance/summary` | GET | Full summary with physical correlation |

### 9.2.3 NEWS Function Code (Phase 4)

**Command:** `NEWS US-TX <GO>` — Texas Node News Sentiment Analysis

**Data Strategy:** Uses free Google News RSS feeds with local NLTK VADER sentiment scoring.
No API keys or paid services required.

**News Categories:**
| Category | Query Keywords | Related Stocks |
|----------|----------------|----------------|
| `GRID` | ERCOT, Texas power grid, Texas blackout | VST, NRG |
| `WATER` | Texas drought, Texas aquifer | TXN |
| `LOGISTICS` | Port of Houston, Houston Ship Channel | TXN |
| `EQUITY` | Vistra Energy, NRG Energy, Texas Instruments | VST, NRG, TXN |

**NLP Library:** NLTK VADER (Valence Aware Dictionary and sEntiment Reasoner)
- Specifically designed for social media and news sentiment
- Works well with short text (headlines)
- No training required, uses pre-built lexicon
- Returns compound score (-1 to 1) plus pos/neg/neu breakdown

**UI Layout:** Dense scrolling list of headlines
- Color-coded by sentiment (Green: positive, Yellow: neutral, Red: negative)
- Category breakdown with aggregate sentiment scores
- Sentiment indicators: ▲▲ (very positive), ▲ (positive), ● (neutral), ▼ (negative), ▼▼ (very negative)

**Ticker Tray Integration:**
- Critical (very negative) headlines appear in ticker tray
- Overall news sentiment indicator shown below alerts

**API Endpoints:**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/news/headlines` | GET | All headlines with sentiment scores |
| `/news/summary` | GET | Aggregated summary with category breakdown |
| `/news/sentiment/{category}` | GET | Quick sentiment for correlation engine |

### 9.3 Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Deployment** | Local Docker Compose | Fast iteration, no cloud limits |
| **Backend** | FastAPI (containerized) | REST API for Streamlit, future expansion |
| **Frontend** | Streamlit (containerized) | Rapid UI development |
| **Database** | PostgreSQL + PostGIS | Free, sufficient for Texas-scale |
| **Data Refresh** | Hourly batch | Balances "live" feel with API limits |
| **Authentication** | None (single-user) | Local-only, skip complexity |
| **Alerting** | In-app only | Visual flags + ticker tray |
| **Map Tiles** | Mapbox (dark mode) | Bloomberg aesthetic via Deck.gl |

### 9.4 Environment Configuration

Required environment variables (`.env`):
```bash
# Database
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=pwst
POSTGRES_USER=pwst
POSTGRES_PASSWORD=<generate-secure-password>

# APIs (all free, no keys required for basic access)
EIA_API_KEY=<optional-for-higher-limits>

# Mapbox
MAPBOX_ACCESS_TOKEN=<your-mapbox-token>

# Application
REFRESH_INTERVAL_MINUTES=60
LOG_LEVEL=INFO
```

---

## 10. Texas-Specific Data Sources

### 10.1 ERCOT Grid Data (via EIA API)

**Endpoint:** `https://api.eia.gov/v2/electricity/rto/region-data/data/`

**Available Metrics:**
- Demand (MW) — Current load
- Net Generation (MW) — Total output
- Interchange (MW) — Imports/exports (minimal for ERCOT)
- Fuel Mix — Generation by source (wind, solar, gas, coal, nuclear)

**Update Frequency:** 5-minute intervals (we'll poll hourly)

**Free Tier:** Unlimited requests with API key, 30/hr without

### 10.2 Texas Groundwater (USGS NWIS)

**Endpoint:** `https://waterservices.usgs.gov/nwis/`

**Available Metrics:**
- Groundwater levels (depth to water table)
- Well site metadata (lat/lon, aquifer name)
- Historical measurements (decades of data)

**Key Aquifers:**
- Ogallala (Panhandle) — Critical for agriculture
- Edwards (Central Texas) — San Antonio water supply
- Gulf Coast — Houston-area subsidence issues
- Trinity — Dallas-Fort Worth supply
- Carrizo-Wilcox — East Texas

**Update Frequency:** Daily to weekly (varies by well)

**Free Tier:** Unlimited, no key required

### 10.3 Texas Reservoirs (USGS + TWDB)

**Endpoint:** `https://waterservices.usgs.gov/nwis/` + Texas Water Development Board

**Available Metrics:**
- Reservoir storage (acre-feet)
- Percent capacity
- Surface elevation

**Key Reservoirs:**
- Lake Travis — Austin water supply
- Lake Texoma — Dallas-area
- Toledo Bend — East Texas
- Amistad — Border region

---

*This document serves as the canonical reference for PWST architecture decisions. All implementation must align with specifications herein unless explicitly superseded by updated versions.*
