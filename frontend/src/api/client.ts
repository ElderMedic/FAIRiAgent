import { getSessionHeaders, withSessionApiPath, type WebSession } from '../utils/session';

type JsonObject = Record<string, unknown>;

export interface MetadataFieldPreview {
  field_name: string;
  value: unknown;
  confidence?: number;
  status?: string;
  status_reason?: string;
  evidence?: string;
  required?: boolean;
  requirement?: string;
}

export interface ISASheetData {
  description?: string;
  columns?: string[];
  rows?: Record<string, unknown>[];
  fields?: MetadataFieldPreview[];
}

export interface MetadataJSON {
  isa_structure: Record<string, ISASheetData>;
  [key: string]: unknown;
}

const API_BASE = '/api/v1';

export interface ProjectResponse {
  project_id: string;
  project_name?: string;
  filename?: string;
  input_files?: string[];
  session_id?: string;
  session_started_at?: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  stop_requested?: boolean;
  stop_requested_at?: string;
  confidence_scores?: Record<string, number>;
  needs_review?: boolean;
  errors?: string[];
  artifacts?: string[];
  message?: string;
  execution_summary?: JsonObject;
  quality_metrics?: JsonObject;
}

export interface DemoDocument {
  key: string;
  label: string;
  filename: string;
  description: string;
  size_bytes: number;
}

export interface DemoOptions {
  default_demo_document_key: string;
  default_ollama_provider: string;
  default_ollama_model: string;
  default_ollama_base_url: string;
  ollama_available: boolean;
  documents: DemoDocument[];
}

export interface ServiceStatus {
  name: string;
  label: string;
  enabled: boolean;
  reachable: boolean;
  status: string;
  message: string;
  endpoint?: string | null;
  details?: JsonObject | null;
}

export interface SystemStatus {
  timestamp: string;
  active_config: JsonObject;
  services: ServiceStatus[];
}

export interface OllamaModel {
  name: string;
  size?: number | null;
  digest?: string | null;
  modified_at?: string | null;
}

export interface OllamaModelsResponse {
  base_url: string;
  reachable: boolean;
  message: string;
  models: OllamaModel[];
}

export interface MemoryWord {
  text: string;
  value: number;
  category: string;
}

export interface MemoryCloud {
  session_words: MemoryWord[];
  scope_words: MemoryWord[];
  session_total: number;
  scope_total: number;
  memory_enabled: boolean;
}

export interface FAIRDSStatisticsTotals {
  packages: number;
  fields: number;
  mandatory_fields: number;
  recommended_fields: number;
  optional_fields: number;
  terms: number;
  unique_field_labels: number;
  packages_with_no_fields: number;
  terms_referenced_in_packages: number;
  mandatory_ratio: number;
}

export interface FAIRDSRequirementCount {
  requirement: string;
  count: number;
}

export interface FAIRDSISAStatistics {
  isa_level: string;
  fields: number;
  mandatory_fields: number;
  recommended_fields: number;
  optional_fields: number;
  packages_count: number;
}

export interface FAIRDSPackageStatistics {
  package_name: string;
  fields: number;
  mandatory_fields: number;
  recommended_fields: number;
  optional_fields: number;
  isa_level_count: number;
  term_linked_fields: number;
}

export interface FAIRDSTermStatistics {
  term: string;
  field_count: number;
}

export interface FAIRDSTermQuality {
  with_definition: number;
  with_example: number;
  with_regex: number;
  with_ontology_url: number;
}

export interface FAIRDSStatisticsResponse {
  available: boolean;
  api_url?: string | null;
  message: string;
  generated_at: string;
  totals: FAIRDSStatisticsTotals;
  requirement_distribution: FAIRDSRequirementCount[];
  isa_levels: FAIRDSISAStatistics[];
  package_leaderboard: FAIRDSPackageStatistics[];
  top_terms: FAIRDSTermStatistics[];
  term_quality: FAIRDSTermQuality;
}

export interface ResourceLoad {
  cpu_pct: number;
  memory_pct: number;
  memory_used_gb: number;
  memory_total_gb: number;
  disk_pct: number;
  /** Pending or running workflow projects for this browser session only. */
  active_runs: number;
  gpu_util_pct?: number | null;
  gpu_memory_used_gb?: number | null;
  gpu_memory_total_gb?: number | null;
}

export interface ArtifactInfo {
  name: string;
  size: number;
  available: boolean;
}

export interface ConfigOverrides {
  llm_provider?: string;
  llm_model?: string;
  llm_base_url?: string;
  llm_api_key?: string;
  fair_ds_api_url?: string;
}

export interface CreateProjectRequest {
  files?: File[];
  sampleDocument?: string;
  projectName?: string;
  configOverrides?: ConfigOverrides;
  demo?: boolean;
}

export interface WorkflowEvent {
  event_type: string;
  project_id: string;
  data: JsonObject;
  timestamp: number;
}

async function request<T>(path: string, options?: RequestInit, session?: WebSession): Promise<T> {
  const headers = new Headers(options?.headers);
  headers.set('Accept', 'application/json');
  const sessionHeaders = session
    ? {
        'X-FAIRifier-Session-Id': session.id,
        'X-FAIRifier-Session-Started-At': session.startedAt,
      }
    : getSessionHeaders();
  for (const [key, value] of Object.entries(sessionHeaders)) {
    headers.set(key, value);
  }
  // FormData must not carry an explicit Content-Type (browser sets boundary).
  if (typeof FormData !== 'undefined' && options?.body instanceof FormData) {
    headers.delete('Content-Type');
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .catch((): { detail: string } => ({ detail: res.statusText })) as { detail?: string };
    throw new Error(detail.detail || res.statusText);
  }
  return res.json();
}

function withResolvedSessionApiPath(path: string, session?: WebSession): string {
  if (!session) return withSessionApiPath(path);
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}session_id=${encodeURIComponent(session.id)}&session_started_at=${encodeURIComponent(session.startedAt)}`;
}

export const api = {
  health: () =>
    request<{ status: string; timestamp: string; version: string }>('/health'),

  demoOptions: () =>
    request<DemoOptions>('/demo-options'),

  systemStatus: () =>
    request<SystemStatus>('/system/status'),

  resourceLoad: () =>
    request<ResourceLoad>('/system/resource-load'),

  ollamaModels: (baseUrl?: string) =>
    request<OllamaModelsResponse>(
      `/system/ollama-models${baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : ''}`,
    ),

  fairdsStatistics: (options?: { refresh?: boolean; top?: number; packages?: number }) => {
    const query = new URLSearchParams();
    if (options?.refresh) query.set('refresh', 'true');
    if (typeof options?.top === 'number') query.set('top', String(options.top));
    if (typeof options?.packages === 'number') query.set('packages', String(options.packages));
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return request<FAIRDSStatisticsResponse>(`/fairds/statistics${suffix}`);
  },

  createProject: ({ files, sampleDocument, projectName, configOverrides, demo }: CreateProjectRequest) => {
    const form = new FormData();
    for (const file of files || []) {
      form.append('files', file);
    }
    if (sampleDocument) form.append('sample_document', sampleDocument);
    if (projectName) form.append('project_name', projectName);
    if (configOverrides) form.append('config_overrides', JSON.stringify(configOverrides));
    if (demo) form.append('demo', 'true');
    return request<ProjectResponse>('/projects', { method: 'POST', body: form });
  },

  listProjects: () =>
    request<{ projects: ProjectResponse[] }>('/projects'),

  getProject: (id: string, session?: WebSession) =>
    request<ProjectResponse>(`/projects/${id}`, undefined, session),

  getProjectInSession: (id: string, session: WebSession) =>
    request<ProjectResponse>(`/projects/${id}`, undefined, session),

  deleteProject: (id: string, session?: WebSession) =>
    request<{ message: string }>(`/projects/${id}`, { method: 'DELETE' }, session),

  stopProject: (id: string, session?: WebSession) =>
    request<ProjectResponse>(`/projects/${id}/stop`, { method: 'POST' }, session),

  memoryCloud: (id: string, session?: WebSession) =>
    request<MemoryCloud>(`/projects/${id}/memory-cloud`, undefined, session),

  listArtifacts: (id: string, session?: WebSession) =>
    request<{ project_id: string; artifacts: ArtifactInfo[] }>(`/projects/${id}/artifacts`, undefined, session),

  getArtifactUrl: (id: string, name: string, session?: WebSession) =>
    `${API_BASE}${withResolvedSessionApiPath(`/projects/${id}/artifacts/${name
      .split('/')
      .map((segment) => encodeURIComponent(segment))
      .join('/')}`, session)}`,

  subscribeEvents: (
    id: string,
    onEvent: (event: WorkflowEvent) => void,
    onError?: (err: Event) => void,
    session?: WebSession,
  ): EventSource => {
    const sessionPath = session
      ? `/projects/${id}/events?session_id=${encodeURIComponent(session.id)}&session_started_at=${encodeURIComponent(session.startedAt)}`
      : withSessionApiPath(`/projects/${id}/events`);
    const source = new EventSource(`${API_BASE}${sessionPath}`);
    const handleEvent = (e: MessageEvent) => {
      try {
        onEvent(JSON.parse(e.data) as WorkflowEvent);
      } catch {
        /* skip malformed */
      }
    };
    for (const t of ['log', 'progress', 'stage_change', 'completed', 'stopped', 'stop_requested', 'error']) {
      source.addEventListener(t, handleEvent);
    }
    if (onError) source.onerror = onError;
    return source;
  },
};
