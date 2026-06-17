import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PRESENTATION_ROOT = resolve(ROOT, "..");

const REQUIRED_ASSETS = [
  {
    slide: "src/chapters/02-fair-pain/FairPain.tsx",
    asset: "figs/fairds_screenshot.png",
    assetRoot: PRESENTATION_ROOT,
  },
  {
    slide: "src/chapters/12-exp1/Exp1.tsx",
    asset: "public/figs/exp1_hierarchical_f1.png",
    assetRoot: ROOT,
    sourceReference: "figs/exp1_hierarchical_f1.png",
  },
  {
    slide: "src/chapters/14-exp2-ablation/Exp2Ablation.tsx",
    asset: "public/figs/exp3_ablation.png",
    assetRoot: ROOT,
    sourceReference: "figs/exp3_ablation.png",
  },
  {
    slide: "src/chapters/15-exp3-passk/Exp3Passk.tsx",
    asset: "public/figs/exp2_pass_at_k.png",
    assetRoot: ROOT,
    sourceReference: "figs/exp2_pass_at_k.png",
  },
  {
    slide: "src/chapters/10-memory/SessionMemory.tsx",
    asset: "figs/MemoryDesign.png",
    assetRoot: PRESENTATION_ROOT,
  },
] as const;

const failures: string[] = [];

for (const { slide, asset, assetRoot, sourceReference = asset } of REQUIRED_ASSETS) {
  const slideSource = readFileSync(join(ROOT, slide), "utf8");
  if (!existsSync(join(assetRoot, asset))) {
    failures.push(`Missing source asset: ${asset}`);
  }
  if (!slideSource.includes(sourceReference)) {
    failures.push(`${slide} does not reference ${sourceReference}`);
  }
}

const stageScaleSource = readFileSync(join(ROOT, "src/hooks/useStageScale.ts"), "utf8");
const margins = stageScaleSource.match(/marginX\s*=\s*(\d+),\s*\n\s*marginY\s*=\s*(\d+),/);
if (!margins) {
  failures.push("Could not read useStageScale default margins.");
} else {
  const [, marginX, marginY] = margins.map(Number);
  if (marginX >= 80 || marginY >= 100) {
    failures.push(
      `Stage margins are still too large: marginX=${marginX}, marginY=${marginY}.`,
    );
  }
}

if (failures.length > 0) {
  console.error("Visual asset validation failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log("Visual asset validation passed.");
