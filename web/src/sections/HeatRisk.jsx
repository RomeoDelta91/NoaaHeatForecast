import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import FieldMap from '../components/FieldMap.jsx';
import { ColorBar, ComparisonChart, DistrictTable, Field, MetricCard, RadioGroup, Toggle } from '../components/Pieces.jsx';
import { climatologyKey, hasField, heatKey, loadField } from '../lib/data.js';
import { makeScale } from '../lib/colors.js';
import { downloadSvgAsPng, downloadText } from '../lib/download.js';
import { extentForDistrict } from '../lib/geo.js';
import { districtStatistics, extent as valueExtent, formatPeriod, summarise, toCsv } from '../lib/stats.js';

const ALL = 'All districts';

export default function HeatRisk({ manifest, districtGeoJson, week, controls, setControls, sidebarMount }) {
  const [payload, setPayload] = useState(null);
  const [climatology, setClimatology] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const svgRef = useRef(null);

  const product = useMemo(
    () => manifest.heatProducts.find((item) => item.name === controls.productName) ?? manifest.heatProducts[0],
    [manifest, controls.productName],
  );

  const thresholds = controls.thresholdType === 'Fixed temperature' ? product.fixedThresholds : manifest.percentiles;
  const threshold = thresholds.includes(controls.threshold)
    ? controls.threshold
    : thresholds[controls.thresholdType === 'Fixed temperature' ? Math.max(thresholds.length - 2, 0) : thresholds.indexOf(90) >= 0 ? thresholds.indexOf(90) : 0];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadField(manifest, heatKey(product.prefix, week, threshold))
      .then((result) => { if (!cancelled) { setPayload(result); setLoading(false); } })
      .catch((problem) => { if (!cancelled) { setError(problem.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [manifest, product.prefix, week, threshold]);

  const wantsClimatology = controls.showClimatology && controls.thresholdType === 'Percentile' && product.supportsClimatology;
  useEffect(() => {
    let cancelled = false;
    if (!wantsClimatology) { setClimatology(null); return undefined; }
    const key = climatologyKey(product.prefix, week, threshold);
    if (!hasField(manifest, key)) { setClimatology('missing'); return undefined; }
    loadField(manifest, key).then((result) => { if (!cancelled) setClimatology(result); }).catch(() => { if (!cancelled) setClimatology('missing'); });
    return () => { cancelled = true; };
  }, [manifest, product.prefix, week, threshold, wantsClimatology]);

  const stats = useMemo(() => {
    if (!payload) return null;
    return districtStatistics(payload.values, payload.grid, manifest.districts, controls.cutoff);
  }, [payload, manifest.districts, controls.cutoff]);

  const summary = useMemo(() => {
    if (!payload || !stats) return null;
    return summarise(stats, payload.values, payload.grid, controls.clip);
  }, [payload, stats, controls.clip]);

  const mapExtent = useMemo(() => {
    if (controls.district === ALL) return manifest.bounds;
    const district = manifest.districts.find((item) => item.name === controls.district);
    return extentForDistrict(district, manifest.bounds);
  }, [controls.district, manifest]);

  const scale = useMemo(() => makeScale('YlOrRd', 0, 100), []);
  const thresholdLabel = controls.thresholdType === 'Fixed temperature' ? `> ${threshold} °C` : `> local P${threshold}`;
  const title = `GEFS Week ${week}: ${product.label} probability ${thresholdLabel} for ≥3 consecutive days`;

  function exportCsv() {
    if (!stats) return;
    const headers = ['District', 'Mean probability (%)', 'Max probability (%)', `Area >= ${controls.cutoff}% (km2)`, 'District area (km2)'];
    const rows = stats.map((row) => [row.district, row.mean.toFixed(1), row.max.toFixed(1), row.riskAreaKm2.toFixed(1), row.areaKm2.toFixed(1)]);
    downloadText(toCsv(headers, rows), `district_statistics_week${week}_${product.prefix}_${threshold}.csv`);
  }

  const sidebar = (
    <div className="sidebar-section">
        <Field label="Variable">
          <select value={product.name} onChange={(event) => setControls({ ...controls, productName: event.target.value })}>
            {manifest.heatProducts.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
          </select>
        </Field>

        <Field label="Threshold type">
          <RadioGroup
            name="threshold-type"
            options={['Fixed temperature', 'Percentile']}
            value={controls.thresholdType}
            onChange={(value) => setControls({ ...controls, thresholdType: value, threshold: null })}
          />
        </Field>

        <Field label={controls.thresholdType === 'Fixed temperature' ? `Threshold: ${threshold} °C` : `Percentile: P${threshold}`}>
          <input
            type="range"
            min={0}
            max={thresholds.length - 1}
            step={1}
            value={Math.max(thresholds.indexOf(threshold), 0)}
            onChange={(event) => setControls({ ...controls, threshold: thresholds[Number(event.target.value)] })}
          />
        </Field>

        <Field label={`Operational risk cutoff: ${controls.cutoff}%`}>
          <input
            type="range"
            min={10}
            max={90}
            step={5}
            value={controls.cutoff}
            onChange={(event) => setControls({ ...controls, cutoff: Number(event.target.value) })}
          />
        </Field>

        <Field label="District">
          <select value={controls.district} onChange={(event) => setControls({ ...controls, district: event.target.value })}>
            {[ALL, ...manifest.districts.map((item) => item.name)].map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </Field>

        <Toggle label="Show district boundaries" checked={controls.boundaries} onChange={(v) => setControls({ ...controls, boundaries: v })} />
        <Toggle label="Show district names" checked={controls.labels} onChange={(v) => setControls({ ...controls, labels: v })} />
        <Toggle label="Show stations" checked={controls.stations} onChange={(v) => setControls({ ...controls, stations: v })} />
        <Toggle label="Clip forecast to Suriname" checked={controls.clip} onChange={(v) => setControls({ ...controls, clip: v })} />
        {controls.thresholdType === 'Percentile' && product.supportsClimatology && (
          <Toggle label="Show percentile temperature threshold" checked={controls.showClimatology} onChange={(v) => setControls({ ...controls, showClimatology: v })} />
        )}

        <hr />
        <p className="sidebar-note">{product.description}</p>
    </div>
  );

  return (
    <>
      {sidebarMount && createPortal(sidebar, sidebarMount)}

      <div className="content">
        {error && <div className="notice notice-error">{error}</div>}
        {loading && !payload && <div className="notice">Loading forecast…</div>}

        {payload && stats && summary && (
          <>
            <span className={`chip ${payload.live ? 'chip-live' : 'chip-demo'}`}>
              {payload.live ? 'Live NOAA/CPC' : 'Demo data'}
            </span>

            <div className="metric-row">
              <MetricCard label="Highest-risk district" value={summary.highest?.district ?? '—'} delta={`Mean ${summary.highest?.mean?.toFixed(0) ?? '—'}%`} />
              <MetricCard label="Maximum probability" value={`${Number.isFinite(summary.maxProbability) ? summary.maxProbability.toFixed(0) : '—'}%`} />
              <MetricCard label={`Area at ≥ ${controls.cutoff}%`} value={`${Number.isFinite(summary.areaShare) ? summary.areaShare.toFixed(0) : '—'}%`} delta={`≈ ${Math.round(summary.riskAreaKm2).toLocaleString('en-GB')} km²`} />
              <MetricCard label="Valid period" value={formatPeriod(payload.meta)} delta={`Week ${week}`} />
            </div>

            <div className="split">
              <section className="panel">
                <FieldMap
                  svgRef={svgRef}
                  field={payload.values}
                  grid={payload.grid}
                  scale={scale}
                  extent={mapExtent}
                  districts={manifest.districts}
                  districtGeoJson={districtGeoJson}
                  selectedDistrict={controls.district === ALL ? null : controls.district}
                  showBoundaries={controls.boundaries}
                  showLabels={controls.labels}
                  showStations={controls.stations}
                  stations={manifest.stations}
                  clip={controls.clip}
                  title={title}
                  unit="%"
                />
                <ColorBar ramp="YlOrRd" min={0} max={100} label="Probability" unit="%" />
                <button className="button" onClick={() => downloadSvgAsPng(svgRef.current, `suriname_week${week}_${product.prefix}_${threshold}.png`)}>
                  Download map as PNG
                </button>
              </section>

              <section className="panel">
                <h2>District probabilities</h2>
                <DistrictTable rows={stats} cutoff={controls.cutoff} />
                {stats.some((row) => row.estimate) && (
                  <p className="footnote">* Small districts without a NOAA grid-cell centre use the nearest grid point; these rows are estimates.</p>
                )}
                <button className="button" onClick={exportCsv}>Download district statistics (CSV)</button>
              </section>
            </div>

            <section className="panel">
              <h2>District comparison</h2>
              <ComparisonChart rows={stats} />
            </section>

            {wantsClimatology && (
              <section className="panel">
                <h2>Local P{threshold} temperature threshold</h2>
                {climatology === 'missing' || !climatology ? (
                  <p className="footnote">The climatological threshold field is not part of the published dataset for this selection.</p>
                ) : (
                  <ClimatologyMap payload={climatology} extent={mapExtent} manifest={manifest} districtGeoJson={districtGeoJson} controls={controls} week={week} product={product} threshold={threshold} />
                )}
              </section>
            )}

            <details className="panel details">
              <summary>Data and processing details</summary>
              <pre>{JSON.stringify(payload.meta, null, 2)}</pre>
            </details>
          </>
        )}
      </div>
    </>
  );
}

function ClimatologyMap({ payload, extent, manifest, districtGeoJson, controls, week, product, threshold }) {
  const svgRef = useRef(null);
  const [min, max] = useMemo(() => valueExtent(payload.values, payload.grid, controls.clip), [payload, controls.clip]);
  const scale = useMemo(() => makeScale('inferno', min, max), [min, max]);
  return (
    <>
      <FieldMap
        svgRef={svgRef}
        field={payload.values}
        grid={payload.grid}
        scale={scale}
        extent={extent}
        districts={manifest.districts}
        districtGeoJson={districtGeoJson}
        showBoundaries
        showLabels={false}
        clip={controls.clip}
        title={`Week ${week} ${product.label}: P${threshold} threshold`}
        unit="°C"
      />
      <ColorBar ramp="inferno" min={min} max={max} label="Temperature" unit="°C" />
      <button className="button" onClick={() => downloadSvgAsPng(svgRef.current, `suriname_week${week}_${product.prefix}_p${threshold}_threshold.png`)}>
        Download threshold map
      </button>
    </>
  );
}
