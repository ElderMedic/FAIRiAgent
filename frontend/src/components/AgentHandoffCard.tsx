import { ArrowLeftRight } from 'lucide-react';
import {
  formatMessageType,
  type AgentHandoffSummary,
} from '../types/agentHandoff';

interface AgentHandoffCardProps {
  handoff: AgentHandoffSummary | null;
}

export default function AgentHandoffCard({ handoff }: AgentHandoffCardProps) {
  const summary = handoff ?? {
    total_messages: 0,
    by_type: {},
    acked: 0,
    unacked: 0,
  };
  const typeEntries = Object.entries(summary.by_type).sort(
    (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
  );
  const hasMessages = summary.total_messages > 0;

  return (
    <article className="page-card" id="agent-handoff-card">
      <div className="page-card__header">
        <div>
          <p className="page-card__eyebrow">Coordination</p>
          <h2 className="page-card__title">Agent handoff (A2A)</h2>
          <p className="page-card__body">
            Structured messages passed between workflow agents — evidence bundles from
            document parsing and field-gap reports from knowledge retrieval.
          </p>
        </div>
        <ArrowLeftRight
          className="w-6 h-6"
          style={{ color: 'var(--color-primary)', opacity: 0.7 }}
          aria-hidden="true"
        />
      </div>

      <div className="result-grounding-grid">
        <div className="result-grounding-stat result-grounding-stat--neutral">
          <p className="result-grounding-stat__value">{summary.total_messages}</p>
          <p className="result-grounding-stat__label">Total messages</p>
        </div>
        <div className="result-grounding-stat result-grounding-stat--success">
          <p className="result-grounding-stat__value">{summary.acked}</p>
          <p className="result-grounding-stat__label">Acknowledged</p>
        </div>
        <div
          className={`result-grounding-stat ${
            summary.unacked > 0
              ? 'result-grounding-stat--warning'
              : 'result-grounding-stat--success'
          }`}
        >
          <p className="result-grounding-stat__value">{summary.unacked}</p>
          <p className="result-grounding-stat__label">Unacknowledged</p>
        </div>
      </div>

      {typeEntries.length > 0 ? (
        <ul className="result-handoff-types">
          {typeEntries.map(([type, count]) => (
            <li key={type} className="result-handoff-types__item">
              <span className="result-handoff-types__type">{formatMessageType(type)}</span>
              <span className="result-handoff-types__count">{count}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="result-handoff-empty">
          {hasMessages
            ? 'Message counts are available, but no type breakdown was recorded.'
            : 'No structured handoff messages for this run. A2A may be disabled (FAIRIFIER_ENABLE_A2A=false) or the workflow predates A2A support.'}
        </p>
      )}
    </article>
  );
}
