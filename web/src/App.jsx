import { useEffect, useState } from 'react';
import HeatRisk from './sections/HeatRisk.jsx';
import AtmosphericContext from './sections/AtmosphericContext.jsx';
import { Field, RadioGroup } from './components/Pieces.jsx';
import { loadDistricts, loadManifest } from './lib/data.js';

const SECTIONS = ['Heat risk', 'Atmospheric context'];

export default function App() {
  const [manifest, setManifest] = useState(null);
  const [districtGeoJson, setDistrictGeoJson] = useState(null);
  const [error, setError] = useState(null);
  const [section, setSection] = useState(SECTIONS[0]);
  const [week, setWeek] = useState(1);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Each section portals its own controls into this node.
  const [sidebarMount, setSidebarMount] = useState(null);

  const [heatControls, setHeatControls] = useState({
    productName: null,
    thresholdType: 'Fixed temperature',
    threshold: null,
    cutoff: 50,
    district: 'All districts',
    boundaries: true,
    labels: true,
    stations: true,
    clip: true,
    showClimatology: false,
  });

  const [contextControls, setContextControls] = useState({
    family: 'Scalar field',
    contextProduct: null,
    level: 850,
    view: 'Average',
    buffer: 8,
  });

  useEffect(() => {
    Promise.all([loadManifest(), loadDistricts()])
      .then(([manifestData, geoJson]) => {
        setManifest(manifestData);
        setDistrictGeoJson(geoJson);
        setHeatControls((current) => ({ ...current, productName: current.productName ?? manifestData.heatProducts[0]?.name }));
        setContextControls((current) => ({ ...current, contextProduct: current.contextProduct ?? manifestData.contextProducts[0]?.name }));
      })
      .catch((problem) => setError(problem.message));
  }, []);

  if (error) {
    return (
      <div className="boot-shell">
        <div className="notice notice-error boot-error">
          <strong>The dashboard data could not be loaded.</strong>
          <p>{error}</p>
          <p className="footnote">Make sure the <code>data/</code> folder sits next to <code>index.html</code> on the web server.</p>
        </div>
      </div>
    );
  }

  if (!manifest || !districtGeoJson) {
    return <div className="boot-shell"><div className="boot">Loading dashboard…</div></div>;
  }

  const generated = new Date(manifest.generatedAt);
  const generatedLabel = Number.isNaN(generated.getTime())
    ? 'unknown'
    : generated.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' });

  const sectionProps = {
    manifest,
    districtGeoJson,
    week,
    sidebarMount,
  };

  return (
    <div className="app-shell">
      <button className="sidebar-toggle" onClick={() => setSidebarOpen((open) => !open)} aria-expanded={sidebarOpen}>
        {sidebarOpen ? '✕ Close controls' : '☰ Dashboard controls'}
      </button>

      <aside className={`sidebar ${sidebarOpen ? 'is-open' : ''}`}>
        <h2 className="sidebar-title">Dashboard controls</h2>

        <Field label="Section">
          <RadioGroup name="section" options={SECTIONS} value={section} onChange={setSection} />
        </Field>

        <Field label="Forecast period" hint="Week 1 represents days 1–7; Week 2 represents days 8–14.">
          <RadioGroup name="week" options={[1, 2]} value={week} onChange={setWeek} format={(value) => `Week ${value}`} />
        </Field>

        <div ref={setSidebarMount} className="sidebar-mount" />
      </aside>

      <main className="main">
        <header className="page-header">
          <h1>Suriname Heat Forecast Dashboard</h1>
          <p>NOAA/CPC GEFS Week 1–2 excessive-heat guidance with official Suriname district boundaries</p>
        </header>

        {section === 'Heat risk' ? (
          <HeatRisk {...sectionProps} controls={heatControls} setControls={setHeatControls} />
        ) : (
          <AtmosphericContext {...sectionProps} controls={contextControls} setControls={setContextControls} />
        )}

        <footer className="page-footer">
          <p>
            This dashboard visualizes NOAA/CPC GEFS guidance and is not an official warning product. Verify operational
            decisions against observations, local procedures, and the latest meteorological analysis.
          </p>
          <p className="credit">Gemaakt door: Ritesh Rajai</p>
          <p className="footnote">
            Data refreshed {generatedLabel} · {manifest.liveCount} live fields, {manifest.demoCount} demo fields
          </p>
        </footer>
      </main>
    </div>
  );
}
