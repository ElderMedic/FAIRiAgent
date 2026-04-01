import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { api, type ProjectResponse } from '../api/client';
import { usePageTitle } from '../hooks/usePageTitle';
import {
  buildAppRoute,
  buildRouteWithSession,
  getWebSession,
  isValidSessionId,
  isValidSessionTimestamp,
  setWebSession,
  type WebSession,
} from '../utils/session';
import './InteriorPages.css';

function projectDestination(project: ProjectResponse) {
  if (project.status === 'pending' || project.status === 'running' || project.stop_requested) {
    return `/run/${project.project_id}`;
  }
  return `/result/${project.project_id}`;
}

function formatProjectName(project: ProjectResponse) {
  return project.project_name || project.filename || project.project_id;
}

function formatSessionDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function sortProjects(projects: ProjectResponse[]) {
  return [...projects].sort((a, b) => {
    const left = Date.parse(a.updated_at || a.created_at || '');
    const right = Date.parse(b.updated_at || b.created_at || '');
    return (Number.isNaN(right) ? 0 : right) - (Number.isNaN(left) ? 0 : left);
  });
}

export default function Recover() {
  usePageTitle('Recover');
  const navigate = useNavigate();
  const location = useLocation();
  const activeSession = useMemo(() => getWebSession(location.search), [location.search]);

  const [sessionIdInput, setSessionIdInput] = useState(activeSession.id);
  const [sessionStartedAtInput, setSessionStartedAtInput] = useState(activeSession.startedAt);
  const [projectIdInput, setProjectIdInput] = useState('');
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [inlineMessage, setInlineMessage] = useState('');
  const [lookupSubmitting, setLookupSubmitting] = useState(false);

  useEffect(() => {
    setSessionIdInput(activeSession.id);
    setSessionStartedAtInput(activeSession.startedAt);
  }, [activeSession.id, activeSession.startedAt]);

  useEffect(() => {
    let cancelled = false;
    setLoadingProjects(true);
    api
      .listProjects()
      .then((result) => {
        if (cancelled) return;
        setProjects(sortProjects(result.projects));
        setSubmitError('');
      })
      .catch((err) => {
        if (cancelled) return;
        setProjects([]);
        setSubmitError(err instanceof Error ? err.message : 'Failed to load session runs');
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingProjects(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeSession.id, activeSession.startedAt]);

  const adoptSession = (session: WebSession) => {
    setWebSession(session);
    navigate(buildRouteWithSession('/recover', session), { replace: true });
  };

  const handleSessionApply = async () => {
    const session: WebSession = {
      id: sessionIdInput.trim(),
      startedAt: sessionStartedAtInput.trim(),
    };

    if (!isValidSessionId(session.id)) {
      setSubmitError('Enter a valid session UUID.');
      return;
    }
    if (!isValidSessionTimestamp(session.startedAt)) {
      setSubmitError('Enter a valid session timestamp.');
      return;
    }

    setLookupSubmitting(true);
    setSubmitError('');
    setInlineMessage('');

    try {
      adoptSession(session);

      const directProjectId = projectIdInput.trim();
      if (!directProjectId) {
        setInlineMessage('Session updated. Recent runs for that session are listed below.');
        return;
      }

      const project = await api.getProjectInSession(directProjectId, session);
      navigate(buildRouteWithSession(projectDestination(project), session));
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Unable to recover that session');
    } finally {
      setLookupSubmitting(false);
    }
  };

  return (
    <div className="page-frame">
      <div className="page-shell page-stack">
        <header className="page-header">
          <Link to={buildAppRoute('/')} className="page-backlink">
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            Back to home
          </Link>
          <p className="page-eyebrow">Recover session</p>
          <h1 className="page-title">Find a previous run or reopen its result files.</h1>
          <p className="page-lede">
            If you refreshed the browser, closed a tab, or moved to another device, use the session UUID
            and timestamp from an earlier FAIRiAgent link to restore that session and reopen its runs.
          </p>
        </header>

        <div className="recover-layout">
          <section className="recover-main">
            <article className="page-card">
              <div className="page-card__header">
                <div>
                  <p className="page-card__eyebrow">Session lookup</p>
                  <h2 className="page-card__title">Restore a session</h2>
                  <p className="page-card__body">
                    Paste the session UUID and start timestamp from a previous link. Add a project ID if
                    you want to jump directly into one run.
                  </p>
                </div>
                <div className="page-card__icon-wrap">
                  <Search className="page-card__icon" aria-hidden="true" />
                </div>
              </div>

              <div className="recover-form-grid">
                <label className="config-field">
                  <span className="config-field__label">Session UUID</span>
                  <input
                    className="config-input"
                    value={sessionIdInput}
                    onChange={(event) => setSessionIdInput(event.target.value)}
                    placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  />
                </label>

                <label className="config-field">
                  <span className="config-field__label">Session started at</span>
                  <input
                    className="config-input"
                    value={sessionStartedAtInput}
                    onChange={(event) => setSessionStartedAtInput(event.target.value)}
                    placeholder="2026-04-01T12:34:56.789Z"
                  />
                </label>

                <label className="config-field">
                  <span className="config-field__label">Project ID</span>
                  <span className="config-field__hint">Optional. Leave blank to list runs for the session.</span>
                  <input
                    className="config-input"
                    value={projectIdInput}
                    onChange={(event) => setProjectIdInput(event.target.value)}
                    placeholder="fairifier_20260401_..."
                  />
                </label>
              </div>

              {submitError && <p className="upload-error">{submitError}</p>}
              {inlineMessage && <p className="recover-note">{inlineMessage}</p>}

              <div className="recover-actions">
                <button
                  type="button"
                  onClick={() => void handleSessionApply()}
                  className="run-cta run-cta--gradient"
                  disabled={lookupSubmitting}
                >
                  {lookupSubmitting ? 'Recovering…' : 'Recover session'}
                </button>
              </div>
            </article>

            <article className="page-card">
              <div className="page-card__header">
                <div>
                  <p className="page-card__eyebrow">Recent runs</p>
                  <h2 className="page-card__title">Runs visible in the active session</h2>
                  <p className="page-card__body">
                    These are the runs currently attached to the session in your browser or the one you
                    just restored.
                  </p>
                </div>
                <div className="result-file-count">
                  {loadingProjects ? 'Loading…' : `${projects.length} runs`}
                </div>
              </div>

              {loadingProjects ? (
                <div className="result-empty-panel">Loading runs for this session…</div>
              ) : projects.length > 0 ? (
                <div className="recover-run-list">
                  {projects.map((project) => (
                    <div key={project.project_id} className="recover-run-row">
                      <div className="recover-run-row__body">
                        <p className="recover-run-row__title">{formatProjectName(project)}</p>
                        <p className="recover-run-row__meta">
                          {project.project_id} · {project.status} · {formatSessionDate(project.updated_at || project.created_at || activeSession.startedAt)}
                        </p>
                      </div>
                      <button
                        type="button"
                        className="recover-open-link"
                        onClick={() => navigate(buildAppRoute(projectDestination(project)))}
                      >
                        Open
                        <ArrowRight className="w-4 h-4" aria-hidden="true" />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="result-empty-panel">
                  No runs were found for this session. Restore another session, or start a new upload.
                </div>
              )}
            </article>
          </section>

          <aside className="result-aside result-aside--sticky">
            <article className="run-sidebar-card">
              <h2 className="run-sidebar-card__title">Active session</h2>
              <div className="run-metric-grid">
                <div className="run-metric">
                  <p className="run-metric__label">Session UUID</p>
                  <p className="run-metric__value">{activeSession.id}</p>
                </div>
                <div className="run-metric">
                  <p className="run-metric__label">Started at</p>
                  <p className="run-metric__value">{activeSession.startedAt}</p>
                </div>
              </div>
            </article>

            <article className="run-sidebar-card">
              <h2 className="run-sidebar-card__title">How recovery works</h2>
              <ul className="page-note-list">
                <li>Each browser session gets a temporary UUID and timestamp.</li>
                <li>Those values are kept in FAIRiAgent links and used to isolate runs and artifacts.</li>
                <li>Restoring the session lets you reopen run pages and download previous outputs.</li>
              </ul>
            </article>

            <article className="run-sidebar-card">
              <div className="recover-sidebar-heading">
                <ShieldCheck className="w-4 h-4" aria-hidden="true" />
                <h2 className="run-sidebar-card__title">Current browser</h2>
              </div>
              <p className="run-sidebar-card__body">
                If you only refreshed the page in the same browser, your session is usually already
                present. This page is mainly for reopening an older link or moving to another device.
              </p>
            </article>

            <Link to={buildAppRoute('/upload')} className="run-cta">
              Start a new run
            </Link>
          </aside>
        </div>
      </div>
    </div>
  );
}
