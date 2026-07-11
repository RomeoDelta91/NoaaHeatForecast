from __future__ import annotations

from datetime import datetime

# Load Arrow's native library before the other compiled extensions
# (GEOS, HDF5, matplotlib): importing it late can crash the Streamlit
# script thread when the dataframe tables are serialized.
import pyarrow  # noqa: F401  # isort: skip

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from heat_dashboard.config import (
    BOUNDARY_FILE,
    CONTEXT_PRODUCTS,
    HEAT_PRODUCTS,
    PERCENTILE_THRESHOLDS,
    SURINAME_BOUNDS,
)
from heat_dashboard.demo import demo_context, demo_probability, demo_wind
from heat_dashboard.geo import (
    clip_to_geometry,
    country_geometry,
    district_by_name,
    district_statistics,
    load_districts,
)
from heat_dashboard.noaa import (
    NOAADataError,
    dataarray_to_netcdf_bytes,
    load_context_field,
    load_heat_probability,
    load_percentile_climatology,
    load_wind_field,
)
from heat_dashboard.plots import (
    context_map,
    figure_png_bytes,
    probability_map,
    threshold_map,
)

st.set_page_config(
    page_title="Suriname Heat Forecast Dashboard",
    page_icon="🌡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .block-container {padding-top: 4rem; padding-bottom: 2rem; max-width: 1600px;}
    [data-testid="stMetric"] {background: white; border: 1px solid #e5e7eb; padding: 0.85rem 1rem; border-radius: 0.8rem; box-shadow: 0 1px 3px rgba(15,23,42,.06);}
    [data-testid="stMetricValue"] {font-size: 1.55rem; line-height: 1.2; white-space: normal; overflow: visible;}
    [data-testid="stSidebar"] {border-right: 1px solid #e5e7eb;}
    .dashboard-title {font-size: 2rem; font-weight: 800; line-height: 1.05; color: #111827; margin-bottom: .15rem;}
    .dashboard-subtitle {color: #6b7280; margin-bottom: .8rem;}
    .source-chip {display:inline-block; background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; border-radius:999px; padding:.18rem .65rem; font-size:.78rem; font-weight:600;}
    .notice {border-left:4px solid #f59e0b; background:#fffbeb; padding:.65rem .85rem; border-radius:.35rem;}
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource
def cached_districts():
    return load_districts(BOUNDARY_FILE)


@st.cache_data(ttl=21600, show_spinner=False)
def cached_heat(product_name: str, week: int, threshold: int):
    return load_heat_probability(HEAT_PRODUCTS[product_name], week, threshold, SURINAME_BOUNDS)


@st.cache_data(ttl=21600, show_spinner=False)
def cached_climatology(product_name: str, week: int, percentile: int):
    return load_percentile_climatology(HEAT_PRODUCTS[product_name], week, percentile, SURINAME_BOUNDS)


@st.cache_data(ttl=21600, show_spinner=False)
def cached_context(product_name: str, view: str, week: int, bounds):
    return load_context_field(product_name, view, week, bounds)


@st.cache_data(ttl=21600, show_spinner=False)
def cached_wind(level: int, view: str, week: int, bounds):
    return load_wind_field(level, view, week, bounds)


def formatted_period(metadata: dict) -> str:
    """Compact validity range that fits inside a metric card."""
    try:
        start = datetime.fromisoformat(metadata["valid_start"])
        end = datetime.fromisoformat(metadata["valid_end"])
        if start.year == end.year and start.month == end.month:
            return f"{start.day}–{end.day} {end.strftime('%b %Y')}"
        if start.year == end.year:
            return f"{start.day} {start.strftime('%b')} – {end.day} {end.strftime('%b %Y')}"
        return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
    except Exception:
        return "Unavailable"


def map_extent_for_selection(districts, selected_name: str, padding: float = 0.18):
    if selected_name == "All districts":
        return SURINAME_BOUNDS
    district = district_by_name(districts, selected_name)
    if district is None:
        return SURINAME_BOUNDS
    minx, miny, maxx, maxy = district.geometry.bounds
    return (minx - padding, maxx + padding, miny - padding, maxy + padding)


districts = cached_districts()
country = country_geometry(districts)

st.markdown('<div class="dashboard-title">Suriname Heat Forecast Dashboard</div>', unsafe_allow_html=True)
st.markdown('<div class="dashboard-subtitle">NOAA/CPC GEFS Week 1–2 excessive-heat guidance with official Suriname district boundaries</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Dashboard controls")
    section = st.radio("Section", ["Heat risk", "Atmospheric context"], horizontal=False)
    data_source = st.radio("Data source", ["Live NOAA/CPC", "Demo data"], help="Demo mode keeps the interface testable when the NOAA server is unavailable.")
    week = st.radio("Forecast period", [1, 2], format_func=lambda value: f"Week {value}", horizontal=True)
    st.caption("Week 1 represents days 1–7; Week 2 represents days 8–14.")

    if st.button("Refresh cached NOAA data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

if section == "Heat risk":
    with st.sidebar:
        product_name = st.selectbox("Variable", list(HEAT_PRODUCTS))
        product = HEAT_PRODUCTS[product_name]
        threshold_type = st.radio("Threshold type", ["Fixed temperature", "Percentile"], horizontal=False)
        if threshold_type == "Fixed temperature":
            threshold = st.select_slider("Threshold", options=list(product.fixed_thresholds), value=product.fixed_thresholds[-2], format_func=lambda value: f"{value} °C")
        else:
            threshold = st.select_slider("Percentile", options=list(PERCENTILE_THRESHOLDS), value=90, format_func=lambda value: f"P{value}")
        probability_cutoff = st.slider("Operational risk cutoff", min_value=10, max_value=90, value=50, step=5, format="%d%%")
        selected_district = st.selectbox("District", ["All districts"] + [item.name for item in districts])
        show_boundaries = st.toggle("Show district boundaries", value=True)
        show_labels = st.toggle("Show district names", value=True)
        show_stations = st.toggle("Show stations", value=True)
        clip_country = st.toggle("Clip forecast to Suriname", value=True)
        show_climatology = False
        if threshold_type == "Percentile" and product.prefix in {"tmax", "tmin"}:
            show_climatology = st.toggle("Show percentile temperature threshold", value=False)
        st.divider()
        st.caption(product.description)

    used_demo = data_source == "Demo data"
    raw_bytes = None
    try:
        if used_demo:
            field, metadata = demo_probability(week, product_name, threshold)
        else:
            with st.spinner("Downloading the selected NOAA/CPC NetCDF product…"):
                field, metadata, raw_bytes = cached_heat(product_name, week, threshold)
    except NOAADataError as exc:
        used_demo = True
        field, metadata = demo_probability(week, product_name, threshold)
        st.warning(f"Live NOAA data could not be loaded. Demo data is displayed instead. Details: {exc}")

    display_field = clip_to_geometry(field, country) if clip_country else field
    stats = district_statistics(field, districts, probability_cutoff)
    highest = stats.iloc[0]
    max_probability = float(np.nanmax(display_field.values))
    risk_area_col = f"Area ≥ {probability_cutoff:.0f}% (km²)"
    total_at_risk = float(stats[risk_area_col].sum())
    total_area = float(stats["District area (km²)"].sum())
    area_share = total_at_risk / total_area * 100 if total_area else np.nan
    validity = formatted_period(metadata)

    source_label = "Demo data" if used_demo else "Live NOAA/CPC"
    st.markdown(f'<span class="source-chip">{source_label}</span>', unsafe_allow_html=True)
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Highest-risk district", str(highest["District"]), f"Mean {highest['Mean probability (%)']:.0f}%")
    kpi2.metric("Maximum probability", f"{max_probability:.0f}%")
    kpi3.metric(f"Area at ≥ {probability_cutoff}%", f"{area_share:.0f}%", f"≈ {total_at_risk:,.0f} km²")
    kpi4.metric("Valid period", validity, f"Week {week}")

    threshold_label = f"> {threshold} °C" if threshold_type == "Fixed temperature" else f"> local P{threshold}"
    title = f"GEFS Week {week}: {product.label} probability {threshold_label} for ≥3 consecutive days"
    extent = map_extent_for_selection(districts, selected_district)

    map_col, table_col = st.columns([1.9, 1.0], gap="large")
    with map_col:
        fig = probability_map(
            display_field,
            districts,
            title,
            extent,
            selected_district=None if selected_district == "All districts" else selected_district,
            show_boundaries=show_boundaries,
            show_labels=show_labels,
            show_stations=show_stations,
        )
        st.pyplot(fig, use_container_width=True)
        png = figure_png_bytes(fig)
        plt.close(fig)
        st.download_button("Download map as PNG", png, file_name=f"suriname_week{week}_{product.prefix}_{threshold}.png", mime="image/png", use_container_width=True)

    with table_col:
        st.subheader("District probabilities")
        display_stats = stats.drop(columns=["Nearest-grid estimate"]).copy()
        numeric_cols = display_stats.select_dtypes(include="number").columns
        display_stats[numeric_cols] = display_stats[numeric_cols].round(1)
        st.dataframe(display_stats, hide_index=True, use_container_width=True, height=410)
        csv_bytes = display_stats.to_csv(index=False).encode("utf-8")
        st.download_button("Download district statistics", csv_bytes, file_name=f"district_statistics_week{week}_{product.prefix}_{threshold}.csv", mime="text/csv", use_container_width=True)
        if stats["Nearest-grid estimate"].any():
            st.caption("Small districts without a NOAA grid-cell centre use the nearest grid point; these rows are estimates.")

    st.subheader("District comparison")
    chart_frame = stats.sort_values("Mean probability (%)", ascending=True)
    bar = px.bar(
        chart_frame,
        x="Mean probability (%)",
        y="District",
        orientation="h",
        color="Mean probability (%)",
        color_continuous_scale="YlOrRd",
        range_color=[0, 100],
        text_auto=".0f",
    )
    bar.update_layout(height=460, coloraxis_showscale=False, margin=dict(l=10, r=20, t=15, b=10), xaxis_range=[0, 100])
    st.plotly_chart(bar, use_container_width=True)

    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "Download processed Suriname subset (NetCDF)",
            dataarray_to_netcdf_bytes(display_field, "probability"),
            file_name=f"suriname_week{week}_{product.prefix}_{threshold}_processed.nc",
            mime="application/x-netcdf",
            use_container_width=True,
        )
    with dl2:
        if raw_bytes is not None:
            st.download_button("Download original NOAA NetCDF", raw_bytes, file_name=metadata["filename"], mime="application/x-netcdf", use_container_width=True)
        else:
            st.button("Original NOAA NetCDF unavailable in demo mode", disabled=True, use_container_width=True)

    if show_climatology:
        st.divider()
        st.subheader(f"Local P{threshold} temperature threshold")
        try:
            if used_demo:
                st.info("Climatological threshold visualization is available with live NOAA data.")
            else:
                climo, climo_meta, climo_raw = cached_climatology(product_name, week, threshold)
                climo_display = clip_to_geometry(climo, country) if clip_country else climo
                climo_fig = threshold_map(climo_display, districts, f"Week {week} {product.label}: P{threshold} threshold", extent)
                st.pyplot(climo_fig, use_container_width=True)
                st.download_button("Download threshold map", figure_png_bytes(climo_fig), file_name=f"suriname_week{week}_{product.prefix}_p{threshold}_threshold.png", mime="image/png")
                plt.close(climo_fig)
        except NOAADataError as exc:
            st.error(str(exc))

    with st.expander("Data and processing details"):
        st.json(metadata)
        st.markdown(
            "The original XCast regridding step has been removed. The dashboard reads the NOAA grid with Xarray, normalizes coordinates, clips it directly with the Suriname district geometry, and calculates district summaries from grid-cell centres."
        )

else:
    with st.sidebar:
        context_type = st.selectbox("Product family", ["Scalar field", "Wind"])
        if context_type == "Scalar field":
            context_product = st.selectbox("Atmospheric product", list(CONTEXT_PRODUCTS))
            view = st.radio("Display", ["Average", "Anomaly", "Climatology"])
        else:
            level = st.selectbox("Wind level", [925, 850, 700, 200, 10], format_func=lambda value: "10 m" if value == 10 else f"{value} hPa")
            view = st.radio("Display", ["Average", "Anomaly", "Climatology"])
        if view == "Climatology":
            st.caption("Climatology is reconstructed as weekly mean minus anomaly.")
        buffer_deg = st.slider("Regional context buffer", 0, 15, 8, help="Adds degrees around Suriname for synoptic context.")

    west, east, south, north = SURINAME_BOUNDS
    context_bounds = (west - buffer_deg, east + buffer_deg, max(-89.0, south - buffer_deg), min(89.0, north + buffer_deg))
    used_demo = data_source == "Demo data"
    u = v = None
    try:
        if context_type == "Scalar field":
            if used_demo:
                field, metadata = demo_context(context_product, view, context_bounds)
            else:
                with st.spinner("Downloading NOAA/CPC circulation fields…"):
                    field, metadata = cached_context(context_product, view, week, context_bounds)
            title = f"GEFS Week {week}: {context_product} — {view}"
            unit = metadata.get("unit", field.attrs.get("units", ""))
        else:
            if used_demo:
                field, u, v, metadata = demo_wind(view, context_bounds)
            else:
                with st.spinner("Downloading NOAA/CPC wind fields…"):
                    field, u, v, metadata = cached_wind(level, view, week, context_bounds)
            level_label = "10-m" if level == 10 else f"{level}-hPa"
            title = f"GEFS Week {week}: {level_label} wind speed and direction — {view}"
            unit = "m/s"
    except NOAADataError as exc:
        used_demo = True
        st.warning(f"Live NOAA data could not be loaded. Demo data is displayed instead. Details: {exc}")
        if context_type == "Scalar field":
            field, metadata = demo_context(context_product, view, context_bounds)
            title = f"Demo: Week {week} {context_product} — {view}"
            unit = metadata.get("unit", "")
        else:
            field, u, v, metadata = demo_wind(view, context_bounds)
            title = f"Demo: Week {week} wind — {view}"
            unit = "m/s"

    st.markdown(f'<span class="source-chip">{"Demo data" if used_demo else "Live NOAA/CPC"}</span>', unsafe_allow_html=True)
    a, b, c = st.columns(3)
    a.metric("Valid period", formatted_period(metadata), f"Week {week}")
    b.metric("Field minimum", f"{float(np.nanmin(field.values)):.1f} {unit}")
    c.metric("Field maximum", f"{float(np.nanmax(field.values)):.1f} {unit}")

    fig = context_map(field, districts, title, context_bounds, unit, u=u, v=v)
    st.pyplot(fig, use_container_width=True)
    map_bytes = figure_png_bytes(fig)
    plt.close(fig)
    d1, d2 = st.columns(2)
    d1.download_button("Download map as PNG", map_bytes, file_name=f"suriname_context_week{week}.png", mime="image/png", use_container_width=True)
    d2.download_button("Download processed field as NetCDF", dataarray_to_netcdf_bytes(field, "context_field"), file_name=f"suriname_context_week{week}.nc", mime="application/x-netcdf", use_container_width=True)

    with st.expander("Data details"):
        st.json(metadata)

st.divider()
st.caption(
    "This dashboard visualizes NOAA/CPC GEFS guidance and is not an official warning product. Verify operational decisions against observations, local procedures, and the latest meteorological analysis."
)
st.caption(
    "Gemaakt door: Ritesh Rajai — persoonlijk project, ontwikkeld in eigen tijd; geen product van de Meteorologische Dienst Suriname."
)
