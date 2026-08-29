import { sampleRamp, ticks } from '../lib/colors.js';

export function MetricCard({ label, value, delta }) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
      {delta && <span className="metric-delta">{delta}</span>}
    </div>
  );
}

export function ColorBar({ ramp, min, max, label, unit = '' }) {
  const stops = Array.from({ length: 21 }, (_, i) => sampleRamp(ramp, i / 20));
  const gradient = `linear-gradient(to right, ${stops.join(',')})`;
  const format = (value) => (Math.abs(max - min) < 12 ? value.toFixed(1) : value.toFixed(0));
  return (
    <div className="colorbar">
      <div className="colorbar-strip" style={{ background: gradient }} />
      <div className="colorbar-ticks">
        {ticks(min, max, 5).map((value) => (
          <span key={value}>{format(value)}</span>
        ))}
      </div>
      <div className="colorbar-label">{label}{unit ? ` (${unit})` : ''}</div>
    </div>
  );
}

export function DistrictTable({ rows, cutoff }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>District</th>
            <th className="numeric">Mean (%)</th>
            <th className="numeric">Max (%)</th>
            <th className="numeric">Area ≥ {cutoff}% (km²)</th>
            <th className="numeric">Area (km²)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.district}>
              <td>{row.district}{row.estimate ? <span className="estimate-flag" title="Nearest-grid estimate">*</span> : null}</td>
              <td className="numeric">{Number.isFinite(row.mean) ? row.mean.toFixed(1) : '—'}</td>
              <td className="numeric">{Number.isFinite(row.max) ? row.max.toFixed(1) : '—'}</td>
              <td className="numeric">{Math.round(row.riskAreaKm2).toLocaleString('en-GB')}</td>
              <td className="numeric">{Math.round(row.areaKm2).toLocaleString('en-GB')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ComparisonChart({ rows }) {
  const sorted = [...rows].sort((a, b) => (a.mean || 0) - (b.mean || 0));
  return (
    <div className="bar-chart">
      {sorted.map((row) => {
        const value = Number.isFinite(row.mean) ? row.mean : 0;
        return (
          <div className="bar-row" key={row.district}>
            <span className="bar-name">{row.district}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${Math.max(value, 0)}%`, background: sampleRamp('YlOrRd', value / 100) }}>
                <span className="bar-value">{value.toFixed(0)}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="control">
      <span className="control-label">{label}</span>
      {children}
      {hint && <span className="control-hint">{hint}</span>}
    </label>
  );
}

export function RadioGroup({ options, value, onChange, name, format = (v) => v }) {
  return (
    <div className="radio-group">
      {options.map((option) => (
        <label key={option} className={`radio ${option === value ? 'is-active' : ''}`}>
          <input type="radio" name={name} checked={option === value} onChange={() => onChange(option)} />
          <span>{format(option)}</span>
        </label>
      ))}
    </div>
  );
}

export function Toggle({ label, checked, onChange }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="toggle-track"><span className="toggle-thumb" /></span>
      <span className="toggle-text">{label}</span>
    </label>
  );
}
