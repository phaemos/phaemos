// builds the production bundle locally with wrangler's dry run. nothing is deployed or sent anywhere.
// the real wrangler.toml keeps a placeholder date that stops a deploy, so the build uses a copy with a
// fixed date. the copy is removed afterwards.
import { execFileSync } from "node:child_process";
import { readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const copy = join(root, "wrangler.build.toml");
const config = readFileSync(join(root, "wrangler.toml"), "utf8").replace(
  /^compatibility_date = .*$/m,
  'compatibility_date = "2026-11-01"',
);
writeFileSync(copy, config);
try {
  execFileSync(
    join(root, "node_modules", ".bin", "wrangler"),
    ["deploy", "--dry-run", "--outdir", "dist", "--config", "wrangler.build.toml"],
    { cwd: root, stdio: "inherit", env: { ...process.env, WRANGLER_SEND_METRICS: "false", CI: "1" } },
  );
  const bytes = statSync(join(root, "dist", "index.js")).size;
  console.log(`bundle: dist/index.js, ${bytes} bytes (${(bytes / 1024).toFixed(1)} KiB)`);
} finally {
  rmSync(copy, { force: true });
}
