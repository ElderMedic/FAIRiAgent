import type { LucideIcon } from 'lucide-react';
import {
  BrainCircuit,
  ClipboardCheck,
  Dna,
  FileStack,
  GitMerge,
  LibraryBig,
  PackageCheck,
  ScanText,
  Telescope,
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

/** Hero "signal" cards: short label; hover/focus reveals detail (see Home.css). */
export const heroSignals: HomeSignal[] = [
  {
    label: 'Full-paper parsing',
    detail: 'Methods, tables, and supplementary material—not abstract-only extraction.',
  },
  {
    label: 'Standards-grounded',
    detail: 'MIxS package selection and FAIR Data Station term lookup run inside the pipeline.',
  },
  {
    label: 'Auditable by design',
    detail: 'Evidence, confidence scores, and artifacts stay attached for every run.',
  },
];

export const valueCards: HomeCard[] = [
  {
    icon: ScanText,
    title: 'Document → metadata draft',
    description:
      'Reads the full paper and converts unstructured content into a structured, submission-oriented metadata draft.',
  },
  {
    icon: BrainCircuit,
    title: 'Specialised agent roles',
    description:
      'Planner, parser, retriever, generator, and critic each own a distinct step—making the pipeline inspectable, not opaque.',
  },
  {
    icon: ClipboardCheck,
    title: 'Runs you can audit',
    description:
      'Logs, confidence signals, and downloadable artifacts remain attached so every draft can be traced back to the source paper.',
  },
];

export const workflowSteps: HomeStep[] = [
  {
    icon: ScanText,
    title: 'Parse',
    body: 'Full-document structured text from PDF or Markdown via MinerU—methods, tables, and supplements included.',
  },
  {
    icon: LibraryBig,
    title: 'Ground',
    body: 'Select MIxS-style checklist packages and retrieve FAIR Data Station schema context before any field is drafted.',
  },
  {
    icon: GitMerge,
    title: 'Draft & critique',
    body: 'Plan → execute → critique → refine: the critic retries on weak evidence or failed schema checks.',
  },
  {
    icon: PackageCheck,
    title: 'Export & review',
    body: 'ISA-oriented JSON, validation report, and processing logs—packaged together, ready for curator handoff.',
  },
];

export const consoleSlides: HomeConsoleSlide[] = [
  {
    label: 'Plan',
    eyebrow: 'Architecture',
    summary: 'Checklist-aware metadata from the full manuscript—not a generic document summary.',
    wideCard: {
      icon: FileStack,
      title: 'Full-document intake',
      body: 'PDF, text, and Markdown all follow one backend path for consistent, reproducible processing.',
    },
    cards: [
      {
        icon: BrainCircuit,
        title: 'Planner agent',
        body: 'Selects the right MIxS-style checklist package before any field drafting begins.',
      },
      {
        icon: LibraryBig,
        title: 'FAIR Data Station',
        body: 'Schema search and curated vocabulary shape each field for downstream repository use.',
      },
    ],
    highlights: ['Full-document path', 'Distinct agent roles', 'Repository-oriented output'],
  },
  {
    label: 'Run',
    eyebrow: 'Execution',
    summary: 'Enough state stays visible to understand what happened and why.',
    wideCard: {
      icon: Telescope,
      title: 'Preflight check',
      body: 'Required services are verified before launch so environment problems surface before processing begins.',
    },
    cards: [
      {
        icon: GitMerge,
        title: 'Critique loop',
        body: 'Retries are targeted at genuinely weak drafts—not the first plausible answer.',
      },
      {
        icon: Dna,
        title: 'One trace per run',
        body: 'Retrieval, model outputs, and critic signals are captured together in a single run object.',
      },
    ],
    highlights: ['Live progress stream', 'SSE-friendly runs', 'Handles complex papers'],
  },
  {
    label: 'Review',
    eyebrow: 'Outputs',
    summary: 'Concrete, downloadable files to inspect, correct, and pass forward.',
    wideCard: {
      icon: PackageCheck,
      title: 'Bundled artifacts',
      body: 'Metadata JSON, validation results, and workflow reports appear together—not scattered through logs.',
    },
    cards: [
      {
        icon: ClipboardCheck,
        title: 'Confidence signals',
        body: 'Field-level scores and summaries help prioritise which parts of the draft need curator attention.',
      },
      {
        icon: FileStack,
        title: 'Persistent outputs',
        body: 'Written to your output folder for re-inspection or direct handoff to FAIR-DS workflows.',
      },
    ],
    highlights: ['Downloadable bundle', 'Nested output support', 'FAIR-DS handoff ready'],
  },
];
