import { useCallback, useState } from 'react';
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';
import { api } from '../api/client';
import type { WebSession } from '../utils/session';
import {
  formatMessageType,
  parseAgentMessageLog,
  type AgentMessageLogEntry,
} from '../types/agentHandoff';

interface AgentMessagesPanelProps {
  projectId: string;
  session: WebSession;
  logAvailable: boolean;
}

function formatTimestamp(value?: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export default function AgentMessagesPanel({
  projectId,
  session,
  logAvailable,
}: AgentMessagesPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [messages, setMessages] = useState<AgentMessageLogEntry[]>([]);
  const [loaded, setLoaded] = useState(false);

  const loadMessages = useCallback(async () => {
    if (!logAvailable || loaded || loading) return;
    setLoading(true);
    setError('');
    try {
      const text = await api.fetchArtifactText(projectId, 'processing_log.jsonl', session);
      setMessages(parseAgentMessageLog(text));
      setLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load processing log');
      setMessages([]);
      setLoaded(true);
    } finally {
      setLoading(false);
    }
  }, [loaded, loading, logAvailable, projectId, session]);

  const handleToggle = () => {
    const next = !expanded;
    setExpanded(next);
    if (next) {
      void loadMessages();
    }
  };

  return (
    <article className="page-card" id="agent-messages-panel">
      <button
        type="button"
        className="result-handoff-toggle"
        onClick={handleToggle}
        aria-expanded={expanded}
      >
        <div className="result-handoff-toggle__text">
          <p className="page-card__eyebrow">Audit trail</p>
          <h2 className="page-card__title result-handoff-toggle__title">
            Agent message log
          </h2>
          <p className="page-card__body">
            Individual A2A messages recorded in processing_log.jsonl at workflow finalization.
          </p>
        </div>
        {expanded ? (
          <ChevronDown className="w-5 h-5" aria-hidden="true" />
        ) : (
          <ChevronRight className="w-5 h-5" aria-hidden="true" />
        )}
      </button>

      {expanded && (
        <div className="result-handoff-log">
          {!logAvailable && (
            <p className="result-handoff-empty">
              processing_log.jsonl is not listed for this project.
            </p>
          )}

          {logAvailable && loading && (
            <div className="result-handoff-log__loading" role="status">
              <RefreshCw className="w-4 h-4 result-empty-state__spinner" aria-hidden="true" />
              <span>Loading agent messages…</span>
            </div>
          )}

          {logAvailable && !loading && error && (
            <p className="result-alert__item">{error}</p>
          )}

          {logAvailable && !loading && !error && messages.length === 0 && loaded && (
            <p className="result-handoff-empty">
              No agent_message events found in the processing log. The run may predate A2A
              logging or A2A was disabled.
            </p>
          )}

          {logAvailable && !loading && messages.length > 0 && (
            <div className="result-handoff-table-wrap">
              <table className="result-summary-table" aria-label="Agent message log">
                <thead>
                  <tr>
                    <th scope="col">From</th>
                    <th scope="col">To</th>
                    <th scope="col">Type</th>
                    <th scope="col">Acked by</th>
                    <th scope="col">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {messages.map((msg) => (
                    <tr key={msg.message_id || `${msg.from_agent}-${msg.timestamp}`}>
                      <td>{msg.from_agent || '—'}</td>
                      <td>{msg.to_agent || '—'}</td>
                      <td>{msg.message_type ? formatMessageType(msg.message_type) : '—'}</td>
                      <td>
                        {msg.acked_by && msg.acked_by.length > 0
                          ? msg.acked_by.join(', ')
                          : '—'}
                      </td>
                      <td>{formatTimestamp(msg.timestamp)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
