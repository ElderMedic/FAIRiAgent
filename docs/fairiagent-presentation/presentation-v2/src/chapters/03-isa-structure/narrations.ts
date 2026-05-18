import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "To understand why this is hard, you need to see what we're asking people to produce. FAIR metadata is not a flat table. It's a 5-layer hierarchical object following the ISA model.",
  "At the top, Investigation captures project-level context. Study defines the research design. Then three multi-row layers: Observation Unit, Sample, and Assay. Each can have multiple rows, so the hard part is keeping each field attached to the right sample, observation unit, or assay. This is not a form-filling problem. This is structured object reconstruction.",
];

export { narrations };
