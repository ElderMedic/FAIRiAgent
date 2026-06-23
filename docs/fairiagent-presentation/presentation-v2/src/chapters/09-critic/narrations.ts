import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "Self-correction: after each agent a Critic scores schema compliance and decides ACCEPT, RETRY with feedback, or ESCALATE.",
  "Example: Critic flags a missing collection date — agent retries with evidence, then ACCEPT.",
  "Some errors need rollback — re-query FAIR-DS and regenerate — not just try harder on the same context.",
];

export { narrations };
