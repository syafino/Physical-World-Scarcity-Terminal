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


def fetch_finance_summary(include_physical: bool = True) -> dict[str, Any]:
    """Fetch financial market summary from the API."""
    try:
        response = httpx.get(
            f"{API_URL}/finance/summary",
            params={"include_physical": include_physical},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {
            "status": "error",
            "message": f"API Error: {str(e)}",
            "quotes": [],
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
                <p style="color: #00FF00;">FIN US-TX &lt;GO&gt;</p>
                <p style="color: #00FF00;">NEWS US-TX &lt;GO&gt;</p>
                <p style="color: #00FF00;">WX US-TX &lt;GO&gt;</p>
                <p style="color: #00FF00;">MACRO US-TX &lt;GO&gt;</p>
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
    elif function_code == "FIN":
        render_fin_data(data)
    elif function_code == "NEWS":
        render_news_data(data)
    elif function_code == "WX":
        render_wx_data(data)
    elif function_code == "MACRO":
        render_macro_data(data)
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


def render_fin_data(data: list[dict]):
    """
    Render financial data panel with split-screen view.
    
    Shows Physical Status (Grid/Water/Port) on left,
    and Texas Proxy Watchlist sparkline charts on right.
    """
    st.markdown("### ▓ FINANCIAL CORRELATION VIEW")
    st.markdown("*Texas Proxy Watchlist - Market/Physical Intersection*")
    
    if not data:
        st.markdown("*No financial data available*")
        return
    
    # Extract physical status from first record (if present)
    physical_status = data[0].get("physical_status", {}) if data else {}
    
    # Create split-screen layout
    col_physical, col_market = st.columns([1, 2])
    
    # ─────────────────────────────────────────────────────────────
    # LEFT PANEL: Physical Status
    # ─────────────────────────────────────────────────────────────
    with col_physical:
        st.markdown("#### Physical Status")
        
        # Grid status
        grid_status = physical_status.get("grid", "NORMAL")
        grid_color = _get_status_color(grid_status)
        st.markdown(
            f"""
            <div style="
                background-color: #161B22;
                border-left: 4px solid {grid_color};
                padding: 8px 12px;
                margin-bottom: 8px;
            ">
                <div style="color: #58A6FF; font-size: 11px;">ERCOT GRID</div>
                <div style="color: {grid_color}; font-size: 16px; font-weight: bold;">{grid_status}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        # Water status
        water_status = physical_status.get("water", "NORMAL")
        water_color = _get_status_color(water_status)
        st.markdown(
            f"""
            <div style="
                background-color: #161B22;
                border-left: 4px solid {water_color};
                padding: 8px 12px;
                margin-bottom: 8px;
            ">
                <div style="color: #58A6FF; font-size: 11px;">TEXAS AQUIFERS</div>
                <div style="color: {water_color}; font-size: 16px; font-weight: bold;">{water_status}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        # Port status
        port_status = physical_status.get("port", "NORMAL")
        port_color = _get_status_color(port_status)
        st.markdown(
            f"""
            <div style="
                background-color: #161B22;
                border-left: 4px solid {port_color};
                padding: 8px 12px;
                margin-bottom: 8px;
            ">
                <div style="color: #58A6FF; font-size: 11px;">PORT OF HOUSTON</div>
                <div style="color: {port_color}; font-size: 16px; font-weight: bold;">{port_status}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        # Exposure legend
        st.markdown(
            """
            <div style="margin-top: 16px; font-size: 10px; color: #6E7681;">
                <strong>Symbol Exposure:</strong><br>
                VST/NRG → GRID<br>
                TXN → GRID + WATR
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    # ─────────────────────────────────────────────────────────────
    # RIGHT PANEL: Market Data + Sparklines
    # ─────────────────────────────────────────────────────────────
    with col_market:
        st.markdown("#### Texas Proxy Watchlist")
        
        for quote in data:
            symbol = quote.get("symbol", "UNK")
            name = quote.get("name", "Unknown")
            price = quote.get("price", 0)
            change_pct = quote.get("change_percent", 0)
            sparkline = quote.get("sparkline", [])
            physical_link = quote.get("physical_link", "")
            
            # Determine color based on change direction
            change_color = "#00FF00" if change_pct >= 0 else "#FF0000"
            arrow = "▲" if change_pct >= 0 else "▼"
            
            # Create a mini-row for each stock
            st.markdown(
                f"""
                <div style="
                    background-color: #161B22;
                    border: 1px solid #30363D;
                    padding: 12px;
                    margin-bottom: 8px;
                    border-radius: 4px;
                ">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <span style="color: #58A6FF; font-size: 16px; font-weight: bold;">{symbol}</span>
                            <span style="color: #6E7681; font-size: 11px; margin-left: 8px;">{name}</span>
                            <span style="color: #6E7681; font-size: 10px; margin-left: 8px;">({physical_link})</span>
                        </div>
                        <div style="text-align: right;">
                            <div style="color: #E6EDF3; font-size: 14px;">${price:.2f}</div>
                            <div style="color: {change_color}; font-size: 12px;">{arrow} {abs(change_pct):.2f}%</div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            
            # Render sparkline chart if available
            if sparkline and len(sparkline) > 1:
                sparkline_df = pd.DataFrame({"price": sparkline})
                st.line_chart(
                    sparkline_df,
                    use_container_width=True,
                    height=60,
                )


def render_news_data(data: list[dict]):
    """
    Render NEWS command - news headlines with sentiment analysis.
    
    Displays a dense scrolling list of headlines color-coded by sentiment:
    - Green: Positive sentiment
    - Yellow: Neutral sentiment  
    - Red: Negative sentiment
    
    Phase 4: Unstructured Data Layer
    """
    st.markdown("### ▓ NEWS & SENTIMENT ANALYSIS")
    
    if not data:
        st.markdown("*No news data available. Fetching from RSS feeds...*")
        return
    
    # Get summary from first record if available
    summary = data[0].get("_summary", {}) if data else {}
    
    # ─────────────────────────────────────────────────────────────
    # Summary Header
    # ─────────────────────────────────────────────────────────────
    if summary:
        overall_sentiment = summary.get("overall_sentiment", 0)
        total_headlines = summary.get("total_headlines", len(data))
        
        # Determine overall sentiment color and label
        if overall_sentiment <= -0.5:
            sentiment_color = "#FF0000"
            sentiment_label = "VERY NEGATIVE"
        elif overall_sentiment <= -0.05:
            sentiment_color = "#FFA500"
            sentiment_label = "NEGATIVE"
        elif overall_sentiment < 0.05:
            sentiment_color = "#FFFF00"
            sentiment_label = "NEUTRAL"
        elif overall_sentiment < 0.5:
            sentiment_color = "#90EE90"
            sentiment_label = "POSITIVE"
        else:
            sentiment_color = "#00FF00"
            sentiment_label = "VERY POSITIVE"
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("HEADLINES", total_headlines)
        with col2:
            st.markdown(
                f"""
                <div style="padding: 8px;">
                    <div style="color: #6E7681; font-size: 12px;">OVERALL SENTIMENT</div>
                    <div style="color: {sentiment_color}; font-size: 24px; font-weight: bold;">
                        {sentiment_label}
                    </div>
                    <div style="color: #6E7681; font-size: 11px;">Score: {overall_sentiment:.3f}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col3:
            categories = summary.get("categories", {})
            negative_total = sum(c.get("negative_count", 0) for c in categories.values())
            st.metric("NEGATIVE HEADLINES", negative_total)
    
    # ─────────────────────────────────────────────────────────────
    # Category Breakdown
    # ─────────────────────────────────────────────────────────────
    if summary and summary.get("categories"):
        st.markdown("#### Category Sentiment")
        
        categories = summary.get("categories", {})
        cols = st.columns(len(categories))
        
        for i, (cat_name, cat_data) in enumerate(categories.items()):
            with cols[i]:
                avg_sent = cat_data.get("avg_sentiment", 0)
                cat_color = _get_sentiment_color(avg_sent)
                
                st.markdown(
                    f"""
                    <div style="
                        background-color: #161B22;
                        border-left: 3px solid {cat_color};
                        padding: 8px;
                        margin-bottom: 8px;
                    ">
                        <div style="color: #58A6FF; font-size: 11px;">{cat_name}</div>
                        <div style="color: {cat_color}; font-size: 14px; font-weight: bold;">
                            {avg_sent:.2f}
                        </div>
                        <div style="color: #6E7681; font-size: 10px;">
                            {cat_data.get('headline_count', 0)} headlines
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    
    # ─────────────────────────────────────────────────────────────
    # Headlines List (scrollable)
    # ─────────────────────────────────────────────────────────────
    st.markdown("#### Headlines")
    
    # Create scrollable container for headlines
    headlines_html = ""
    
    for item in data[:30]:  # Limit displayed headlines
        title = item.get("title", "")
        source = item.get("source", "Unknown")
        sentiment_score = item.get("sentiment_score", 0)
        sentiment_label = item.get("sentiment_label", "NEUTRAL")
        category = item.get("category", "")
        published = item.get("published_at", "")[:16] if item.get("published_at") else ""
        url = item.get("url", "")
        
        # Get color based on sentiment
        sentiment_color = _get_sentiment_color(sentiment_score)
        
        # Sentiment indicator
        if sentiment_score <= -0.5:
            indicator = "▼▼"
        elif sentiment_score <= -0.05:
            indicator = "▼"
        elif sentiment_score < 0.05:
            indicator = "●"
        elif sentiment_score < 0.5:
            indicator = "▲"
        else:
            indicator = "▲▲"
        
        headlines_html += f"""
        <div style="
            background-color: #161B22;
            border-left: 3px solid {sentiment_color};
            padding: 8px 12px;
            margin-bottom: 4px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
        ">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <div style="flex: 1;">
                    <a href="{url}" target="_blank" style="color: #E6EDF3; text-decoration: none;">
                        {title}
                    </a>
                    <div style="color: #6E7681; font-size: 10px; margin-top: 4px;">
                        {source} | {category} | {published}
                    </div>
                </div>
                <div style="
                    color: {sentiment_color};
                    font-weight: bold;
                    min-width: 50px;
                    text-align: right;
                ">
                    {indicator} {sentiment_score:.2f}
                </div>
            </div>
        </div>
        """
    
    st.markdown(
        f"""
        <div style="max-height: 400px; overflow-y: auto;">
            {headlines_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_wx_data(data: list[dict]):
    """
    Render WX command - weather forecasts with temperature danger zones.
    
    Shows 7-day forecasts for key Texas locations with:
    - Temperature danger zone indicators (heat/freeze risk)
    - Grid strain predictions
    - Temperature chart with danger thresholds
    - NWS weather alerts
    
    Phase 5: The Predictive Layer
    """
    st.markdown("### ▓ WEATHER FORECAST & PREDICTIVE ANALYSIS")
    st.markdown("*Texas Node Predictive Layer - Anticipating Scarcity Before It Happens*")
    
    if not data:
        st.markdown("*No weather data available. Fetching from NWS API...*")
        return
    
    # Get summary from first record if available
    summary = data[0].get("_summary", {}) if data else {}
    nws_alerts = data[0].get("_nws_alerts", []) if data else []
    
    # ─────────────────────────────────────────────────────────────
    # Summary Header - Grid Strain Prediction
    # ─────────────────────────────────────────────────────────────
    if summary:
        heat_risk = summary.get("overall_heat_risk", "NONE")
        freeze_risk = summary.get("overall_freeze_risk", "NONE")
        grid_strain = summary.get("overall_grid_strain", "NORMAL")
        
        # Determine grid strain color
        strain_colors = {
            "NORMAL": "#00FF00",
            "ELEVATED": "#FFFF00",
            "HIGH": "#FFA500",
            "SEVERE": "#FF4500",
            "EXTREME": "#FF0000",
        }
        strain_color = strain_colors.get(grid_strain, "#6E7681")
        
        # Risk colors
        risk_colors = {
            "NONE": "#00FF00",
            "MODERATE": "#FFFF00",
            "HIGH": "#FFA500",
            "SEVERE": "#FF4500",
            "EXTREME": "#FF0000",
        }
        heat_color = risk_colors.get(heat_risk, "#6E7681")
        freeze_color = risk_colors.get(freeze_risk, "#6E7681")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(
                f"""
                <div style="
                    background-color: #161B22;
                    border-left: 4px solid {strain_color};
                    padding: 12px;
                ">
                    <div style="color: #6E7681; font-size: 11px;">48H GRID STRAIN PREDICTION</div>
                    <div style="color: {strain_color}; font-size: 24px; font-weight: bold;">
                        {grid_strain}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(
                f"""
                <div style="
                    background-color: #161B22;
                    border-left: 4px solid {heat_color};
                    padding: 12px;
                ">
                    <div style="color: #6E7681; font-size: 11px;">HEAT RISK</div>
                    <div style="color: {heat_color}; font-size: 20px; font-weight: bold;">
                        {heat_risk}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col3:
            st.markdown(
                f"""
                <div style="
                    background-color: #161B22;
                    border-left: 4px solid {freeze_color};
                    padding: 12px;
                ">
                    <div style="color: #6E7681; font-size: 11px;">FREEZE RISK</div>
                    <div style="color: {freeze_color}; font-size: 20px; font-weight: bold;">
                        {freeze_risk}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    
    # ─────────────────────────────────────────────────────────────
    # NWS Active Alerts
    # ─────────────────────────────────────────────────────────────
    if nws_alerts:
        st.markdown("#### Active Weather Alerts")
        for alert in nws_alerts[:3]:
            event = alert.get("event", "Weather Alert")
            headline = alert.get("headline", "")[:100]
            severity = alert.get("severity", "")
            
            alert_color = "#FF0000" if severity in ["Extreme", "Severe"] else "#FFA500"
            
            st.markdown(
                f"""
                <div style="
                    background-color: #161B22;
                    border-left: 4px solid {alert_color};
                    padding: 8px 12px;
                    margin-bottom: 4px;
                    font-size: 11px;
                ">
                    <span style="color: {alert_color}; font-weight: bold;">{event}</span>
                    <span style="color: #6E7681; margin-left: 8px;">{headline}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
    
    # ─────────────────────────────────────────────────────────────
    # Location Forecasts with Temperature Chart
    # ─────────────────────────────────────────────────────────────
    st.markdown("#### Location Forecasts (48h)")
    
    for loc_data in data:
        location_name = loc_data.get("location_name", "Unknown")
        purpose = loc_data.get("purpose", "")
        max_temp = loc_data.get("max_temp_48h")
        min_temp = loc_data.get("min_temp_48h")
        heat_risk = loc_data.get("heat_risk", "NONE")
        freeze_risk = loc_data.get("freeze_risk", "NONE")
        hourly = loc_data.get("hourly", [])
        
        # Skip if no location name (might be summary metadata)
        if not location_name or location_name == "Unknown":
            continue
        
        # Determine location color based on highest risk
        if heat_risk in ["HIGH", "EXTREME"] or freeze_risk in ["SEVERE", "EXTREME"]:
            loc_color = "#FF0000"
        elif heat_risk == "MODERATE" or freeze_risk == "MODERATE":
            loc_color = "#FFA500"
        else:
            loc_color = "#00FF00"
        
        col_info, col_chart = st.columns([1, 2])
        
        with col_info:
            st.markdown(
                f"""
                <div style="
                    background-color: #161B22;
                    border-left: 4px solid {loc_color};
                    padding: 12px;
                    margin-bottom: 8px;
                ">
                    <div style="color: #58A6FF; font-size: 14px; font-weight: bold;">{location_name}</div>
                    <div style="color: #6E7681; font-size: 10px; margin-bottom: 8px;">{purpose}</div>
                    <div style="display: flex; justify-content: space-between;">
                        <div>
                            <div style="color: #6E7681; font-size: 10px;">HIGH</div>
                            <div style="color: {'#FF4500' if max_temp and max_temp >= 98 else '#E6EDF3'}; font-size: 18px;">
                                {max_temp}°F
                            </div>
                        </div>
                        <div>
                            <div style="color: #6E7681; font-size: 10px;">LOW</div>
                            <div style="color: {'#00BFFF' if min_temp and min_temp <= 32 else '#E6EDF3'}; font-size: 18px;">
                                {min_temp}°F
                            </div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        
        with col_chart:
            # Build temperature chart from hourly data
            if hourly and len(hourly) > 0:
                temps = []
                times = []
                for h in hourly[:48]:  # 48 hours
                    temps.append(h.get("temperature", 0))
                    times.append(h.get("time", ""))
                
                if temps:
                    chart_df = pd.DataFrame({
                        "Temperature (°F)": temps,
                    })
                    
                    # Simple line chart
                    st.line_chart(
                        chart_df,
                        use_container_width=True,
                        height=100,
                    )
                    
                    # Danger zone indicators
                    thresholds = summary.get("thresholds", {})
                    heat_threshold = thresholds.get("HIGH_HEAT", 98)
                    freeze_threshold = thresholds.get("FREEZE_WARNING", 32)
                    
                    if max(temps) >= heat_threshold:
                        st.markdown(
                            f"<span style='color: #FF4500; font-size: 10px;'>⚠ DANGER ZONE: Temps exceed {heat_threshold}°F</span>",
                            unsafe_allow_html=True,
                        )
                    if min(temps) <= freeze_threshold:
                        st.markdown(
                            f"<span style='color: #00BFFF; font-size: 10px;'>⚠ FREEZE ZONE: Temps below {freeze_threshold}°F</span>",
                            unsafe_allow_html=True,
                        )
        
        st.markdown("---")
    
    # ─────────────────────────────────────────────────────────────
    # Thresholds Reference
    # ─────────────────────────────────────────────────────────────
    with st.expander("Temperature Thresholds Reference", expanded=False):
        thresholds = summary.get("thresholds", {})
        st.markdown(
            f"""
            | Threshold | Temperature | Impact |
            |-----------|-------------|--------|
            | EXTREME_HEAT | >{thresholds.get('EXTREME_HEAT', 100)}°F | Extreme grid strain, rolling blackouts possible |
            | HIGH_HEAT | >{thresholds.get('HIGH_HEAT', 98)}°F | High grid strain danger zone |
            | MODERATE_HEAT | >{thresholds.get('MODERATE_HEAT', 95)}°F | Elevated demand, monitor closely |
            | FREEZE_WARNING | <{thresholds.get('FREEZE_WARNING', 32)}°F | Freeze risk, pipe/infrastructure concern |
            | HARD_FREEZE | <{thresholds.get('HARD_FREEZE', 25)}°F | Severe freeze (2021 crisis level) |
            | EXTREME_COLD | <{thresholds.get('EXTREME_COLD', 15)}°F | Extreme cold emergency |
            """
        )


def render_macro_data(data: list[dict]):
    """
    Render MACRO command - commodity baseline data.
    
    Shows Henry Hub Natural Gas spot prices with:
    - Current price and 30-day moving average
    - Premium/discount status
    - Price chart over 30 days
    - Grid cost impact assessment
    
    Phase 6: The Macro-Commodity Layer
    """
    st.markdown("### ▓ COMMODITY BASELINE: HENRY HUB NATURAL GAS")
    st.markdown("*Texas Grid Power Generation Cost Indicator*")
    
    if not data:
        st.markdown("*No commodity data available. Check FRED API key in .env*")
        return
    
    record = data[0] if data else {}
    summary = record.get("_summary", {})
    series_info = record.get("_series_info", {})
    chart_data = record.get("chart_data", [])
    
    # ─────────────────────────────────────────────────────────────
    # Summary Header - Price and Status
    # ─────────────────────────────────────────────────────────────
    latest_price = record.get("latest_price")
    ma_30d = record.get("moving_average_30d")
    premium_pct = record.get("premium_percent", 0)
    is_above_ma = record.get("is_above_ma", False)
    alert_level = summary.get("commodity_alert_level", "NORMAL")
    grid_impact = summary.get("grid_cost_impact", "NORMAL")
    is_mock = record.get("is_mock", True)
    
    # Determine colors
    alert_colors = {
        "NORMAL": "#00FF00",
        "ELEVATED": "#FFFF00",
        "PREMIUM": "#FFA500",
        "SPIKE": "#FF0000",
    }
    alert_color = alert_colors.get(alert_level, "#6E7681")
    
    impact_colors = {
        "NORMAL": "#00FF00",
        "ELEVATED": "#FFFF00",
        "HIGH": "#FFA500",
        "CRITICAL": "#FF0000",
    }
    impact_color = impact_colors.get(grid_impact, "#6E7681")
    
    # Price direction
    direction_icon = "▲" if is_above_ma else "▼" if not is_above_ma and ma_30d else "─"
    direction_color = "#FF4500" if is_above_ma else "#00FF00" if ma_30d else "#6E7681"
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(
            f"""
            <div style="
                background-color: #161B22;
                border-left: 4px solid {alert_color};
                padding: 12px;
            ">
                <div style="color: #6E7681; font-size: 11px;">SPOT PRICE</div>
                <div style="color: {alert_color}; font-size: 28px; font-weight: bold;">
                    ${latest_price:.2f if latest_price else 'N/A'}
                </div>
                <div style="color: #6E7681; font-size: 10px;">$/MMBtu</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    with col2:
        st.markdown(
            f"""
            <div style="
                background-color: #161B22;
                border-left: 4px solid {direction_color};
                padding: 12px;
            ">
                <div style="color: #6E7681; font-size: 11px;">VS 30-DAY AVG</div>
                <div style="color: {direction_color}; font-size: 24px; font-weight: bold;">
                    {direction_icon} {premium_pct:+.1f}%
                </div>
                <div style="color: #6E7681; font-size: 10px;">MA: ${ma_30d:.2f if ma_30d else 'N/A'}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    with col3:
        st.markdown(
            f"""
            <div style="
                background-color: #161B22;
                border-left: 4px solid {impact_color};
                padding: 12px;
            ">
                <div style="color: #6E7681; font-size: 11px;">GRID COST IMPACT</div>
                <div style="color: {impact_color}; font-size: 24px; font-weight: bold;">
                    {grid_impact}
                </div>
                <div style="color: #6E7681; font-size: 10px;">Generation Cost Level</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    # Alert message if present
    alert_msg = summary.get("alert_message")
    if alert_msg:
        st.markdown(
            f"""
            <div style="
                background-color: #161B22;
                border-left: 4px solid {alert_color};
                padding: 8px 12px;
                margin-top: 8px;
                font-size: 12px;
                color: {alert_color};
            ">
                ⚠ {alert_msg}
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    # Mock data warning
    if is_mock:
        st.markdown(
            """
            <div style="
                background-color: #2D1F00;
                border-left: 4px solid #FFA500;
                padding: 8px 12px;
                margin-top: 8px;
                font-size: 11px;
                color: #FFA500;
            ">
                ⚠ USING MOCK DATA - Add FRED_API_KEY to .env for live prices
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    # ─────────────────────────────────────────────────────────────
    # Price Chart
    # ─────────────────────────────────────────────────────────────
    st.markdown("#### 30-Day Price History")
    
    if chart_data:
        df = pd.DataFrame(chart_data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        
        # Add threshold lines as separate columns
        premium_threshold = record.get("premium_threshold", 4.00)
        spike_threshold = record.get("spike_threshold", 6.00)
        historical_avg = record.get("historical_avg", 2.50)
        
        df["Premium Threshold"] = premium_threshold
        df["Historical Avg"] = historical_avg
        
        # Create chart
        st.line_chart(
            df.set_index("date")[["price", "Premium Threshold", "Historical Avg"]],
            use_container_width=True,
            height=250,
        )
        
        # Legend
        st.markdown(
            f"""
            <div style="font-size: 10px; color: #6E7681; display: flex; gap: 20px;">
                <span>● Price</span>
                <span style="color: #FFA500;">── Premium Threshold (${premium_threshold})</span>
                <span style="color: #58A6FF;">── Historical Avg (${historical_avg})</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown("*No chart data available*")
    
    # ─────────────────────────────────────────────────────────────
    # Context Information
    # ─────────────────────────────────────────────────────────────
    with st.expander("Henry Hub & Texas Grid Context", expanded=False):
        texas_relevance = series_info.get("texas_relevance", "N/A")
        st.markdown(
            f"""
            **Why Henry Hub Matters for Texas:**
            
            {texas_relevance}
            
            **Price Thresholds:**
            | Level | Price | Interpretation |
            |-------|-------|----------------|
            | NORMAL | <${record.get('premium_threshold', 4.00):.2f} | Typical trading range |
            | PREMIUM | >${record.get('premium_threshold', 4.00):.2f} | Above normal, elevated generation costs |
            | SPIKE | >${record.get('spike_threshold', 6.00):.2f} | Major price spike, severe cost impact |
            
            **Linked Fate v5 Correlation:**
            - If GRID STRAIN + GAS PREMIUM → "STRAIN MET WITH COMMODITY PREMIUM"
            - If GRID EMERGENCY + GAS SPIKE → "EXTREME COST EVENT"
            
            **Data Source:** FRED API (St. Louis Fed) - Series: DHHNGSP
            """
        )


def _get_sentiment_color(sentiment: float) -> str:
    """Get color for sentiment score."""
    if sentiment <= -0.5:
        return "#FF0000"  # Very negative - red
    elif sentiment <= -0.05:
        return "#FFA500"  # Negative - orange
    elif sentiment < 0.05:
        return "#FFFF00"  # Neutral - yellow
    elif sentiment < 0.5:
        return "#90EE90"  # Positive - light green
    else:
        return "#00FF00"  # Very positive - green


def _get_status_color(status: str) -> str:
    """Get color for status level."""
    colors = {
        "NORMAL": "#00FF00",
        "WATCH": "#FFFF00",
        "WARNING": "#FFA500",
        "CRITICAL": "#FF0000",
    }
    return colors.get(status, "#6E7681")


def fetch_news_sentiment():
    """Fetch news sentiment summary for ticker tray."""
    try:
        response = httpx.get(f"{API_URL}/news/summary", timeout=5.0)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


def fetch_predictive_alerts():
    """Fetch predictive weather alerts for ticker tray (Phase 5)."""
    try:
        response = httpx.get(f"{API_URL}/weather/predictive-alerts", timeout=5.0)
        if response.status_code == 200:
            return response.json().get("predictive_alerts", [])
    except Exception:
        pass
    return []


def fetch_weather_danger():
    """Fetch weather danger assessment for ticker tray (Phase 5)."""
    try:
        response = httpx.get(f"{API_URL}/weather/danger", timeout=5.0)
        if response.status_code == 200:
            return response.json().get("danger_assessment", {})
    except Exception:
        pass
    return {}


def render_ticker_tray():
    """
    Render the PWST Ticker Tray - bottom component showing risk alerts.
    
    Fetches alerts from the API and displays them in a compact ticker format.
    Alerts are color-coded by severity level.
    
    Phase 4: Also includes high-impact negative news headlines.
    Phase 5: Includes predictive weather alerts with [PREDICTIVE] tag.
    """
    # Fetch active alerts (excluding NORMAL status)
    alerts = fetch_alerts(active_only=True, limit=30)
    
    # Filter out NORMAL alerts for ticker display
    active_alerts = [a for a in alerts if a.get("alert_level") != "NORMAL"]
    
    # Separate predictive alerts (Phase 5)
    predictive_alerts = [a for a in active_alerts if a.get("alert_type") == "PREDICTIVE"]
    physical_alerts = [a for a in active_alerts if a.get("alert_type") != "PREDICTIVE"]
    
    # Summary counts
    critical_count = len([a for a in alerts if a.get("alert_level") == "CRITICAL"])
    warning_count = len([a for a in alerts if a.get("alert_level") == "WARNING"])
    watch_count = len([a for a in alerts if a.get("alert_level") == "WATCH"])
    predictive_count = len(predictive_alerts)
    
    # Fetch news sentiment (Phase 4)
    news_data = fetch_news_sentiment()
    critical_headlines = news_data.get("critical_headlines", []) if news_data else []
    overall_sentiment = news_data.get("overall_sentiment", 0) if news_data else 0
    
    # Fetch weather danger (Phase 5)
    weather_danger = fetch_weather_danger()
    overall_danger = weather_danger.get("overall", {}) if weather_danger else {}
    grid_strain = overall_danger.get("grid_strain_prediction", "NORMAL")
    
    # Build ticker text
    if not active_alerts and not critical_headlines:
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
        elif predictive_count > 0:
            parts.append(f"◆ {predictive_count} PREDICTIVE")
            ticker_color = "#FF6B6B"  # Salmon for predictive
        elif critical_headlines:
            parts.append(f"● {len(critical_headlines)} NEG NEWS")
            ticker_color = "#FFA500"
        else:
            parts.append(f"● {watch_count} WATCH")
            ticker_color = "#FFFF00"
        
        # Add individual alert details
        alert_details = []
        
        # Prioritize predictive alerts (Phase 5)
        for a in predictive_alerts[:2]:
            title = a.get("title", "Predictive Alert")[:50]
            alert_details.append(f"[PREDICTIVE] {title}")
        
        # Then physical alerts
        for a in physical_alerts[:2]:
            level = a.get("alert_level", "WATCH")
            title = a.get("title", "Alert")
            alert_type = a.get("alert_type", "SYS")
            alert_details.append(f"[{alert_type}] {title}")
        
        # Add critical news headlines (Phase 4)
        for h in critical_headlines[:1]:  # Limit to 1 headline (reduced for predictive)
            title = h.get("title", "")[:40]
            category = h.get("category", "NEWS")
            alert_details.append(f"[{category}] {title}...")
        
        ticker_text = " | ".join(parts) + " — " + " | ".join(alert_details)
    
    # Main ticker
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
    
    # Secondary line: Weather prediction + News sentiment (Phase 4 + 5)
    # Determine grid strain color
    strain_colors = {
        "NORMAL": "#00FF00",
        "ELEVATED": "#FFFF00", 
        "HIGH": "#FFA500",
        "SEVERE": "#FF4500",
        "EXTREME": "#FF0000",
    }
    strain_color = strain_colors.get(grid_strain, "#6E7681")
    
    sent_color = _get_sentiment_color(overall_sentiment) if news_data else "#6E7681"
    sent_label = "POSITIVE" if overall_sentiment > 0.05 else "NEGATIVE" if overall_sentiment < -0.05 else "NEUTRAL"
    
    st.markdown(
        f"""
        <div style="
            background-color: #0D1117;
            padding: 4px 16px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            color: #6E7681;
            display: flex;
            justify-content: space-between;
        ">
            <span>
                <span style="color: {strain_color};">◆</span>
                48H GRID FORECAST: <span style="color: {strain_color};">{grid_strain}</span>
            </span>
            <span>
                <span style="color: {sent_color};">●</span>
                NEWS: <span style="color: {sent_color};">{sent_label}</span>
                ({overall_sentiment:.2f})
            </span>
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
            | `FIN [region] <GO>` | Financial correlation view (Phase 3) |
            | `NEWS [region] <GO>` | News sentiment analysis (Phase 4) |
            | `WX [region] <GO>` | Weather forecasts & predictive analysis (Phase 5) |
            | `MACRO [region] <GO>` | Commodity baseline - Henry Hub gas prices (Phase 6) |
            | `RISK [region] <GO>` | Risk dashboard |
            
            **Regions:** `US-TX` (Texas), `ERCOT` (Texas Grid), `HOU` (Port of Houston)
            
            **Watchlist:** `VST` (Vistra), `NRG` (NRG Energy), `TXN` (Texas Instruments)
            
            **News Categories:** GRID, WATER, LOGISTICS, EQUITY
            
            **Weather Locations:** DALLAS, HOUSTON (ERCOT load center, Port/Logistics)
            
            **Danger Zones:** >98°F (heat risk), <25°F (freeze risk)
            
            **Commodity:** Henry Hub Natural Gas (DHHNGSP) - ERCOT generation cost indicator
            
            **Keyboard:** Press `Enter` to execute command
            """
        )

    # PWST Ticker Tray - Fixed bottom component showing risk alerts
    render_ticker_tray()


if __name__ == "__main__":
    main()
