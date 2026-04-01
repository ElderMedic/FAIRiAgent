import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowLeft,
  Brain,
  CheckCircle2,
  ChevronDown,
  Cpu,
  Database,
  Play,
  RefreshCw,
  Server,
  Wrench,
} from 'lucide-react';
import {
  api,
  type ConfigOverrides,
  type DemoOptions,
  type OllamaModelsResponse,
  type ServiceStatus,
  type SystemStatus,
} from '../api/client';
import { usePageTitle } from '../hooks/usePageTitle';
import './InteriorPages.css';

const LLM_PROVIDERS = [
  { value: '', label: 'Server default' },
  { value: 'qwen', label: 'Qwen' },
  { value: 'gemini', label: 'Google Gemini' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'ollama', label: 'Ollama' },
  { value: 'anthropic', label: 'Anthropic' },
];

const OLLAMA_CUSTOM_VALUE = '__custom__';
const SERVICE_ORDER = ['mineru', 'fair_ds', 'ollama', 'qdrant', 'mem0'];

function readConfigString(
  source: SystemStatus['active_config'] | undefined,
  key: string,
  fallback: string,
) {
  const value = source?.[key];
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function statusClasses(status: string) {
  if (status === 'ready') {
    return {
      badge: 'bg-success/12 text-success border-success/20',
      card: 'border-success/20 bg-white shadow-[0_18px_40px_-30px_rgba(0,196,140,0.65)]',
      icon: 'text-success bg-success/12',
    };
  }
  if (status === 'disabled') {
    return {
      badge: 'bg-surface-tertiary text-text-secondary border-border',
      card: 'border-border bg-white',
      icon: 'text-text-secondary bg-surface-secondary',
    };
  }
  return {
    badge: 'bg-warning/12 text-warning border-warning/20',
    card: 'border-warning/20 bg-white shadow-[0_18px_40px_-30px_rgba(245,166,35,0.65)]',
    icon: 'text-warning bg-warning/12',
  };
}

function getServiceIcon(name: string) {
  switch (name) {
    case 'mem0':
      return Brain;
    case 'fair_ds':
    case 'qdrant':
      return Database;
    case 'ollama':
      return Cpu;
    case 'mineru':
      return Wrench;
    default:
      return Server;
  }
}

function prettifyDetailKey(key: string) {
  return key.replace(/_/g, ' ');
}

function formatDetailValue(value: unknown) {
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  if (value === null || value === undefined || value === '') {
    return 'n/a';
  }
  return String(value);
}

function serviceDetailEntries(service: ServiceStatus) {
  const details = service.details || {};
  const preferredKeys: Record<string, string[]> = {
    ollama: ['base_url_reachable', 'default_model_available', 'model_count', 'default_model'],
    mineru: ['cli_detected', 'server_reachable', 'cli_path', 'backend', 'timeout_seconds'],
    fair_ds: ['api_root_reachable', 'timeout_seconds', 'last_error'],
    qdrant: ['reachable', 'host', 'port', 'collection'],
    mem0: [
      'package_installed',
      'qdrant_reachable',
      'provider',
      'llm_model',
      'memory_llm_reachable',
      'memory_model_available',
      'embedding_provider',
      'embedding_model',
    ],
  };
  const keys = preferredKeys[service.name] || Object.keys(details);
  return keys
    .filter((key) => details[key] !== undefined && details[key] !== null && details[key] !== '')
    .map((key) => ({
      key,
      label: prettifyDetailKey(key),
      value: formatDetailValue(details[key]),
    }));
}

function serviceSummary(service: ServiceStatus) {
  const details = service.details || {};
  if (service.name === 'mem0') {
    return [
      `provider ${String(details.provider || 'n/a')}`,
      `model ${String(details.llm_model || 'n/a')}`,
      `embed ${String(details.embedding_model || 'n/a')}`,
    ];
  }
  if (service.name === 'ollama') {
    return [
      `models ${String(details.model_count ?? 0)}`,
      `default ${String(details.default_model || 'n/a')}`,
    ];
  }
  if (service.name === 'mineru') {
    return [
      `backend ${String(details.backend || 'n/a')}`,
      `cli ${details.cli_detected ? 'detected' : 'missing'}`,
    ];
  }
  if (service.name === 'qdrant') {
    return [`collection ${String(details.collection || 'n/a')}`];
  }
  return Object.entries(details)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .slice(0, 2)
    .map(([key, value]) => `${prettifyDetailKey(key)} ${String(value)}`);
}

export default function Config() {
  usePageTitle('Configuration');
  const navigate = useNavigate();
  const location = useLocation();
  const { file, projectName, demoMode, sampleDocumentKey, demoOptions } = (location.state as {
    file?: File;
    projectName?: string;
    demoMode?: boolean;
    sampleDocumentKey?: string;
    demoOptions?: DemoOptions;
  }) || {};

  const [config, setConfig] = useState<ConfigOverrides>(() => ({
    llm_provider: demoOptions?.default_ollama_provider,
    llm_model: demoOptions?.default_ollama_model,
    llm_base_url: demoOptions?.default_ollama_base_url,
  }));
  const [ollamaTagMode, setOllamaTagMode] = useState<'preset' | 'custom'>('preset');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState('');
  const [ollamaModels, setOllamaModels] = useState<OllamaModelsResponse | null>(null);
  const [ollamaLoading, setOllamaLoading] = useState(false);
  const [ollamaError, setOllamaError] = useState('');

  const resolvedOllamaBaseUrl = (config.llm_base_url || demoOptions?.default_ollama_base_url || '').trim();

  const orderedServices = useMemo(() => {
    if (!systemStatus) {
      return [];
    }
    return [...systemStatus.services].sort((left, right) => {
      const leftIndex = SERVICE_ORDER.indexOf(left.name);
      const rightIndex = SERVICE_ORDER.indexOf(right.name);
      return (leftIndex === -1 ? 999 : leftIndex) - (rightIndex === -1 ? 999 : rightIndex);
    });
  }, [systemStatus]);

  const readyServiceCount = orderedServices.filter((service) => service.status === 'ready').length;
  const activeWarnings = orderedServices.filter((service) => service.status === 'warning');
  const preflightBlockedByOllama = config.llm_provider === 'ollama';

  const loadSystemStatus = async () => {
    setStatusLoading(true);
    setStatusError('');
    try {
      const result = await api.systemStatus();
      setSystemStatus(result);
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : 'Failed to load system status');
    } finally {
      setStatusLoading(false);
    }
  };

  const loadOllamaModels = async (baseUrl: string) => {
    if (!baseUrl) {
      setOllamaModels(null);
      setOllamaError('');
      return;
    }
    setOllamaLoading(true);
    setOllamaError('');
    try {
      const result = await api.ollamaModels(baseUrl);
      setOllamaModels(result);
      if (!result.reachable) {
        setOllamaError(result.message);
      }
    } catch (err) {
      setOllamaModels(null);
      setOllamaError(err instanceof Error ? err.message : 'Failed to load Ollama model tags');
    } finally {
      setOllamaLoading(false);
    }
  };

  useEffect(() => {
    void loadSystemStatus();
  }, []);

  useEffect(() => {
    if (config.llm_provider !== 'ollama') {
      return;
    }
    const timer = window.setTimeout(() => {
      void loadOllamaModels(resolvedOllamaBaseUrl);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [config.llm_provider, resolvedOllamaBaseUrl]);

  useEffect(() => {
    if (config.llm_provider !== 'ollama' || !ollamaModels || !config.llm_model) {
      return;
    }
    if (!ollamaModels.models.length) {
      return;
    }
    const modelNames = ollamaModels.models.map((model) => model.name);
    setOllamaTagMode(modelNames.includes(config.llm_model) ? 'preset' : 'custom');
  }, [config.llm_provider, config.llm_model, ollamaModels]);

  const ollamaStartBlockedReason = useMemo(() => {
    if (!preflightBlockedByOllama) {
      return '';
    }
    if (!resolvedOllamaBaseUrl) {
      return 'Provide an Ollama base URL before starting.';
    }
    if (ollamaLoading) {
      return 'Checking Ollama availability before launch.';
    }
    if (!ollamaModels && !ollamaError) {
      return 'Waiting for Ollama preflight check.';
    }
    if (ollamaError) {
      return ollamaError;
    }
    if (ollamaModels && !ollamaModels.reachable) {
      return ollamaModels.message;
    }
    if (ollamaTagMode === 'custom' && !(config.llm_model || '').trim()) {
      return 'Enter a custom Ollama tag before starting.';
    }
    return '';
  }, [
    config.llm_model,
    ollamaError,
    ollamaLoading,
    ollamaModels,
    ollamaTagMode,
    preflightBlockedByOllama,
    resolvedOllamaBaseUrl,
  ]);

  if (!file && !sampleDocumentKey && !demoMode) {
    return (
      <div className="min-h-screen pt-24 pb-16 px-6 bg-surface-secondary flex items-center justify-center">
        <div className="text-center">
          <p className="text-text-secondary mb-4">No file selected. Please upload a document first (or enable Demo mode).</p>
          <button
            onClick={() => navigate('/upload')}
            className="px-6 py-2.5 rounded-xl text-sm font-semibold text-white bg-primary hover:bg-primary-dark transition-colors cursor-pointer"
          >
            Go to Upload
          </button>
        </div>
      </div>
    );
  }

  const update = (key: keyof ConfigOverrides, value: string) => {
    setConfig((prev) => ({ ...prev, [key]: value || undefined }));
  };

  const handleProviderChange = (value: string) => {
    setConfig((prev) => ({
      ...prev,
      llm_provider: value || undefined,
      llm_base_url: value === 'ollama'
        ? prev.llm_base_url || demoOptions?.default_ollama_base_url
        : prev.llm_base_url,
      llm_model: value === 'ollama'
        ? prev.llm_model || demoOptions?.default_ollama_model
        : prev.llm_model,
    }));
    if (value === 'ollama' && !config.llm_model) {
      setOllamaTagMode('preset');
    }
  };

  const handleStart = async () => {
    if (ollamaStartBlockedReason) {
      setError(`Start blocked: ${ollamaStartBlockedReason}`);
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const hasOverrides = Object.values(config).some(Boolean);
      const result = await api.createProject({
        file,
        sampleDocument: sampleDocumentKey,
        projectName,
        configOverrides: hasOverrides ? config : undefined,
        demo: !!demoMode,
      });
      navigate(`/run/${result.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create project');
      setSubmitting(false);
    }
  };

  const ollamaSelectValue = ollamaTagMode === 'custom' ? OLLAMA_CUSTOM_VALUE : config.llm_model || '';
  const startDisabled = submitting || Boolean(ollamaStartBlockedReason);
  const selectedInputTitle = file
    ? file.name
    : sampleDocumentKey
      ? `Bundled sample: ${sampleDocumentKey}`
      : 'Demo mode';
  const selectedInputMeta = projectName || 'Unnamed project';

  return (
    <div className="page-frame">
      <div className="page-shell page-stack">
        <header className="page-header">
          <button
            type="button"
            onClick={() => navigate('/upload')}
            className="page-backlink"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to upload
          </button>
          <p className="page-eyebrow">Step 2 of 3</p>
          <h1 className="page-title">Review environment and launch the run.</h1>
          <p className="page-lede">
            Verify local services, choose the workflow model, and start the backend run from a clean,
            readable control surface. Live checks update before launch so the page reflects the actual state
            of MinerU, FAIR-DS, Ollama, Qdrant, and memory tooling.
          </p>
        </header>

        <div className="config-layout">
          <section className="config-main">
            <div className="page-card">
              <div className="page-card__header">
                <div>
                  <p className="page-card__eyebrow">Launch Configuration</p>
                  <h2 className="page-card__title">Workflow inputs</h2>
                </div>
              </div>

              <div className="config-panel">
                <div className="config-hero-note">
                  Demo presets only prefill inputs. Submitting this page still starts the real backend
                  workflow and streams the real processing log.
                </div>

                <div className="config-field">
                  <label htmlFor="llm_provider" className="config-field__label">
                    LLM Provider
                  </label>
                  <div className="config-select-wrap">
                    <select
                      id="llm_provider"
                      value={config.llm_provider || ''}
                      onChange={(e) => handleProviderChange(e.target.value)}
                      className="config-select"
                    >
                      {LLM_PROVIDERS.map((provider) => (
                        <option key={provider.value} value={provider.value}>
                          {provider.label}
                        </option>
                      ))}
                    </select>
                    <ChevronDown className="config-select-icon" />
                  </div>
                </div>

                <div className="config-field-grid config-field-grid--split">
                  <div className="config-field">
                    <label htmlFor="llm_base_url" className="config-field__label">
                      LLM Base URL
                    </label>
                    <div className="config-inline-input">
                      <input
                        id="llm_base_url"
                        type="text"
                        value={config.llm_base_url || ''}
                        onChange={(e) => update('llm_base_url', e.target.value)}
                        placeholder="e.g. http://localhost:11434 or https://api.openai.com/v1"
                        className="config-input"
                      />
                      {config.llm_provider === 'ollama' && (
                        <button
                          type="button"
                          onClick={() => void loadOllamaModels(resolvedOllamaBaseUrl)}
                          className="config-inline-action"
                        >
                          <RefreshCw className={ollamaLoading ? 'animate-spin' : ''} />
                          Refresh
                        </button>
                      )}
                    </div>
                    {config.llm_provider === 'ollama' && (
                      <p className="config-field__hint">
                        The tag list is pulled from{' '}
                        <strong>{resolvedOllamaBaseUrl || 'your Ollama base URL'}</strong>.
                      </p>
                    )}
                  </div>

                  <div className="config-field">
                    <label htmlFor="fair_ds_api_url" className="config-field__label">
                      FAIR-DS API URL
                    </label>
                    <input
                      id="fair_ds_api_url"
                      type="text"
                      value={config.fair_ds_api_url || ''}
                      onChange={(e) => update('fair_ds_api_url', e.target.value)}
                      placeholder="https://fair-ds.example.com/api"
                      className="config-input"
                    />
                    <p className="config-field__hint">
                      Leave blank to use the endpoint already configured on the server.
                    </p>
                  </div>
                </div>

                {config.llm_provider === 'ollama' ? (
                  <div className="config-live-panel">
                    <div className="page-card__header">
                      <div>
                        <p className="page-card__eyebrow">Live Ollama Registry</p>
                        <h3 className="page-card__title">Model tag selection</h3>
                        <p className="page-card__body">
                          Pick a detected tag from the local registry, or switch to a custom tag if you want
                          to test a model name manually.
                        </p>
                      </div>
                      <div
                        className={`config-badge ${
                          ollamaModels?.reachable ? 'config-badge--success' : 'config-badge--warning'
                        }`}
                      >
                        {ollamaModels?.reachable ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                        {ollamaModels?.reachable ? `${ollamaModels.models.length} tags loaded` : 'Registry not reachable'}
                      </div>
                    </div>

                    <div className="config-field-grid config-field-grid--split">
                      <div className="config-field">
                        <label htmlFor="ollama_model_tag" className="config-field__label">
                          Ollama Model Tag
                        </label>
                        <div className="config-select-wrap">
                          <select
                            id="ollama_model_tag"
                            value={ollamaSelectValue}
                            onChange={(e) => {
                              if (e.target.value === OLLAMA_CUSTOM_VALUE) {
                                setOllamaTagMode('custom');
                                if (ollamaModels?.models.some((model) => model.name === config.llm_model)) {
                                  update('llm_model', '');
                                }
                                return;
                              }
                              setOllamaTagMode('preset');
                              update('llm_model', e.target.value);
                            }}
                            className="config-select"
                            disabled={ollamaLoading}
                          >
                            <option value="">Use server default tag</option>
                            {ollamaModels?.models.map((model) => (
                              <option key={model.name} value={model.name}>
                                {model.name}
                              </option>
                            ))}
                            <option value={OLLAMA_CUSTOM_VALUE}>Custom tag…</option>
                          </select>
                          <ChevronDown className="config-select-icon" />
                        </div>
                      </div>

                      <div className="config-summary-card">
                        <p className="config-summary-card__label">Registry Message</p>
                        <p className="config-summary-card__value">
                          {ollamaLoading
                            ? 'Fetching model tags…'
                            : ollamaModels?.message || ollamaError || 'No Ollama lookup performed yet.'}
                        </p>
                      </div>
                    </div>

                    {ollamaTagMode === 'custom' && (
                      <div className="config-field">
                        <label htmlFor="custom_ollama_tag" className="config-field__label">
                          Custom Ollama Tag
                        </label>
                        <input
                          id="custom_ollama_tag"
                          type="text"
                          value={config.llm_model || ''}
                          onChange={(e) => update('llm_model', e.target.value)}
                          placeholder="e.g. qwen3:8b or llama3.2:latest"
                          className="config-input"
                        />
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="config-field">
                    <label htmlFor="llm_model" className="config-field__label">
                      LLM Model
                    </label>
                    <input
                      id="llm_model"
                      type="text"
                      value={config.llm_model || ''}
                      onChange={(e) => update('llm_model', e.target.value)}
                      placeholder="e.g. gpt-4.1, gemini-2.5-pro, qwen-plus-latest"
                      className="config-input"
                    />
                  </div>
                )}

                <div className="config-field">
                  <label htmlFor="llm_api_key" className="config-field__label">
                    LLM API Key
                  </label>
                  <input
                    id="llm_api_key"
                    type="password"
                    value={config.llm_api_key || ''}
                    onChange={(e) => update('llm_api_key', e.target.value)}
                    placeholder="sk-..."
                    className="config-input"
                  />
                </div>

                <div className="config-summary-grid">
                  <div className="config-summary-card">
                    <p className="config-summary-card__label">Workflow LLM</p>
                    <p className="config-summary-card__value">
                      {(config.llm_provider || readConfigString(systemStatus?.active_config, 'llm_provider', 'server default'))}
                      {' / '}
                      {(config.llm_model || readConfigString(systemStatus?.active_config, 'llm_model', 'server default'))}
                    </p>
                  </div>
                  <div className="config-summary-card">
                    <p className="config-summary-card__label">Memory Layer</p>
                    <p className="config-summary-card__value">
                      {systemStatus?.services.find((service) => service.name === 'mem0')?.message || 'No memory status yet'}
                    </p>
                  </div>
                </div>

                {ollamaStartBlockedReason && (
                  <div className="config-alert config-alert--warning">
                    <strong>Start blocked.</strong> {ollamaStartBlockedReason}
                  </div>
                )}

                {statusError && (
                  <div className="config-alert config-alert--error">
                    <strong>System check failed.</strong> {statusError}
                  </div>
                )}

                {ollamaError && config.llm_provider === 'ollama' && ollamaError !== ollamaStartBlockedReason && (
                  <div className="config-alert config-alert--warning">
                    <strong>Ollama lookup.</strong> {ollamaError}
                  </div>
                )}

                {error && (
                  <div className="config-alert config-alert--error">{error}</div>
                )}

                <button
                  onClick={handleStart}
                  disabled={startDisabled}
                  className="config-cta config-cta--full"
                >
                  {submitting ? (
                    <>
                      <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Creating project…
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4" />
                      Start Processing
                    </>
                  )}
                </button>
              </div>
            </div>
          </section>

          <aside className="config-aside config-aside--sticky">
            <div className="page-card page-card--soft">
              <div className="config-selected-input">
                <p className="config-selected-input__label">Selected Input</p>
                <p className="config-selected-input__title">{selectedInputTitle}</p>
                <p className="config-selected-input__meta">{selectedInputMeta}</p>
              </div>
            </div>

            <div className="page-card">
              <div className="config-toolbar">
                <div>
                  <p className="page-card__eyebrow">Integration Checks</p>
                  <h2 className="page-card__title">System status</h2>
                  <p className="page-card__body">
                    Live reachability for the local toolchain and memory path.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void loadSystemStatus()}
                  className="config-toolbar-button"
                >
                  <RefreshCw className={statusLoading ? 'animate-spin' : ''} />
                  Refresh
                </button>
              </div>

              <div className="config-summary-grid">
                <div className="config-summary-card">
                  <p className="config-summary-card__label">Overall</p>
                  <p className="config-summary-card__value">
                    {readyServiceCount}/{orderedServices.length || 0} services ready
                  </p>
                </div>
                <div className="config-summary-card">
                  <p className="config-summary-card__label">Attention</p>
                  <p className="config-summary-card__value">
                    {activeWarnings.length
                      ? `${activeWarnings.length} services need attention`
                      : 'All tracked services look reachable'}
                  </p>
                </div>
              </div>

              <div className="config-service-stack">
                {statusLoading && !orderedServices.length && (
                  <div className="config-alert">Checking local services…</div>
                )}

                {orderedServices.map((service) => {
                  const Icon = getServiceIcon(service.name);
                  const tone = statusClasses(service.status);
                  return (
                    <article
                      key={service.name}
                      className={`config-service-card config-service-card--${service.status} ${tone.card}`}
                    >
                      <div className="config-service-card__row">
                        <div className={`config-service-card__icon-wrap ${tone.icon}`}>
                          <Icon className="h-5 w-5" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="config-service-card__title-row">
                            <h3 className="config-service-card__title">{service.label}</h3>
                            <span className={`config-service-card__status config-service-card__status--${service.status} ${tone.badge}`}>
                              {service.status}
                            </span>
                          </div>
                          <p className="config-service-card__body">{service.message}</p>
                          {service.endpoint && (
                            <p className="config-service-card__endpoint">{service.endpoint}</p>
                          )}
                          {serviceSummary(service).length > 0 && (
                            <div className="config-chip-row">
                              {serviceSummary(service).map((item) => (
                                <span key={item} className="config-chip">
                                  {item}
                                </span>
                              ))}
                            </div>
                          )}
                          {serviceDetailEntries(service).length > 0 && (
                            <div className="config-detail-grid">
                              {serviceDetailEntries(service).map((item) => (
                                <div key={item.key} className="config-detail-card">
                                  <p className="config-detail-card__label">{item.label}</p>
                                  <p className="config-detail-card__value">{item.value}</p>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
