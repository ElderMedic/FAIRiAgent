import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Activity, CheckCircle2, XCircle, ArrowRight } from 'lucide-react';
import { api, type ProjectResponse, type WorkflowEvent } from '../api/client';
import { usePageTitle } from '../hooks/usePageTitle';

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

  const [stage, setStage] = useState('Initializing');
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<'running' | 'completed' | 'error'>('running');
  const [errorMsg, setErrorMsg] = useState('');

  const syncProjectState = (project: ProjectResponse) => {
    if (project.status === 'completed') {
      setStatus('completed');
      setProgress(100);
      setStage('Completed');
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
              case 'completed':
                setStatus('completed');
                setProgress(100);
                setStage('Completed');
                stopPolling();
                source?.close();
                break;
              case 'error':
                setStatus('error');
                setStage('Failed');
                setErrorMsg(errorText || message || 'An error occurred');
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
      stopPolling();
      source?.close();
    };
  }, [projectId]);

  // Auto-scroll logs
  useEffect(() => {
    const el = logContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  return (
    <div className="min-h-screen pt-20 sm:pt-24 pb-12 sm:pb-16 px-4 sm:px-6 bg-surface-secondary">
      <div className="w-full max-w-3xl mx-auto">
        <div className="w-full">
          <h1 className="text-3xl font-bold text-text-primary mb-2">Processing</h1>
          <p className="text-text-secondary mb-8">
            Project <code className="text-xs bg-surface-tertiary px-2 py-0.5 rounded font-mono">{projectId}</code>
          </p>

          <div className="w-full bg-surface rounded-2xl border border-border p-6 sm:p-8 shadow-sm space-y-6">
            <div className="bg-surface-secondary rounded-xl px-4 py-3 border border-border">
              <p className="text-xs text-text-secondary leading-relaxed">
                This page streams live events from the server (SSE). If you reload, you may lose the live log stream, but you can still
                open Results once the run completes.
              </p>
            </div>
            {/* Status header */}
            <div className="flex items-center gap-3" role="status" aria-live="polite">
              {status === 'running' && (
                <Activity className="w-5 h-5 text-primary animate-pulse" aria-hidden />
              )}
              {status === 'completed' && (
                <CheckCircle2 className="w-5 h-5 text-success" aria-hidden />
              )}
              {status === 'error' && (
                <XCircle className="w-5 h-5 text-error" aria-hidden />
              )}
              <span className="text-lg font-semibold text-text-primary leading-snug">{stage}</span>
              {status === 'running' && (
                <span className="ml-auto text-sm text-text-tertiary">
                  <span className="inline-flex gap-0.5">
                    <span className="animate-bounce">.</span>
                    <span className="animate-bounce [animation-delay:150ms]">.</span>
                    <span className="animate-bounce [animation-delay:300ms]">.</span>
                  </span>
                </span>
              )}
            </div>

            {/* Progress bar */}
            <div>
              <div className="flex justify-between text-xs text-text-tertiary mb-1.5">
                <span>Progress</span>
                <span aria-hidden="true">{Math.round(progress)}%</span>
              </div>
              <div className="h-2 bg-surface-tertiary rounded-full overflow-hidden" aria-hidden="true">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-primary to-accent"
                  style={{ width: `${progress}%`, transition: 'width 0.5s ease-out' }}
                />
              </div>
            </div>

            {/* Log area */}
            <div>
              <p className="text-sm font-medium text-text-primary mb-2">Activity Log</p>
              <div
                ref={logContainerRef}
                role="log"
                aria-live="polite"
                aria-relevant="additions"
                className="h-72 overflow-y-auto bg-bg-dark rounded-xl p-5 font-mono text-xs leading-relaxed"
              >
                {logs.length === 0 ? (
                  <p className="text-white/30">Waiting for events…</p>
                ) : (
                  logs.map((entry, i) => (
                    <div key={i} className="flex gap-3">
                      <span className="text-white/25 shrink-0 select-none">{entry.timestamp}</span>
                      <span
                        className={
                          entry.type === 'error'
                            ? 'text-red-400'
                            : entry.type === 'completed'
                              ? 'text-green-400'
                              : entry.type === 'stage_change'
                                ? 'text-blue-400'
                                : 'text-white/70'
                        }
                      >
                        {entry.message}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Error */}
            {status === 'error' && errorMsg && (
              <div className="bg-error/10 border border-error/20 rounded-xl px-4 py-3">
                <p className="text-sm text-error">{errorMsg}</p>
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-3">
              {status === 'completed' && (
                <button
                  onClick={() => navigate(`/result/${projectId}`)}
                  className="flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-xl
                    text-sm font-semibold text-white bg-gradient-to-r from-primary to-accent
                    hover:shadow-lg transition-shadow cursor-pointer"
                >
                  View Results
                  <ArrowRight className="w-4 h-4" />
                </button>
              )}
              {status === 'error' && (
                <button
                  onClick={() => navigate('/upload')}
                  className="flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-xl
                    text-sm font-semibold text-white bg-primary hover:bg-primary-dark
                    transition-colors cursor-pointer"
                >
                  Try Again
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
