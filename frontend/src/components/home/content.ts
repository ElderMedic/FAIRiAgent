import type { LucideIcon } from 'lucide-react';
import {
  Bot,
  Database,
  FileSearch,
  Network,
  ShieldCheck,
  Workflow,
} from 'lucide-react';

export interface HomeSignal {
  label: string;
  detail: string;
}

export interface HomeCard {
  icon: LucideIcon;
  title: string;
  description: string;
}

export interface HomeStep {
  icon: LucideIcon;
  title: string;
  body: string;
}

export interface HomeConsoleItem {
  icon: LucideIcon;
  title: string;
  body: string;
}

export interface HomeConsoleSlide {
  label: string;
  eyebrow: string;
  summary: string;
  wideCard: HomeConsoleItem;
  cards: [HomeConsoleItem, HomeConsoleItem];
  highlights: string[];
}

export const heroSignals: HomeSignal[] = [
  {
    label: 'Research-first',
    detail: 'Built around papers, supplements, and protocol-like documents rather than blank metadata forms',
  },
  {
    label: 'Evidence-linked',
    detail: 'Outputs keep field-level evidence, provenance, and validation visible for review',
  },
  {
    label: 'FAIR-DS ready',
    detail: 'Metadata drafts are shaped for package-aware downstream use instead of generic summaries',
  },
];

export const valueCards: HomeCard[] = [
  {
    icon: FileSearch,
    title: 'From scientific narrative to structured fields',
    description:
      'The workflow starts from the source document and keeps experimental context in view while building metadata, so researchers are not asked to reconstruct everything later from memory.',
  },
  {
    icon: Bot,
    title: 'Multi-agent by design, not by slogan',
    description:
      'Document parsing, package and term retrieval, JSON generation, critique, and validation are separated into explicit steps. That makes the system easier to steer, inspect, and improve than a one-shot chatbot flow.',
  },
  {
    icon: ShieldCheck,
    title: 'A harness around the run, not a black box',
    description:
      'Service checks, live logs, confidence summaries, and downloadable artifacts stay attached to each run. For wet-lab teams, that means a draft can be checked against the paper instead of accepted on faith.',
  },
];

export const workflowSteps: HomeStep[] = [
  {
    icon: FileSearch,
    title: 'Ingest',
    body: 'Load your own document or the bundled earthworm paper and enter the same backend workflow either way.',
  },
  {
    icon: Network,
    title: 'Configure',
    body: 'Pick provider settings and retrieval context before execution starts.',
  },
  {
    icon: Workflow,
    title: 'Refine',
    body: 'Extraction, critique, and validation loops reduce brittle output and make problems visible earlier.',
  },
  {
    icon: Database,
    title: 'Export',
    body: 'Review metadata artifacts and downstream files without losing the operational trail.',
  },
];

export const consoleHighlights = [
  'FastAPI backend with streaming run progress',
  'Works with local or cloud model providers',
  'Built for iterative review, not blind autopilot',
];

export const consoleSlides: HomeConsoleSlide[] = [
  {
    label: 'Intake',
    eyebrow: 'Run architecture',
    summary: 'Read the source document, recover context, then move toward structured FAIR metadata.',
    wideCard: {
      icon: FileSearch,
      title: 'Document intake',
      body: 'PDF, TXT, and Markdown enter the same backend path, so papers and lighter notes can be processed without switching tools.',
    },
    cards: [
      {
        icon: Workflow,
        title: 'Specialized roles',
        body: 'Parsing, planning, retrieval, generation, and critique are treated as separate concerns instead of one monolithic prompt.',
      },
      {
        icon: Database,
        title: 'Package-aware drafting',
        body: 'The system works toward FAIR-DS compatible metadata files rather than leaving the result as free text.',
      },
    ],
    highlights: [
      'Papers and bundled examples use the same path',
      'One workflow across CLI, API, and Web UI',
      'Built for metadata drafting, not generic chat',
    ],
  },
  {
    label: 'Observe',
    eyebrow: 'Runtime view',
    summary: 'The system keeps enough state visible that a researcher can follow what happened during the run.',
    wideCard: {
      icon: ShieldCheck,
      title: 'Preflight checks',
      body: 'MinerU, FAIR-DS, Ollama, Qdrant, and memory readiness are checked before launch so obvious environment problems show up early.',
    },
    cards: [
      {
        icon: Workflow,
        title: 'Live processing',
        body: 'Stage changes and log lines stream into the run page, so processing feels inspectable rather than mysterious.',
      },
      {
        icon: Bot,
        title: 'Context in the loop',
        body: 'Retrieved knowledge, model output, and critique are part of the same run instead of being scattered across separate tools.',
      },
    ],
    highlights: [
      'Service cards reflect actual local reachability',
      'SSE keeps run state live without refresh',
      'Useful when debugging a difficult document',
    ],
  },
  {
    label: 'Export',
    eyebrow: 'Result surface',
    summary: 'A run ends with files that can be reviewed, compared, and handed forward.',
    wideCard: {
      icon: Database,
      title: 'Artifact review',
      body: 'Metadata JSON, validation reports, workflow summaries, and conversion outputs are listed together instead of being buried in logs.',
    },
    cards: [
      {
        icon: ShieldCheck,
        title: 'Confidence summary',
        body: 'Confidence scores and execution details make it easier to decide whether a draft is ready to refine or needs closer review.',
      },
      {
        icon: FileSearch,
        title: 'Persistent outputs',
        body: 'Core downloadable files are written to the output directory so a run can be revisited later or moved into the next FAIR step.',
      },
    ],
    highlights: [
      'Files remain attached to the run',
      'Artifact downloads include nested outputs',
      'Designed for downstream FAIR-DS handoff',
    ],
  },
];
