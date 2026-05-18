import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "Even with grounding, agents make mistakes. So we add a self-correction mechanism. After each agent, a Critic evaluates the output against a rubric: schema compliance, data types, confidence thresholds.",
  "The decision is three-way. Accept and move on. Retry with specific feedback. Escalate for human review. But here's the key: some errors can't be fixed by just trying again. The system sometimes needs rollback to an earlier state.",
  "That's the difference between 'try harder' and 'try differently.' Rollback re-queries the API, re-reads the document, regenerates from a better starting point.",
];

export { narrations };
