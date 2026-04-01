import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  BookOpen,
  Code2,
  ExternalLink,
  Layers,
  MonitorCog,
  Network,
} from 'lucide-react';
import { usePageTitle } from '../hooks/usePageTitle';
import {
  DEEPWIKI_URL,
  FAIR_DS_URL,
  GITHUB_DOCS_TREE_URL,
  GITHUB_REPO_URL,
} from '../constants/site';
import './InteriorPages.css';

const overviewItems = [
  'CLI-first multi-agent framework for extracting metadata from research documents',
  'FAIR-DS compatible JSON output for downstream review and reuse',
  'Flexible providers across local and hosted model backends',
];

const links = [
  {
    href: GITHUB_REPO_URL,
    label: 'Source code on GitHub',
    icon: Code2,
    emphasized: true,
  },
  {
    href: GITHUB_DOCS_TREE_URL,
    label: 'Documentation folder',
    icon: BookOpen,
  },
  {
    href: FAIR_DS_URL,
    label: 'FAIR Data Station',
    icon: Network,
  },
  {
    href: DEEPWIKI_URL,
    label: 'DeepWiki overview',
    icon: Layers,
  },
];

export default function About() {
  usePageTitle('About');

  return (
    <div className="page-frame page-frame--about">
      <div className="page-shell page-stack">
        <header className="page-header">
          <Link to="/" className="page-backlink">
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            Back to home
          </Link>
          <div className="about-kicker">
            <MonitorCog className="w-4 h-4" aria-hidden="true" />
            Project overview
          </div>
          <p className="page-eyebrow">About FAIRiAgent</p>
          <h1 className="page-title">A research workflow for FAIR metadata generation.</h1>
          <p className="page-lede">
            FAIRiAgent is built to move from research documents to structured metadata with clearer
            process control, evidence handling, and reviewability than a one-shot extraction pipeline.
          </p>
        </header>

        <div className="about-layout">
          <section className="page-stack">
            <div className="about-overview-grid">
              <article className="page-card">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">What it is</p>
                    <h2 className="page-card__title">The core system</h2>
                  </div>
                  <div className="page-card__icon-wrap">
                    <Layers className="page-card__icon" aria-hidden="true" />
                  </div>
                </div>
                <p className="page-card__body">
                  FAIRiAgent is a CLI-first, multi-agent framework that reads PDFs and other research
                  documents, then builds FAIR-DS compatible JSON metadata from them.
                </p>
                <ul className="about-bullet-list">
                  {overviewItems.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </article>

              <article className="page-card page-card--soft">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">How it operates</p>
                    <h2 className="page-card__title">The processing path</h2>
                  </div>
                  <div className="page-card__icon-wrap">
                    <Network className="page-card__icon" aria-hidden="true" />
                  </div>
                </div>
                <p className="page-card__body">
                  Documents are parsed, grounded against relevant context, passed through specialized
                  agents, then refined and validated before final artifacts are produced.
                </p>
                <p className="page-card__body">
                  For a deeper architectural walkthrough, see{' '}
                  <code className="page-inline-code">docs/en/ARCHITECTURE_AND_FLOW.md</code>.
                </p>
              </article>
            </div>

            <div className="about-card-grid">
              <article className="page-card">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">This interface</p>
                    <h2 className="page-card__title">What the web UI covers</h2>
                  </div>
                  <div className="page-card__icon-wrap">
                    <MonitorCog className="page-card__icon" aria-hidden="true" />
                  </div>
                </div>
                <p className="page-card__body">
                  The React application works with the FastAPI backend at{' '}
                  <code className="page-inline-code">/api/v1</code> for uploads, configuration,
                  streaming progress, and artifact downloads. It is designed for local or LAN use.
                </p>
              </article>

              <article className="page-card">
                <div className="page-card__header">
                  <div>
                    <p className="page-card__eyebrow">Links and references</p>
                    <h2 className="page-card__title">Where to keep reading</h2>
                  </div>
                  <div className="page-card__icon-wrap">
                    <BookOpen className="page-card__icon" aria-hidden="true" />
                  </div>
                </div>
                <ul className="page-link-list about-link-list">
                  {links.map((item) => (
                    <li key={item.href}>
                      <a
                        href={item.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={item.emphasized ? 'font-semibold text-primary' : undefined}
                      >
                        <item.icon className="w-4 h-4" aria-hidden="true" />
                        {item.label}
                        <ExternalLink className="w-3.5 h-3.5 opacity-60" aria-hidden="true" />
                      </a>
                    </li>
                  ))}
                </ul>
              </article>
            </div>
          </section>

          <aside className="page-stack">
            <div className="page-card page-card--soft">
              <div className="page-card__header">
                <div>
                  <p className="page-card__eyebrow">Operating notes</p>
                  <h2 className="page-card__title">Usage expectations</h2>
                </div>
                <div className="page-card__icon-wrap">
                  <Layers className="page-card__icon" aria-hidden="true" />
                </div>
              </div>
              <ul className="page-note-list">
                <li>Review all outputs before publication or compliance use.</li>
                <li>Provider keys, data handling, and institutional policy remain your responsibility.</li>
                <li>The legacy Streamlit path remains available if needed.</li>
              </ul>
            </div>

            <p className="about-footnote">
              This page summarizes the repository and documentation for orientation. The source repository
              remains the canonical reference for the latest implementation details.
            </p>
          </aside>
        </div>
      </div>
    </div>
  );
}
