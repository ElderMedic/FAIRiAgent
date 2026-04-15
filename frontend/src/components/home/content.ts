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

/** Hero “signal” cards: short label; hover/focus reveals detail (see Home.css). */
export const heroSignals: HomeSignal[] = [
  {
    label: 'Full-paper intake',
    detail: 'PDFs, methods, tables, and supplements—not abstract-only snippets.',
  },
  {
    label: 'MIxS / FAIR-DS grounded',
    detail: 'Checklist choice, field structure, and term grounding run in the pipeline.',
  },
  {
    label: 'Review-first output',
    detail: 'Evidence, validation, and artifacts stay with the run for curator review.',
  },
];

export const valueCards: HomeCard[] = [
  {
    icon: FileSearch,
    title: 'Paper → metadata draft',
    description:
      'Starts from the document and moves toward structured, submission-oriented metadata.',
  },
  {
    icon: Bot,
    title: 'Specialised agents',
    description:
      'Planner, parser, retriever, generator, and critic—inspectable roles, not one giant prompt.',
  },
  {
    icon: ShieldCheck,
    title: 'A run you can audit',
    description:
      'Logs, confidence signals, and downloads stay attached so outputs can be checked against the paper.',
  },
];

export const workflowSteps: HomeStep[] = [
  {
    icon: FileSearch,
    title: 'Parse',
    body: 'Structured text from full PDFs (e.g. MinerU), including tables and supplements.',
  },
  {
    icon: Network,
    title: 'Ground',
    body: 'Choose MIxS-style packages and FAIR Data Station context before drafting fields.',
  },
  {
    icon: Workflow,
    title: 'Draft & critique',
    body: 'Plan → execute → critique → refine: retry when evidence or schema checks fail.',
  },
  {
    icon: Database,
    title: 'Export & review',
    body: 'ISA-oriented JSON, validation, and reports—ready for correction and handoff.',
  },
];

export const consoleSlides: HomeConsoleSlide[] = [
  {
    label: 'Plan',
    eyebrow: 'Architecture',
    summary: 'From manuscript to checklist-aware metadata—not a generic summary.',
    wideCard: {
      icon: FileSearch,
      title: 'Paper-scale input',
      body: 'PDF, text, or Markdown share one backend path for consistent processing.',
    },
    cards: [
      {
        icon: Workflow,
        title: 'Planner',
        body: 'Selects the appropriate MIxS-style package before field drafting.',
      },
      {
        icon: Database,
        title: 'FAIR Data Station',
        body: 'Schema search and curated context shape the draft for downstream use.',
      },
    ],
    highlights: ['Full-document path', 'Distinct agent roles', 'Repository-oriented output'],
  },
  {
    label: 'Run',
    eyebrow: 'Execution',
    summary: 'Enough state visible to see what happened and why.',
    wideCard: {
      icon: ShieldCheck,
      title: 'Preflight',
      body: 'Key services are checked before launch so environment issues surface early.',
    },
    cards: [
      {
        icon: Workflow,
        title: 'Critique loop',
        body: 'Retries target weak drafts instead of returning the first plausible answer.',
      },
      {
        icon: Bot,
        title: 'One run object',
        body: 'Retrieval, model output, and critic signals stay in one trace.',
      },
    ],
    highlights: ['Live progress', 'SSE-friendly runs', 'Suited to difficult papers'],
  },
  {
    label: 'Review',
    eyebrow: 'Outputs',
    summary: 'Concrete files to inspect, correct, and pass forward.',
    wideCard: {
      icon: Database,
      title: 'Artifacts',
      body: 'Metadata JSON, validation, and workflow reports listed together—not buried in logs.',
    },
    cards: [
      {
        icon: ShieldCheck,
        title: 'Confidence',
        body: 'Scores and summaries help judge how close a draft is to submission-ready.',
      },
      {
        icon: FileSearch,
        title: 'Persistent files',
        body: 'Written to your output area for revisit or downstream FAIR steps.',
      },
    ],
    highlights: ['Downloadable bundle', 'Nested outputs supported', 'Handoff to FAIR-DS workflows'],
  },
];
