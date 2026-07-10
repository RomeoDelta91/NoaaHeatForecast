import matplotlib.pyplot as plt

from heat_dashboard.config import BOUNDARY_FILE, SURINAME_BOUNDS
from heat_dashboard.demo import demo_probability, demo_wind
from heat_dashboard.geo import load_districts
from heat_dashboard.plots import (
    context_map,
    figure_png_bytes,
    probability_map,
    threshold_map,
)

PNG_MAGIC = b"\x89PNG"


def test_probability_map_renders_png():
    districts = load_districts(BOUNDARY_FILE)
    field, _ = demo_probability(1, "Maximum temperature (Tmax)", 35)
    fig = probability_map(
        field,
        districts,
        "Test map",
        SURINAME_BOUNDS,
        selected_district="Paramaribo",
        show_boundaries=True,
        show_labels=True,
        show_stations=True,
    )
    try:
        assert figure_png_bytes(fig).startswith(PNG_MAGIC)
    finally:
        plt.close(fig)


def test_threshold_map_renders():
    districts = load_districts(BOUNDARY_FILE)
    field, _ = demo_probability(1, "Maximum temperature (Tmax)", 35)
    fig = threshold_map(field, districts, "Threshold", SURINAME_BOUNDS)
    try:
        assert figure_png_bytes(fig).startswith(PNG_MAGIC)
    finally:
        plt.close(fig)


def test_context_map_with_wind_vectors():
    districts = load_districts(BOUNDARY_FILE)
    speed, u, v, _ = demo_wind("Average", SURINAME_BOUNDS)
    fig = context_map(speed, districts, "Wind", SURINAME_BOUNDS, "m/s", u=u, v=v)
    try:
        assert figure_png_bytes(fig).startswith(PNG_MAGIC)
    finally:
        plt.close(fig)
