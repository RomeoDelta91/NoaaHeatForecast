// Equirectangular projection with a cos(latitude) correction on x, which
// reproduces the aspect ratio the matplotlib maps use.

export function makeProjection(extent) {
  const [west, east, south, north] = extent;
  const k = Math.max(Math.cos(((south + north) / 2) * (Math.PI / 180)), 0.2);
  return {
    k,
    width: (east - west) * k,
    height: north - south,
    x: (lon) => (lon - west) * k,
    y: (lat) => north - lat,
    extent,
  };
}

/** Turn a GeoJSON geometry into an SVG path string. */
export function geometryToPath(geometry, projection) {
  if (!geometry) return '';
  const rings = [];
  const collect = (coordinates, depth) => {
    if (depth === 1) rings.push(coordinates);
    else coordinates.forEach((child) => collect(child, depth - 1));
  };
  if (geometry.type === 'Polygon') collect(geometry.coordinates, 2);
  else if (geometry.type === 'MultiPolygon') collect(geometry.coordinates, 3);
  else return '';

  return rings
    .map((ring) => {
      const points = ring.map(([lon, lat]) => `${projection.x(lon).toFixed(4)},${projection.y(lat).toFixed(4)}`);
      return points.length ? `M${points.join('L')}Z` : '';
    })
    .join('');
}

/** Rough centroid of a geometry's largest ring, for label placement. */
export function labelPoint(geometry) {
  let best = null;
  let bestArea = -Infinity;
  const consider = (ring) => {
    let area = 0;
    let cx = 0;
    let cy = 0;
    for (let i = 0; i < ring.length - 1; i += 1) {
      const [x1, y1] = ring[i];
      const [x2, y2] = ring[i + 1];
      const cross = x1 * y2 - x2 * y1;
      area += cross;
      cx += (x1 + x2) * cross;
      cy += (y1 + y2) * cross;
    }
    area /= 2;
    if (Math.abs(area) > bestArea && area !== 0) {
      bestArea = Math.abs(area);
      best = [cx / (6 * area), cy / (6 * area)];
    }
  };
  const walk = (coordinates, depth) => {
    if (depth === 1) consider(coordinates);
    else coordinates.forEach((child) => walk(child, depth - 1));
  };
  if (geometry.type === 'Polygon') walk(geometry.coordinates, 2);
  else if (geometry.type === 'MultiPolygon') walk(geometry.coordinates, 3);
  return best;
}

/** Map extent for the selected district, or the full-country default. */
export function extentForDistrict(district, fallback, padding = 0.18) {
  if (!district?.bounds) return fallback;
  const [minx, miny, maxx, maxy] = district.bounds;
  return [minx - padding, maxx + padding, miny - padding, maxy + padding];
}

/** Crop a regional extent to a smaller buffer around Suriname. */
export function bufferedExtent(bounds, buffer) {
  const [west, east, south, north] = bounds;
  return [west - buffer, east + buffer, Math.max(-89, south - buffer), Math.min(89, north + buffer)];
}

/** Nice axis tick values inside [min, max]. */
export function axisTicks(min, max, target = 5) {
  const span = max - min;
  if (!(span > 0)) return [];
  const raw = span / target;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) || magnitude * 10;
  const first = Math.ceil(min / step) * step;
  const values = [];
  for (let value = first; value <= max + 1e-9; value += step) values.push(Number(value.toFixed(6)));
  return values;
}
