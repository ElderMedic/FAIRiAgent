import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SLIDE_PATH = join(ROOT, "src", "chapters", "05-llm-falls-short", "LlmFallsShort.tsx");
const NARRATION_PATH = join(ROOT, "src", "chapters", "05-llm-falls-short", "narrations.ts");

function assert(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

const slideSource = readFileSync(SLIDE_PATH, "utf8");
const narrationSource = readFileSync(NARRATION_PATH, "utf8");

assert(
  !slideSource.includes("row binding"),
  "Slide 5 still uses the abstract 'row binding' wording.",
);
assert(
  slideSource.includes("Flat fields with no clue which sample or assay they belong to"),
  "Slide 5 should explain the issue as values not being attached to the right sample or assay.",
);
assert(
  !narrationSource.includes("without row binding"),
  "Slide 5 narration still uses the abstract 'row binding' phrasing.",
);
assert(
  narrationSource.includes("you cannot tell which sample, observation unit, or assay a field belongs to"),
  "Slide 5 narration should explain the issue as losing which experimental entity a field belongs to.",
);

console.log("Slide 5 copy validation passed.");
