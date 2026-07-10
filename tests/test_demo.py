import numpy as np

from heat_dashboard.config import SURINAME_BOUNDS
from heat_dashboard.demo import demo_context, demo_probability, demo_wind


def test_demo_probability_range_and_metadata():
    field, metadata = demo_probability(1, "Maximum temperature (Tmax)", 35)
    values = field.values
    assert np.isfinite(values).all()
    assert values.min() >= 0 and values.max() <= 100
    assert metadata["valid_start"] < metadata["valid_end"]


def test_demo_probability_deterministic():
    first, _ = demo_probability(2, "Maximum heat index", 38)
    second, _ = demo_probability(2, "Maximum heat index", 38)
    assert np.array_equal(first.values, second.values)


def test_demo_probability_threshold_monotonic_on_average():
    low, _ = demo_probability(1, "Maximum temperature (Tmax)", 30)
    high, _ = demo_probability(1, "Maximum temperature (Tmax)", 41)
    assert float(low.values.mean()) > float(high.values.mean())


def test_demo_context_units():
    field, metadata = demo_context("Mean sea-level pressure", "Average", SURINAME_BOUNDS)
    assert metadata["unit"] == "hPa"
    assert 950 < float(field.values.mean()) < 1050


def test_demo_context_anomaly_centered():
    field, _ = demo_context("2-m air temperature", "Anomaly", SURINAME_BOUNDS)
    assert abs(float(field.values.mean())) < 3.0


def test_demo_wind_components_consistent():
    speed, u, v, metadata = demo_wind("Average", SURINAME_BOUNDS)
    assert metadata["unit"] == "m/s"
    reconstructed = np.hypot(u.values, v.values)
    assert np.allclose(speed.values, reconstructed, atol=1e-5)
