import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const TAKEAWAYS_PATH = join(ROOT, "src", "chapters", "17-takeaways", "Takeaways.tsx");
const CLOSING_CSS_PATH = join(ROOT, "src", "chapters", "18-closing", "Closing.css");

function countOccurrences(source: string, needle: string): number {
  return source.split(needle).length - 1;
}

function assert(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

const takeawaysSource = readFileSync(TAKEAWAYS_PATH, "utf8");
assert(
  /step\s*>=\s*5\s*&&\s*\(\s*<div className="tk-coda">/.test(takeawaysSource),
  "Takeaways coda should only appear on the final step.",
);
assert(
  !/step\s*>\s*3/.test(takeawaysSource),
  "Takeaways should not reveal all descriptions early with a broad step > 3 condition.",
);
assert(
  countOccurrences(takeawaysSource, "step >= 2 + i") === 1,
  "Takeaways description reveal should be keyed to each card's own step.",
);

const descriptions = [...takeawaysSource.matchAll(/desc:\s*"([^"]+)"/g)].map((match) => match[1]);
const coda = takeawaysSource.match(/<div className="tk-coda">([\s\S]*?)<\/div>/)?.[1].replace(/\s+/g, " ").trim();

assert(descriptions.length === 4, "Takeaways should define four takeaway descriptions.");
assert(descriptions.every((desc) => desc.length <= 150), "Takeaways descriptions are still too long for the slide layout.");
assert(Boolean(coda) && coda.length <= 125, "Takeaways coda is still too long for the slide footer.");

const closingCss = readFileSync(CLOSING_CSS_PATH, "utf8");
assert(
  /\.cl-info\s*\{[\s\S]*opacity:\s*0;[\s\S]*transform:\s*translateY\(/.test(closingCss),
  "Closing info block is missing an entry animation start state.",
);
assert(
  /\.cl-info-in\s*\{[\s\S]*opacity:\s*1;[\s\S]*transform:\s*translateY\(0\)/.test(closingCss),
  "Closing info block is missing an animated visible state.",
);

console.log("Ending slide validation passed.");
