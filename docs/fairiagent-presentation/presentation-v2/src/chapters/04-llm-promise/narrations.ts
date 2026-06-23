import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "So here's a natural thought: LLMs can read papers and extract information. Why not outsource the boring metadata work to an LLM?",
  "But there's a fundamental difference between asking an LLM to generate text, and asking it to reconstruct a structured metadata object that obeys a specific schema with row-level binding. This is the paradigm shift: from a single prompt-response to a multi-step auditable workflow.",
];

export { narrations };
