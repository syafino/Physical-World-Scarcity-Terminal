# PWST Technical Architecture Specification
## Physical World Scarcity Terminal — Source of Truth Document
**Version:** 0.1.0-alpha  
**Last Updated:** 2026-02-25  
**Status:** DRAFT — Pre-Implementation

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
| P2 | NWS API | Weather alerts | Unlimited | `requests` | ✅ Verified |
| P2 | USDA NASS | Crop statistics | Unlimited | `requests` | ✅ Verified |
| P3 | MarineTraffic | AIS vessel positions | 100/day free | `requests` | [TO BE VERIFIED] |
| P3 | UN Comtrade | Trade flows | 100/hr guest | `comtradeapicall` | [TO BE VERIFIED] |

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

### 6.2 Correlation Engine

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
│   │   └── scheduler.py        # Celery tasks
│   ├── analysis/
│   │   ├── anomaly.py
│   │   ├── correlation.py
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
