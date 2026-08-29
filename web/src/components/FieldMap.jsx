import { useEffect, useMemo, useRef, useState } from 'react';
import { geometryToPath, labelPoint, makeProjection, axisTicks } from '../lib/geo.js';

/**
 * Renders a gridded field as an image layer inside an SVG, with district
 * boundaries, stations and optional wind vectors drawn on top.
 *
 * The grid goes through an offscreen canvas rather than one rect per cell:
 * a regional field is 120x120, and 14k DOM nodes would stall the browser.
 * Pixelated scaling keeps the blocky look of the matplotlib originals, and
 * the single <image> node still serialises cleanly for PNG export.
 */
export default function FieldMap({
  field,
  grid,
  scale,
  extent,
  districts,
  districtGeoJson,
  selectedDistrict,
  showBoundaries = true,
  showLabels = true,
  showStations = false,
  stations = [],
  clip = false,
  title,
  unit = '%',
  wind = null,
  svgRef,
}) {
  const [hover, setHover] = useState(null);
  const canvasRef = useRef(document.createElement('canvas'));
  const [imageUrl, setImageUrl] = useState(null);

  const projection = useMemo(() => makeProjection(extent), [extent]);

  // Paint the grid into an offscreen canvas whenever the data or scale change.
  useEffect(() => {
    if (!field || !grid) return;
    const columns = grid.lon.length;
    const rows = grid.lat.length;
    const canvas = canvasRef.current;
    canvas.width = columns;
    canvas.height = rows;
    const context = canvas.getContext('2d');
    const image = context.createImageData(columns, rows);

    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        const source = row * columns + column;
        // Latitudes ascend in the data but descend down the image.
        const target = ((rows - 1 - row) * columns + column) * 4;
        const value = field[source];
        const visible = value !== null && Number.isFinite(value) && (!clip || grid.inCountry[source]);
        if (!visible) {
          image.data[target + 3] = 0;
          continue;
        }
        const colour = scale(value);
        const match = /rgb\((\d+),(\d+),(\d+)\)/.exec(colour || '');
        if (!match) {
          image.data[target + 3] = 0;
          continue;
        }
        image.data[target] = Number(match[1]);
        image.data[target + 1] = Number(match[2]);
        image.data[target + 2] = Number(match[3]);
        image.data[target + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
    setImageUrl(canvas.toDataURL('image/png'));
  }, [field, grid, scale, clip]);

  // The image spans cell edges, not centres.
  const imageBox = useMemo(() => {
    if (!grid) return null;
    const stepLon = grid.lon.length > 1 ? Math.abs(grid.lon[1] - grid.lon[0]) : 1;
    const stepLat = grid.lat.length > 1 ? Math.abs(grid.lat[1] - grid.lat[0]) : 1;
    const west = grid.lon[0] - stepLon / 2;
    const east = grid.lon[grid.lon.length - 1] + stepLon / 2;
    const north = grid.lat[grid.lat.length - 1] + stepLat / 2;
    const south = grid.lat[0] - stepLat / 2;
    return {
      x: projection.x(west),
      y: projection.y(north),
      width: projection.x(east) - projection.x(west),
      height: projection.y(south) - projection.y(north),
    };
  }, [grid, projection]);

  const paths = useMemo(() => {
    if (!districtGeoJson) return [];
    return districtGeoJson.features.map((feature) => ({
      name: feature.properties?.name ?? '',
      d: geometryToPath(feature.geometry, projection),
      label: labelPoint(feature.geometry),
    }));
  }, [districtGeoJson, projection]);

  const windVectors = useMemo(() => {
    if (!wind?.u || !grid) return [];
    const columns = grid.lon.length;
    const rows = grid.lat.length;
    const step = Math.max(1, Math.round(Math.max(columns, rows) / 20));
    const vectors = [];
    let maxSpeed = 0;
    for (let i = 0; i < wind.u.length; i += 1) {
      const speed = Math.hypot(wind.u[i] ?? 0, wind.v[i] ?? 0);
      if (Number.isFinite(speed) && speed > maxSpeed) maxSpeed = speed;
    }
    const reference = maxSpeed || 1;
    const arrowLength = ((projection.extent[1] - projection.extent[0]) / 26) * projection.k;
    for (let row = 0; row < rows; row += step) {
      for (let column = 0; column < columns; column += step) {
        const index = row * columns + column;
        const u = wind.u[index];
        const v = wind.v[index];
        if (!Number.isFinite(u) || !Number.isFinite(v)) continue;
        const speed = Math.hypot(u, v);
        const length = (speed / reference) * arrowLength;
        if (!(length > 0.001)) continue;
        vectors.push({
          x: projection.x(grid.lon[column]),
          y: projection.y(grid.lat[row]),
          dx: (u / speed) * length,
          dy: -(v / speed) * length,
        });
      }
    }
    return vectors;
  }, [wind, grid, projection]);

  function handleMove(event) {
    const svg = event.currentTarget;
    const rect = svg.getBoundingClientRect();
    const [west, east, south, north] = projection.extent;
    const fractionX = (event.clientX - rect.left) / rect.width;
    const fractionY = (event.clientY - rect.top) / rect.height;
    const lon = west + fractionX * (east - west);
    const lat = north - fractionY * (north - south);
    if (!grid) return;

    let bestRow = -1;
    let bestColumn = -1;
    let bestLat = Infinity;
    let bestLon = Infinity;
    grid.lat.forEach((value, index) => {
      const distance = Math.abs(value - lat);
      if (distance < bestLat) { bestLat = distance; bestRow = index; }
    });
    grid.lon.forEach((value, index) => {
      const distance = Math.abs(value - lon);
      if (distance < bestLon) { bestLon = distance; bestColumn = index; }
    });
    if (bestRow < 0 || bestColumn < 0) return setHover(null);

    const index = bestRow * grid.lon.length + bestColumn;
    const value = field[index];
    if (value === null || !Number.isFinite(value) || (clip && !grid.inCountry[index])) return setHover(null);
    const districtIndex = grid.districtIndex[index];
    return setHover({
      lon: grid.lon[bestColumn],
      lat: grid.lat[bestRow],
      value,
      district: districtIndex >= 0 ? districts?.[districtIndex]?.name : null,
      screenX: fractionX,
      screenY: fractionY,
    });
  }

  const [west, east, south, north] = projection.extent;
  const lonTicks = axisTicks(west, east, 5);
  const latTicks = axisTicks(south, north, 5);
  const pad = { left: 0.06 * projection.width, bottom: 0.06 * projection.height, top: 0.075 * projection.height, right: 0.02 * projection.width };
  const viewBox = `${-pad.left} ${-pad.top} ${projection.width + pad.left + pad.right} ${projection.height + pad.top + pad.bottom}`;
  const fontSize = projection.height / 34;

  return (
    <div className="map-wrapper">
      <svg
        ref={svgRef}
        className="field-map"
        viewBox={viewBox}
        xmlns="http://www.w3.org/2000/svg"
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={title}
      >
        <rect x={-pad.left} y={-pad.top} width={projection.width + pad.left + pad.right} height={projection.height + pad.top + pad.bottom} fill="#ffffff" />
        {title && (
          <text
            className="map-title"
            x={-pad.left}
            y={-pad.top * 0.3}
            // Long titles shrink to stay inside the viewBox. 0.62em is a
            // conservative average glyph width for this bold sans stack.
            fontSize={Math.min(
              fontSize * 1.05,
              (projection.width + pad.left + pad.right) / Math.max(title.length, 1) / 0.62,
            )}
            fontWeight="700"
            fill="#111827"
          >
            {title}
          </text>
        )}

        <clipPath id="plot-area">
          <rect x={0} y={0} width={projection.width} height={projection.height} />
        </clipPath>
        <rect x={0} y={0} width={projection.width} height={projection.height} fill="#f8fafc" />

        <g clipPath="url(#plot-area)">
          {imageUrl && imageBox && (
            <image
              href={imageUrl}
              x={imageBox.x}
              y={imageBox.y}
              width={imageBox.width}
              height={imageBox.height}
              preserveAspectRatio="none"
              style={{ imageRendering: 'pixelated' }}
            />
          )}

          {lonTicks.map((value) => (
            <line key={`gx${value}`} x1={projection.x(value)} y1={0} x2={projection.x(value)} y2={projection.height} stroke="#e5e7eb" strokeWidth={projection.height / 900} />
          ))}
          {latTicks.map((value) => (
            <line key={`gy${value}`} x1={0} y1={projection.y(value)} x2={projection.width} y2={projection.y(value)} stroke="#e5e7eb" strokeWidth={projection.height / 900} />
          ))}

          {windVectors.map((vector, index) => (
            <line
              key={`w${index}`}
              x1={vector.x - vector.dx / 2}
              y1={vector.y - vector.dy / 2}
              x2={vector.x + vector.dx / 2}
              y2={vector.y + vector.dy / 2}
              stroke="#111827"
              strokeWidth={projection.height / 600}
              markerEnd="url(#wind-arrow)"
            />
          ))}

          {paths.map((path) => {
            const isSelected = path.name === selectedDistrict;
            if (!showBoundaries && !isSelected) return null;
            return (
              <path
                key={path.name}
                d={path.d}
                fill="none"
                stroke={isSelected ? '#1d4ed8' : '#374151'}
                strokeWidth={(isSelected ? 2.1 : 0.9) * (projection.height / 700)}
                strokeLinejoin="round"
              />
            );
          })}

          {showStations && stations.map((station) => (
            <g key={station.name}>
              <path
                d={`M${projection.x(station.lon)},${projection.y(station.lat) - fontSize * 0.34}l${fontSize * 0.34},${fontSize * 0.6}h${-fontSize * 0.68}Z`}
                fill="#fbbf24"
                stroke="#0f172a"
                strokeWidth={projection.height / 1400}
              />
              <text x={projection.x(station.lon) + fontSize * 0.4} y={projection.y(station.lat) - fontSize * 0.3} fontSize={fontSize * 0.58} fill="#334155">{station.name}</text>
            </g>
          ))}

          {showLabels && paths.filter((path) => path.label).map((path) => (
            <text
              key={`l${path.name}`}
              x={projection.x(path.label[0])}
              y={projection.y(path.label[1])}
              fontSize={fontSize * 0.72}
              textAnchor="middle"
              fill="#111827"
              stroke="#ffffff"
              strokeWidth={fontSize * 0.12}
              paintOrder="stroke"
            >
              {path.name}
            </text>
          ))}
        </g>

        <defs>
          <marker id="wind-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
            <path d="M0,1L9,5L0,9z" fill="#111827" />
          </marker>
        </defs>

        <rect x={0} y={0} width={projection.width} height={projection.height} fill="none" stroke="#111827" strokeWidth={projection.height / 500} />

        {lonTicks.map((value) => (
          <text key={`tx${value}`} x={projection.x(value)} y={projection.height + pad.bottom * 0.62} fontSize={fontSize * 0.72} textAnchor="middle" fill="#374151">
            {value.toFixed(0)}°
          </text>
        ))}
        {latTicks.map((value) => (
          <text key={`ty${value}`} x={-pad.left * 0.12} y={projection.y(value) + fontSize * 0.25} fontSize={fontSize * 0.72} textAnchor="end" fill="#374151">
            {value.toFixed(0)}°
          </text>
        ))}
      </svg>

      {hover && (
        <div className="map-tooltip" style={{ left: `${hover.screenX * 100}%`, top: `${hover.screenY * 100}%` }}>
          <strong>{hover.value.toFixed(1)}{unit === '%' ? '%' : ` ${unit}`}</strong>
          {hover.district && <span>{hover.district}</span>}
          <span className="muted">{hover.lat.toFixed(2)}°, {hover.lon.toFixed(2)}°</span>
        </div>
      )}
    </div>
  );
}
