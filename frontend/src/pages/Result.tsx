import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FileDown,
  RefreshCw,
  Square,
  XCircle,
} from 'lucide-react';
import { api, type ArtifactInfo, type ProjectResponse } from '../api/client';
import { usePageTitle } from '../hooks/usePageTitle';
import { buildAppRoute } from '../utils/session';
import './InteriorPages.css';

function formatSize(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatSummaryValue(value: unknown) {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}

function scoreToneClass(score: number) {
  const pct = Math.round(score * 100);
  if (pct >= 80) return 'result-score-card--success';
  if (pct >= 50) return 'result-score-card--warning';
  return 'result-score-card--error';
}

function scoreLabel(label: string) {
  return label.replace(/_/g, ' ');
}

export default function Result() {
  usePageTitle('Results');
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [error, setError] = useState('');
  const [resolvedProjectId, setResolvedProjectId] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    Promise.all([
      api.getProject(projectId),
      api.listArtifacts(projectId).catch(() => ({ project_id: projectId, artifacts: [] })),
    ])
      .then(([proj, arts]) => {
        setProject(proj);
        setArtifacts(arts.artifacts);
        setError('');
        setResolvedProjectId(projectId);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load project');
        setResolvedProjectId(projectId);
      });
  }, [projectId]);

  const loading = Boolean(projectId) && resolvedProjectId !== projectId;
  const visibleError = resolvedProjectId === projectId ? error : '';

  if (loading) {
    return (
      <div className="page-frame">
        <div className="page-shell result-empty-state" role="status" aria-live="polite">
          <RefreshCw className="w-6 h-6 result-empty-state__spinner" aria-hidden="true" />
          <p className="result-empty-state__body">Loading results…</p>
        </div>
      </div>
    );
  }

  if (visibleError) {
    return (
      <div className="page-frame">
        <div className="page-shell result-empty-state">
          <XCircle className="w-8 h-8 result-empty-state__icon" aria-hidden="true" />
          <p className="result-empty-state__body">{visibleError}</p>
          <button
            type="button"
            onClick={() => navigate(buildAppRoute('/upload'))}
            className="run-cta"
          >
            Upload new document
          </button>
        </div>
      </div>
    );
  }

  if (!project || !projectId) return null;

  const isCompleted = project.status === 'completed';
  const isStopped = project.status === 'interrupted' || project.status === 'stopped';
  const isFailed = project.status === 'failed' || project.status === 'error';

  const statusClass = isCompleted
    ? 'result-status-pill--success'
    : isStopped
      ? 'result-status-pill--warning'
      : isFailed
        ? 'result-status-pill--error'
        : 'result-status-pill--neutral';

  const statusIcon = isCompleted ? (
    <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
  ) : isStopped ? (
    <Square className="w-4 h-4" aria-hidden="true" />
  ) : isFailed ? (
    <XCircle className="w-4 h-4" aria-hidden="true" />
  ) : (
    <RefreshCw className="w-4 h-4" aria-hidden="true" />
  );

  const scores = Object.entries(project.confidence_scores || {});
  const summary = Object.entries(project.execution_summary || {});
  const recommendedArtifacts = ['metadata_json.json', 'validation_report.txt', 'workflow_report.json'];

  return (
    <div className="page-frame">
      <div className="page-shell page-stack">
        <header className="page-header">
          <button
            type="button"
            onClick={() => navigate(buildAppRoute('/upload'))}
            className="page-backlink"
          >
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            Process another document
          </button>
          <p className="page-eyebrow">Step 4 of 4</p>
          <h1 className="page-title">{project.project_name || project.filename || 'Workflow results'}</h1>
          <p className="page-lede">
            Review the run summary, inspect confidence signals, and download the files produced by this
            workflow before reusing or submitting the output downstream.
          </p>
        </header>

        <div className="result-layout">
          <section className="result-main">
            <article className="page-card">
              <div className="page-card__header">
                <div>
                  <p className="page-card__eyebrow">Inspection guide</p>
                  <h2 className="page-card__title">What is on this page?</h2>
                  <p className="page-card__body">
                    Confidence scores summarize output quality across critique, structure, and validation
                    checks. The artifact list contains the concrete files written by the run, including the
                    metadata draft, validation output, and workflow reports.
                  </p>
                </div>
                <div className={`result-status-pill ${statusClass}`}>
                  {statusIcon}
                  <span>{project.status}</span>
                </div>
              </div>
            </article>

            {scores.length > 0 && (
              <article className="page-card">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">Confidence</p>
                    <h2 className="page-card__title">Scoring overview</h2>
                  </div>
                </div>
                <div className="result-score-grid">
                  {scores.map(([key, value]) => {
                    const pct = Math.round(value * 100);
                    return (
                      <div key={key} className={`result-score-card ${scoreToneClass(value)}`}>
                        <p className="result-score-card__label">{scoreLabel(key)}</p>
                        <p className="result-score-card__value">{pct}%</p>
                        <div className="result-score-card__track" aria-hidden="true">
                          <div
                            className="result-score-card__fill"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </article>
            )}

            {summary.length > 0 && (
              <article className="page-card">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">Run summary</p>
                    <h2 className="page-card__title">Execution details</h2>
                  </div>
                </div>
                <div className="result-summary-grid">
                  {summary.map(([key, value]) => (
                    <div key={key} className="result-summary-card">
                      <p className="result-summary-card__label">{scoreLabel(key)}</p>
                      <p className="result-summary-card__value">{formatSummaryValue(value)}</p>
                    </div>
                  ))}
                </div>
              </article>
            )}

            {project.errors && project.errors.length > 0 && (
              <article className="page-card result-alert">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">Run notes</p>
                    <h2 className="page-card__title">Issues reported by the workflow</h2>
                  </div>
                </div>
                <div className="result-alert__list">
                  {project.errors.map((entry, index) => (
                    <p key={`${entry}-${index}`} className="result-alert__item">
                      {entry}
                    </p>
                  ))}
                </div>
              </article>
            )}

            <article className="page-card">
              <div className="page-card__header">
                <div>
                  <p className="page-card__eyebrow">Artifacts</p>
                  <h2 className="page-card__title">Files available for download</h2>
                  <p className="page-card__body">
                    Start with <strong>metadata_json.json</strong>, then review the validation report and
                    workflow report before handing the output off to another system.
                  </p>
                </div>
                <div className="result-file-count">{artifacts.length} files</div>
              </div>

              {artifacts.length > 0 ? (
                <div className="result-file-list">
                  {artifacts.map((artifact) => {
                    const filename = artifact.name.split('/').pop() || artifact.name;
                    return (
                      <div key={artifact.name} className="result-file-row">
                        <div className="result-file-row__icon">
                          <FileDown className="w-4 h-4" aria-hidden="true" />
                        </div>
                        <div className="result-file-row__content">
                          <p className="result-file-row__name">{filename}</p>
                          <p className="result-file-row__meta">
                            {artifact.name.includes('/') ? `${artifact.name} · ` : ''}
                            {formatSize(artifact.size)}
                          </p>
                        </div>
                        {artifact.available ? (
                          <a
                            href={api.getArtifactUrl(projectId, artifact.name)}
                            download
                            className="result-download-link"
                          >
                            <Download className="w-4 h-4" aria-hidden="true" />
                            Download
                          </a>
                        ) : (
                          <span className="result-download-link result-download-link--disabled">
                            Unavailable
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="result-empty-panel">
                  No artifacts were listed for this project.
                </div>
              )}
            </article>
          </section>

          <aside className="result-aside result-aside--sticky">
            <article className="run-sidebar-card">
              <h2 className="run-sidebar-card__title">Project</h2>
              <p className="run-sidebar-card__body">{project.filename || 'Processed document'}</p>
              <div className="run-metric-grid">
                <div className="run-metric">
                  <p className="run-metric__label">Project ID</p>
                  <p className="run-metric__value">{projectId}</p>
                </div>
                <div className="run-metric">
                  <p className="run-metric__label">Status</p>
                  <p className="run-metric__value">{project.status}</p>
                </div>
                <div className="run-metric">
                  <p className="run-metric__label">Created</p>
                  <p className="run-metric__value">{project.created_at || 'Not available'}</p>
                </div>
                <div className="run-metric">
                  <p className="run-metric__label">Updated</p>
                  <p className="run-metric__value">{project.updated_at || 'Not available'}</p>
                </div>
              </div>
            </article>

            <article className="run-sidebar-card">
              <h2 className="run-sidebar-card__title">Start here</h2>
              <ul className="page-note-list">
                {recommendedArtifacts.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </article>

            <button
              type="button"
              onClick={() => navigate(buildAppRoute('/upload'))}
              className="run-cta run-cta--gradient"
            >
              Process another document
            </button>
          </aside>
        </div>
      </div>
    </div>
  );
}
