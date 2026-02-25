# Physical World Scarcity Terminal (PWST)

> **DIY Bloomberg for the Physical Economy**

A command-driven terminal interface for monitoring real-world infrastructure data: water scarcity, power grid strain, logistics chokepoints, and climate anomalies.

![Terminal Style](https://img.shields.io/badge/style-terminal--dark-0D1117?style=flat-square)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

## Overview

PWST provides Bloomberg-style function codes for querying physical infrastructure data:

```
WATR US-TX <GO>    → Groundwater levels across Texas
GRID ERCOT <GO>    → ERCOT power grid status
RISK US-TX <GO>    → Composite risk dashboard
```

**Key Features:**
- 📊 **Command-driven interface** — 4-letter function codes like Bloomberg
- 🗺️ **3D geospatial maps** — PyDeck with Mapbox dark theme
- ⚠️ **Anomaly detection** — Z-score based alerts (2σ/3σ thresholds)
- 🔄 **Automated ingestion** — Hourly batch updates from USGS, EIA
- 🐳 **Docker-ready** — Single `docker-compose up` deployment

## Quick Start

### Prerequisites

- Docker & Docker Compose v2+
- [EIA API Key](https://www.eia.gov/opendata/register.php) (free, for grid data)
- [Mapbox Access Token](https://www.mapbox.com/) (free tier, for maps)

### 1. Clone & Configure

```bash
git clone https://github.com/youruser/physical-world-scarcity-terminal.git
cd physical-world-scarcity-terminal

# Copy environment template
cp .env.example .env

# Edit .env and add your API keys
# EIA_API_KEY=your_key_here
# MAPBOX_ACCESS_TOKEN=pk.your_token_here
```

### 2. Launch

```bash
# Start all services
docker-compose up --build

# Or run in background
docker-compose up -d --build
```

### 3. Access

| Service | URL |
|---------|-----|
| **Terminal UI** | http://localhost:8501 |
| **API** | http://localhost:8000 |
| **API Docs** | http://localhost:8000/docs |

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  PWST Terminal (Streamlit)         http://localhost:8501         │
├──────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ WATR US-TX <GO>                                    │ ● API  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────┐ ┌──────────────────────┐   │
│  │                                  │ │ ▓ GROUNDWATER LEVELS │   │
│  │       PyDeck 3D Map              │ │ AVG: 142.3 ft        │   │
│  │       (Mapbox Dark)              │ │ MAX: 312.1 ft        │   │
│  │                                  │ │ STATIONS: 847        │   │
│  │                                  │ │                      │   │
│  └──────────────────────────────────┘ │ ┌──────────────────┐ │   │
│  ┌──────────────────────────────────┐ │ │ Station | Depth  │ │   │
│  │ ▓ ANOMALY TICKER: 2 CRITICAL     │ │ │ --------+------- │ │   │
│  └──────────────────────────────────┘ │ │ ...              │ │   │
│                                       └──────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  FastAPI Backend                    http://localhost:8000        │
├──────────────────────────────────────────────────────────────────┤
│  POST /command  →  Execute WATR/GRID/RISK commands               │
│  GET /observations  →  Query time-series data                    │
│  GET /anomalies  →  List active anomalies                        │
└──────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   PostgreSQL    │ │     Redis       │ │  Celery Worker  │
│   + PostGIS     │ │   (broker)      │ │  + Beat         │
│                 │ │                 │ │                 │
│ observations    │ │ task queue      │ │ hourly ingest   │
│ anomalies       │ │ result store    │ │ anomaly scan    │
│ stations        │ │                 │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## Function Codes

| Code | Description | Data Source |
|------|-------------|-------------|
| `WATR` | Groundwater levels | [USGS NWIS](https://waterservices.usgs.gov/) |
| `GRID` | Power grid status | [EIA API v2](https://www.eia.gov/opendata/) |
| `RISK` | Composite risk dashboard | Calculated from anomalies |

### Command Syntax

```
<FUNCTION> <REGION> [MODIFIERS] <GO>
```

**Examples:**
```
WATR US-TX <GO>           # Texas groundwater
WATR US-TX SORT depth <GO>  # Sorted by depth
GRID ERCOT <GO>           # ERCOT grid status
RISK US-TX <GO>           # Texas risk dashboard
```

## Development

### Local Development (without Docker)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Start PostgreSQL + Redis (via Docker)
docker-compose up -d db redis

# Run API
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Run UI (separate terminal)
streamlit run src/ui/app.py --server.port 8501

# Run worker (separate terminal)
celery -A src.scheduler worker --loglevel=info

# Run scheduler (separate terminal)
celery -A src.scheduler beat --loglevel=info
```

### Project Structure

```
physical-world-scarcity-terminal/
├── docker-compose.yml      # Service orchestration
├── Dockerfile              # Python app container
├── pyproject.toml          # Dependencies
├── .env.example            # Environment template
├── scripts/
│   └── init_db.sql         # Database schema + seeds
├── src/
│   ├── api/
│   │   └── main.py         # FastAPI endpoints
│   ├── config/
│   │   └── settings.py     # Pydantic settings
│   ├── db/
│   │   ├── connection.py   # SQLAlchemy engine
│   │   └── models.py       # ORM models
│   ├── ingestion/
│   │   ├── base.py         # Base fetcher
│   │   ├── usgs.py         # USGS water fetcher
│   │   └── eia.py          # EIA grid fetcher
│   ├── analysis/
│   │   └── anomaly.py      # Z-score detection
│   ├── ui/
│   │   └── app.py          # Streamlit frontend
│   └── scheduler.py        # Celery tasks
└── docs/
    ├── SPEC_ARCHITECT.md   # Technical specification
    └── USER_GUIDE.md       # User documentation
```

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=html
```

## Configuration

All configuration via environment variables (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection | `postgresql://...` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379` |
| `EIA_API_KEY` | EIA API key | (required for GRID) |
| `MAPBOX_ACCESS_TOKEN` | Mapbox token | (optional) |
| `ANOMALY_THRESHOLD_CRITICAL` | Z-score for critical | `3.0` |
| `ANOMALY_THRESHOLD_SIGNIFICANT` | Z-score for warnings | `2.0` |

## Data Sources

### USGS NWIS (Water)
- **Endpoint:** `https://waterservices.usgs.gov/nwis/`
- **Rate Limit:** Unlimited (be respectful)
- **Auth:** None required
- **Data:** Groundwater levels, stream flow, water quality

### EIA API v2 (Energy)
- **Endpoint:** `https://api.eia.gov/v2/`
- **Rate Limit:** 30/hour (anon), unlimited with key
- **Auth:** Free API key
- **Data:** Grid demand, generation by fuel type

## Roadmap

- [ ] **v0.2** — Add SHIP (AIS vessel tracking)
- [ ] **v0.3** — Add CROP (USDA crop conditions)
- [ ] **v0.4** — Add CLIM (NOAA weather alerts)
- [ ] **v0.5** — Multi-region expansion (US-CA, US-FL)
- [ ] **v1.0** — Cloud deployment (AWS/GCP)

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/ship-tracking`)
3. Commit changes (`git commit -am 'Add SHIP function code'`)
4. Push to branch (`git push origin feature/ship-tracking`)
5. Open a Pull Request

## License

MIT License — See [LICENSE](LICENSE) for details.

---

**Built for the physical economy.** Because water tables and grid strain move markets before tweets do.
