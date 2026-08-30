// Fetches the pre-generated JSON dataset. Everything is static, so a simple
// in-memory cache is enough: each field is downloaded at most once per visit.

/**
 * Where the JSON dataset lives.
 *
 * By default it sits next to index.html, so the whole site is one folder.
 * Setting VITE_DATA_BASE_URL at build time points the app at an absolute
 * URL instead — useful when the page is uploaded once to your own hosting
 * while the data keeps refreshing somewhere else (that host must send
 * Access-Control-Allow-Origin; GitHub Pages does).
 */
function resolveBase() {
  const configured = (import.meta.env.VITE_DATA_BASE_URL || '').trim();
  if (configured) return configured.endsWith('/') ? configured : `${configured}/`;
  const prefix = import.meta.env.BASE_URL || './';
  return `${prefix.endsWith('/') ? prefix : `${prefix}/`}data/`;
}

const BASE = resolveBase();
const cache = new Map();

async function getJson(path) {
  if (!cache.has(path)) {
    cache.set(
      path,
      fetch(`${BASE}${path}`, { cache: 'no-cache' }).then((response) => {
        if (!response.ok) throw new Error(`Could not load ${path} (HTTP ${response.status})`);
        return response.json();
      }).catch((error) => {
        cache.delete(path); // let a later attempt retry
        throw error;
      }),
    );
  }
  return cache.get(path);
}

export const loadManifest = () => getJson('index.json');
export const loadDistricts = () => getJson('districts.geojson');
export const loadGrid = (gridId) => getJson(`grids/${gridId}.json`);

/** Resolve one field plus its grid, given a manifest key. */
export async function loadField(manifest, key) {
  const entry = manifest.fields[key];
  if (!entry) throw new Error(`This combination is not in the published dataset (${key}).`);
  const field = await getJson(entry.path);
  const grid = await loadGrid(field.gridId);
  return { ...field, grid, live: entry.live };
}

export const hasField = (manifest, key) => Boolean(manifest.fields[key]);

export const heatKey = (prefix, week, threshold) => `heat/${prefix}/${week}/${threshold}`;
export const climatologyKey = (prefix, week, percentile) => `climatology/${prefix}/${week}/${percentile}`;
export const contextKey = (variable, week, view) => `context/${variable}/${week}/${view}`;
export const windKey = (level, week, view) => `wind/${level}/${week}/${view}`;
