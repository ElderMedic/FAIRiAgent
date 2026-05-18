import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "Let me zoom in on grounding, one of the most important pieces. Without grounding, the LLM generates field names from training data — some real, some hallucinated. No way to tell which is which.",
  "With FAIR-DS grounding, the agent queries the live terminology service. It asks: what packages exist? What fields does this package require? Then it generates metadata constrained by what actually exists.",
  "Here's a concrete example. Without grounding: the LLM invents a package called GenomicsCore — sounds plausible, doesn't exist. With grounding: the system correctly selects Genome from the FAIR-DS registry. The difference is not model size. It's access to authoritative sources.",
];

export { narrations };
