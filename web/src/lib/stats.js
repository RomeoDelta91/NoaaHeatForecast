// District statistics, recomputed in the browser.
//
// The build step bakes a district index into every grid, so changing the
// operational risk cutoff is instant and needs no extra download. This
// mirrors heat_dashboard.geo.district_statistics, including the
// nearest-grid fallback for districts too small to contain a cell centre.

/** Index of the grid cell whose centre is closest to (lon, lat). */
function nearestCell(grid, lon, lat) {
  let best = -1;
  let bestDistance = Infinity;
  for (let row = 0; row < grid.lat.length; row += 1) {
    for (let column = 0; column < grid.lon.length; column += 1) {
      const dLat = grid.lat[row] - lat;
      const dLon = grid.lon[column] - lon;
      const distance = dLat * dLat + dLon * dLon;
      if (distance < bestDistance) {
        bestDistance = distance;
        best = row * grid.lon.length + column;
      }
    }
  }
  return best;
}

/**
 * Per-district probability summary, sorted by descending mean.
 * `districts` is the manifest list (name, areaKm2, point).
 */
export function districtStatistics(values, grid, districts, cutoff) {
  const buckets = districts.map(() => []);
  const riskArea = districts.map(() => 0);
  const totalCellArea = districts.map(() => 0);

  for (let i = 0; i < values.length; i += 1) {
    const position = grid.districtIndex[i];
    if (position < 0) continue;
    const value = values[i];
    if (value === null || !Number.isFinite(value)) continue;
    buckets[position].push(value);
    const cellArea = grid.cellAreaKm2[i] ?? 0;
    totalCellArea[position] += cellArea;
    if (value >= cutoff) riskArea[position] += cellArea;
  }

  const rows = districts.map((district, position) => {
    const cells = buckets[position];
    let mean;
    let max;
    let riskShare;
    let estimate = false;

    if (cells.length) {
      mean = cells.reduce((sum, value) => sum + value, 0) / cells.length;
      max = Math.max(...cells);
      riskShare = totalCellArea[position] ? riskArea[position] / totalCellArea[position] : 0;
    } else {
      // Too small for a grid-cell centre: fall back to the nearest point.
      estimate = true;
      const index = nearestCell(grid, district.point[0], district.point[1]);
      const value = index >= 0 ? values[index] : null;
      mean = Number.isFinite(value) ? value : NaN;
      max = mean;
      riskShare = Number.isFinite(mean) && mean >= cutoff ? 1 : 0;
    }

    return {
      district: district.name,
      mean,
      max,
      riskAreaKm2: riskShare * district.areaKm2,
      areaKm2: district.areaKm2,
      estimate,
    };
  });

  return rows.sort((a, b) => (Number.isFinite(b.mean) ? b.mean : -1) - (Number.isFinite(a.mean) ? a.mean : -1));
}

/** Headline numbers for the KPI row. */
export function summarise(rows, values, grid, clip) {
  let max = -Infinity;
  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    if (value === null || !Number.isFinite(value)) continue;
    if (clip && !grid.inCountry[i]) continue;
    if (value > max) max = value;
  }
  const totalRisk = rows.reduce((sum, row) => sum + (row.riskAreaKm2 || 0), 0);
  const totalArea = rows.reduce((sum, row) => sum + row.areaKm2, 0);
  return {
    highest: rows[0],
    maxProbability: Number.isFinite(max) ? max : NaN,
    riskAreaKm2: totalRisk,
    areaShare: totalArea ? (totalRisk / totalArea) * 100 : NaN,
  };
}

/** Min/max of a value array, ignoring nulls and optionally clipping. */
export function extent(values, grid, clip = false) {
  let min = Infinity;
  let max = -Infinity;
  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    if (value === null || !Number.isFinite(value)) continue;
    if (clip && grid && !grid.inCountry[i]) continue;
    if (value < min) min = value;
    if (value > max) max = value;
  }
  return Number.isFinite(min) ? [min, max] : [0, 1];
}

/** "11–17 Jul 2026", matching the Streamlit footer formatting. */
export function formatPeriod(meta) {
  if (!meta?.valid_start || !meta?.valid_end) return 'Unavailable';
  const start = new Date(`${meta.valid_start}T00:00:00Z`);
  const end = new Date(`${meta.valid_end}T00:00:00Z`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return 'Unavailable';
  const options = { timeZone: 'UTC', month: 'short' };
  const month = (date) => date.toLocaleString('en-GB', options);
  if (start.getUTCFullYear() === end.getUTCFullYear() && start.getUTCMonth() === end.getUTCMonth()) {
    return `${start.getUTCDate()}–${end.getUTCDate()} ${month(end)} ${end.getUTCFullYear()}`;
  }
  if (start.getUTCFullYear() === end.getUTCFullYear()) {
    return `${start.getUTCDate()} ${month(start)} – ${end.getUTCDate()} ${month(end)} ${end.getUTCFullYear()}`;
  }
  return `${start.getUTCDate()} ${month(start)} ${start.getUTCFullYear()} – ${end.getUTCDate()} ${month(end)} ${end.getUTCFullYear()}`;
}

export const toCsv = (headers, rows) =>
  [headers.join(','), ...rows.map((row) => row.map((cell) => (typeof cell === 'string' && cell.includes(',') ? `"${cell}"` : cell)).join(','))].join('\n');
