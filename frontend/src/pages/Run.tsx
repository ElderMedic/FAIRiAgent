import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Activity, CheckCircle2, Square, XCircle, ArrowLeft, ArrowRight } from 'lucide-react';
import { api, type ProjectResponse, type ResourceLoad, type WorkflowEvent } from '../api/client';
import { usePageTitle } from '../hooks/usePageTitle';
import { buildAppRoute, getWebSession } from '../utils/session';
import './InteriorPages.css';

interface LogEntry {
  timestamp: string;
  message: string;
  type: string;
}

function formatTimestamp(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('en-US', { hour12: false });
}

function readEventString(data: WorkflowEvent['data'], key: string) {
  const value = data[key];
  return typeof value === 'string' ? value : '';
}

export default function Run() {
  usePageTitle('Processing');
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const logContainerRef = useRef<HTMLDivElement>(null);
  const session = getWebSession();

  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [stage, setStage] = useState('Initializing');
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<'running' | 'stopping' | 'stopped' | 'completed' | 'error'>('running');
  const [errorMsg, setErrorMsg] = useState('');
  const [stopSubmitting, setStopSubmitting] = useState(false);
  const [resourceLoad, setResourceLoad] = useState<ResourceLoad | null>(null);

  const syncProjectState = (project: ProjectResponse) => {
    setProject(project);
    if (project.stop_requested && (project.status === 'pending' || project.status === 'running')) {
      setStatus('stopping');
      setStage('Stopping');
      return false;
    }
    if (project.status === 'completed') {
      setStatus('completed');
      setProgress(100);
      setStage('Completed');
      return true;
    }
    if (project.status === 'interrupted' || project.status === 'stopped') {
      setStatus('stopped');
      setStage('Stopped');
      return true;
    }
    if (project.status === 'failed' || project.status === 'error') {
      setStatus('error');
      setStage('Failed');
      setErrorMsg(project.errors?.[0] || 'Project failed');
      return true;
    }
    if (project.status) {
      setStage(project.status);
    }
    return false;
  };

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    let pollTimer: number | undefined;
    let source: EventSource | undefined;

    const stopPolling = () => {
      if (pollTimer !== undefined) {
        window.clearInterval(pollTimer);
        pollTimer = undefined;
      }
    };

    const startPolling = () => {
      if (pollTimer !== undefined) return;
      pollTimer = window.setInterval(async () => {
        if (!projectId || !active) return;
        try {
          const project = await api.getProject(projectId);
          if (syncProjectState(project)) {
            stopPolling();
            source?.close();
          }
        } catch {
          /* keep polling */
        }
      }, 1500);
    };

    api.getProject(projectId)
      .then((project) => {
        if (!active) return;
        if (syncProjectState(project)) {
          return;
        }

        source = api.subscribeEvents(
          projectId,
          (event: WorkflowEvent) => {
            const message = readEventString(event.data, 'message');
            const stageName = readEventString(event.data, 'stage');
            const errorText = readEventString(event.data, 'error');
            const entry: LogEntry = {
              timestamp: formatTimestamp(event.timestamp),
              message: message || stageName || JSON.stringify(event.data),
              type: event.event_type,
            };
            setLogs((prev) => [...prev, entry]);

            switch (event.event_type) {
              case 'stage_change':
                if (stageName) setStage(stageName);
                break;
              case 'progress':
                if (typeof event.data.progress === 'number') setProgress(event.data.progress);
                break;
              case 'stop_requested':
                setStatus('stopping');
                setStage('Stopping');
                setStopSubmitting(false);
                break;
              case 'stopped':
                setStatus('stopped');
                setStage('Stopped');
                setStopSubmitting(false);
                stopPolling();
                source?.close();
                break;
              case 'completed':
                setStatus('completed');
                setProgress(100);
                setStage('Completed');
                setStopSubmitting(false);
                stopPolling();
                source?.close();
                break;
              case 'error':
                setStatus('error');
                setStage('Failed');
                setErrorMsg(errorText || message || 'An error occurred');
                setStopSubmitting(false);
                source?.close();
                startPolling();
                break;
            }
          },
          () => {
            startPolling();
          },
        );
        startPolling();
      })
      .catch(() => {
        startPolling();
      });

    return () => {
      active = false;
      setStopSubmitting(false);
      stopPolling();
      source?.close();
    };
  }, [projectId]);

  // Resource load polling
  useEffect(() => {
    let active = true;
    const fetch = () => {
      api.resourceLoad()
        .then((data) => { if (active) setResourceLoad(data); })
        .catch(() => { /* non-critical */ });
    };
    fetch();
    const timer = window.setInterval(fetch, 8000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  // Auto-scroll logs
  useEffect(() => {
    const el = logContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  const statusToneClass = (() => {
    if (status === 'completed') return 'run-status-pill--completed';
    if (status === 'stopped') return 'run-status-pill--stopped';
    if (status === 'stopping') return 'run-status-pill--stopping';
    if (status === 'error') return 'run-status-pill--error';
    return 'run-status-pill--running';
  })();

  const statusLabel = (() => {
    if (status === 'completed') return 'Completed';
    if (status === 'stopped') return 'Stopped';
    if (status === 'stopping') return 'Stopping';
    if (status === 'error') return 'Failed';
    return 'Running';
  })();
  const latestLog = logs.length ? logs[logs.length - 1] : null;
  const canStop = Boolean(projectId && (status === 'running' || status === 'stopping'));

  const handleStop = async () => {
    if (!projectId || stopSubmitting || status === 'stopping') return;
    setStopSubmitting(true);
    setErrorMsg('');
    try {
      const updated = await api.stopProject(projectId);
      syncProjectState(updated);
      setLogs((prev) => [
        ...prev,
        {
          timestamp: formatTimestamp(Date.now() / 1000),
          message: 'Stop requested. Waiting for the workflow to exit cleanly.',
          type: 'stop_requested',
        },
      ]);
      setStatus('stopping');
      setStage('Stopping');
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to stop the run');
      setStopSubmitting(false);
    }
  };

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
            Back to upload
          </button>
          <p className="page-eyebrow">Step 3 of 3</p>
          <h1 className="page-title">Processing in progress.</h1>
          <p className="page-lede">
            This page follows the live backend run. Progress, stage changes, and log entries stay attached
            to the project so you can see what happened before opening the final result files.
          </p>
        </header>

        <div className="run-layout">
          <section className="run-main">
            <article className="run-status-card">
              <div className="run-status-card__top" role="status" aria-live="polite">
                <div className={`run-status-pill ${statusToneClass}`}>
                  {status === 'running' && (
                    <Activity className="w-5 h-5 animate-pulse" aria-hidden />
                  )}
                  {status === 'stopping' && (
                    <Activity className="w-5 h-5 animate-pulse" aria-hidden />
                  )}
                  {status === 'stopped' && (
                    <Square className="w-5 h-5" aria-hidden />
                  )}
                  {status === 'completed' && (
                    <CheckCircle2 className="w-5 h-5" aria-hidden />
                  )}
                  {status === 'error' && (
                    <XCircle className="w-5 h-5" aria-hidden />
                  )}
                  <span>{statusLabel}</span>
                </div>
                <div className="run-progress-meta">
                  {Math.round(progress)}% complete
                </div>
              </div>

              <div className="run-progress-block">
                <div className="run-progress-row">
                  <span>Current stage</span>
                  <span>{stage}</span>
                </div>
                <div className="run-progress-bar" aria-hidden="true">
                  <div
                    className="run-progress-bar__fill"
                    style={{ width: `${progress}%`, transition: 'width 0.5s ease-out' }}
                  />
                </div>
              </div>

              <div className="run-live-note">
                Live events arrive over SSE. Reloading the page may interrupt the live stream, but the
                project and its output files remain attached to this session until you remove them.
              </div>

              {canStop && (
                <div className="run-action-row">
                  <button
                    type="button"
                    onClick={() => void handleStop()}
                    disabled={stopSubmitting || status === 'stopping'}
                    className="run-cta run-cta--secondary"
                  >
                    {status === 'stopping' ? 'Stop requested' : 'Stop run'}
                  </button>
                </div>
              )}
            </article>

            <article className="run-log-card">
              <h2 className="run-log-card__title">Activity log</h2>
              <p className="run-log-card__body">
                Server events are appended here as the workflow moves through parsing, retrieval, metadata
                drafting, and validation.
              </p>
              <div
                ref={logContainerRef}
                role="log"
                aria-live="polite"
                aria-relevant="additions"
                className="run-log-stream"
              >
                {logs.length === 0 ? (
                  <div className="run-log-line">
                    <span className="run-log-line__time">--:--:--</span>
                    <span className="run-log-line__message">Waiting for events…</span>
                  </div>
                ) : (
                  logs.map((entry, i) => (
                    <div key={`${entry.timestamp}-${i}`} className="run-log-line">
                      <span className="run-log-line__time">{entry.timestamp}</span>
                      <span className={`run-log-line__message run-log-line__message--${entry.type}`}>
                        {entry.message}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </article>
          </section>

          <aside className="run-aside run-aside--sticky">
            <article className="run-sidebar-card">
              <h2 className="run-sidebar-card__title">Project</h2>
              <p className="run-sidebar-card__body">
                {project?.project_name || 'Processing run'}
              </p>
              <div className="run-metric-grid">
                <div className="run-metric">
                  <p className="run-metric__label">Input file</p>
                  <p className="run-metric__value run-metric__value--file">
                    {project?.filename
                      ? project.filename.split('/').pop()
                      : '—'}
                  </p>
                </div>
                <div className="run-metric">
                  <p className="run-metric__label">Project ID</p>
                  <p className="run-metric__value">{projectId}</p>
                </div>
                <div className="run-metric">
                  <p className="run-metric__label">Stage</p>
                  <p className="run-metric__value">{stage}</p>
                </div>
                <div className="run-metric">
                  <p className="run-metric__label">Session UUID <span className="run-metric__hint">(copy to recover)</span></p>
                  <p
                    className="run-metric__value run-metric__value--copyable"
                    title="Click to copy"
                    onClick={() => navigator.clipboard?.writeText(session.id).catch(() => {})}
                  >{session.id}</p>
                </div>
                <div className="run-metric">
                  <p className="run-metric__label">Latest event</p>
                  <p className="run-metric__value">
                    {latestLog ? latestLog.message : 'Workflow started'}
                  </p>
                </div>
              </div>
            </article>

            {resourceLoad && (
              <article className="run-sidebar-card">
                <h2 className="run-sidebar-card__title">Server load</h2>
                <div className="run-resource-grid">
                  <div className="run-resource">
                    <div className="run-resource__header">
                      <span className="run-resource__label">CPU</span>
                      <span className="run-resource__value">{resourceLoad.cpu_pct}%</span>
                    </div>
                    <div className="run-resource__bar">
                      <div
                        className={`run-resource__fill ${resourceLoad.cpu_pct >= 90 ? 'run-resource__fill--high' : resourceLoad.cpu_pct >= 60 ? 'run-resource__fill--mid' : ''}`}
                        style={{ width: `${resourceLoad.cpu_pct}%` }}
                      />
                    </div>
                  </div>
                  <div className="run-resource">
                    <div className="run-resource__header">
                      <span className="run-resource__label">Memory</span>
                      <span className="run-resource__value">
                        {resourceLoad.memory_pct}% · {resourceLoad.memory_used_gb}/{resourceLoad.memory_total_gb} GB
                      </span>
                    </div>
                    <div className="run-resource__bar">
                      <div
                        className={`run-resource__fill ${resourceLoad.memory_pct >= 90 ? 'run-resource__fill--high' : resourceLoad.memory_pct >= 70 ? 'run-resource__fill--mid' : ''}`}
                        style={{ width: `${resourceLoad.memory_pct}%` }}
                      />
                    </div>
                  </div>
                  <div className="run-resource">
                    <div className="run-resource__header">
                      <span className="run-resource__label">Disk</span>
                      <span className="run-resource__value">{resourceLoad.disk_pct}%</span>
                    </div>
                    <div className="run-resource__bar">
                      <div
                        className={`run-resource__fill ${resourceLoad.disk_pct >= 90 ? 'run-resource__fill--high' : resourceLoad.disk_pct >= 70 ? 'run-resource__fill--mid' : ''}`}
                        style={{ width: `${resourceLoad.disk_pct}%` }}
                      />
                    </div>
                  </div>
                  {typeof resourceLoad.gpu_util_pct === 'number' && (
                    <div className="run-resource">
                      <div className="run-resource__header">
                        <span className="run-resource__label">GPU</span>
                        <span className="run-resource__value">
                          {resourceLoad.gpu_util_pct}%
                          {resourceLoad.gpu_memory_used_gb != null &&
                          resourceLoad.gpu_memory_total_gb != null &&
                          resourceLoad.gpu_memory_total_gb > 0
                            ? ` · VRAM ${resourceLoad.gpu_memory_used_gb}/${resourceLoad.gpu_memory_total_gb} GB`
                            : ''}
                        </span>
                      </div>
                      <div className="run-resource__bar">
                        <div
                          className={`run-resource__fill ${resourceLoad.gpu_util_pct >= 90 ? 'run-resource__fill--high' : resourceLoad.gpu_util_pct >= 60 ? 'run-resource__fill--mid' : ''}`}
                          style={{ width: `${resourceLoad.gpu_util_pct}%` }}
                        />
                      </div>
                    </div>
                  )}
                  <div className="run-resource run-resource--inline">
                    <span
                      className="run-resource__label"
                      title="Workflow jobs pending or running under this page’s session (same Session UUID), not all users on the server."
                    >
                      Session runs (active)
                    </span>
                    <span className="run-resource__badge">{resourceLoad.active_runs}</span>
                  </div>
                </div>
              </article>
            )}

            {status === 'error' && errorMsg && (
              <article className="run-sidebar-card">
                <h2 className="run-sidebar-card__title">Run issue</h2>
                <p className="run-sidebar-card__body">{errorMsg}</p>
              </article>
            )}

            {(status === 'completed' || status === 'stopped') && (
              <button
                onClick={() => navigate(buildAppRoute(`/result/${projectId}`))}
                className="run-cta run-cta--gradient"
              >
                View results
                <ArrowRight className="w-4 h-4" />
              </button>
            )}

            {status === 'error' && (
              <button
                onClick={() => navigate(buildAppRoute('/upload'))}
                className="run-cta"
              >
                Try again
              </button>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}
