import { getSessionHeaders, withSessionApiPath, type WebSession } from '../utils/session';

type JsonObject = Record<string, unknown>;

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

  getProject: (id: string) =>
    request<ProjectResponse>(`/projects/${id}`),

  getProjectInSession: (id: string, session: WebSession) =>
    request<ProjectResponse>(`/projects/${id}`, undefined, session),

  deleteProject: (id: string) =>
    request<{ message: string }>(`/projects/${id}`, { method: 'DELETE' }),

  stopProject: (id: string) =>
    request<ProjectResponse>(`/projects/${id}/stop`, { method: 'POST' }),

  memoryCloud: (id: string) =>
    request<MemoryCloud>(`/projects/${id}/memory-cloud`),

  listArtifacts: (id: string) =>
    request<{ project_id: string; artifacts: ArtifactInfo[] }>(`/projects/${id}/artifacts`),

  getArtifactUrl: (id: string, name: string) =>
    `${API_BASE}${withSessionApiPath(`/projects/${id}/artifacts/${name
      .split('/')
      .map((segment) => encodeURIComponent(segment))
      .join('/')}`)}`,

  subscribeEvents: (
    id: string,
    onEvent: (event: WorkflowEvent) => void,
    onError?: (err: Event) => void,
  ): EventSource => {
    const source = new EventSource(`${API_BASE}${withSessionApiPath(`/projects/${id}/events`)}`);
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
