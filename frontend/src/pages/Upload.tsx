import { useEffect, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  FileText,
  FlaskConical,
  FolderUp,
  ShieldCheck,
  X,
} from 'lucide-react';
import { api, type DemoDocument, type DemoOptions } from '../api/client';
import { usePageTitle } from '../hooks/usePageTitle';
import { buildAppRoute } from '../utils/session';
import './InteriorPages.css';

const ACCEPTED_TYPES = ['.pdf', '.txt', '.md', '.csv', '.tsv', '.xlsx', '.xls', '.json', '.zip'];
const ACCEPTED_MIME = [
  'application/pdf',
  'text/plain',
  'text/markdown',
  'text/csv',
  'text/tab-separated-values',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel',
  'application/json',
  'application/zip',
  'application/x-zip-compressed',
];
const MAX_FILES = 8;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Upload() {
  usePageTitle('Upload');
  const navigate = useNavigate();
  const location = useLocation();
  const locationState = (location.state as { demoMode?: boolean } | null) ?? null;
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [projectName, setProjectName] = useState('');
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const [demoMode, setDemoMode] = useState(Boolean(locationState?.demoMode));
  const [demoOptions, setDemoOptions] = useState<DemoOptions | null>(null);
  const [sampleDocumentKey, setSampleDocumentKey] = useState('');

  useEffect(() => {
    let active = true;
    api.demoOptions()
      .then((options) => {
        if (!active) return;
        setDemoOptions(options);
        const availableKeys = options.documents.map((doc) => doc.key);
        const fallbackKey = availableKeys[0] || '';
        setSampleDocumentKey(
          availableKeys.includes(options.default_demo_document_key)
            ? options.default_demo_document_key
            : fallbackKey,
        );
      })
      .catch(() => {
        /* demo metadata is optional */
      });
    return () => {
      active = false;
    };
  }, []);

  const hasSampleDocs = demoOptions !== null && demoOptions.documents.length > 0;

  const sampleDocument: DemoDocument | undefined = demoOptions?.documents.find(
    (doc) => doc.key === sampleDocumentKey,
  );

  const validateFile = (nextFile: File): boolean => {
    const ext = `.${nextFile.name.split('.').pop()?.toLowerCase()}`;
    if (!ACCEPTED_TYPES.includes(ext) && !ACCEPTED_MIME.includes(nextFile.type)) {
      setError(`Unsupported file type. Please upload ${ACCEPTED_TYPES.join(', ')} files.`);
      return false;
    }
    return true;
  };

  const mergeFiles = (incoming: File[]) => {
    const validIncoming = incoming.filter((nextFile) => validateFile(nextFile));
    if (!validIncoming.length) return;
    setFiles((prev) => {
      const dedup = new Map<string, File>();
      for (const file of [...prev, ...validIncoming]) {
        dedup.set(`${file.name}:${file.size}:${file.lastModified}`, file);
      }
      const merged = Array.from(dedup.values());
      if (merged.length > MAX_FILES) {
        setError(`You can upload up to ${MAX_FILES} files per run.`);
        return merged.slice(0, MAX_FILES);
      }
      setError('');
      return merged;
    });
  };

  const handleDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const droppedFiles = Array.from(event.dataTransfer.files || []);
    if (droppedFiles.length) mergeFiles(droppedFiles);
  };

  const handleContinue = () => {
    if (!files.length && !(hasSampleDocs && sampleDocumentKey) && !(hasSampleDocs && demoMode)) return;
    navigate(buildAppRoute('/config'), {
      state: {
        files: files.length ? files : undefined,
        projectName: projectName || undefined,
        demoMode,
        sampleDocumentKey: sampleDocumentKey || undefined,
        demoOptions: demoOptions || undefined,
      },
    });
  };

  return (
    <div className="page-frame">
      <div className="page-shell page-stack">
        <header className="page-header">
          <p className="page-eyebrow">Preparation</p>
          <h1 className="page-title">Bring in a document and prepare the run.</h1>
          <p className="page-lede">
            Start with a research paper or note in PDF, TXT, or Markdown. This screen keeps the setup
            compact, but gives the workflow enough context to begin cleanly.
          </p>
        </header>

        <div className="upload-layout">
          <section className="upload-main">
            <div className="page-card">
              <div className="page-card__header">
                <div>
                  <p className="page-card__eyebrow">Document input</p>
                  <h2 className="page-card__title">Upload or choose the bundled sample</h2>
                </div>
                <div className="page-card__icon-wrap">
                  <FolderUp className="page-card__icon" aria-hidden="true" />
                </div>
              </div>

              <p className="page-card__body">
                The same backend pipeline runs in both cases. The bundled sample is a real reference
                document kept in the repository for quick end-to-end checks.
              </p>

              {hasSampleDocs && (
                <div className="upload-inline-card">
                  <div className="upload-toggle">
                    <div className="upload-toggle__copy" id="quick-sample-label">
                      <p className="upload-toggle__title">Quick sample preset</p>
                      <p className="upload-toggle__body">
                        Use the bundled earthworm paper and move directly into configuration.
                      </p>
                    </div>
                    <button
                      type="button"
                      aria-pressed={demoMode}
                      aria-labelledby="quick-sample-label"
                      onClick={() => setDemoMode((value) => !value)}
                      className={`upload-toggle__button ${demoMode ? 'is-on' : ''}`}
                    >
                      {demoMode ? 'Enabled' : 'Disabled'}
                    </button>
                  </div>
                </div>
              )}

              <div
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                onClick={() => inputRef.current?.click()}
                className={`upload-dropzone ${dragging ? 'upload-dropzone--active' : ''}`}
              >
                <input
                  ref={inputRef}
                  aria-label="Upload a research document"
                  type="file"
                  multiple
                  accept={ACCEPTED_TYPES.join(',')}
                  className="hidden"
                  onChange={(event) => {
                    const selectedFiles = Array.from(event.target.files || []);
                    if (selectedFiles.length) {
                      mergeFiles(selectedFiles);
                    }
                    event.currentTarget.value = '';
                  }}
                />
                <FolderUp className="upload-dropzone__icon" aria-hidden="true" />
                <p className="upload-dropzone__title">Drop files here or click to browse</p>
                <p className="upload-dropzone__body">
                  Supported formats: PDF, TXT, Markdown, CSV/TSV, Excel, JSON, ZIP. Up to {MAX_FILES} files.
                </p>
                {demoMode && (
                  <p className="upload-dropzone__body">
                    Quick sample mode is active, so you can continue even without uploading a file.
                  </p>
                )}
              </div>

              {error && (
                <p className="upload-error" role="alert">
                  {error}
                </p>
              )}

              {hasSampleDocs && (
                <div className="upload-section">
                  <label htmlFor="sample_document" className="upload-section__label">
                    Bundled sample document
                  </label>
                  <select
                    id="sample_document"
                    value={sampleDocumentKey}
                    onChange={(event) => setSampleDocumentKey(event.target.value)}
                    className="upload-select"
                  >
                    {demoOptions!.documents.map((doc) => (
                      <option key={doc.key} value={doc.key}>
                        {doc.label} · {doc.filename}
                      </option>
                    ))}
                  </select>
                  {sampleDocument && (
                    <p className="upload-section__hint">{sampleDocument.description}</p>
                  )}
                </div>
              )}

              {files.map((file, idx) => (
                <div className="upload-file-pill" key={`${file.name}:${file.size}:${file.lastModified}`}>
                  <FileText className="upload-file-pill__icon" aria-hidden="true" />
                  <div className="flex-1 min-w-0">
                    <p className="upload-file-pill__name">{file.name}</p>
                    <p className="upload-file-pill__meta">
                      {formatSize(file.size)} · file {idx + 1}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      setFiles((prev) =>
                        prev.filter(
                          (candidate) =>
                            `${candidate.name}:${candidate.size}:${candidate.lastModified}` !==
                            `${file.name}:${file.size}:${file.lastModified}`,
                        ),
                      );
                    }}
                    aria-label={`Remove ${file.name}`}
                    className="upload-file-pill__remove"
                  >
                    <X className="w-4 h-4" aria-hidden="true" />
                  </button>
                </div>
              ))}

              <div className="upload-section">
                <label htmlFor="project_name" className="upload-section__label">
                  Project name
                </label>
                <input
                  id="project_name"
                  type="text"
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  placeholder="e.g. Nitrogen amendment study"
                  className="upload-input"
                />
                <p className="upload-section__hint">
                  This helps identify the run later. It does not change the generated artifacts.
                </p>
              </div>

              <div className="upload-actions">
                <button
                  type="button"
                  onClick={handleContinue}
                  disabled={!files.length && !(hasSampleDocs && sampleDocumentKey) && !(hasSampleDocs && demoMode)}
                  className="upload-button upload-button--primary"
                >
                  Continue to configuration
                  <ArrowRight className="upload-button__icon" aria-hidden="true" />
                </button>
              </div>
            </div>
          </section>

          <aside className="upload-aside">
            <div className="page-card page-card--soft">
              <div className="page-card__header">
                <div>
                  <p className="page-card__eyebrow">Accepted input</p>
                  <h2 className="page-card__title">Formats and operating model</h2>
                </div>
                <div className="page-card__icon-wrap">
                  <FlaskConical className="page-card__icon" aria-hidden="true" />
                </div>
              </div>

              <div className="upload-meta-grid">
                <div className="upload-meta">
                  <p className="upload-meta__label">Formats</p>
                  <p className="upload-meta__value">PDF, TXT, Markdown, CSV/TSV, Excel, JSON, ZIP</p>
                </div>
                <div className="upload-meta">
                  <p className="upload-meta__label">Execution mode</p>
                  <p className="upload-meta__value">Local workstation or trusted-network deployment</p>
                </div>
                <div className="upload-meta">
                  <p className="upload-meta__label">Sample path</p>
                  <p className="upload-meta__value">Bundled sample still runs the real backend flow</p>
                </div>
              </div>
            </div>

            <div className="page-card">
              <div className="page-card__header">
                <div>
                  <p className="page-card__eyebrow">What happens next</p>
                  <h2 className="page-card__title">The workflow after upload</h2>
                </div>
                <div className="page-card__icon-wrap">
                  <ShieldCheck className="page-card__icon" aria-hidden="true" />
                </div>
              </div>

              <ul className="page-note-list">
                <li>Choose providers and runtime settings on the next screen.</li>
                <li>Start the run and stream progress through the pipeline.</li>
                <li>Review artifacts and confidence signals before reuse or submission.</li>
              </ul>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
