import {Potree, PotreeLoader, Vector3, SplatType} from 'potree';

const $ = id => document.getElementById(id);
const started = performance.now();
const origin = [566000, 153000, 0];
const local = a => a.map((v, i) => v - origin[i]);
const scenePoint = a => new Vector3(...local(a));
const clouds = new Map();
const sourceLabels = {
  tatry: 'Tatry · NMT 2019 + DMR 5.0',
  nmt2019: 'Tatry · NMT 2019 · siatka 5 m',
  regional: 'Tatry · NMT z ALS 2025 · krok 4 m',
  kozia: 'Kozia · lokalny szczegół ALS 2025',
};
const failures = [];
let model, viewer, groups, selected = 'Kozia', view = 'above', readyAt = null;
let renderedLegs = 0, firstFrameAt = null, lastFrame = null;
const frameTimes = [];

function fail(message) {
  if (failures.includes(String(message))) return;
  failures.push(String(message));
  $('error').textContent = String(message);
  $('error').style.display = 'block';
  $('status').textContent = 'Błąd — widok może być niekompletny. Odśwież stronę, aby ponowić.';
}
window.addEventListener('error', event => fail(event.message));
window.addEventListener('unhandledrejection', event => fail(event.reason?.message || event.reason));

function choose(id) {
  selected = id;
  $('cave').value = id;
}

function setView(kind) {
  view = kind;
  if (kind === 'region') choose('all');
  const b = selected === 'all' ? model.bounds : groups.get(selected).bounds;
  const middle = b.min.map((v, i) => (v + b.max[i]) / 2);
  const size = b.max.map((v, i) => v - b.min[i]);
  const radius = Math.max(150, Math.hypot(...size));
  if (kind === 'below') {
    const position = [middle[0] + radius * .52, middle[1] - radius * .60, middle[2] - radius * .65];
    viewer.controls.set({position: local(position), pivot: local(middle)});
  } else {
    viewer.controls.set({position: local([middle[0] + radius * .52, middle[1] - radius * .65, middle[2] + radius * .75]), pivot: local(middle)});
  }
  updateVisibility();
  updateCaption();
}

function updateVisibility() {
  for (const [key, cloud] of clouds) cloud.visible = $('terrain').checked && key === $('source').value;
}

function updateCaption() {
  const name = selected === 'all' ? 'Cały model JKTZ' : groups.get(selected).name;
  $('caption').textContent = `${name} · ${view === 'below' ? 'kamera pod powierzchnią' : 'widok z góry'} · ${$('source').selectedOptions[0].textContent}`;
}

function getState() {
  return {
    ready: readyAt !== null, readyMs: readyAt, firstFrameMs: firstFrameAt,
    selected, view, origin, crs: model?.crs, catalogSource: model?.source,
    camera: viewer ? viewer.camera.getWorldPosition().toArray().map((v, i) => v + origin[i]) : null,
    renderedLegs, totalLegs: model?.counts.legs,
    terrainVisible: $('terrain').checked, source: $('source').value,
    pointBudget: Potree.settings.pointBudget,
    points: Potree.state.numVisiblePoints, nodes: Potree.state.numNodes,
    fps: Potree.state.fps, frames: frameTimes.slice(), failures: failures.slice(),
    clouds: [...clouds].map(([key, c]) => ({key, visible: c.visible, rootLoaded: c.root.loaded, points: c.loader.metadata.points, position: c.position.toArray(), bounds: c.getBoundingBoxWorld?.()})),
    adapter: viewer ? {vendor: viewer.renderer.adapter.info.vendor, architecture: viewer.renderer.adapter.info.architecture} : null,
    memoryJS: performance.memory ? {used: performance.memory.usedJSHeapSize, total: performance.memory.totalJSHeapSize} : null,
    resources: viewer?.renderer.createResourceReport(),
  };
}

window.jktz = {getState, setView, select: id => {choose(id); setView('above');}, resetTiming: () => {frameTimes.length = 0;}, getModel: () => model, getClouds: () => clouds};

async function init() {
  if (!isSecureContext || !navigator.gpu) throw new Error('Ten podgląd wymaga WebGPU w obsługiwanej przeglądarce oraz HTTPS lub localhost.');
  const adapter = await navigator.gpu.requestAdapter();
  if (!adapter) throw new Error('Przeglądarka nie udostępniła urządzenia WebGPU.');
  model = await fetch('../../data/caves.json').then(r => {if (!r.ok) throw Error('Nie można odczytać poligonów'); return r.json();});
  if (model.origin.some((v, i) => v !== origin[i])) throw Error('Niezgodny początek układu współrzędnych');
  groups = new Map(model.groups.map(g => [g.id, g]));
  $('cave').replaceChildren(...[['all', 'Wszystkie jaskinie JKTZ'], ...model.groups.map(g => [g.id, g.name])].map(([id, name]) => {const o = document.createElement('option'); o.value = id; o.textContent = name; return o;}));
  $('catalogRelease').textContent = model.source.version;
  $('catalogRelease').href = model.source.releaseUrl;
  const publication = await fetch('../../publication.json').then(r => {if (!r.ok) throw Error('Brak manifestu publikacji'); return r.json();});
  const sources = publication.terrain.clouds;
  $('dmrAttribution').hidden = !sources.tatry;
  const sourceSelect = $('source');
  sourceSelect.replaceChildren(...Object.keys(sourceLabels).filter(key => sources[key]).map(key => new Option(sourceLabels[key], key)));
  sourceSelect.value = ['tatry', 'nmt2019', 'regional'].find(key => sources[key]);
  choose(groups.has('Kozia') ? 'Kozia' : model.groups[0].id);
  if (/^[a-f0-9]{40}$/.test(publication.commit)) $('codeSource').href = `https://github.com/dlubom/jktz-mapa-3d/tree/${publication.commit}`;
  viewer = await Potree.init($('canvas'));
  window.potree = viewer;
  window.Potree = Potree;
  viewer.renderer.device.addEventListener('uncapturederror', event => fail(`WebGPU: ${event.error.message}`));
  viewer.renderer.device.lost.then(info => fail(`Urządzenie WebGPU utracone: ${info.message}`));
  Object.assign(Potree.settings, {edlEnabled: true, hqsEnabled: false, dilateEnabled: false, pointBudget: 1_000_000, pointSize: 2, minNodeSize: 60, attribute: 'rgba', splatType: SplatType.POINTS, showBoundingBox: false});
  const requestedBudget = Number(new URLSearchParams(location.search).get('budget') || 1000000);
  if ([1000000, 2000000, 4000000].includes(requestedBudget)) {Potree.settings.pointBudget = requestedBudget; $('budget').value = String(requestedBudget);}
  const cyan = new Vector3(0, 1, 1), yellow = new Vector3(1, 1, 0);
  const rendered = new Map(model.groups.map(g => [g.id, g.legs.map(a => [scenePoint(a.slice(0, 3)), scenePoint(a.slice(3, 6))])]));
  viewer.onUpdate(() => {
    renderedLegs = 0;
    if ($('caveVisible').checked) {
      const visibleGroups = selected === 'all' ? model.groups : [groups.get(selected)];
      for (const group of visibleGroups) for (const [a, b] of rendered.get(group.id)) {viewer.renderer.drawLine(a, b, cyan); renderedLegs++;}
      if (selected === 'Kozia' || selected === 'all') for (const c of model.controls.filter(c => ['opening', 'gnss'].includes(c.role))) {
        for (let axis = 0; axis < 3; axis++) {const a = [c.x, c.y, c.z], b = a.slice(); a[axis] -= 2; b[axis] += 2; viewer.renderer.drawLine(scenePoint(a), scenePoint(b), yellow);}
      }
    }
  });
  Potree.events.onFrameEnd(() => {
    const now = performance.now();
    if (firstFrameAt === null) firstFrameAt = now - started;
    if (lastFrame !== null) {frameTimes.push(now - lastFrame); if (frameTimes.length > 1800) frameTimes.shift();}
    lastFrame = now;
    const active = clouds.get($('source').value);
    if (active?.root.loaded && Potree.state.numVisiblePoints > 0 && readyAt === null) readyAt = now - started;
  });
  $('above').onclick = () => setView('above');
  $('below').onclick = () => setView('below');
  $('region').onclick = () => setView('region');
  $('cave').onchange = () => {choose($('cave').value); setView('above');};
  $('source').onchange = () => {updateVisibility(); updateCaption();};
  $('terrain').onchange = updateVisibility;
  $('budget').onchange = () => {Potree.settings.pointBudget = Number($('budget').value);};
  $('size').oninput = () => {Potree.settings.pointSize = Number($('size').value); $('sizeValue').textContent = $('size').value;};
  setView(new URLSearchParams(location.search).get('view') || 'below');
  const activeSource = $('source').value;
  for (const key of [activeSource, ...Object.keys(sources).filter(key => key !== activeSource)]) {
    const cloud = await PotreeLoader.load(new URL(`../../data/${sources[key].metadata}`, location.href).href);
    cloud.name = key;
    cloud.position.sub(new Vector3(...origin));
    cloud.updateWorld();
    clouds.set(key, cloud);
    viewer.scene.root.children.push(cloud);
    updateVisibility();
  }
  const coverage = await fetch('../../data/coverage.json').then(r => {if (!r.ok) throw Error('Brak danych o pokryciu terenu'); return r.json();});
  $('coverage').textContent = coverage.description;
  $('coverageSummary').textContent = `${coverage.source || 'ALS 2025'} obejmuje ${coverage.summary}.`;
  setInterval(() => {
    const active = clouds.get($('source').value);
    if (active?.loader.error) fail(active.loader.error);
    if (!failures.length) $('status').textContent = active?.root.loaded ? 'WebGPU działa · dane wczytywane zależnie od widoku' : 'Ładowanie hierarchii punktów…';
    $('metrics').textContent = `${Number(Potree.state.numVisiblePoints || 0).toLocaleString('pl-PL')} widocznych punktów · ${renderedLegs.toLocaleString('pl-PL')} odcinków · ${Potree.state.fps} kl./s`;
  }, 500);
}
init().catch(fail);
