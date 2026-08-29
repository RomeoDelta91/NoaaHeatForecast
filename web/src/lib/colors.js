// Colour ramps matching the matplotlib scales used by the Python dashboard,
// so the web maps read identically to the exported figures.

const RAMPS = {
  YlOrRd: ['#ffffcc', '#ffeda0', '#fed976', '#feb24c', '#fd8d3c', '#fc4e2a', '#e31a1c', '#bd0026', '#800026'],
  inferno: ['#000004', '#1b0c41', '#4a0c6b', '#781c6d', '#a52c60', '#cf4446', '#ed6925', '#fb9b06', '#fcffa4'],
  viridis: ['#440154', '#472d7b', '#3b528b', '#2c728e', '#21918c', '#28ae80', '#5ec962', '#addc30', '#fde725'],
  RdBu_r: ['#053061', '#2166ac', '#4393c3', '#92c5de', '#d1e5f0', '#f7f7f7', '#fddbc7', '#f4a582', '#d6604d', '#b2182b', '#67001f'],
};

function hexToRgb(hex) {
  const value = parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

const CACHE = new Map();
function rampRgb(name) {
  if (!CACHE.has(name)) CACHE.set(name, (RAMPS[name] || RAMPS.viridis).map(hexToRgb));
  return CACHE.get(name);
}

/** Sample a ramp at t in [0,1] with linear interpolation between stops. */
export function sampleRamp(name, t) {
  const stops = rampRgb(name);
  if (!Number.isFinite(t)) return null;
  const clamped = Math.min(1, Math.max(0, t));
  const scaled = clamped * (stops.length - 1);
  const index = Math.min(stops.length - 2, Math.floor(scaled));
  const fraction = scaled - index;
  const [r1, g1, b1] = stops[index];
  const [r2, g2, b2] = stops[index + 1];
  const mix = (a, b) => Math.round(a + (b - a) * fraction);
  return `rgb(${mix(r1, r2)},${mix(g1, g2)},${mix(b1, b2)})`;
}

/** Build a value -> css colour function for a fixed domain. */
export function makeScale(name, min, max) {
  const span = max - min || 1;
  return (value) => (Number.isFinite(value) ? sampleRamp(name, (value - min) / span) : null);
}

/** Evenly spaced tick values for a colour bar. */
export function ticks(min, max, count = 5) {
  return Array.from({ length: count }, (_, i) => min + ((max - min) * i) / (count - 1));
}
