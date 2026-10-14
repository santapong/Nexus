"""Fixed qualified stdlib Node asset; no Pydantic or image dependency is introduced."""

# ruff: noqa: E501 -- exact qualified JavaScript bytes retain their reviewed source/hash.

from __future__ import annotations

import hashlib

CSV_WRAPPER_SOURCE = r"""'use strict';
// PROPOSAL ASSET ONLY. Not mounted, configured, or executed against StockFlow.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const child = require('node:child_process');
const ROOT = process.cwd();
const phase = ROOT === '/scratch/work/baseline' ? 'baseline' : ROOT === '/scratch/work/post' ? 'post' : null;
if (!phase || process.env.NEXUS_OUTPUT_DIR !== `/outputs/${phase}`) throw Error('Invalid fixed CSV phase');
const OUTPUT = `/outputs/${phase}/checks`;
const MAX = 2097152;
const flags = fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW;
const sha = raw => crypto.createHash('sha256').update(raw).digest('hex');
function readOrdinary(name, limit = MAX) {
  const fd = fs.openSync(name, flags);
  try {
    const st = fs.fstatSync(fd);
    if (!st.isFile() || st.nlink !== 1 || st.size < 1 || st.size > limit) throw Error('Invalid ordinary input');
    const raw = Buffer.alloc(st.size + 1);
    const count = fs.readSync(fd, raw, 0, raw.length, 0);
    if (count !== st.size) throw Error('Changed bounded input');
    return raw.subarray(0, count);
  } finally { fs.closeSync(fd); }
}
function requireReal(name) {
  if (fs.realpathSync(name) !== name) throw Error('Changed fixed CSV namespace');
}
function run(pkg, args) {
  const result = child.spawnSync('/usr/local/bin/node', ['/tools/package/bin/pnpm.cjs', '--filter', pkg, 'exec', 'vitest', 'run', ...args,
    '--config=vitest.config.ts', '--reporter=json', '--allowOnly=false', '--passWithNoTests=false', '--maxWorkers=1', '--minWorkers=1'],
    { cwd: ROOT, env: process.env, stdio: 'inherit', timeout: 290000, killSignal: 'SIGKILL' });
  if (result.error || result.signal || result.status === null) throw Error('Unknown CSV test command');
  return result.status;
}
const rawPins = readOrdinary('/node-commands/csv-regression-pins.json', 65536);
const pins = JSON.parse(rawPins.toString('utf8'));
if (pins.schema_version !== 'nexus.builder.csv-regression.v1' || pins.reporter_version !== 'vitest2.1.9') throw Error('Invalid fixed CSV pins');
const sourceFiles = {
  baseline_module: '/source/baseline/packages/shared/src/csv/index.ts',
  post_module: '/source/post/packages/shared/src/csv/index.ts',
  baseline_test: '/source/baseline/packages/shared/src/csv/csv.test.ts',
  post_test: '/source/post/packages/shared/src/csv/csv.test.ts',
};
const sources = {};
for (const [key, name] of Object.entries(sourceFiles)) {
  requireReal(name);
  const raw = readOrdinary(name, 1048576);
  if (sha(raw) !== pins[key + '_sha256']) throw Error('Changed immutable CSV source');
  sources[key] = raw;
}
if (sha(readOrdinary('/node-commands/csv-test-wrapper.cjs', 1048576)) !== pins.wrapper_sha256) throw Error('Changed CSV wrapper');
const activeModule = `${ROOT}/packages/shared/src/csv/index.ts`;
const activeTest = `${ROOT}/packages/shared/src/csv/csv.test.ts`;
for (const [name, key] of [[activeModule, phase + '_module'], [activeTest, phase + '_test']]) {
  requireReal(name);
  if (sha(readOrdinary(name, 1048576)) !== pins[key + '_sha256']) throw Error('Changed actual CSV execution source');
}
for (const pkg of ['packages/shared', 'apps/web']) {
  const packageFile = `${ROOT}/${pkg}/node_modules/vitest/package.json`;
  if (JSON.parse(readOrdinary(packageFile, 65536)).version !== '2.1.9') throw Error('Wrong pinned Vitest version');
}
fs.mkdirSync(OUTPUT, { recursive: true });
const evidence = { schema_version: 'nexus.builder.csv-wrapper-observation.v1', phase, pins_sha256: sha(rawPins), source_hashes: {}, reports: {} };
for (const [key, raw] of Object.entries(sources)) evidence.source_hashes[key] = sha(raw);
function capture(role, name, status) {
  const raw = readOrdinary(name);
  evidence.reports[role] = { path: name, sha256: sha(raw), byte_length: raw.length, exit_code: status };
}
if (phase === 'post') {
  const parent = `${ROOT}/packages/shared/src`;
  requireReal(parent);
  const parentFd = fs.openSync(parent, flags | fs.constants.O_DIRECTORY);
  let probeFd;
  const probe = `${parent}/.nexus-csv-before`;
  const anchoredProbe = `/proc/self/fd/${parentFd}/.nexus-csv-before`;
  try {
    fs.mkdirSync(anchoredProbe, { mode: 0o700 }); // Must not preexist; never overwrite another tree.
    probeFd = fs.openSync(anchoredProbe, flags | fs.constants.O_DIRECTORY);
    const expected = { 'index.ts': sources.baseline_module, 'csv.test.ts': sources.post_test };
    for (const [name, raw] of Object.entries(expected)) {
      const fd = fs.openSync(`/proc/self/fd/${probeFd}/${name}`, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, 0o600);
      try { fs.writeFileSync(fd, raw); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    }
    if (fs.statSync(probe).ino !== fs.fstatSync(probeFd).ino || fs.realpathSync(probe) !== probe) throw Error('Changed CSV probe namespace');
    const report = `${OUTPUT}/csv-before-vitest.json`;
    const status = run('@stockflow/shared', ['src/.nexus-csv-before/csv.test.ts', `--outputFile=${report}`]);
    capture('before_probe', report, status);
    if (status !== 1) throw Error('CSV before probe did not fail normally');
    if (fs.statSync(probe).ino !== fs.fstatSync(probeFd).ino || fs.realpathSync(probe) !== probe) throw Error('Changed CSV probe after execution');
    const entries = fs.readdirSync(`/proc/self/fd/${probeFd}`).sort();
    if (JSON.stringify(entries) !== JSON.stringify(Object.keys(expected).sort())) throw Error('CSV probe has unexpected files');
    for (const [name, raw] of Object.entries(expected)) {
      const leaf = `/proc/self/fd/${probeFd}/${name}`;
      if (sha(readOrdinary(leaf, 1048576)) !== sha(raw)) throw Error('CSV probe bytes changed');
    }
    // All leaves verified before mutation; descriptor relative unlink cannot follow ancestors.
    for (const name of entries) fs.unlinkSync(`/proc/self/fd/${probeFd}/${name}`);
    fs.rmdirSync(anchoredProbe);
    fs.fsyncSync(parentFd);
    if (fs.existsSync(probe)) throw Error('CSV probe remained after cleanup');
  } finally {
    if (probeFd !== undefined) fs.closeSync(probeFd);
    fs.closeSync(parentFd);
  }
}
for (const [pkg, role] of [['@stockflow/shared', 'shared'], ['@stockflow/web', 'web']]) {
  const report = `${OUTPUT}/${role}-vitest.json`;
  const status = run(pkg, [`--outputFile=${report}`]);
  capture(`${phase}_${role}`, report, status);
  if (status !== 0) throw Error('Complete CSV phase suite failed');
}
for (const [name, key] of [[activeModule, phase + '_module'], [activeTest, phase + '_test']]) {
  requireReal(name);
  if (sha(readOrdinary(name, 1048576)) !== pins[key + '_sha256']) throw Error('CSV test altered actual source');
}
fs.writeFileSync(`${OUTPUT}/csv-wrapper-observation.json`, JSON.stringify(evidence), { flag: 'wx', mode: 0o600 });
// Host independently decodes actual captured JSON; no seven-case pass flag is emitted here.
"""


def csv_wrapper_source() -> str:
    """Return immutable server-owned bytes rather than a caller-selected executable."""
    return CSV_WRAPPER_SOURCE


def csv_wrapper_sha256() -> str:
    """Pin the exact staged Node wrapper used by the bounded v4 recipe."""
    return hashlib.sha256(CSV_WRAPPER_SOURCE.encode()).hexdigest()
