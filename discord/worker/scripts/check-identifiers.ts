// fails when a file under discord/worker or discord/content holds something shaped like a Discord id,
// a webhook address, a key or a token. run from discord/worker.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export interface Rule {
  name: string;
  pattern: RegExp;
}

// the patterns are written so that this file does not match them itself.
export const RULES: Rule[] = [
  { name: "a run of 17 to 20 digits (a Discord id)", pattern: /(?<![0-9])[0-9]{17,20}(?![0-9])/ },
  { name: "a webhook address", pattern: /discord(?:app)?\.com\/api(?:\/v[0-9]+)?\/webhooks\//i },
  { name: "a webhook path", pattern: /\/api\/webhooks\//i },
  { name: "a 64 character hex string (a key)", pattern: /(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])/ },
  { name: "a Discord bot token", pattern: /[MNO][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}/ },
  { name: "a GitHub token", pattern: /\bgh[pousr]_[A-Za-z0-9]{36,}/ },
  { name: "a GitHub fine grained token", pattern: /\bgithub_pat_[A-Za-z0-9_]{20,}/ },
  { name: "an AWS key", pattern: /\bAKIA[0-9A-Z]{16}\b/ },
  { name: "a Slack token", pattern: /\bxox[baprs]-[A-Za-z0-9-]{10,}/ },
  { name: "a signed token", pattern: /\beyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]{10,}/ },
  { name: "a private key", pattern: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  { name: "a Cloudflare token", pattern: /\bcfut_[A-Za-z0-9]{20,}/ },
  {
    name: "a secret assigned to a long literal",
    pattern: /(?:api[_-]?key|secret|token|password)["']?\s*[:=]\s*["'][A-Za-z0-9_\-/+]{24,}["']/i,
  },
];

const SKIP_DIRS = new Set(["node_modules", "dist", ".wrangler", ".git"]);
const TEXT = /\.(ts|js|mjs|json|toml|md|txt|yml|yaml|example|gitignore|npmrc)$|^\.[a-z]+$/;

export function listFiles(root: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(root)) {
    if (SKIP_DIRS.has(entry)) continue;
    const full = join(root, entry);
    const info = statSync(full);
    if (info.isDirectory()) out.push(...listFiles(full));
    else if (TEXT.test(entry) || entry === "LICENSE") out.push(full);
  }
  return out;
}

export function scan(text: string): string[] {
  return RULES.filter((r) => r.pattern.test(text)).map((r) => r.name);
}

export function checkTree(roots: string[]): string[] {
  const problems: string[] = [];
  for (const root of roots) {
    for (const file of listFiles(root)) {
      // the lock file holds package hashes and nothing a person wrote, so only its digit runs are skipped.
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, i) => {
        for (const name of scan(line)) {
          if (file.endsWith("package-lock.json") && name.startsWith("a run of")) continue;
          if (file.endsWith("package-lock.json") && name.startsWith("a 64 char")) continue;
          problems.push(`${relative(process.cwd(), file)}:${i + 1}: ${name}`);
        }
      });
    }
  }
  return problems;
}

const here = fileURLToPath(new URL(".", import.meta.url));
if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  const worker = resolve(here, "..");
  const problems = checkTree([worker, resolve(worker, "..", "content")]);
  if (problems.length > 0) {
    for (const p of problems) console.error(p);
    console.error(
      `${problems.length} problem(s). Nothing shaped like an id, a webhook address, a key or a token may be in this folder.`,
    );
    process.exit(1);
  }
  console.log("no identifiers, webhook addresses, keys or tokens found");
}
