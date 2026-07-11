"""Static configuration for the Suriname heat dashboard.

Everything environment-specific lives here: NOAA/CPC endpoint templates,
product catalogues, geographic bounds, and the boundary-file location.
If NOAA reorganises its directory layout only this module needs updating;
the application automatically falls back to demo data whenever a download
fails, so a stale URL never breaks the interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent

#: Web-ready EPSG:4326 district boundaries (GeoJSON FeatureCollection with a
#: ``name`` property per district). Replace this file with the official
#: General Bureau of Statistics boundaries to refine the simplified shapes.
BOUNDARY_FILE = PROJECT_ROOT / "data" / "boundaries" / "suriname_districts.geojson"

#: Map extent used for downloads and plotting: (west, east, south, north).
SURINAME_BOUNDS = (-58.5, -53.5, 1.5, 6.5)

#: Percentile exceedance thresholds offered in the sidebar (matching the
#: NOAA/CPC Global Heat Hazard Outlook product set).
PERCENTILE_THRESHOLDS = (80, 85, 90, 95)

#: Root of the NOAA/CPC International Desks area served over HTTPS.
NOAA_INTERNATIONAL_BASE = "https://ftp.cpc.ncep.noaa.gov/International"

#: Directory holding the pre-processed Week-1/Week-2 GEFS products the
#: dashboard reads (weekly means, anomalies, and heat-exceedance
#: probabilities). Filenames follow ``wk{week}_{product}{threshold}_c3.nc``
#: (e.g. ``wk1_tmax35_c3.nc`` for Tmax > 35 °C, ``wk1_tmax90_c3.nc`` for
#: Tmax > local P90) and ``wk{week}_{product}climo{percentile}.nc`` for the
#: percentile climatologies.
NOAA_DATA_URL = f"{NOAA_INTERNATIONAL_BASE}/PREPARE_africa/subseasonal/realtime/data/"

#: Kept as an alias for provenance strings.
NOAA_BASE_URL = NOAA_DATA_URL

#: The exceedance must hold for at least this many consecutive days.
CONSECUTIVE_DAYS = 3

#: Directory listings searched, in order, when no exact filename guess
#: matches: the loader downloads each index page, extracts the ``.nc``
#: links, and picks the file whose name matches the requested product.
HEAT_LISTING_DIRECTORIES = (
    NOAA_DATA_URL,
    f"{NOAA_INTERNATIONAL_BASE}/global_heat/",
    f"{NOAA_INTERNATIONAL_BASE}/global_heat/percentile/",
    f"{NOAA_INTERNATIONAL_BASE}/multi_heat/",
)

CONTEXT_LISTING_DIRECTORIES = (
    NOAA_DATA_URL,
    f"{NOAA_INTERNATIONAL_BASE}/multi_heat/",
)

#: Seconds before a NOAA download attempt is abandoned.
DOWNLOAD_TIMEOUT = 60

#: Meteorological stations drawn on the maps: (name, longitude, latitude).
STATIONS = (
    ("Paramaribo (Cultuurtuin)", -55.17, 5.85),
    ("Nieuw Nickerie", -56.97, 5.93),
    ("Totness", -56.33, 5.88),
    ("Zanderij (JAP Airport)", -55.19, 5.45),
    ("Moengo", -54.40, 5.61),
    ("Albina", -54.06, 5.50),
    ("Kwamalasamutu", -56.79, 2.35),
    ("Sipaliwini Airstrip", -56.13, 2.03),
)


@dataclass(frozen=True)
class HeatProduct:
    """One GEFS excessive-heat probability product."""

    prefix: str
    label: str
    description: str
    fixed_thresholds: tuple[int, ...]

    def filename(self, week: int, threshold: int) -> str:
        """Documented NetCDF filename for a fixed (°C) or percentile threshold.

        Fixed thresholds are always below 50 °C and percentiles are always
        80 or higher, so the magnitude alone identifies the threshold type;
        NOAA uses the same ``wk{week}_{product}{threshold}_c3.nc`` pattern
        for both (``wk1_tmax35_c3.nc`` vs ``wk1_tmax90_c3.nc``).
        """
        return f"wk{week}_{self.prefix}{threshold}_c{CONSECUTIVE_DAYS}.nc"

    def climatology_filename(self, week: int, percentile: int) -> str:
        return f"wk{week}_{self.prefix}climo{percentile}.nc"

    def url_candidates(self, week: int, threshold: int) -> list[str]:
        """Exact URLs to try before falling back to listing discovery."""
        return [NOAA_DATA_URL + self.filename(week, threshold)]

    def climatology_url_candidates(self, week: int, percentile: int) -> list[str]:
        return [NOAA_DATA_URL + self.climatology_filename(week, percentile)]


HEAT_PRODUCTS: dict[str, HeatProduct] = {
    "Maximum temperature (Tmax)": HeatProduct(
        prefix="tmax",
        label="Tmax",
        description="Probability that daily maximum 2-m temperature exceeds the selected threshold on at least three consecutive days.",
        fixed_thresholds=(33, 35, 37, 39, 41),
    ),
    "Minimum temperature (Tmin)": HeatProduct(
        prefix="tmin",
        label="Tmin",
        description="Probability that daily minimum 2-m temperature stays above the selected threshold on at least three consecutive days — warm nights limit overnight recovery.",
        fixed_thresholds=(23, 25, 27, 29),
    ),
    "Maximum heat index": HeatProduct(
        prefix="himax",
        label="Max heat index",
        description="Probability that the daytime heat index (temperature and humidity combined) exceeds the selected threshold on at least three consecutive days.",
        fixed_thresholds=(35, 37, 39, 41, 43),
    ),
    "Minimum heat index": HeatProduct(
        prefix="himin",
        label="Min heat index",
        description="Probability that the overnight heat index stays above the selected threshold on at least three consecutive days.",
        fixed_thresholds=(26, 28, 30, 32),
    ),
    "Hybrid heat (daytime)": HeatProduct(
        prefix="hybmax",
        label="Hybrid heat (day)",
        description="NOAA/CPC hybrid daytime product combining maximum temperature and heat index into one excessive-heat probability.",
        fixed_thresholds=(35, 37, 39, 41),
    ),
    "Hybrid heat (overnight)": HeatProduct(
        prefix="hybmin",
        label="Hybrid heat (night)",
        description="NOAA/CPC hybrid overnight product combining minimum temperature and heat index into one excessive-heat probability.",
        fixed_thresholds=(26, 28, 30, 32),
    ),
}


@dataclass(frozen=True)
class ContextProduct:
    """One scalar atmospheric-context field."""

    variable: str
    unit: str
    description: str = ""
    #: Views the NOAA server publishes directly; anything else is derived.
    views: tuple[str, ...] = field(default=("Average", "Anomaly", "Climatology"))


#: NOAA publishes each context field as a weekly mean (``...t.nc``) and an
#: anomaly (``...a.nc``); climatology is always derived as mean − anomaly.
CONTEXT_PRODUCTS: dict[str, ContextProduct] = {
    "Mean sea-level pressure": ContextProduct(
        variable="mslp",
        unit="hPa",
        description="Week-mean sea-level pressure.",
        views=("Average", "Anomaly"),
    ),
    "500-hPa geopotential height": ContextProduct(
        variable="hgt500",
        unit="gpm",
        description="Week-mean 500-hPa geopotential height.",
        views=("Average", "Anomaly"),
    ),
    "2-m air temperature": ContextProduct(
        variable="t2m",
        unit="°C",
        description="Week-mean 2-m air temperature.",
        views=("Average", "Anomaly"),
    ),
}

#: Wind levels offered in the sidebar (hPa; 10 means 10-m wind).
WIND_LEVELS = (925, 850, 700, 200, 10)


#: Filename suffix per published view: weekly mean (total) or anomaly.
VIEW_SUFFIXES = {"Average": "t", "Anomaly": "a"}


def wind_level_tag(level: int) -> str:
    return "10m" if level == 10 else f"{level}"


def wind_filenames(level: int, view: str, week: int) -> tuple[str, str]:
    """The documented (u, v) NetCDF filenames for a wind level and view.

    Example: 850-hPa week-1 mean wind is ``wk1_u850t.nc``/``wk1_v850t.nc``
    and its anomaly ``wk1_u850a.nc``/``wk1_v850a.nc``.
    """
    suffix = VIEW_SUFFIXES[view]
    tag = wind_level_tag(level)
    return (
        f"wk{week}_u{tag}{suffix}.nc",
        f"wk{week}_v{tag}{suffix}.nc",
    )


def context_filename(variable: str, view: str, week: int) -> str:
    """Documented context filename, e.g. ``wk1_mslpt.nc`` / ``wk1_mslpa.nc``."""
    return f"wk{week}_{variable}{VIEW_SUFFIXES[view]}.nc"


def context_url(filename: str) -> str:
    return NOAA_DATA_URL + filename
