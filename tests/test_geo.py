import numpy as np
import xarray as xr

from heat_dashboard.config import BOUNDARY_FILE, SURINAME_BOUNDS
from heat_dashboard.geo import (
    clip_to_geometry,
    country_geometry,
    district_by_name,
    district_statistics,
    load_districts,
)

EXPECTED_DISTRICTS = {
    "Brokopondo",
    "Commewijne",
    "Coronie",
    "Marowijne",
    "Nickerie",
    "Para",
    "Paramaribo",
    "Saramacca",
    "Sipaliwini",
    "Wanica",
}


def sample_field():
    west, east, south, north = SURINAME_BOUNDS
    lon = np.arange(west, east, 0.2)
    lat = np.arange(south, north, 0.2)
    values = np.tile(np.linspace(0, 100, lon.size), (lat.size, 1))
    return xr.DataArray(values, coords={"lat": lat, "lon": lon}, dims=("lat", "lon"))


def test_load_districts_names():
    districts = load_districts(BOUNDARY_FILE)
    assert {district.name for district in districts} == EXPECTED_DISTRICTS
    assert all(district.geometry.is_valid for district in districts)


def test_country_geometry_covers_paramaribo():
    districts = load_districts(BOUNDARY_FILE)
    country = country_geometry(districts)
    from shapely.geometry import Point

    assert country.contains(Point(-55.17, 5.82))


def test_district_by_name():
    districts = load_districts(BOUNDARY_FILE)
    assert district_by_name(districts, "Sipaliwini").name == "Sipaliwini"
    assert district_by_name(districts, "Atlantis") is None


def test_clip_to_geometry_masks_outside():
    districts = load_districts(BOUNDARY_FILE)
    country = country_geometry(districts)
    clipped = clip_to_geometry(sample_field(), country)
    values = clipped.values
    assert np.isnan(values).any(), "cells outside Suriname should be masked"
    assert np.isfinite(values).any(), "cells inside Suriname should survive"


def test_district_statistics_shape_and_sorting():
    districts = load_districts(BOUNDARY_FILE)
    stats = district_statistics(sample_field(), districts, probability_cutoff=50)
    assert len(stats) == len(districts)
    assert list(stats.columns) == [
        "District",
        "Mean probability (%)",
        "Max probability (%)",
        "Area ≥ 50% (km²)",
        "District area (km²)",
        "Nearest-grid estimate",
    ]
    means = stats["Mean probability (%)"].tolist()
    assert means == sorted(means, reverse=True)
    assert (stats["Area ≥ 50% (km²)"] <= stats["District area (km²)"] + 1e-6).all()
    # Sipaliwini dominates the country's land area.
    assert stats.loc[stats["District"] == "Sipaliwini", "District area (km²)"].iloc[0] > 50000
