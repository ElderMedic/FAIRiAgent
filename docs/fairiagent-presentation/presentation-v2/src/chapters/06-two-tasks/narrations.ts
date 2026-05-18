import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "This is where the core insight comes in. Metadata generation is actually two distinct tasks, and they fail differently.",
  "Metadata Schema is about structure: which package, which fields, which ISA sheet, which row. Value Extraction is about content: what value, which row, what evidence.",
  "A system can select the correct package but fill incorrect values. And a system can extract plausible values while failing to reconstruct the ISA hierarchy. These two tasks must be designed and evaluated separately.",
];

export { narrations };
