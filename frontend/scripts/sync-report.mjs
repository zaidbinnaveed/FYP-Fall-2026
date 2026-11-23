#!/usr/bin/env node
/**
 * Copies the research report written by `oscc-ml report` into the static site so the UI shows
 * real numbers ("Results from run folders") instead of sample data.
 *
 *   npm run sync-report                 # ../ml_research/runs/report/summary.json
 *   npm run sync-report -- <path>       # another summary.json (e.g. from an imported results zip)
 *
 * Without a report nothing is copied and the app keeps using clearly labelled sample data.
 */
import { copyFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = resolve(
  process.argv[2] ?? resolve(frontendDir, '..', 'ml_research', 'runs', 'report', 'summary.json'),
);
const target = resolve(frontendDir, 'public', 'report', 'summary.json');

if (!existsSync(source)) {
  console.log(`No research report at ${source}.`);
  console.log('The app will show sample data (labelled "Sample data — not real results").');
  process.exit(0);
}

let report;
try {
  report = JSON.parse(readFileSync(source, 'utf8'));
} catch (error) {
  console.error(`Not valid JSON: ${source}\n${error}`);
  process.exit(1);
}
if (!report || !Array.isArray(report.rows)) {
  console.error(`Not an oscc-ml report summary (no "rows" array): ${source}`);
  process.exit(1);
}

mkdirSync(dirname(target), { recursive: true });
copyFileSync(source, target);
console.log(`Copied ${report.rows.length} rows from ${source}`);
console.log(`  -> ${target} (served as /report/summary.json)`);
