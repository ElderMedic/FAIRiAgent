import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  BarChart3,
  Database,
  Layers,
  RefreshCw,
  Tags,
} from 'lucide-react';
import {
  api,
  type FAIRDSISAStatistics,
  type FAIRDSStatisticsResponse,
} from '../api/client';
import { usePageTitle } from '../hooks/usePageTitle';
import './InteriorPages.css';

const ISA_LABELS: Record<string, string> = {
  investigation: 'Investigation',
  study: 'Study',
  observationunit: 'ObservationUnit',
  sample: 'Sample',
  assay: 'Assay',
};

const REQUIREMENT_LABELS: Record<string, string> = {
  mandatory: 'Mandatory',
  recommended: 'Recommended',
  optional: 'Optional',
};

const REQUIREMENT_TONES: Record<string, string> = {
  mandatory: 'stats-chip--mandatory',
  recommended: 'stats-chip--recommended',
  optional: 'stats-chip--optional',
};

function formatPercent(value: number, digits = 1) {
  return `${(value * 100).toFixed(digits)}%`;
}

function formatDateTime(iso: string) {
  if (!iso) return 'n/a';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString('en-US', {
    hour12: false,
  });
}

function isaDisplayName(isaLevel: string) {
  return ISA_LABELS[isaLevel] || isaLevel;
}

function renderISAFieldMix(isa: FAIRDSISAStatistics) {
  const total = isa.fields || 1;
  const mandatory = (isa.mandatory_fields / total) * 100;
  const recommended = (isa.recommended_fields / total) * 100;
  const optional = (isa.optional_fields / total) * 100;

  return (
    <div className="stats-stacked-bar" aria-hidden>
      <span className="stats-stacked-bar__segment stats-stacked-bar__segment--mandatory" style={{ width: `${mandatory}%` }} />
      <span className="stats-stacked-bar__segment stats-stacked-bar__segment--recommended" style={{ width: `${recommended}%` }} />
      <span className="stats-stacked-bar__segment stats-stacked-bar__segment--optional" style={{ width: `${optional}%` }} />
    </div>
  );
}

export default function FairdsStats() {
  usePageTitle('FAIR-DS Stats');
  const [stats, setStats] = useState<FAIRDSStatisticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const loadStats = async (refresh: boolean) => {
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError('');
    try {
      const next = await api.fairdsStatistics({
        refresh,
        top: 12,
        packages: 18,
      });
      setStats(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load FAIR-DS statistics');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    void loadStats(false);
  }, []);

  const maxISAFields = useMemo(
    () => Math.max(...(stats?.isa_levels.map((item) => item.fields) || [1])),
    [stats],
  );

  const maxPackageFields = useMemo(
    () => Math.max(...(stats?.package_leaderboard.map((item) => item.fields) || [1])),
    [stats],
  );

  return (
    <div className="page-frame">
      <div className="page-shell page-stack">
        <header className="page-header">
          <Link to="/" className="page-backlink">
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            Back to home
          </Link>
          <p className="page-eyebrow">FAIR-DS Analytics</p>
          <h1 className="page-title">Package and term statistics.</h1>
          <p className="page-lede">
            This view aggregates FAIR-DS package metadata and term coverage so package design, ISA
            distribution, and mandatory-field density can be inspected before run-time retrieval.
          </p>
        </header>

        <div className="stats-layout">
          <section className="stats-main">
            <article className="page-card">
              <div className="page-card__header">
                <div>
                  <p className="page-card__eyebrow">Snapshot</p>
                  <h2 className="page-card__title">Current FAIR-DS dataset profile</h2>
                </div>
                <button
                  type="button"
                  onClick={() => void loadStats(true)}
                  disabled={refreshing}
                  className="stats-refresh-button"
                >
                  <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} aria-hidden />
                  Refresh
                </button>
              </div>
              <p className="page-card__body">
                {stats?.message || 'Loading FAIR-DS statistics...'}
              </p>

              {error ? (
                <div className="config-alert config-alert--error">{error}</div>
              ) : null}

              {loading && !stats ? (
                <p className="stats-loading">Loading aggregated data...</p>
              ) : null}

              {stats ? (
                <div className="stats-summary-grid">
                  <div className="stats-summary-card">
                    <p className="stats-summary-card__label">Packages</p>
                    <p className="stats-summary-card__value">{stats.totals.packages}</p>
                  </div>
                  <div className="stats-summary-card">
                    <p className="stats-summary-card__label">Terms</p>
                    <p className="stats-summary-card__value">{stats.totals.terms}</p>
                  </div>
                  <div className="stats-summary-card">
                    <p className="stats-summary-card__label">Fields</p>
                    <p className="stats-summary-card__value">{stats.totals.fields}</p>
                  </div>
                  <div className="stats-summary-card">
                    <p className="stats-summary-card__label">Mandatory Ratio</p>
                    <p className="stats-summary-card__value">{formatPercent(stats.totals.mandatory_ratio)}</p>
                  </div>
                  <div className="stats-summary-card">
                    <p className="stats-summary-card__label">Unique Field Labels</p>
                    <p className="stats-summary-card__value">{stats.totals.unique_field_labels}</p>
                  </div>
                  <div className="stats-summary-card">
                    <p className="stats-summary-card__label">Terms Referenced</p>
                    <p className="stats-summary-card__value">{stats.totals.terms_referenced_in_packages}</p>
                  </div>
                </div>
              ) : null}
            </article>

            {stats ? (
              <article className="page-card">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">Requirement Mix</p>
                    <h2 className="page-card__title">Mandatory / Recommended / Optional</h2>
                  </div>
                  <div className="page-card__icon-wrap">
                    <BarChart3 className="page-card__icon" aria-hidden />
                  </div>
                </div>
                <div className="stats-stacked-bar stats-stacked-bar--large" aria-hidden>
                  {stats.requirement_distribution.map((item) => {
                    const width = stats.totals.fields
                      ? (item.count / stats.totals.fields) * 100
                      : 0;
                    return (
                      <span
                        key={item.requirement}
                        className={`stats-stacked-bar__segment stats-stacked-bar__segment--${item.requirement}`}
                        style={{ width: `${width}%` }}
                      />
                    );
                  })}
                </div>
                <div className="stats-chip-row">
                  {stats.requirement_distribution.map((item) => {
                    const ratio = stats.totals.fields ? item.count / stats.totals.fields : 0;
                    return (
                      <span
                        key={item.requirement}
                        className={`stats-chip ${REQUIREMENT_TONES[item.requirement] || ''}`}
                      >
                        {REQUIREMENT_LABELS[item.requirement] || item.requirement}: {item.count} ({formatPercent(ratio)})
                      </span>
                    );
                  })}
                </div>
              </article>
            ) : null}

            {stats ? (
              <article className="page-card">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">ISA Coverage</p>
                    <h2 className="page-card__title">Field volume per ISA level</h2>
                  </div>
                  <div className="page-card__icon-wrap">
                    <Layers className="page-card__icon" aria-hidden />
                  </div>
                </div>
                <div className="stats-isa-list">
                  {stats.isa_levels.map((isa) => {
                    const width = maxISAFields ? (isa.fields / maxISAFields) * 100 : 0;
                    return (
                      <article key={isa.isa_level} className="stats-isa-row">
                        <div className="stats-isa-row__head">
                          <p className="stats-isa-row__title">{isaDisplayName(isa.isa_level)}</p>
                          <p className="stats-isa-row__meta">
                            {isa.fields} fields · {isa.packages_count} packages
                          </p>
                        </div>
                        <div className="stats-isa-row__bar">
                          <span style={{ width: `${width}%` }} />
                        </div>
                        {renderISAFieldMix(isa)}
                      </article>
                    );
                  })}
                </div>
              </article>
            ) : null}

            {stats ? (
              <article className="page-card">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">Package Leaderboard</p>
                    <h2 className="page-card__title">Most field-heavy packages</h2>
                  </div>
                  <div className="page-card__icon-wrap">
                    <Database className="page-card__icon" aria-hidden />
                  </div>
                </div>
                <div className="stats-package-list">
                  {stats.package_leaderboard.map((item) => {
                    const width = maxPackageFields ? (item.fields / maxPackageFields) * 100 : 0;
                    return (
                      <article key={item.package_name} className="stats-package-row">
                        <div className="stats-package-row__head">
                          <p className="stats-package-row__title">{item.package_name}</p>
                          <p className="stats-package-row__meta">
                            {item.fields} fields · {item.mandatory_fields} mandatory · {item.isa_level_count} ISA levels
                          </p>
                        </div>
                        <div className="stats-package-row__bar">
                          <span style={{ width: `${width}%` }} />
                        </div>
                      </article>
                    );
                  })}
                </div>
              </article>
            ) : null}
          </section>

          <aside className="stats-aside">
            {stats ? (
              <article className="page-card page-card--soft">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">Source</p>
                    <h2 className="page-card__title">FAIR-DS endpoint status</h2>
                  </div>
                </div>
                <div className="stats-status-line">
                  <span className={`stats-status-badge ${stats.available ? 'is-ready' : 'is-down'}`}>
                    {stats.available ? 'Available' : 'Unavailable'}
                  </span>
                  <span className="stats-status-time">{formatDateTime(stats.generated_at)}</span>
                </div>
                <p className="page-card__body">{stats.api_url || 'No API URL configured'}</p>
              </article>
            ) : null}

            {stats ? (
              <article className="page-card">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">Term Quality</p>
                    <h2 className="page-card__title">How complete are term definitions</h2>
                  </div>
                  <div className="page-card__icon-wrap">
                    <Tags className="page-card__icon" aria-hidden />
                  </div>
                </div>
                <div className="stats-term-quality-grid">
                  <div className="stats-term-quality-card">
                    <p className="stats-term-quality-card__label">With Definition</p>
                    <p className="stats-term-quality-card__value">{stats.term_quality.with_definition}</p>
                  </div>
                  <div className="stats-term-quality-card">
                    <p className="stats-term-quality-card__label">With Example</p>
                    <p className="stats-term-quality-card__value">{stats.term_quality.with_example}</p>
                  </div>
                  <div className="stats-term-quality-card">
                    <p className="stats-term-quality-card__label">With Regex</p>
                    <p className="stats-term-quality-card__value">{stats.term_quality.with_regex}</p>
                  </div>
                  <div className="stats-term-quality-card">
                    <p className="stats-term-quality-card__label">With Ontology URL</p>
                    <p className="stats-term-quality-card__value">{stats.term_quality.with_ontology_url}</p>
                  </div>
                </div>
              </article>
            ) : null}

            {stats?.top_terms.length ? (
              <article className="page-card">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">Top Terms</p>
                    <h2 className="page-card__title">Most reused field terms</h2>
                  </div>
                </div>
                <ul className="stats-term-list">
                  {stats.top_terms.map((item) => (
                    <li key={item.term}>
                      <span>{item.term}</span>
                      <strong>{item.field_count}</strong>
                    </li>
                  ))}
                </ul>
              </article>
            ) : null}
          </aside>
        </div>
      </div>
    </div>
  );
}
