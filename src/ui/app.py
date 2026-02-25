"""
PWST Streamlit Frontend

Terminal-style interface with:
- Command palette (Cmd+K)
- 3D geospatial map (PyDeck)
- High-density data panels
- Anomaly ticker
"""

import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import pandas as pd
import pydeck as pdk
import streamlit as st

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

API_URL = os.getenv("API_URL", "http://localhost:8000")
MAPBOX_TOKEN = os.getenv("MAPBOX_ACCESS_TOKEN", "")
MAPBOX_STYLE = os.getenv("MAPBOX_STYLE", "mapbox://styles/mapbox/dark-v11")

# Texas center coordinates
TEXAS_CENTER = {"latitude": 31.0, "longitude": -100.0}

# Terminal color palette
COLORS = {
    "background": "#0D1117",
    "surface": "#161B22",
    "text": "#E6EDF3",
    "accent": "#58A6FF",
    "normal": "#00FF00",
    "watch": "#FFFF00",
    "warning": "#FFA500",
    "critical": "#FF0000",
    "stale": "#808080",
}

# ─────────────────────────────────────────────────────────────
# Page Configuration
# ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PWST | Physical World Scarcity Terminal",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS for terminal aesthetic
st.markdown(
    """
    <style>
    /* Global terminal styling */
    .stApp {
        background-color: #0D1117;
        color: #E6EDF3;
    }
    
    /* Remove default padding */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0;
        max-width: 100%;
    }
    
    /* Header styling */
    .terminal-header {
        font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
        font-size: 14px;
        color: #58A6FF;
        background-color: #161B22;
        padding: 8px 16px;
        border-bottom: 1px solid #30363D;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    
    /* Command input styling */
    .stTextInput > div > div > input {
        background-color: #0D1117 !important;
        color: #00FF00 !important;
        font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
        font-size: 16px !important;
        border: 1px solid #30363D !important;
        border-radius: 0 !important;
    }
    
    .stTextInput > div > div > input:focus {
        border-color: #58A6FF !important;
        box-shadow: 0 0 0 1px #58A6FF !important;
    }
    
    /* Data panel styling */
    .data-panel {
        background-color: #161B22;
        border: 1px solid #30363D;
        padding: 12px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
        height: 100%;
    }
    
    .data-panel h3 {
        color: #58A6FF;
        font-size: 12px;
        margin: 0 0 8px 0;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    /* Anomaly badge */
    .anomaly-badge {
        display: inline-block;
        padding: 2px 6px;
        border-radius: 2px;
        font-size: 10px;
        font-weight: bold;
        margin-right: 4px;
    }
    
    .anomaly-critical {
        background-color: #FF0000;
        color: #000;
    }
    
    .anomaly-warning {
        background-color: #FFA500;
        color: #000;
    }
    
    .anomaly-watch {
        background-color: #FFFF00;
        color: #000;
    }
    
    /* Ticker styling */
    .ticker {
        background-color: #161B22;
        border-top: 1px solid #30363D;
        padding: 8px 16px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        color: #E6EDF3;
        overflow: hidden;
        white-space: nowrap;
    }
    
    /* Status indicators */
    .status-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 6px;
    }
    
    .status-normal { background-color: #00FF00; }
    .status-watch { background-color: #FFFF00; }
    .status-warning { background-color: #FFA500; }
    .status-critical { background-color: #FF0000; }
    
    /* Table styling */
    .dataframe {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 11px !important;
    }
    
    .dataframe th {
        background-color: #161B22 !important;
        color: #58A6FF !important;
    }
    
    .dataframe td {
        background-color: #0D1117 !important;
        color: #E6EDF3 !important;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Metric styling */
    [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace;
        color: #00FF00;
    }
    
    [data-testid="stMetricDelta"] {
        font-family: 'JetBrains Mono', monospace;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────
# Session State
# ─────────────────────────────────────────────────────────────

if "command_history" not in st.session_state:
    st.session_state.command_history = []
if "current_data" not in st.session_state:
    st.session_state.current_data = None
if "current_anomalies" not in st.session_state:
    st.session_state.current_anomalies = []
if "current_function" not in st.session_state:
    st.session_state.current_function = None
if "last_command" not in st.session_state:
    st.session_state.last_command = ""


# ─────────────────────────────────────────────────────────────
# API Client
# ─────────────────────────────────────────────────────────────


def execute_command(command: str) -> dict[str, Any]:
    """Execute a command via the API."""
    try:
        response = httpx.post(
            f"{API_URL}/command",
            json={"command": command},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {
            "success": False,
            "message": f"API Error: {str(e)}",
            "data": None,
            "anomalies": None,
        }


def fetch_alerts(active_only: bool = True, limit: int = 50) -> list[dict]:
    """Fetch risk alerts from the API."""
    try:
        response = httpx.get(
            f"{API_URL}/alerts",
            params={"active_only": active_only, "limit": limit},
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        # Return empty list on error - don't break the UI
        return []


def check_api_health() -> bool:
    """Check if API is healthy."""
    try:
        response = httpx.get(f"{API_URL}/health", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# Map Component
# ─────────────────────────────────────────────────────────────


def create_map(data: Optional[list[dict]], anomaly_ids: Optional[set] = None) -> pdk.Deck:
    """Create PyDeck map with data points."""
    layers = []

    if data:
        # Filter to records with coordinates
        geo_data = [d for d in data if d.get("latitude") and d.get("longitude")]

        if geo_data:
            df = pd.DataFrame(geo_data)

            # Color based on anomaly status
            def get_color(row):
                # Check if this station has an anomaly
                if anomaly_ids and row.get("station_id") in anomaly_ids:
                    return [255, 0, 0, 200]  # Red for anomaly
                return [0, 255, 0, 180]  # Green for normal

            df["color"] = df.apply(get_color, axis=1)

            # Scatter layer for stations
            scatter_layer = pdk.Layer(
                "ScatterplotLayer",
                data=df,
                get_position=["longitude", "latitude"],
                get_color="color",
                get_radius=5000,
                radius_min_pixels=4,
                radius_max_pixels=15,
                pickable=True,
            )
            layers.append(scatter_layer)

            # Column layer for values (if water levels)
            if "value" in df.columns:
                # Normalize values for column height
                max_val = df["value"].abs().max()
                if max_val > 0:
                    df["height"] = (df["value"].abs() / max_val) * 50000

                    column_layer = pdk.Layer(
                        "ColumnLayer",
                        data=df,
                        get_position=["longitude", "latitude"],
                        get_elevation="height",
                        elevation_scale=1,
                        radius=3000,
                        get_fill_color="color",
                        pickable=True,
                        auto_highlight=True,
                    )
                    layers.append(column_layer)

    # Create deck
    view_state = pdk.ViewState(
        latitude=TEXAS_CENTER["latitude"],
        longitude=TEXAS_CENTER["longitude"],
        zoom=5.5,
        pitch=45,
        bearing=0,
    )

    # Use Carto dark basemap (free, no API key required) if no Mapbox token
    if MAPBOX_TOKEN:
        map_style = MAPBOX_STYLE
        api_keys = {"mapbox": MAPBOX_TOKEN}
    else:
        map_style = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
        api_keys = None
    
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_style=map_style,
        api_keys=api_keys,
        tooltip={
            "text": "{station_name}\nValue: {value}\nObserved: {observed_at}",
            "style": {
                "backgroundColor": "#161B22",
                "color": "#E6EDF3",
                "fontFamily": "JetBrains Mono, monospace",
                "fontSize": "12px",
            },
        },
    )

    return deck


# ─────────────────────────────────────────────────────────────
# UI Components
# ─────────────────────────────────────────────────────────────


def render_header():
    """Render terminal header."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    api_status = "●" if check_api_health() else "○"

    st.markdown(
        f"""
        <div class="terminal-header">
            <div>
                <span style="color: #00FF00; font-weight: bold;">PWST</span>
                <span style="color: #6E7681;">v0.1.0</span>
                <span style="margin-left: 20px;">
                    {st.session_state.last_command or "Ready"}
                </span>
            </div>
            <div>
                <span style="color: {'#00FF00' if api_status == '●' else '#FF0000'};">{api_status}</span>
                <span style="margin-left: 10px; color: #6E7681;">{now}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_data_panel(data: Optional[list[dict]], function_code: Optional[str]):
    """Render the data panel."""
    if not data:
        st.markdown(
            """
            <div class="data-panel">
                <h3>▓ NO DATA LOADED</h3>
                <p style="color: #6E7681;">Enter a command to load data</p>
                <p style="color: #6E7681; margin-top: 10px;">Examples:</p>
                <p style="color: #00FF00;">WATR US-TX &lt;GO&gt;</p>
                <p style="color: #00FF00;">GRID ERCOT &lt;GO&gt;</p>
                <p style="color: #00FF00;">RISK US-TX &lt;GO&gt;</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # Show data based on function
    if function_code == "WATR":
        render_water_data(data)
    elif function_code == "GRID":
        render_grid_data(data)
    elif function_code == "FLOW":
        render_flow_data(data)
    elif function_code == "RISK":
        render_risk_data(data)
    else:
        # Generic table view
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, height=400)


def render_water_data(data: list[dict]):
    """Render water data panel."""
    st.markdown("### ▓ GROUNDWATER LEVELS")
    st.markdown(f"*{len(data)} stations*")

    # Summary metrics
    if data:
        values = [d.get("value", 0) for d in data if d.get("value")]
        if values:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("AVG DEPTH", f"{sum(values)/len(values):.1f} ft")
            with col2:
                st.metric("MAX DEPTH", f"{max(values):.1f} ft")
            with col3:
                st.metric("STATIONS", len(data))

    # Data table
    df = pd.DataFrame(data)
    if not df.empty:
        display_cols = ["station_id", "station_name", "value", "aquifer", "observed_at"]
        display_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(
            df[display_cols].head(20),
            use_container_width=True,
            height=300,
        )


def render_grid_data(data: list[dict]):
    """Render grid data panel."""
    st.markdown("### ▓ ERCOT GRID STATUS")

    if not data:
        st.markdown("*No grid data available*")
        return

    df = pd.DataFrame(data)

    # Latest readings
    if not df.empty:
        latest = df.iloc[0] if len(df) > 0 else {}

        col1, col2 = st.columns(2)
        with col1:
            demand = latest.get("grid_demand", "N/A")
            st.metric("DEMAND", f"{demand:,.0f} MW" if isinstance(demand, (int, float)) else demand)
        with col2:
            gen = latest.get("grid_generation", "N/A")
            st.metric("GENERATION", f"{gen:,.0f} MW" if isinstance(gen, (int, float)) else gen)

        col3, col4 = st.columns(2)
        with col3:
            wind = latest.get("grid_wind", "N/A")
            st.metric("WIND", f"{wind:,.0f} MW" if isinstance(wind, (int, float)) else wind)
        with col4:
            solar = latest.get("grid_solar", "N/A")
            st.metric("SOLAR", f"{solar:,.0f} MW" if isinstance(solar, (int, float)) else solar)

    # Time series chart (exclude summary row)
    if "observed_at" in df.columns and "grid_demand" in df.columns:
        chart_df = df[df.get("is_summary", False) != True].copy() if "is_summary" in df.columns else df.copy()
        chart_df["observed_at"] = pd.to_datetime(chart_df["observed_at"])
        chart_df = chart_df.sort_values("observed_at")

        st.line_chart(
            chart_df.set_index("observed_at")[["grid_demand", "grid_generation"]].dropna(),
            use_container_width=True,
            height=200,
        )


def render_flow_data(data: list[dict]):
    """Render port/logistics data panel."""
    st.markdown("### ▓ PORT OF HOUSTON STATUS")

    if not data:
        st.markdown("*No port data available*")
        return

    df = pd.DataFrame(data)
    
    # Get port summaries (records with port_name)
    port_summaries = df[df.get("port_name", pd.Series([None]*len(df))).notna()].copy() if "port_name" in df.columns else pd.DataFrame()
    
    if not port_summaries.empty:
        for _, port in port_summaries.iterrows():
            port_name = port.get("port_name", "Unknown Port")
            
            st.markdown(f"**{port_name}**")
            
            col1, col2 = st.columns(2)
            with col1:
                vessels = port.get("port_vessels", "N/A")
                st.metric(
                    "VESSELS IN PORT", 
                    f"{vessels:.0f}" if isinstance(vessels, (int, float)) else vessels
                )
            with col2:
                waiting = port.get("port_waiting", "N/A")
                # Color-code waiting vessels
                if isinstance(waiting, (int, float)):
                    if waiting > 30:
                        delta_color = "inverse"  # Red
                    elif waiting > 15:
                        delta_color = "off"
                    else:
                        delta_color = "normal"
                    st.metric(
                        "VESSELS WAITING", 
                        f"{waiting:.0f}",
                        delta=f"{'CONGESTED' if waiting > 15 else 'NORMAL'}",
                        delta_color=delta_color
                    )
                else:
                    st.metric("VESSELS WAITING", waiting)

            col3, col4 = st.columns(2)
            with col3:
                dwell = port.get("port_dwell", "N/A")
                st.metric(
                    "AVG DWELL TIME", 
                    f"{dwell:.1f} hrs" if isinstance(dwell, (int, float)) else dwell
                )
            with col4:
                throughput = port.get("port_throughput", "N/A")
                st.metric(
                    "THROUGHPUT", 
                    f"{throughput:,.0f} TEU" if isinstance(throughput, (int, float)) else throughput
                )
            
            st.markdown("---")
    
    # Time series chart for waiting vessels
    time_series_df = df[df.get("port_name", pd.Series([None]*len(df))).isna()].copy() if "port_name" in df.columns else df.copy()
    
    if not time_series_df.empty and "observed_at" in time_series_df.columns and "port_waiting" in time_series_df.columns:
        time_series_df["observed_at"] = pd.to_datetime(time_series_df["observed_at"])
        time_series_df = time_series_df.sort_values("observed_at")
        
        st.markdown("**Vessels Waiting (24h)**")
        st.line_chart(
            time_series_df.set_index("observed_at")[["port_waiting"]].dropna(),
            use_container_width=True,
            height=150,
        )


def render_risk_data(data: list[dict]):
    """Render risk dashboard."""
    st.markdown("### ▓ RISK DASHBOARD")

    if not data:
        st.markdown("*No active risks detected*")
        return

    for category in data:
        severity = category.get("max_severity", 0)
        color = (
            COLORS["critical"]
            if severity > 0.75
            else COLORS["warning"]
            if severity > 0.5
            else COLORS["watch"]
            if severity > 0.25
            else COLORS["normal"]
        )

        st.markdown(
            f"""
            <div style="
                background-color: #161B22;
                border-left: 4px solid {color};
                padding: 8px 12px;
                margin-bottom: 8px;
            ">
                <div style="color: #58A6FF; text-transform: uppercase; font-size: 11px;">
                    {category.get('category', 'Unknown')}
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 4px;">
                    <span>Anomalies: {category.get('anomaly_count', 0)}</span>
                    <span>Critical: {category.get('critical_count', 0)}</span>
                    <span>Severity: {severity:.2f}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_ticker_tray():
    """
    Render the PWST Ticker Tray - bottom component showing risk alerts.
    
    Fetches alerts from the API and displays them in a compact ticker format.
    Alerts are color-coded by severity level.
    """
    # Fetch active alerts (excluding NORMAL status)
    alerts = fetch_alerts(active_only=True, limit=30)
    
    # Filter out NORMAL alerts for ticker display
    active_alerts = [a for a in alerts if a.get("alert_level") != "NORMAL"]
    
    # Summary counts
    critical_count = len([a for a in alerts if a.get("alert_level") == "CRITICAL"])
    warning_count = len([a for a in alerts if a.get("alert_level") == "WARNING"])
    watch_count = len([a for a in alerts if a.get("alert_level") == "WATCH"])
    
    # Build ticker text
    if not active_alerts:
        # No active alerts - show nominal status
        ticker_color = "#00FF00"
        ticker_text = "▓ SYSTEM NOMINAL — All feeds operating within normal parameters"
    else:
        # Build alert summary
        parts = []
        if critical_count > 0:
            parts.append(f"⚠ {critical_count} CRITICAL")
            ticker_color = "#FF0000"
        elif warning_count > 0:
            parts.append(f"● {warning_count} WARNING")
            ticker_color = "#FFA500"
        else:
            parts.append(f"● {watch_count} WATCH")
            ticker_color = "#FFFF00"
        
        # Add individual alert details
        alert_details = []
        for a in active_alerts[:5]:  # Limit to 5 alerts
            level = a.get("alert_level", "WATCH")
            title = a.get("title", "Alert")
            alert_type = a.get("alert_type", "SYS")
            
            # Color code by level
            if level == "CRITICAL":
                alert_details.append(f"[{alert_type}] {title}")
            elif level == "WARNING":
                alert_details.append(f"[{alert_type}] {title}")
            else:
                alert_details.append(f"[{alert_type}] {title}")
        
        ticker_text = " | ".join(parts) + " — " + " | ".join(alert_details)
    
    # Render as simple styled div
    st.markdown(
        f"""
        <div style="
            background-color: #161B22;
            border-top: 2px solid {ticker_color};
            border-left: 4px solid {ticker_color};
            padding: 10px 16px;
            font-family: 'JetBrains Mono', 'Consolas', monospace;
            font-size: 12px;
            color: #E6EDF3;
            margin-top: 16px;
        ">
            <span style="color: {ticker_color}; font-weight: bold;">ALERTS</span>
            &nbsp;&nbsp;
            {ticker_text}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_anomaly_ticker(anomalies: list[dict]):
    """Legacy anomaly ticker - now replaced by render_ticker_tray."""
    # Keep for backward compatibility with anomaly display
    if not anomalies:
        return
    
    critical = [a for a in anomalies if a.get("type") == "critical_deviation"]
    warnings = [a for a in anomalies if a.get("type") == "significant_deviation"]
    
    if critical or warnings:
        parts = []
        if critical:
            parts.append(f"⚠ {len(critical)} CRITICAL")
        if warnings:
            parts.append(f"● {len(warnings)} WARNINGS")

        ticker_text = " | ".join(parts) + " — "

        # Add recent anomaly details
        for a in anomalies[:3]:
            ticker_text += f"[{a.get('indicator_code', 'UNK')} z={a.get('z_score', 0):.1f}σ] "

        ticker_color = COLORS["critical"] if critical else COLORS["warning"]

        st.markdown(
            f"""
            <div class="ticker" style="border-left: 3px solid {ticker_color};">
                {ticker_text}
            </div>
            """,
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────


def main():
    """Main application entry point."""
    # Header
    render_header()

    # Command input
    st.markdown("<br>", unsafe_allow_html=True)
    command = st.text_input(
        "Command",
        placeholder="Enter command (e.g., WATR US-TX <GO>) — Press Enter to execute",
        label_visibility="collapsed",
        key="command_input",
    )

    # Execute command on input
    if command and command != st.session_state.last_command:
        st.session_state.last_command = command
        st.session_state.command_history.append(command)

        with st.spinner("Executing..."):
            result = execute_command(command)

        if result.get("success"):
            st.session_state.current_data = result.get("data")
            st.session_state.current_anomalies = result.get("anomalies", [])
            st.session_state.current_function = result.get("function_code")
        else:
            st.error(result.get("message", "Command failed"))

    # Main layout: Map (left) + Data Panel (right)
    col_map, col_data = st.columns([2, 1])

    with col_map:
        # Get anomaly station IDs for highlighting
        anomaly_stations = set()
        if st.session_state.current_anomalies:
            for a in st.session_state.current_anomalies:
                if a.get("station_id"):
                    anomaly_stations.add(a["station_id"])

        # Render map
        deck = create_map(st.session_state.current_data, anomaly_stations)
        st.pydeck_chart(deck, use_container_width=True, height=500)

    with col_data:
        render_data_panel(
            st.session_state.current_data,
            st.session_state.current_function,
        )

    # Anomaly list (if any)
    if st.session_state.current_anomalies:
        st.markdown("### ▓ ACTIVE ANOMALIES")
        for anomaly in st.session_state.current_anomalies[:10]:
            severity = anomaly.get("severity", 0)
            badge_class = (
                "anomaly-critical"
                if anomaly.get("type") == "critical_deviation"
                else "anomaly-warning"
            )

            st.markdown(
                f"""
                <div style="
                    background-color: #161B22;
                    padding: 8px;
                    margin-bottom: 4px;
                    font-family: monospace;
                    font-size: 11px;
                ">
                    <span class="anomaly-badge {badge_class}">
                        {anomaly.get('type', 'ANOMALY')[:8].upper()}
                    </span>
                    z={anomaly.get('z_score', 0):.2f}σ |
                    baseline={anomaly.get('baseline', 0):.1f} |
                    observed={anomaly.get('observed', 0):.1f} |
                    {anomaly.get('detected_at', '')[:16]}
                </div>
                """,
                unsafe_allow_html=True,
            )

    # Legacy anomaly ticker (inline)
    render_anomaly_ticker(st.session_state.current_anomalies)

    # Help text
    with st.expander("Command Reference", expanded=False):
        st.markdown(
            """
            | Command | Description |
            |---------|-------------|
            | `WATR [region] <GO>` | Groundwater levels |
            | `GRID [region] <GO>` | Power grid status |
            | `FLOW [port] <GO>` | Port/logistics data |
            | `RISK [region] <GO>` | Risk dashboard |
            
            **Regions:** `US-TX` (Texas), `ERCOT` (Texas Grid), `HOU` (Port of Houston)
            
            **Keyboard:** Press `Enter` to execute command
            """
        )

    # PWST Ticker Tray - Fixed bottom component showing risk alerts
    render_ticker_tray()


if __name__ == "__main__":
    main()
