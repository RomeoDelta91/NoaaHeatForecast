# Suriname Heat Forecast Dashboard

A Streamlit dashboard that converts the supplied NOAA/CPC shell-script workflow into a deployable pure-Python application.

## What is included

- Live Week-1 and Week-2 NOAA/CPC GEFS excessive-heat probability products.
- Tmax, Tmin, maximum/minimum Heat Index, and NOAA/CPC hybrid heat products.
- Fixed-temperature and percentile exceedance thresholds for at least three consecutive days.
- Official Suriname district boundaries, district statistics, station markers, clipping, and district zoom.
- Atmospheric context maps for MSLP, 500-hPa geopotential height, 2-m temperature, and 10-m/925/850/700/200-hPa winds.
- PNG, CSV, and processed NetCDF downloads.
- Demo mode and automatic demo fallback when the NOAA server cannot be reached.

## Why XCast is no longer required

The original scripts used `xc.regrid()` primarily to put the NOAA field on the Caribbean-mask grid. This app does not require that intermediate mask. Xarray reads and normalizes the NOAA grid directly, while Shapely clips the field with the actual Suriname boundary and calculates district statistics. The runtime therefore uses only pip-installable packages.

## Repository structure

```text
app.py                         Streamlit entrypoint
heat_dashboard/                Download, geospatial, demo and plotting modules
data/boundaries/               Web-ready EPSG:4326 district GeoJSON
data/shapefiles/               Original .shp/.shx/.dbf/.prj files
requirements.txt               Streamlit Cloud Python dependencies
.streamlit/config.toml         Theme and server settings
tests/                         Lightweight local tests
```

## District boundaries

`data/boundaries/suriname_districts.geojson` is derived from the official
`data/shapefiles/DistriktenSuriname` shapefile (UTM Zone 21N), reprojected
to EPSG:4326 and lightly simplified (~50 m tolerance) for the web. The app
reads only the GeoJSON at runtime, so no GDAL/GeoPandas dependency is
needed. To regenerate it after updating the shapefiles, reproject each
feature to WGS84 and write a FeatureCollection with a `name` property per
district.

## NOAA endpoint configuration

The dashboard reads NOAA/CPC's pre-processed Week-1/Week-2 GEFS products
(weekly means, anomalies, and heat-exceedance probabilities — not raw
ensemble members) from

```text
https://ftp.cpc.ncep.noaa.gov/International/PREPARE_africa/subseasonal/realtime/data/
```

Heat filenames follow `wk{week}_{product}{threshold}_c3.nc`, where the
product is `tmax`, `tmin`, `himax`, `himin`, `hybmax`, or `hybmin`, the
threshold is a fixed limit (`35`) or percentile (`90`), and `c3` means the
threshold must hold for at least three consecutive days — for example
`wk1_tmax35_c3.nc` or `wk2_himax35_c3.nc`. The percentile climatologies
follow `wk{week}_{product}climo{percentile}.nc` (e.g. `wk1_tmaxclimo90.nc`).

The atmospheric-context fields use `wk{week}_{variable}{view}.nc`, where
the view suffix is `t` for the weekly mean (total) and `a` for the anomaly
— for example `wk1_mslpt.nc`/`wk1_mslpa.nc` for sea-level pressure,
`wk1_hgt500t.nc` for 500-hPa height, and `wk1_u850t.nc`/`wk1_v850t.nc` for
the 850-hPa wind components. No climatology files are published for these
fields; the app reconstructs climatology as weekly mean minus anomaly.

All URL templates live in `heat_dashboard/config.py`. When an exact
filename returns 404, the loader downloads the directory listings named in
`HEAT_LISTING_DIRECTORIES`/`CONTEXT_LISTING_DIRECTORIES`, extracts the
`.nc` links, and picks the file whose name matches the requested product,
week, and threshold — so the app survives NOAA renaming files or moving
them between the listed directories. Whenever every lookup fails the app
shows a warning listing the URLs it tried and falls back to demo data, so
the interface keeps working while paths are stale.

## Run locally

Use Python 3.12.

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Create a new GitHub repository.
2. Upload every file and folder from this project; keep the folder structure unchanged.
3. In Streamlit Community Cloud, choose **Create app** and select the repository.
4. Set the main file path to `app.py`.
5. Select Python 3.12 when the deployment interface offers a Python-version choice.
6. Deploy.

No passwords or Streamlit secrets are required. The app downloads public NOAA/CPC files over HTTPS.

## Operational notes

- The NOAA endpoint and individual products must be reachable from Streamlit Community Cloud.
- The app downloads only the selected product, rather than generating all maps on every rerun.
- Downloads are cached for six hours.
- Small districts that do not contain a NOAA grid-cell centre use the nearest grid point and are marked as estimates.
- District area-at-risk values are approximate because the source products are gridded and relatively coarse.
- This application is a visualization and decision-support tool, not an official warning product.

## Acknowledgement

The supplied reference shell workflow identifies Endalkachew Bekele, NOAA/CPC/International Desks (October 2024) as its author. See `THIRD_PARTY_NOTICE.md`.
