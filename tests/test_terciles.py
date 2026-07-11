import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from heat_dashboard.config import (
    BOUNDARY_FILE,
    SUBSEASONAL_PERIODS,
    SURINAME_BOUNDS,
    TERCILE_CATEGORIES,
    tercile_url,
)
from heat_dashboard.demo import demo_precip_terciles
from heat_dashboard.geo import district_tercile_statistics, load_districts
from heat_dashboard.plots import figure_png_bytes, tercile_map


def test_tercile_urls_match_documented_links():
    base = "https://ftp.cpc.ncep.noaa.gov/International/subseasonal2/"
    assert tercile_url("1") == base + "gefs_week1_tercile.nc"
    assert tercile_url("2") == base + "gefs_week2_tercile.nc"
    assert tercile_url("34") == base + "gefs_week34_tercile.nc"
    assert [item[0] for item in SUBSEASONAL_PERIODS.values()] == ["1", "2", "34"]


def test_demo_terciles_sum_to_100():
    for period in SUBSEASONAL_PERIODS:
        field, metadata = demo_precip_terciles(period, SURINAME_BOUNDS)
        assert list(field["category"].values) == list(TERCILE_CATEGORIES)
        totals = field.values.sum(axis=0)
        assert np.allclose(totals, 100.0, atol=0.01)
        assert metadata["valid_start"] < metadata["valid_end"]


def test_district_tercile_statistics_columns_and_dominance():
    districts = load_districts(BOUNDARY_FILE)
    field, _ = demo_precip_terciles("Week 1", SURINAME_BOUNDS)
    stats = district_tercile_statistics(field, districts)
    assert len(stats) == len(districts)
    assert list(stats.columns) == [
        "District",
        "Below normal (%)",
        "Near normal (%)",
        "Above normal (%)",
        "Dominant tercile",
        "Nearest-grid estimate",
    ]
    for _, row in stats.iterrows():
        means = {name: row[f"{name} (%)"] for name in TERCILE_CATEGORIES}
        assert row["Dominant tercile"] == max(means, key=means.get)


def test_tercile_map_renders_png():
    districts = load_districts(BOUNDARY_FILE)
    field, _ = demo_precip_terciles("Week 3–4", SURINAME_BOUNDS)
    fig = tercile_map(field, districts, "Terciles", SURINAME_BOUNDS)
    try:
        assert figure_png_bytes(fig).startswith(b"\x89PNG")
    finally:
        plt.close(fig)


def test_load_precip_terciles_pipeline_with_mocked_download(monkeypatch):
    """Full loader test against a synthetic NOAA-style tercile file."""
    import heat_dashboard.noaa as noaa

    lon = np.arange(300.0, 308.0, 1.0)  # 0-360 convention
    lat = np.arange(8.0, -1.0, -1.0)  # descending
    rng = np.random.default_rng(11)
    scores = rng.uniform(0, 1, (1, 3, lat.size, lon.size))
    fractions = scores / scores.sum(axis=1, keepdims=True)
    dataset = xr.Dataset(
        {"precip": (("time", "M", "latitude", "longitude"), fractions.astype("float32"))},
        coords={"time": [0], "M": [0, 1, 2], "latitude": lat, "longitude": lon},
    )
    raw = bytes(dataset.to_netcdf())

    requested = {}

    def fake_download(url):
        requested["url"] = url
        return raw

    monkeypatch.setattr(noaa, "_download", fake_download)
    field, metadata, payload = noaa.load_precip_terciles("Week 2", SURINAME_BOUNDS)

    assert requested["url"].endswith("/International/subseasonal2/gefs_week2_tercile.nc")
    assert payload == raw
    assert field.dims == ("category", "lat", "lon")
    assert list(field["category"].values) == list(TERCILE_CATEGORIES)
    totals = field.values.sum(axis=0)
    assert np.allclose(totals[np.isfinite(totals)], 100.0, atol=0.5)
    assert metadata["period"] == "Week 2"
