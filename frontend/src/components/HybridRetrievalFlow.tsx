import { Database, FileSearch, GitMerge, Layers3, Search, Sparkles } from 'lucide-react';
import type { ServiceStatus, SystemStatus } from '../api/client';

export interface RetrievalMetrics {
  semantic_index_status?: string;
  semantic_index_available?: boolean;
  indexed_chunk_count?: number;
  chunk_count?: number;
  section_count?: number;
  evidence_items?: number;
  fields_with_retrieval_telemetry?: number;
  prompt_mode_counts?: Record<string, number>;
  rerank_status?: string;
  qdrant_fallback_used?: boolean;
}

interface Props {
  activeConfig?: SystemStatus['active_config'];
  qdrant?: ServiceStatus;
  metrics?: RetrievalMetrics;
  compact?: boolean;
}

function readBool(config: SystemStatus['active_config'] | undefined, key: string, fallback = true) {
  const value = config?.[key];
  return typeof value === 'boolean' ? value : fallback;
}

function sumModes(modes: Record<string, number> | undefined, needle: string) {
  return Object.entries(modes || {}).reduce(
    (total, [key, value]) => total + (key.toLowerCase().includes(needle) ? value : 0),
    0,
  );
}

export default function HybridRetrievalFlow({ activeConfig, qdrant, metrics, compact = false }: Props) {
  const semanticEnabled = readBool(activeConfig, 'semantic_index_enabled');
  const hybridEnabled = readBool(activeConfig, 'hybrid_retrieval_enabled');
  const mapReduceEnabled = readBool(activeConfig, 'mapreduce_enabled');
  const lexicalFirst = readBool(activeConfig, 'retrieval_prompt_adaptive_lexical');
  const semanticAvailable = metrics
    ? Boolean(metrics.semantic_index_available)
    : semanticEnabled && Boolean(qdrant?.reachable);
  const promptModes = metrics?.prompt_mode_counts || {};
  const lexicalFields = sumModes(promptModes, 'lexical');
  const semanticFields = sumModes(promptModes, 'semantic');

  const nodes = [
    {
      key: 'sources',
      icon: Layers3,
      title: 'Source workspace',
      detail: metrics?.section_count != null ? `${metrics.section_count} sections` : 'Paper + supplements',
      active: true,
    },
    {
      key: 'index',
      icon: Database,
      title: 'Chunk & index',
      detail: metrics?.indexed_chunk_count != null
        ? `${metrics.indexed_chunk_count} indexed chunks`
        : semanticAvailable ? 'Qdrant ready' : 'Lexical fallback ready',
      active: semanticAvailable || mapReduceEnabled,
    },
    {
      key: 'retrieve',
      icon: GitMerge,
      title: 'Hybrid retrieval',
      detail: hybridEnabled ? 'RRF + optional rerank' : 'Lexical only',
      active: hybridEnabled,
    },
    {
      key: 'prompt',
      icon: Sparkles,
      title: 'Grounded prompt',
      detail: metrics?.fields_with_retrieval_telemetry != null
        ? `${metrics.fields_with_retrieval_telemetry} fields searched`
        : lexicalFirst ? 'Lexical-first, semantic fallback' : 'Blended evidence',
      active: true,
    },
  ];

  return (
    <div className={`retrieval-flow ${compact ? 'retrieval-flow--compact' : ''}`}>
      <div className="retrieval-flow__nodes" aria-label="Hybrid retrieval pipeline">
        {nodes.map((node, index) => {
          const Icon = node.icon;
          return (
            <div className="retrieval-flow__step-wrap" key={node.key}>
              <div className={`retrieval-flow__node ${node.active ? 'is-active' : 'is-fallback'}`}>
                <Icon aria-hidden="true" />
                <span className="retrieval-flow__title">{node.title}</span>
                <span className="retrieval-flow__detail">{node.detail}</span>
              </div>
              {index < nodes.length - 1 && <span className="retrieval-flow__connector" aria-hidden="true" />}
            </div>
          );
        })}
      </div>

      <div className="retrieval-flow__channels">
        <div className="retrieval-flow__channel">
          <Search aria-hidden="true" />
          <span>Lexical</span>
          <strong>{metrics ? lexicalFields : 'primary'}</strong>
        </div>
        <div className={`retrieval-flow__channel ${semanticAvailable ? '' : 'is-muted'}`}>
          <FileSearch aria-hidden="true" />
          <span>Semantic fallback</span>
          <strong>{metrics ? semanticFields : semanticAvailable ? 'ready' : 'unavailable'}</strong>
        </div>
        {metrics?.rerank_status && (
          <div className="retrieval-flow__channel">
            <GitMerge aria-hidden="true" />
            <span>Reranker</span>
            <strong>{metrics.rerank_status}</strong>
          </div>
        )}
      </div>
    </div>
  );
}
