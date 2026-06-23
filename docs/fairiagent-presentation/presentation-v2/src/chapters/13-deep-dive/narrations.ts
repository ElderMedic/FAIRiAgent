import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "Let me take you inside one concrete run to show what's actually happening.",
  "On the left: the FAIRiAgent trace. The Planner identifies the domain and prioritizes the Genome package. The Knowledge Retriever queries FAIR-DS and returns real field definitions.",
  "The Generator produces fields with ISA sheet assignments. The Critic evaluates, finds a missing mandatory field, returns RETRY with specific feedback. The Generator retries, adds the field with evidence, and the Critic accepts.",
  "On the right: the baseline output from a single prompt. Wrong package, flat fields, hallucinated accession number, no ISA row binding. The difference is not token count. It's auditability.",
];

export { narrations };
