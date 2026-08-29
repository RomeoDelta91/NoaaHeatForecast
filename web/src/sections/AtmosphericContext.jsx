import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import FieldMap from '../components/FieldMap.jsx';
import { ColorBar, Field, MetricCard, RadioGroup } from '../components/Pieces.jsx';
import { contextKey, loadField, windKey } from '../lib/data.js';
import { makeScale } from '../lib/colors.js';
import { downloadSvgAsPng } from '../lib/download.js';
import { bufferedExtent } from '../lib/geo.js';
import { extent as valueExtent, formatPeriod } from '../lib/stats.js';

export default function AtmosphericContext({ manifest, districtGeoJson, week, controls, setControls, sidebarMount }) {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const svgRef = useRef(null);

  const isWind = controls.family === 'Wind';
  const contextProduct = useMemo(
    () => manifest.contextProducts.find((item) => item.name === controls.contextProduct) ?? manifest.contextProducts[0],
    [manifest, controls.contextProduct],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const key = isWind ? windKey(controls.level, week, controls.view) : contextKey(contextProduct.variable, week, controls.view);
    loadField(manifest, key)
      .then((result) => { if (!cancelled) { setPayload(result); setLoading(false); } })
      .catch((problem) => { if (!cancelled) { setError(problem.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [manifest, isWind, controls.level, controls.view, contextProduct.variable, week]);

  const mapExtent = useMemo(() => bufferedExtent(manifest.bounds, controls.buffer), [manifest.bounds, controls.buffer]);
  const [min, max] = useMemo(() => (payload ? valueExtent(payload.values) : [0, 1]), [payload]);
  const isAnomaly = controls.view === 'Anomaly';
  const limit = Math.max(Math.abs(min), Math.abs(max)) || 1;
  const ramp = isAnomaly ? 'RdBu_r' : 'viridis';
  const domain = isAnomaly ? [-limit, limit] : [min, max];
  const scale = useMemo(() => makeScale(ramp, domain[0], domain[1]), [ramp, domain[0], domain[1]]);

  const unit = payload?.unit ?? (isWind ? 'm/s' : contextProduct.unit);
  const levelLabel = controls.level === 10 ? '10-m' : `${controls.level}-hPa`;
  const title = isWind
    ? `GEFS Week ${week}: ${levelLabel} wind speed and direction — ${controls.view}`
    : `GEFS Week ${week}: ${contextProduct.name} — ${controls.view}`;

  const sidebar = (
    <div className="sidebar-section">
        <Field label="Product family">
          <select value={controls.family} onChange={(event) => setControls({ ...controls, family: event.target.value })}>
            <option>Scalar field</option>
            <option>Wind</option>
          </select>
        </Field>

        {isWind ? (
          <Field label="Wind level">
            <select value={controls.level} onChange={(event) => setControls({ ...controls, level: Number(event.target.value) })}>
              {manifest.windLevels.map((level) => (
                <option key={level} value={level}>{level === 10 ? '10 m' : `${level} hPa`}</option>
              ))}
            </select>
          </Field>
        ) : (
          <Field label="Atmospheric product">
            <select value={contextProduct.name} onChange={(event) => setControls({ ...controls, contextProduct: event.target.value })}>
              {manifest.contextProducts.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
            </select>
          </Field>
        )}

        <Field label="Display">
          <RadioGroup name="view" options={manifest.views} value={controls.view} onChange={(value) => setControls({ ...controls, view: value })} />
        </Field>
        {controls.view === 'Climatology' && <p className="sidebar-note">Climatology is reconstructed as weekly mean minus anomaly.</p>}

        <Field label={`Regional context buffer: ${controls.buffer}°`} hint="Adds degrees around Suriname for synoptic context.">
          <input
            type="range"
            min={0}
            max={manifest.contextBuffer}
            step={1}
            value={controls.buffer}
            onChange={(event) => setControls({ ...controls, buffer: Number(event.target.value) })}
          />
        </Field>
    </div>
  );

  return (
    <>
      {sidebarMount && createPortal(sidebar, sidebarMount)}

      <div className="content">
        {error && <div className="notice notice-error">{error}</div>}
        {loading && !payload && <div className="notice">Loading field…</div>}

        {payload && (
          <>
            <span className={`chip ${payload.live ? 'chip-live' : 'chip-demo'}`}>
              {payload.live ? 'Live NOAA/CPC' : 'Demo data'}
            </span>

            <div className="metric-row metric-row-3">
              <MetricCard label="Valid period" value={formatPeriod(payload.meta)} delta={`Week ${week}`} />
              <MetricCard label="Field minimum" value={`${min.toFixed(1)} ${unit}`} />
              <MetricCard label="Field maximum" value={`${max.toFixed(1)} ${unit}`} />
            </div>

            <section className="panel">
              <FieldMap
                svgRef={svgRef}
                field={payload.values}
                grid={payload.grid}
                scale={scale}
                extent={mapExtent}
                districts={manifest.districts}
                districtGeoJson={districtGeoJson}
                showBoundaries={false}
                showLabels={false}
                title={title}
                unit={unit}
                wind={isWind ? { u: payload.u, v: payload.v } : null}
              />
              <ColorBar ramp={ramp} min={domain[0]} max={domain[1]} label={isWind ? 'Wind speed' : contextProduct.name} unit={unit} />
              <button className="button" onClick={() => downloadSvgAsPng(svgRef.current, `suriname_context_week${week}.png`)}>
                Download map as PNG
              </button>
            </section>

            <details className="panel details">
              <summary>Data details</summary>
              <pre>{JSON.stringify(payload.meta, null, 2)}</pre>
            </details>
          </>
        )}
      </div>
    </>
  );
}
