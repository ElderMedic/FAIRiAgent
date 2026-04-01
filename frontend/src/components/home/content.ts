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
    label: 'Full-paper input',
    detail: 'Built for papers, methods sections, tables, and supplements rather than isolated text snippets',
  },
  {
    label: 'MIxS and FAIR-DS aware',
    detail: 'Checklist choice, field structure, and term grounding are part of the run instead of being patched in later',
  },
  {
    label: 'Review before reuse',
    detail: 'Runs keep evidence, validation, and downloadable artifacts together so a researcher can inspect the draft properly',
  },
];

export const valueCards: HomeCard[] = [
  {
    icon: FileSearch,
    title: 'From papers to metadata drafts',
    description:
      'FAIRiAgent starts from the scientific document itself and works toward a structured draft, so the burden of reconstructing metadata from memory is reduced.',
  },
  {
    icon: Bot,
    title: 'Specialized agents with explicit roles',
    description:
      'Planner, parser, retriever, generator, and critic roles stay separate. That makes the workflow easier to inspect and improve than a single-pass extraction prompt.',
  },
  {
    icon: ShieldCheck,
    title: 'A review surface around each run',
    description:
      'Service checks, live logs, confidence signals, and artifacts stay attached to each run. For wet-lab teams, that means the draft can be checked against the paper instead of trusted blindly.',
  },
];

export const workflowSteps: HomeStep[] = [
  {
    icon: FileSearch,
    title: 'Parse the paper',
    body: 'Convert a PDF or related document into structured text so methods, tables, and supplementary detail can enter the same workflow.',
  },
  {
    icon: Network,
    title: 'Choose the right schema',
    body: 'Select the relevant MIxS package and retrieve FAIR Data Station context before field-level drafting begins.',
  },
  {
    icon: Workflow,
    title: 'Draft and critique',
    body: 'Generate metadata, inspect evidence coverage, and retry when the critic finds missing context or weak support.',
  },
  {
    icon: Database,
    title: 'Review the result',
    body: 'Export JSON metadata, validation output, and workflow reports with the operational trail still attached.',
  },
];

export const consoleHighlights = [
  'Built for complete biological papers, not abstract-only extraction',
  'Supports local and hosted model backends',
  'Designed for curator review instead of one-shot output',
];

export const consoleSlides: HomeConsoleSlide[] = [
  {
    label: 'Plan',
    eyebrow: 'Workflow architecture',
    summary: 'The run starts from the source paper and moves toward a specific metadata package, not a generic summary.',
    wideCard: {
      icon: FileSearch,
      title: 'Paper-scale intake',
      body: 'PDF, TXT, and Markdown enter the same backend path so papers, methods notes, and lighter supporting documents can be processed consistently.',
    },
    cards: [
      {
        icon: Workflow,
        title: 'Checklist selection',
        body: 'The planner works toward the appropriate MIxS-style package before the drafting stage starts.',
      },
      {
        icon: Database,
        title: 'Grounded drafting',
        body: 'Field structure and term lookup are tied to FAIR Data Station resources so the output is shaped for downstream use.',
      },
    ],
    highlights: [
      'Complete papers use the same path as bundled examples',
      'Planner, parser, retriever, generator, and critic stay distinct',
      'Output is aimed at metadata submission work, not generic chat',
    ],
  },
  {
    label: 'Run',
    eyebrow: 'Runtime view',
    summary: 'The run keeps enough state visible that a researcher can follow what happened and why.',
    wideCard: {
      icon: ShieldCheck,
      title: 'Preflight checks',
      body: 'MinerU, FAIR-DS, Ollama, Qdrant, and memory readiness are checked before launch so obvious environment problems show up early.',
    },
    cards: [
      {
        icon: Workflow,
        title: 'Critique-guided retries',
        body: 'The workflow can retry a weak draft instead of returning the first plausible answer it produced.',
      },
      {
        icon: Bot,
        title: 'Context stays attached',
        body: 'Retrieved knowledge, model output, and critique signals remain part of the same run rather than being scattered across tools.',
      },
    ],
    highlights: [
      'Service status reflects actual local reachability',
      'Live events keep long runs inspectable',
      'Useful when a difficult paper needs closer review',
    ],
  },
  {
    label: 'Review',
    eyebrow: 'Result surface',
    summary: 'A run ends with concrete files that can be reviewed, corrected, and handed forward.',
    wideCard: {
      icon: Database,
      title: 'Artifact review',
      body: 'Metadata JSON, validation reports, workflow summaries, and conversion outputs are listed together instead of being buried in logs.',
    },
    cards: [
      {
        icon: ShieldCheck,
        title: 'Confidence summary',
        body: 'Confidence scores and execution details make it easier to decide whether a draft is close to submission-ready or still needs work.',
      },
      {
        icon: FileSearch,
        title: 'Persistent outputs',
        body: 'Core downloadable files are written to the output directory so a run can be revisited later or moved into the next FAIR step.',
      },
    ],
    highlights: [
      'Files stay attached to the run',
      'Artifact downloads include nested outputs',
      'Designed for downstream FAIR-DS handoff',
    ],
  },
];
