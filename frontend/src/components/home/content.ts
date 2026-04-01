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

export const heroSignals: HomeSignal[] = [
  {
    label: 'Local-first',
    detail: 'Designed for workstation or trusted-LAN use',
  },
  {
    label: 'Evidence-aware',
    detail: 'Structured outputs with provenance and validation',
  },
  {
    label: 'FAIR-DS aligned',
    detail: 'Research metadata shaped for downstream reuse',
  },
  {
    label: 'CLI + API + Web UI',
    detail: 'One workflow, multiple operator surfaces',
  },
];

export const valueCards: HomeCard[] = [
  {
    icon: FileSearch,
    title: 'Document-first operation',
    description:
      'Start from the paper, not a blank form. PDF, TXT, and Markdown files move through one consistent metadata workflow.',
  },
  {
    icon: Bot,
    title: 'Agentic, not one-shot',
    description:
      'Parsing, retrieval, generation, critique, and validation are treated as separate concerns instead of a single opaque prompt.',
  },
  {
    icon: ShieldCheck,
    title: 'Honest for internal use',
    description:
      'The UI is designed for local or trusted-network teams that need reviewability more than product-marketing theatrics.',
  },
];

export const workflowSteps: HomeStep[] = [
  {
    icon: FileSearch,
    title: 'Ingest',
    body: 'Load a real document or the bundled sample and enter the same backend workflow either way.',
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
