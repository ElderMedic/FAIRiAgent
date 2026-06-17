import type { Narration } from "../../registry/types";

const narrations: Narration[] = [
  "Here's what happens when you ask a single LLM call to produce FAIR metadata.",
  "First: hallucination. The model invents package names that don't exist. It makes up accession numbers. Let me show you an example.",
  "Second: context rot. In a long document, the model forgets early information. By the time it's generating assay-level fields, it's already lost the sampling context from the methods.",
  "Third: no ISA structure. The output is flat. You can read the fields, but you cannot tell which sample, observation unit, or assay a field belongs to. It looks like metadata, but it's not usable for submission.",
];

export { narrations };
