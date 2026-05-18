import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ISA_PATH = join(ROOT, "src", "chapters", "03-isa-structure", "IsaStructure.tsx");
const NARRATION_PATH = join(ROOT, "src", "chapters", "03-isa-structure", "narrations.ts");

function assert(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

const isaSource = readFileSync(ISA_PATH, "utf8");
const narrationSource = readFileSync(NARRATION_PATH, "utf8");

assert(
  !isaSource.includes("Row binding"),
  "Slide 3 still uses the abstract 'Row binding' label.",
);
assert(
  isaSource.includes("Which sample / assay does each value belong to?"),
  "Slide 3 should explain the challenge as mapping each value to the right sample or assay.",
);
assert(
  !narrationSource.includes("bound to the correct row"),
  "Slide 3 narration still uses the abstract 'bound to the correct row' phrasing.",
);
assert(
  narrationSource.includes("keeping each field attached to the right sample, observation unit, or assay"),
  "Slide 3 narration should explain the challenge as keeping each field attached to the right experimental entity.",
);

console.log("ISA slide copy validation passed.");
