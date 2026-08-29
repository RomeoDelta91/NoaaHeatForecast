# Suriname Heat Forecast Dashboard — web version

A static React build of the Streamlit dashboard, meant to be linked from an
existing site (for example an Elementor button on WordPress).

## Why the data is pre-generated

A browser cannot download the NOAA products itself: `ftp.cpc.ncep.noaa.gov`
sends no CORS headers, and the files are NetCDF4 (HDF5 underneath), which
would need about a megabyte of WebAssembly to decode. So the Python
pipeline in `heat_dashboard/` runs server-side — locally or in GitHub
Actions — and writes small JSON files that the site fetches on demand.

The Suriname subset is tiny, so this is cheap: a heat field is ~4 KB, and
the first page view loads roughly 200 KB in total. Each grid also carries a
baked-in district index, which lets the browser recompute district
statistics instantly whenever the risk cutoff slider moves.

## Build it

```bash
# 1. Generate the data (needs the Python requirements installed)
python scripts/build_web_data.py           # live NOAA, demo fallback per field
python scripts/build_web_data.py --demo    # demo data only, no network

# 2. Build the site
cd web
npm install
npm run build      # writes web/dist/
npm run dev        # or run a live dev server on :5173
```

`web/dist/` is a self-contained folder — HTML, one JS bundle, one CSS file
and the `data/` directory. Asset paths are relative, so it works from any
URL depth.

## Publish it

**GitHub Pages (automatic).** `.github/workflows/publish-dashboard.yml`
rebuilds the data and redeploys twice a day. Enable it once under
*Settings → Pages → Source: GitHub Actions*. The workflow runs on GitHub's
runners, which can reach NOAA, so the published site shows live guidance.

**Your own hosting.** Upload the contents of `web/dist/` to any folder that
your web server serves, for example `public_html/heat-dashboard/`, and link
to `https://your-domain/heat-dashboard/`. No PHP, database or Node runtime
is needed. To refresh the forecast, re-run the two build steps and re-upload
`dist/` (or just its `data/` folder).

**Inside a WordPress page.** Either link straight to the URL, or embed it
with an Elementor HTML widget:

```html
<iframe src="https://your-domain/heat-dashboard/" title="Suriname Heat Forecast Dashboard"
        style="width:100%;height:1500px;border:0"></iframe>
```

A plain link is usually the better experience: the dashboard is tall and
brings its own responsive layout.

## Data freshness

The footer states when the dataset was generated and how many fields are
live versus demo, so a stale or failed refresh is visible on the page
rather than silent. Individual fields that could not be downloaded fall
back to demo data and are labelled "Demo data" in the header chip.
