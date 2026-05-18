import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const TITLE_PATH = join(ROOT, "src", "chapters", "01-title", "Title.tsx");
const NARRATION_PATH = join(ROOT, "src", "chapters", "01-title", "narrations.ts");

function assert(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

const titleSource = readFileSync(TITLE_PATH, "utf8");
const narrationSource = readFileSync(NARRATION_PATH, "utf8");

assert(
  titleSource.includes("Reconstructing FAIR Metadata Objects with Multi-Agent Systems"),
  "Title slide subtitle should use 'Multi-Agent Systems'.",
);
assert(
  !titleSource.includes("Multi-Agent Workflows"),
  "Title slide subtitle still uses 'Multi-Agent Workflows'.",
);
assert(
  narrationSource.includes("Reconstructing FAIR Metadata Objects with Multi-Agent Systems"),
  "Title narration should match the 'Multi-Agent Systems' wording.",
);
assert(
  !narrationSource.includes("Multi-Agent Workflows"),
  "Title narration still uses 'Multi-Agent Workflows'.",
);

console.log("Title copy validation passed.");
