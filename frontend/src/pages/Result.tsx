import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Download, CheckCircle2, XCircle, ArrowLeft, FileDown, RefreshCw } from 'lucide-react';
import { api, type ProjectResponse, type ArtifactInfo } from '../api/client';
import { usePageTitle } from '../hooks/usePageTitle';

function ScoreCard({ label, score }: { label: string; score: number }) {
  const pct = Math.round(score * 100);
  const color =
    pct >= 80 ? 'text-success' : pct >= 50 ? 'text-warning' : 'text-error';

  return (
    <div className="bg-surface-secondary rounded-xl p-4 border border-border">
      <p className="text-xs text-text-tertiary mb-1 capitalize">{label.replace(/_/g, ' ')}</p>
      <p className={`text-2xl font-bold ${color}`}>{pct}%</p>
      <div className="mt-2 h-1.5 bg-surface-tertiary rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${
            pct >= 80 ? 'bg-success' : pct >= 50 ? 'bg-warning' : 'bg-error'
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function Result() {
  usePageTitle('Results');
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [error, setError] = useState('');
  const [resolvedProjectId, setResolvedProjectId] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    Promise.all([
      api.getProject(projectId),
      api.listArtifacts(projectId).catch(() => ({ project_id: projectId, artifacts: [] })),
    ])
      .then(([proj, arts]) => {
        setProject(proj);
        setArtifacts(arts.artifacts);
        setError('');
        setResolvedProjectId(projectId);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load project');
        setResolvedProjectId(projectId);
      });
  }, [projectId]);

  const loading = Boolean(projectId) && resolvedProjectId !== projectId;
  const visibleError = resolvedProjectId === projectId ? error : '';

  if (loading) {
    return (
      <div
        className="min-h-screen pt-24 pb-16 px-6 bg-surface-secondary flex flex-col items-center justify-center gap-3"
        role="status"
        aria-live="polite"
      >
        <RefreshCw className="w-6 h-6 text-primary animate-spin" aria-hidden />
        <span className="text-sm text-text-secondary">Loading results…</span>
      </div>
    );
  }

  if (visibleError) {
    return (
      <div className="min-h-screen pt-24 pb-16 px-6 bg-surface-secondary flex items-center justify-center">
        <div className="text-center">
          <XCircle className="w-8 h-8 text-error mx-auto mb-3" />
          <p className="text-text-secondary mb-4">{visibleError}</p>
          <button
            onClick={() => navigate('/upload')}
            className="px-6 py-2.5 rounded-xl text-sm font-semibold text-white bg-primary hover:bg-primary-dark transition-colors cursor-pointer"
          >
            Upload New Document
          </button>
        </div>
      </div>
    );
  }

  if (!project) return null;

  const isCompleted = project.status === 'completed';
  const scores = project.confidence_scores || {};
  const summary = project.execution_summary || {};
  const formatSize = (size: number) => {
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="min-h-screen pt-20 sm:pt-24 pb-12 sm:pb-16 px-4 sm:px-6 bg-surface-secondary">
      <div className="w-full max-w-4xl mx-auto">
        <div className="w-full">
          <button
            onClick={() => navigate('/upload')}
            className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary mb-6 transition-colors cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4" />
            Process another document
          </button>

          {/* Header */}
          <div className="flex items-start gap-4 mb-8">
            <div className="flex-1">
              <h1 className="text-3xl font-bold text-text-primary mb-1">
                {project.project_name || 'Results'}
              </h1>
              <p className="text-sm text-text-secondary">
                Project {projectId}
              </p>
            </div>
            <div
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium ${
                isCompleted
                  ? 'bg-success/10 text-success'
                  : 'bg-error/10 text-error'
              }`}
            >
              {isCompleted ? (
                <CheckCircle2 className="w-4 h-4" />
              ) : (
                <XCircle className="w-4 h-4" />
              )}
              {project.status}
            </div>
          </div>

          <div className="mb-8 bg-surface rounded-2xl border border-border p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-text-primary mb-2">What am I looking at?</h2>
            <p className="text-sm text-text-secondary leading-relaxed">
              Confidence scores summarize output quality across multiple checks. Artifacts are the concrete files you can download and
              submit/use downstream (JSON metadata, validation report, processing log, etc.).
            </p>
          </div>

          {/* Confidence scores */}
          {Object.keys(scores).length > 0 && (
            <div className="mb-8">
              <h2 className="text-lg font-semibold text-text-primary mb-4">Confidence Scores</h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                {Object.entries(scores).map(([key, val]) => (
                  <ScoreCard key={key} label={key} score={val} />
                ))}
              </div>
            </div>
          )}

          {/* Execution summary */}
          {Object.keys(summary).length > 0 && (
            <div className="mb-8">
              <h2 className="text-lg font-semibold text-text-primary mb-4">Execution Summary</h2>
              <div className="bg-surface rounded-2xl border border-border p-6 shadow-sm">
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                  {Object.entries(summary).map(([key, val]) => (
                    <div key={key}>
                      <p className="text-xs text-text-tertiary capitalize mb-0.5">
                        {key.replace(/_/g, ' ')}
                      </p>
                      <p className="text-sm font-medium text-text-primary">
                        {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Errors */}
          {project.errors && project.errors.length > 0 && (
            <div className="mb-8">
              <h2 className="text-lg font-semibold text-text-primary mb-4">Errors</h2>
              <div className="bg-error/5 border border-error/20 rounded-2xl p-6 space-y-2">
                {project.errors.map((err, i) => (
                  <p key={i} className="text-sm text-error">{err}</p>
                ))}
              </div>
            </div>
          )}

          {/* Artifacts */}
          {artifacts.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold text-text-primary mb-4">
                Files ({artifacts.length})
              </h2>
              <div className="bg-surface rounded-2xl border border-border shadow-sm divide-y divide-border">
                {artifacts.map((art) => (
                  <div key={art.name} className="flex items-center gap-4 px-6 py-4">
                    <FileDown className="w-5 h-5 text-text-tertiary shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-text-primary break-all">
                        {art.name.split('/').pop() || art.name}
                      </p>
                      <p className="text-xs text-text-tertiary break-all">
                        {art.name.includes('/') ? `${art.name} · ` : ''}{formatSize(art.size)}
                      </p>
                    </div>
                    {art.available ? (
                      <a
                        href={api.getArtifactUrl(projectId!, art.name)}
                        download
                        className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold
                          text-primary bg-primary/10 hover:bg-primary/20 transition-colors no-underline"
                      >
                        <Download className="w-3.5 h-3.5" />
                        Download
                      </a>
                    ) : (
                      <span className="text-xs text-text-tertiary">Unavailable</span>
                    )}
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-text-tertiary leading-relaxed">
                Start with <span className="font-semibold text-text-secondary">metadata_json.json</span>,
                then review <span className="font-semibold text-text-secondary">validation_report.txt</span> and{' '}
                <span className="font-semibold text-text-secondary">workflow_report.json</span>.
              </p>
            </div>
          )}

          {/* Process another */}
          <div className="mt-12 text-center">
            <button
              onClick={() => navigate('/upload')}
              className="inline-flex items-center gap-2 px-8 py-3 rounded-xl text-sm font-semibold
                text-white bg-primary hover:bg-primary-dark transition-colors cursor-pointer"
            >
              Process Another Document
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
