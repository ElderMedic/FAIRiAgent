import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "Grounding: the Retriever queries live FAIR-DS — which packages exist, which fields are mandatory.",
  "Without grounding the model invents GenomicsCore. With grounding it selects Genome from the registry.",
  "Authoritative sources, not model size, make the difference.",
];

export { narrations };
