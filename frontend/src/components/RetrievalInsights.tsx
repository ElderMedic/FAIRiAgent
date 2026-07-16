import { useEffect, useMemo, useState } from 'react';
import { Activity, DatabaseZap } from 'lucide-react';
import { api, type ArtifactInfo } from '../api/client';
import type { WebSession } from '../utils/session';
import HybridRetrievalFlow, { type RetrievalMetrics } from './HybridRetrievalFlow';

interface WorkflowReport {
  retrieval_metrics?: RetrievalMetrics;
  section_coverage?: {
    processed_sections?: number;
    sections_processed?: number;
    sections_total?: number;
    evidence_records?: number;
    field_candidates?: number;
  };
}

interface Props {
  projectId: string;
  session: WebSession;
  artifacts: ArtifactInfo[];
}

function safeNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

export default function RetrievalInsights({ projectId, session, artifacts }: Props) {
  const [reportState, setReportState] = useState<{ key: string; data: WorkflowReport | null }>({
    key: '',
    data: null,
  });
  const reportArtifact = useMemo(
    () => artifacts.find((artifact) => artifact.name === 'workflow_report.json' || artifact.name.endsWith('/workflow_report.json')),
    [artifacts],
  );
  const reportKey = `${projectId}:${reportArtifact?.name || ''}`;
  const report = reportState.key === reportKey ? reportState.data : null;

  useEffect(() => {
    let active = true;
    if (!reportArtifact?.available) {
      return () => { active = false; };
    }
    api.fetchArtifactText(projectId, reportArtifact.name, session)
      .then((text) => {
        if (!active) return;
        const parsed = JSON.parse(text) as WorkflowReport;
        setReportState({ key: reportKey, data: parsed });
      })
      .catch(() => {
        if (active) setReportState({ key: reportKey, data: null });
      });
    return () => { active = false; };
  }, [projectId, reportArtifact, reportKey, session]);

  const metrics = report?.retrieval_metrics;
  if (!metrics) return null;

  const coverage = report?.section_coverage;
  const processedSections = safeNumber(coverage?.processed_sections ?? coverage?.sections_processed);
  const totalSections = safeNumber(coverage?.sections_total ?? metrics.section_count);
  const evidenceCount = safeNumber(metrics.evidence_items ?? coverage?.evidence_records);

  return (
    <article className="page-card retrieval-insights">
      <div className="page-card__header">
        <div>
          <p className="page-card__eyebrow">Retrieval trace</p>
          <h2 className="page-card__title">How source evidence reached the metadata prompt</h2>
          <p className="page-card__body">
            Lexical matches are preferred when available. Semantic search fills lexical misses and degrades safely when Qdrant or embeddings are unavailable.
          </p>
        </div>
        <DatabaseZap className="page-card__icon" aria-hidden="true" />
      </div>

      <HybridRetrievalFlow metrics={metrics} />

      <div className="retrieval-insights__stats">
        <div>
          <Activity aria-hidden="true" />
          <span>Sections covered</span>
          <strong>{processedSections || totalSections}{totalSections ? ` / ${totalSections}` : ''}</strong>
        </div>
        <div>
          <DatabaseZap aria-hidden="true" />
          <span>Evidence records</span>
          <strong>{evidenceCount}</strong>
        </div>
        <div>
          <DatabaseZap aria-hidden="true" />
          <span>Semantic index</span>
          <strong>{metrics.qdrant_fallback_used ? 'Lexical fallback' : metrics.semantic_index_status || 'unknown'}</strong>
        </div>
      </div>
    </article>
  );
}
