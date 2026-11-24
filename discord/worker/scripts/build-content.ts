// turns discord/content/commands.toml into the json the worker bundles and checks it.
// run with --check to fail when the json on disk is out of date.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "smol-toml";
import { validateContent } from "../src/validate.ts";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "..", "..", "content", "commands.toml");
const target = join(here, "..", "src", "content.generated.json");

const parsed = parse(readFileSync(source, "utf8"));
const problems = validateContent(parsed);
if (problems.length > 0) {
  for (const p of problems) console.error(`content: ${p}`);
  process.exit(1);
}
const output = `${JSON.stringify(parsed, null, 2)}\n`;
if (process.argv.includes("--check")) {
  const current = existsSync(target) ? readFileSync(target, "utf8") : "";
  if (current !== output) {
    console.error("content.generated.json is out of date. run: npm run content");
    process.exit(1);
  }
  console.log("content.generated.json is up to date");
} else {
  writeFileSync(target, output);
  console.log("wrote src/content.generated.json");
}
