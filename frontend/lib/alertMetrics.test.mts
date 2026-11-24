// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ALERT_METRICS } from './alertMetrics.ts';

// the dashboard asks the API for the readings a rule may watch (GET /alert-metrics) and falls back to this list when that fails;
// the fallback must never name a field the backend's post schema lacks, because a rule on it is refused or never fires.
const SCHEMA = readFileSync(new URL('../../backend/app/schemas/telemetry.py', import.meta.url), 'utf8');

function ingestFields(): Set<string> {
  const start = SCHEMA.indexOf('class TelemetryIngest(BaseModel):');
  assert.ok(start >= 0, 'TelemetryIngest not found');
  const rest = SCHEMA.slice(start + 10);
  const end = rest.search(/\nclass /);
  const block = end === -1 ? rest : rest.slice(0, end);
  return new Set([...block.matchAll(/^    ([a-z][a-z0-9_]*)\s*:/gm)].map((m) => m[1]));
}

test('every reading the rule form can fall back to exists in the backend schema', () => {
  const fields = ingestFields();
  assert.ok(fields.has('temperature') && fields.has('vib_magnitude'), 'the schema parse found the fields');
  for (const m of ALERT_METRICS) {
    if (m.key === 'anomaly_score') continue;
    assert.ok(fields.has(m.key), `${m.key} is not a field of TelemetryIngest`);
  }
});
