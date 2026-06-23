import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CHAPTERS_DIR = join(ROOT, "src", "chapters");
const APP_PATH = join(ROOT, "src", "App.tsx");

function countNarrations(source: string): number {
  const body = source.match(/const\s+narrations:\s*Narration\[\]\s*=\s*\[([\s\S]*?)\];/)?.[1] ?? "";
  const withoutComments = body.replace(/\/\/.*$/gm, "");
  return [...withoutComments.matchAll(/^\s*"/gm)].length;
}

function maxStepGate(source: string): number {
  return Math.max(
    0,
    ...[...source.matchAll(/step\s*>=\s*(\d+)/g)].map((match) => Number(match[1])),
  );
}

function appUsesOneBasedVisualStep(source: string): boolean {
  return (
    /<Cmp\s+step=\{\s*stepper\.cursor\.step\s*\+\s*1\s*\}/.test(source) ||
    /const\s+visualStep\s*=\s*stepper\.cursor\.step\s*\+\s*1\s*;[\s\S]*<Cmp\s+step=\{\s*visualStep\s*\}/.test(
      source,
    )
  );
}

const appSource = readFileSync(APP_PATH, "utf8");
const oneBasedVisualStep = appUsesOneBasedVisualStep(appSource);
const componentImports = [
  ...readFileSync(join(ROOT, "src", "registry", "chapters.ts"), "utf8").matchAll(
    /from\s+"..\/chapters\/([^"]+)"/g,
  ),
]
  .map((match) => match[1])
  .filter((importPath) => !importPath.endsWith("/narrations"));

const failures: string[] = [];

for (const componentImport of new Set(componentImports)) {
  const folder = join(CHAPTERS_DIR, dirname(componentImport));
  const tsxPath = join(CHAPTERS_DIR, `${componentImport}.tsx`);
  const narrationPath = join(folder, "narrations.ts");

  let tsxSource: string;
  try {
    tsxSource = readFileSync(tsxPath, "utf8");
  } catch {
    continue;
  }

  const narrationCount = countNarrations(readFileSync(narrationPath, "utf8"));
  const maxGate = maxStepGate(tsxSource);
  const maxReachableStep = oneBasedVisualStep ? narrationCount : narrationCount - 1;

  if (maxGate > maxReachableStep) {
    failures.push(
      `${dirname(componentImport)}: highest gate step >= ${maxGate}, but only ${narrationCount} narration step(s) are reachable with ${oneBasedVisualStep ? "1-based" : "0-based"} visual steps`,
    );
  }
}

if (!oneBasedVisualStep) {
  failures.unshift("App passes the 0-based cursor step into chapter components; chapter animation gates are authored as 1-based reveal steps.");
}

if (failures.length > 0) {
  console.error("Step gate validation failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log("Step gate validation passed.");
