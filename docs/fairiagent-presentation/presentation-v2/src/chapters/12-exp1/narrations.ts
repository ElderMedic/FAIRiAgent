import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "The first question: does the agentic workflow improve extraction? The answer is yes. Across all baselines, Full achieves the highest scores on both metrics.",
  "But look at the gap. The improvement is largest on Hierarchical-F1, the structural score. Baselines don't do ISA row reconstruction. Value accuracy also improves, but the gap is smaller. Getting the structure right is where the agentic design adds the most value.",
];

export { narrations };
