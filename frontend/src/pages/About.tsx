import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  BookOpen,
  BrainCircuit,
  Code2,
  Dna,
  ExternalLink,
  Layers,
  MonitorCog,
  Share2,
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
  'Designed for complete biological papers—methods sections, result tables, and supplementary material are all in scope',
  'Planner, parser, retriever, generator, and critic roles give each step a clear purpose, making the pipeline inspectable rather than a single opaque prompt',
  'Every run keeps logs, confidence scores, and downloadable artifacts together so each draft can be verified against the source document',
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
    icon: Share2,
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
          <h1 className="page-title">Multi-agent metadata curation for biological research.</h1>
          <p className="page-lede">
            The metadata needed for FAIR reuse and repository submission already exists in most
            biological papers—buried in methods sections, result tables, and supplementary files.
            FAIRiAgent bridges the gap between a finished manuscript and a structured, review-ready
            metadata package.
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
                    <Dna className="page-card__icon" aria-hidden="true" />
                  </div>
                </div>
                <p className="page-card__body">
                  FAIRiAgent is a LangGraph-based multi-agent system that reads full research
                  documents, retrieves FAIR-DS schema context, and produces structured metadata
                  drafts for biological studies. Its goal is to reduce the manual effort between a
                  finished paper and a repository-ready metadata package.
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
                    <h2 className="page-card__title">The system architecture</h2>
                  </div>
                  <div className="page-card__icon-wrap">
                    <BrainCircuit className="page-card__icon" aria-hidden="true" />
                  </div>
                </div>
                <p className="page-card__body">
                  The pipeline combines document parsing, checklist package selection, FAIR-DS
                  retrieval, metadata drafting, critique, and validation. Keeping these stages
                  explicit lets the system adapt, retry on failure, and surface uncertainty—rather
                  than pretending the task is linear or trivial.
                </p>
                <p className="page-card__body">
                  This matters because the bottleneck in biological data curation is not generic
                  summarisation—it is standards-heavy extraction from long, heterogeneous scientific
                  documents. FAIRiAgent keeps retrieval, evidence, critique, and validation
                  transparent so a researcher can trace exactly how any draft field was produced. See{' '}
                  <code className="page-inline-code">docs/en/ARCHITECTURE_AND_FLOW.md</code> for a
                  full walkthrough.
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
                  The React application communicates with the FastAPI backend at{' '}
                  <code className="page-inline-code">/api/v1</code> for document uploads,
                  configuration, live streaming progress, and artifact downloads. It gives
                  researchers a single place to launch a run, follow what the agents are doing,
                  and review the full output bundle once processing is complete.
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
                <li>Review all outputs before any publication, submission, or compliance use—FAIRiAgent produces drafts, not final decisions.</li>
                <li>LLM provider keys, data handling practices, and institutional data-sharing policies remain the researcher's responsibility.</li>
                <li>FAIRiAgent reduces metadata friction significantly, but unusual study designs and ambiguous documents still benefit from domain-expert review.</li>
              </ul>
            </div>

            <p className="about-footnote">
              This page summarises the project for orientation. The source repository and its
              documentation folder remain the canonical references for the latest implementation
              details, configuration options, and architecture decisions.
            </p>
          </aside>
        </div>
      </div>
    </div>
  );
}
