import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "So what do we learn from FAIRiAgent beyond the implementation itself?",
  "The first point is that FAIR metadata management is not only value extraction. The target is a structured description of the study: design, samples, assays, values, and evidence. That is why the system has to reason over the metadata object, not just produce a summary of the paper.",
  "The second point is that community standards need to guide the workflow itself. FAIR-DS packages and fields are not something to clean up after generation. They should constrain what the agent proposes. And the third point is evidence: a curator needs to see where a value came from, which ISA row it belongs to, and what remains uncertain.",
  "The broader goal is assisted curation, not full automation. The agent reduces repetitive searching and form filling, but the scientist still controls interpretation, correction, and final release.",
  "",
];

export { narrations };
