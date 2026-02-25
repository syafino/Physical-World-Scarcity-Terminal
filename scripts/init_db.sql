-- ===========================================
-- PWST Initial Database Setup
-- ===========================================
-- This script runs automatically when the PostgreSQL container starts
-- for the first time (via docker-entrypoint-initdb.d)

-- Enable PostGIS extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Verify PostGIS installation
SELECT PostGIS_Version();

-- ===========================================
-- CORE DIMENSION TABLES
-- ===========================================

-- Regions (states, watersheds, grid zones)
CREATE TABLE IF NOT EXISTS regions (
    region_id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    region_type VARCHAR(50) NOT NULL,
    geometry GEOMETRY(MultiPolygon, 4326),
    parent_region_id INTEGER REFERENCES regions(region_id),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_regions_geometry ON regions USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_regions_code ON regions(code);
CREATE INDEX IF NOT EXISTS idx_regions_type ON regions(region_type);

-- Data Sources (APIs we pull from)
CREATE TABLE IF NOT EXISTS data_sources (
    source_id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    base_url VARCHAR(500),
    api_type VARCHAR(50),
    rate_limit_per_hour INTEGER,
    is_free BOOLEAN DEFAULT TRUE,
    auth_method VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    last_successful_fetch TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indicators (metrics we track)
CREATE TABLE IF NOT EXISTS indicators (
    indicator_id SERIAL PRIMARY KEY,
    code VARCHAR(30) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL,
    unit VARCHAR(50),
    description TEXT,
    function_code VARCHAR(4) NOT NULL,
    source_id INTEGER REFERENCES data_sources(source_id),
    update_frequency INTERVAL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_indicators_function ON indicators(function_code);
CREATE INDEX IF NOT EXISTS idx_indicators_category ON indicators(category);

-- ===========================================
-- MONITORING STATIONS
-- ===========================================

-- Physical monitoring stations (wells, gauges, etc.)
CREATE TABLE IF NOT EXISTS stations (
    station_id SERIAL PRIMARY KEY,
    external_id VARCHAR(50) NOT NULL,
    source_id INTEGER NOT NULL REFERENCES data_sources(source_id),
    name VARCHAR(255),
    station_type VARCHAR(50) NOT NULL,
    location GEOMETRY(Point, 4326) NOT NULL,
    region_id INTEGER REFERENCES regions(region_id),
    elevation_m DOUBLE PRECISION,
    aquifer_name VARCHAR(255),
    metadata JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_stations_location ON stations USING GIST(location);
CREATE INDEX IF NOT EXISTS idx_stations_source ON stations(source_id);
CREATE INDEX IF NOT EXISTS idx_stations_type ON stations(station_type);
CREATE INDEX IF NOT EXISTS idx_stations_region ON stations(region_id);

-- ===========================================
-- TIME-SERIES OBSERVATIONS
-- ===========================================

-- Main observations table (partitioned by month for scale)
CREATE TABLE IF NOT EXISTS observations (
    observation_id BIGSERIAL,
    indicator_id INTEGER NOT NULL REFERENCES indicators(indicator_id),
    station_id INTEGER REFERENCES stations(station_id),
    region_id INTEGER REFERENCES regions(region_id),
    location GEOMETRY(Point, 4326),
    observed_at TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    value_raw JSONB,
    quality_flag VARCHAR(20) DEFAULT 'valid',
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (observation_id, observed_at)
) PARTITION BY RANGE (observed_at);

-- Create partitions for current and future months
CREATE TABLE IF NOT EXISTS observations_2026_01 PARTITION OF observations
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE IF NOT EXISTS observations_2026_02 PARTITION OF observations
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE IF NOT EXISTS observations_2026_03 PARTITION OF observations
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS observations_2026_04 PARTITION OF observations
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE IF NOT EXISTS observations_2026_05 PARTITION OF observations
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS observations_2026_06 PARTITION OF observations
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

CREATE INDEX IF NOT EXISTS idx_obs_indicator_time ON observations(indicator_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_obs_station_time ON observations(station_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_obs_region ON observations(region_id, observed_at DESC);

-- ===========================================
-- ANOMALY DETECTION
-- ===========================================

CREATE TABLE IF NOT EXISTS anomalies (
    anomaly_id BIGSERIAL PRIMARY KEY,
    indicator_id INTEGER NOT NULL REFERENCES indicators(indicator_id),
    station_id INTEGER REFERENCES stations(station_id),
    region_id INTEGER REFERENCES regions(region_id),
    location GEOMETRY(Point, 4326),
    detected_at TIMESTAMPTZ NOT NULL,
    anomaly_type VARCHAR(50) NOT NULL,
    severity DOUBLE PRECISION,
    baseline_value DOUBLE PRECISION,
    observed_value DOUBLE PRECISION,
    z_score DOUBLE PRECISION,
    is_acknowledged BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anomalies_time ON anomalies(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_severity ON anomalies(severity DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_indicator ON anomalies(indicator_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_unacked ON anomalies(is_acknowledged) WHERE NOT is_acknowledged;

-- ===========================================
-- COMMAND AUDIT LOG
-- ===========================================

CREATE TABLE IF NOT EXISTS command_log (
    log_id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    command_raw VARCHAR(500) NOT NULL,
    function_code VARCHAR(4),
    region_code VARCHAR(20),
    parameters JSONB,
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    response_time_ms INTEGER,
    result_count INTEGER,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_cmdlog_session ON command_log(session_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_cmdlog_function ON command_log(function_code, executed_at DESC);

-- ===========================================
-- INGESTION TRACKING
-- ===========================================

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id BIGSERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(source_id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'running',
    records_fetched INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_ingestion_source ON ingestion_runs(source_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_status ON ingestion_runs(status);

-- ===========================================
-- SEED DATA: Data Sources
-- ===========================================

INSERT INTO data_sources (code, name, base_url, api_type, rate_limit_per_hour, is_free, auth_method, status) VALUES
    ('USGS_NWIS', 'USGS National Water Information System', 'https://waterservices.usgs.gov/nwis/', 'REST', NULL, TRUE, 'NONE', 'active'),
    ('EIA_API', 'US Energy Information Administration', 'https://api.eia.gov/v2/', 'REST', 30, TRUE, 'API_KEY', 'active'),
    ('NOAA_NCEI', 'NOAA National Centers for Environmental Information', 'https://www.ncei.noaa.gov/cdo-web/api/v2/', 'REST', 5, TRUE, 'API_KEY', 'active'),
    ('NWS_API', 'National Weather Service API', 'https://api.weather.gov/', 'REST', NULL, TRUE, 'NONE', 'active')
ON CONFLICT (code) DO NOTHING;

-- ===========================================
-- SEED DATA: Indicators (MVP)
-- ===========================================

INSERT INTO indicators (code, name, category, unit, description, function_code, source_id, update_frequency) VALUES
    -- Water indicators
    ('GW_LEVEL', 'Groundwater Level', 'water', 'feet below surface', 'Depth to water table from ground surface', 'WATR', 
        (SELECT source_id FROM data_sources WHERE code = 'USGS_NWIS'), '6 hours'),
    ('GW_LEVEL_CHANGE', 'Groundwater Level Change', 'water', 'feet', 'Change in groundwater level from baseline', 'WATR',
        (SELECT source_id FROM data_sources WHERE code = 'USGS_NWIS'), '6 hours'),
    ('RESERVOIR_STORAGE', 'Reservoir Storage', 'water', 'acre-feet', 'Total water volume in reservoir', 'LAKE',
        (SELECT source_id FROM data_sources WHERE code = 'USGS_NWIS'), '1 day'),
    ('RESERVOIR_PCT', 'Reservoir Percent Capacity', 'water', 'percent', 'Current storage as percent of capacity', 'LAKE',
        (SELECT source_id FROM data_sources WHERE code = 'USGS_NWIS'), '1 day'),
    
    -- Energy indicators
    ('GRID_DEMAND', 'Grid Demand', 'energy', 'MW', 'Current electricity demand on grid', 'GRID',
        (SELECT source_id FROM data_sources WHERE code = 'EIA_API'), '1 hour'),
    ('GRID_GENERATION', 'Grid Generation', 'energy', 'MW', 'Total electricity generation', 'GRID',
        (SELECT source_id FROM data_sources WHERE code = 'EIA_API'), '1 hour'),
    ('GRID_CAPACITY_MARGIN', 'Capacity Margin', 'energy', 'MW', 'Available reserve capacity', 'GRID',
        (SELECT source_id FROM data_sources WHERE code = 'EIA_API'), '1 hour'),
    ('GRID_WIND', 'Wind Generation', 'energy', 'MW', 'Electricity from wind sources', 'GRID',
        (SELECT source_id FROM data_sources WHERE code = 'EIA_API'), '1 hour'),
    ('GRID_SOLAR', 'Solar Generation', 'energy', 'MW', 'Electricity from solar sources', 'GRID',
        (SELECT source_id FROM data_sources WHERE code = 'EIA_API'), '1 hour'),
    ('GRID_GAS', 'Natural Gas Generation', 'energy', 'MW', 'Electricity from natural gas', 'GRID',
        (SELECT source_id FROM data_sources WHERE code = 'EIA_API'), '1 hour')
ON CONFLICT (code) DO NOTHING;

-- ===========================================
-- SEED DATA: Texas Region
-- ===========================================

INSERT INTO regions (code, name, region_type, metadata) VALUES
    ('US-TX', 'Texas', 'state', '{"iso_code": "US-TX", "fips": "48"}'),
    ('ERCOT', 'ERCOT Grid Zone', 'grid_zone', '{"operator": "Electric Reliability Council of Texas"}')
ON CONFLICT (code) DO NOTHING;

-- Link ERCOT to Texas
UPDATE regions SET parent_region_id = (SELECT region_id FROM regions WHERE code = 'US-TX')
WHERE code = 'ERCOT';

-- ===========================================
-- HELPER FUNCTIONS
-- ===========================================

-- Function to get latest observation for an indicator
CREATE OR REPLACE FUNCTION get_latest_observation(p_indicator_code VARCHAR, p_station_id INTEGER DEFAULT NULL)
RETURNS TABLE (
    station_id INTEGER,
    value DOUBLE PRECISION,
    observed_at TIMESTAMPTZ,
    quality_flag VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT ON (o.station_id)
        o.station_id,
        o.value,
        o.observed_at,
        o.quality_flag
    FROM observations o
    JOIN indicators i ON o.indicator_id = i.indicator_id
    WHERE i.code = p_indicator_code
      AND (p_station_id IS NULL OR o.station_id = p_station_id)
    ORDER BY o.station_id, o.observed_at DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to calculate z-score for anomaly detection
CREATE OR REPLACE FUNCTION calculate_z_score(
    p_value DOUBLE PRECISION,
    p_mean DOUBLE PRECISION,
    p_stddev DOUBLE PRECISION
) RETURNS DOUBLE PRECISION AS $$
BEGIN
    IF p_stddev = 0 OR p_stddev IS NULL THEN
        RETURN 0;
    END IF;
    RETURN (p_value - p_mean) / p_stddev;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ===========================================
-- GRANTS (for application user)
-- ===========================================

-- Grant permissions to pwst user (if different from owner)
-- GRANT ALL ON ALL TABLES IN SCHEMA public TO pwst;
-- GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO pwst;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO pwst;

COMMIT;
