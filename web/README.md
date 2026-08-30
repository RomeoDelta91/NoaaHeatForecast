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

## Publish it on your own hosting, automatically

You should never have to rebuild and upload by hand. Pick one of these two
setups; both refresh twice a day on GitHub's servers, which — unlike a
browser — can reach `ftp.cpc.ncep.noaa.gov`.

### A. GitHub uploads to your hosting over FTPS (recommended)

`.github/workflows/deploy-to-hosting.yml` downloads the NOAA data, builds
the site, and uploads it to your web space. Add four repository secrets
once, under *Settings → Secrets and variables → Actions*:

| Secret | Value |
| --- | --- |
| `FTP_SERVER` | hostname only, e.g. `ftp.your-domain.com` (no `ftp://`) |
| `FTP_USERNAME` | the FTP/SFTP account |
| `FTP_PASSWORD` | its password |
| `FTP_DIR` | target folder **with a trailing slash**, e.g. `public_html/heat-dashboard/` |

If your host refuses FTPS, add a repository *variable* `FTP_PROTOCOL` set
to `ftp` or `sftp`. Then run the workflow once by hand (*Actions → Deploy
dashboard to web hosting → Run workflow*) to confirm it connects, and link
Elementor to `https://your-domain/heat-dashboard/`. After that it maintains
itself.

The upload is incremental — it keeps a small sync-state file on the server
and sends only what changed, so a routine refresh moves a few hundred
kilobytes. It never touches anything else in your hosting account.

### B. Upload the page once, let the data come from GitHub Pages

If you would rather not store hosting credentials on GitHub, build the site
so it reads its data from an absolute URL:

```bash
cd web
VITE_DATA_BASE_URL=https://<your-github-user>.github.io/NoaaHeatForecast/data/ npm run build
```

Upload `web/dist/index.html` and `web/dist/assets/` to your hosting once —
no `data/` folder needed. Enable *Settings → Pages → Source: GitHub
Actions*, and `publish-dashboard.yml` keeps that data URL fresh twice a
day. GitHub Pages sends `Access-Control-Allow-Origin: *`, so the browser is
allowed to read it from your domain. The trade-off is that page loads now
depend on GitHub Pages being reachable.

### Manual, if you ever need it

```bash
python scripts/build_web_data.py
cd web && npm run build
```

Then upload the contents of `web/dist/`. No PHP, database or Node runtime
is required on the server.

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
