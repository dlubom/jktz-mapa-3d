/* Runtime regresji retry, bez GPU i pobierania danych.
 * node --experimental-vm-modules --test tests/loader_retry.cjs
 * Opcjonalnie POTREE_LOADER_PATH wskazuje istniejący loader (np. dist/...).
 * Domyślnie test wykonuje bieżący patch_vendor.py na przypiętym ZIP w temp.
 */
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = process.env.POTREE_LOADER_PATH
  ? fs.readFileSync(path.resolve(root, process.env.POTREE_LOADER_PATH), 'utf8')
  : execFileSync(process.env.PYTHON || 'python3', ['-c', `
from pathlib import Path, PurePosixPath
import subprocess, sys, tempfile, zipfile
root = Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix="jktz-loader-retry-") as work:
    output = Path(work)
    vendor = output / "vendor/potree-next"
    with zipfile.ZipFile(root / "vendor/potree-next.zip") as archive:
        for name in archive.namelist():
            relative = PurePosixPath(*PurePosixPath(name).parts[1:])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe vendor path")
            (vendor / relative).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(root / "scripts/patch_vendor.py"),
                    "--output", str(output)], check=True, stdout=sys.stderr)
    print((vendor / "src/potree/octree/loader/PotreeLoader.js").read_text())
`, root], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']});

async function fixture() {
  const pending = [];
  let posted = 0, returned = 0, hierarchyFailure = false, hierarchyRequests = 0;
  class Vector3 {
    constructor(x = 0, y = 0, z = 0) {Object.assign(this, {x, y, z});}
    toArray() {return [this.x, this.y, this.z];}
  }
  class Empty {}
  const bindings = {
    PointAttributeTypes: {}, PointAttribute: Empty, PointAttributes: Empty,
    Vector3, Box3: Empty, Matrix4: Empty, PointCloudOctree: Empty,
    REFINEMENT: {}, PointCloudOctreeNode: Empty, Geometry: Empty, MAPPINGS: {},
    WorkerPool: {
      getWorker() {
        return {postMessage(message) {posted++; pending.push({worker: this, message});}};
      },
      returnWorker() {returned++;},
    },
  };
  const context = vm.createContext({
    URL, document: {baseURI: 'https://example.invalid/viewer/'},
    console: {log() {}},
    fetch: async () => {
      hierarchyRequests++;
      if (hierarchyFailure) throw Error('Controlled hierarchy transport failure');
      const buffer = new ArrayBuffer(22), data = new DataView(buffer);
      data.setUint8(0, 1); // LEAF, no children.
      data.setUint32(2, 1, true);
      data.setBigUint64(6, 0n, true);
      data.setBigUint64(14, 12n, true);
      return {status: 206, arrayBuffer: async () => buffer};
    },
  });
  const dependency = new vm.SyntheticModule(Object.keys(bindings), function() {
    for (const [name, value] of Object.entries(bindings)) this.setExport(name, value);
  }, {context});
  const module = new vm.SourceTextModule(source, {context, identifier: 'PotreeLoader.js'});
  await module.link(specifier => {
    assert.equal(specifier, 'potree', 'Unexpected loader dependency');
    return dependency;
  });
  await module.evaluate();
  const loader = new module.namespace.PotreeLoader();
  loader.url = 'https://example.invalid/data/metadata.json';
  loader.metadata = {encoding: 'DEFAULT', boundingBox: {min: [0, 0, 0]}};
  loader.attributes = {};
  loader.scale = [0.001, 0.001, 0.001];
  loader.offset = [0, 0, 0];
  loader.octree = {loader, events: {dispatcher: {dispatch() {}}}};
  const node = (name = 'r', mode = 'worker') => ({
    name, nodeType: mode === 'hierarchy' ? 2 : 1, loaded: false, loading: false,
    loadAttempts: 0, numPoints: 1, byteOffset: 0, byteSize: 12,
    hierarchyByteOffset: 0, hierarchyByteSize: 22,
    boundingBox: {min: new Vector3(), max: new Vector3(1, 1, 1)},
  });
  async function attempt(target, mode, succeeds) {
    const before = posted;
    hierarchyFailure = mode === 'hierarchy' && !succeeds;
    await loader.loadNode(target);
    if (mode === 'hierarchy' && !succeeds) {
      assert.equal(posted, before, 'A failed hierarchy must not start a decoder');
    } else {
      assert.equal(posted, before + 1, 'Retry must start a decoder');
      const {worker, message} = pending.shift();
      assert.equal(message.name, target.name);
      assert.equal(target.loading, true);
      worker.onmessage({data: succeeds ? {buffer: new ArrayBuffer(12), statsList: []} : 'failed'});
    }
    assert.equal(target.loading, false, 'Completion must release the loading slot');
    assert.equal(target.loaded, succeeds);
  }
  return {loader, node, attempt, counts: () => ({posted, returned, hierarchyRequests})};
}

for (const mode of ['worker', 'hierarchy']) {
  test(`${mode}: a transient failure and successful retry leave no error`, async () => {
    const f = await fixture(), node = f.node('r', mode);
    await f.attempt(node, mode, false);
    assert.equal(node.loadAttempts, 1);
    assert.ok(!f.loader.error, 'A retryable failure must not become an application error');
    await f.attempt(node, mode, true);
    assert.ok(node.geometry);
    assert.ok(!f.loader.error, 'Successful retry must not leave a stale loader error');
    assert.equal(node.loadAttempts, 0);
    assert.equal(f.counts().posted, f.counts().returned);
  });

  test(`${mode}: six consecutive failures end retries and expose an error`, async () => {
    const f = await fixture(), node = f.node('r', mode);
    for (let number = 1; number <= 6; number++) {
      await f.attempt(node, mode, false);
      assert.equal(node.loadAttempts, number);
      if (number < 6) assert.ok(!f.loader.error, 'Error must wait for retry exhaustion');
    }
    assert.ok(f.loader.error, 'Exhausted retries must be visible to the application');
    const exhausted = f.counts();
    await f.loader.loadNode(node);
    assert.deepEqual(f.counts(), exhausted, 'A seventh call must not retry');
    assert.equal(node.loading, false);
  });

  test(`${mode}: success resets the attempt budget for a later reload`, async () => {
    const f = await fixture(), node = f.node('r', mode);
    for (let number = 0; number < 5; number++) await f.attempt(node, mode, false);
    await f.attempt(node, mode, true);
    assert.equal(node.loadAttempts, 0, 'Success must reset prior failures');
    node.loaded = false;
    node.nodeType = mode === 'hierarchy' ? 2 : 1;
    await f.attempt(node, mode, false);
    assert.equal(node.loadAttempts, 1);
    assert.ok(!f.loader.error, 'A later reload must get its own retry budget');
  });
}

test('success in another node does not hide an exhausted node error', async () => {
  const f = await fixture(), failed = f.node('r0'), healthy = f.node('r1');
  for (let number = 0; number < 6; number++) await f.attempt(failed, 'worker', false);
  const terminalError = f.loader.error;
  assert.ok(terminalError);
  await f.attempt(healthy, 'worker', true);
  assert.equal(f.loader.error, terminalError);
  assert.equal(healthy.loadAttempts, 0);
});
