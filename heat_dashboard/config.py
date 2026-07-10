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

#: Percentile exceedance thresholds offered in the sidebar.
PERCENTILE_THRESHOLDS = (75, 85, 90, 95)

#: Root of the NOAA/CPC International Desks GEFS guidance served over HTTPS.
NOAA_BASE_URL = "https://ftp.cpc.ncep.noaa.gov/international/gefs_heat"

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
        """NetCDF filename for a fixed (°C) or percentile threshold.

        Fixed thresholds are always below 50 °C and percentiles are always
        75 or higher, so the magnitude alone identifies the threshold type.
        """
        if threshold >= 50:
            return f"{self.prefix}_p{threshold:02d}_wk{week}.nc"
        return f"{self.prefix}_ge{threshold:02d}c_wk{week}.nc"

    def climatology_filename(self, week: int, percentile: int) -> str:
        return f"{self.prefix}_p{percentile:02d}_climo_wk{week}.nc"

    def url(self, week: int, threshold: int) -> str:
        return f"{NOAA_BASE_URL}/wk{week}/{self.filename(week, threshold)}"

    def climatology_url(self, week: int, percentile: int) -> str:
        return f"{NOAA_BASE_URL}/wk{week}/{self.climatology_filename(week, percentile)}"


HEAT_PRODUCTS: dict[str, HeatProduct] = {
    "Maximum temperature (Tmax)": HeatProduct(
        prefix="tmax",
        label="Tmax",
        description="Probability that daily maximum 2-m temperature exceeds the selected threshold on at least three consecutive days.",
        fixed_thresholds=(30, 32, 35, 38, 41),
    ),
    "Minimum temperature (Tmin)": HeatProduct(
        prefix="tmin",
        label="Tmin",
        description="Probability that daily minimum 2-m temperature stays above the selected threshold on at least three consecutive days — warm nights limit overnight recovery.",
        fixed_thresholds=(21, 24, 26, 27, 29),
    ),
    "Maximum heat index": HeatProduct(
        prefix="himax",
        label="Max heat index",
        description="Probability that the daytime heat index (temperature and humidity combined) exceeds the selected threshold on at least three consecutive days.",
        fixed_thresholds=(32, 35, 38, 41, 43),
    ),
    "Minimum heat index": HeatProduct(
        prefix="himin",
        label="Min heat index",
        description="Probability that the overnight heat index stays above the selected threshold on at least three consecutive days.",
        fixed_thresholds=(24, 27, 29, 32),
    ),
    "Excessive heat (CPC hybrid)": HeatProduct(
        prefix="heat",
        label="Excessive heat",
        description="NOAA/CPC hybrid product that combines daytime maximum temperature and overnight minimum heat index into a single excessive-heat probability.",
        fixed_thresholds=(32, 35, 38, 41),
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


CONTEXT_PRODUCTS: dict[str, ContextProduct] = {
    "Mean sea-level pressure": ContextProduct(
        variable="mslp",
        unit="hPa",
        description="Week-mean sea-level pressure.",
    ),
    "500-hPa geopotential height": ContextProduct(
        variable="z500",
        unit="gpm",
        description="Week-mean 500-hPa geopotential height.",
    ),
    "2-m air temperature": ContextProduct(
        variable="t2m",
        unit="°C",
        description="Week-mean 2-m air temperature. Climatology is reconstructed as average minus anomaly.",
        views=("Average", "Anomaly"),
    ),
}

#: Wind levels offered in the sidebar (hPa; 10 means 10-m wind).
WIND_LEVELS = (925, 850, 700, 200, 10)


def wind_filenames(level: int, view: str, week: int) -> tuple[str, str]:
    """Return the (u, v) NetCDF filenames for a wind level and view."""
    suffix = {"Average": "avg", "Anomaly": "anom", "Climatology": "climo"}[view]
    tag = "10m" if level == 10 else f"{level}"
    return (
        f"uwnd{tag}_{suffix}_wk{week}.nc",
        f"vwnd{tag}_{suffix}_wk{week}.nc",
    )


def context_filename(variable: str, view: str, week: int) -> str:
    suffix = {"Average": "avg", "Anomaly": "anom", "Climatology": "climo"}[view]
    return f"{variable}_{suffix}_wk{week}.nc"


def context_url(filename: str) -> str:
    return f"{NOAA_BASE_URL}/context/{filename}"
