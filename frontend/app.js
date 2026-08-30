/* app.js - Simple plain JS frontend for Dataset Annotator */

const API_BASE = 'http://localhost:8080';

// State
let canvas = null;
let ctx = null;
let annotations = []; // Local in-memory annotations
let selectedAnnotationId = null;
let currentTool = 'select';
let currentDatasetId = null;
let currentDataItemId = 1;
let currentImage = null;
let isDrawing = false;
let drawStart = { x: 0, y: 0 };
let currentDrawRect = null;
let imageScale = 1;
let imageOffset = { x: 0, y: 0 };
let totalItems = 0;

// Tree/navigation state
let treeNodes = [];
let treeItems = [];
let treeExpanded = new Set();
let currentItemIndex = -1;
let currentItemStatus = null;

// Interaction state
let interactionMode = null; // 'move', 'resize', 'rotate', null
let interactionHandle = null;
let interactionStart = { x: 0, y: 0 };
let originalAnnotation = null;

// Field/taxonomy state
const FALLBACK_FIELDS = [
  { name: 'Text', datatype: 'string', allow_custom: false, provide_suggestions: true },
  { name: 'Type', datatype: 'enum', enum_values: ['Medicine', 'Advice', 'Frequency', 'Other'], allow_custom: true, custom_label: 'Other (specify)' },
  { name: 'Dosage', datatype: 'string', allow_custom: false, provide_suggestions: true },
  { name: 'Frequency', datatype: 'enum', enum_values: ['Once daily', 'Twice daily', 'Three times daily', 'Four times daily', 'As needed', 'Weekly', 'Monthly', 'Other'], allow_custom: true, custom_label: 'Other (specify)' },
  { name: 'Route', datatype: 'enum', enum_values: ['Oral', 'Topical', 'Injection', 'Inhalation', 'Sublingual', 'Rectal', 'Other'], allow_custom: true, custom_label: 'Other (specify)' },
  { name: 'Confidence', datatype: 'number', allow_custom: false, provide_suggestions: false },
  { name: 'Notes', datatype: 'string', allow_custom: false, provide_suggestions: false }
];
let fieldConfigs = FALLBACK_FIELDS;  // from /api/fields/config (user-facing fields)
let enumCache = {};             // field name -> enum values from /api/fields/enum-values
let currentFieldConfig = null;  // FieldConfig for the currently selected field name
let currentSuggestionField = null;   // field name to mine backend suggestions from
let currentSuggestionBase = [];      // local base options (e.g. enum values) to merge in
let fieldNameTimer = null;
let suggestionTimer = null;

// User-created ("Other") field names, persisted so they stay available for
// every annotation in a session.
let customFieldRegistry = [];
try {
  customFieldRegistry = JSON.parse(localStorage.getItem('datasetAnnotatorCustomFields') || '[]');
  if (!Array.isArray(customFieldRegistry)) customFieldRegistry = [];
} catch (e) {
  customFieldRegistry = [];
}
function persistCustomFields() {
  localStorage.setItem('datasetAnnotatorCustomFields', JSON.stringify(customFieldRegistry));
}
function registerCustomField(name) {
  if (!name) return;
  const known = new Set(fieldConfigs.map(f => f.name));
  if (!known.has(name) && !customFieldRegistry.includes(name)) {
    customFieldRegistry.push(name);
    persistCustomFields();
  }
}

// Initialize
document.addEventListener('DOMContentLoaded', init);

async function init() {
  canvas = document.getElementById('canvas');
  ctx = canvas.getContext('2d');
  
  loadFieldConfigs();
  loadS3ConfigFromStorage();
  await setupDataset();
  setupCanvas();
  setupEventListeners();
  setupSidebarResizer();
  fitCanvasToContainer();
  window.addEventListener('resize', () => {
    fitCanvasToContainer();
    layoutImage();
  });
  renderCanvas();
}

async function setupDataset() {
  try {
    const r = await fetch(`${API_BASE}/api/datasets`);
    if (r.ok) {
      const data = await r.json();
      if (data.datasets && data.datasets.length > 0) {
        const ds = data.datasets[0];
        currentDatasetId = ds.id;
        document.getElementById('datasetPath').textContent = ds.name || 'Dataset';
        if (ds.path) document.getElementById('folderPathInput').value = ds.path;
        await loadTree(ds.id);
      } else {
        document.getElementById('datasetPath').textContent = 'No dataset yet';
        setTreeStatus('Enter a folder path above and click Open');
      }
    }
  } catch (e) {
    console.error('Failed to load datasets:', e);
  }
}

async function openFolder() {
  const pathInput = document.getElementById('folderPathInput');
  const path = pathInput.value.trim();
  if (!path) {
    setTreeStatus('Enter a folder path first');
    return;
  }
  setTreeStatus('Opening ' + path + ' ...');
  try {
    const r = await fetch(`${API_BASE}/api/datasets/open`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    if (!r.ok) {
      setTreeStatus('Failed: ' + (await r.text() || r.status));
      return;
    }
    const data = await r.json();
    currentDatasetId = data.dataset_id;
    document.getElementById('datasetPath').textContent = data.name;
    document.getElementById('folderPathInput').value = data.path;
    await loadTree(data.dataset_id);
  } catch (e) {
    setTreeStatus('Error: ' + e.message);
  }
}

async function loadTree(datasetId) {
  currentDatasetId = datasetId;
  try {
    const r = await fetch(`${API_BASE}/api/datasets/${datasetId}/tree`);
    if (!r.ok) {
      setTreeStatus('Failed to load tree');
      return;
    }
    const data = await r.json();
    treeNodes = data.nodes || [];
    treeItems = data.items || [];
    totalItems = treeItems.length;
    treeExpanded = new Set();
    seedExpanded(treeNodes, '');
    renderTree();
    if (treeItems.length > 0) {
      setTreeStatus(treeItems.length + ' image(s)');
      await loadItemAt(0);
    } else {
      setTreeStatus('No supported images found in this folder');
    }
  } catch (e) {
    setTreeStatus('Tree error: ' + e.message);
  }
}

function seedExpanded(nodes, prefix) {
  nodes.forEach(n => {
    if (n.type === 'dir') {
      const key = prefix + '/' + n.name;
      treeExpanded.add(key);
      seedExpanded(n.children, key);
    }
  });
}

async function loadItemAt(index) {
  if (index < 0 || index >= treeItems.length) return;
  currentItemIndex = index;
  const item = treeItems[index];
  currentDataItemId = item.id;
  currentItemStatus = item.status;
  await loadImage(item);
  await loadAnnotationsFromServer();
  updateNavButtons();
  updateTreeHighlight(item.id);
}

function updateNavButtons() {
  document.getElementById('prevImgBtn').disabled = currentItemIndex <= 0;
  document.getElementById('nextImgBtn').disabled = currentItemIndex >= treeItems.length - 1;
  document.getElementById('markDoneBtn').disabled = currentItemIndex < 0;
  const counter = document.getElementById('itemCounter');
  if (counter) counter.textContent = treeItems.length ? (currentItemIndex + 1) + ' / ' + treeItems.length : '0 / 0';
  updateDoneButton();
}

function updateDoneButton() {
  const btn = document.getElementById('markDoneBtn');
  const done = currentItemStatus === 'done';
  btn.textContent = done ? 'Unmark Done' : 'Mark Done';
  btn.classList.toggle('done', done);
}

async function toggleDone() {
  if (currentItemIndex < 0) return;
  const item = treeItems[currentItemIndex];
  const newStatus = item.status === 'done' ? 'pending' : 'done';
  try {
    const r = await fetch(`${API_BASE}/api/datasets/${currentDatasetId}/items/${item.id}/status?status=${encodeURIComponent(newStatus)}`, {
      method: 'PATCH'
    });
    if (r.ok) {
      item.status = newStatus;
      currentItemStatus = newStatus;
      renderTree();
      updateTreeHighlight(item.id);
      updateNavButtons();
    }
  } catch (e) {
    console.error('Failed to toggle done:', e);
  }
}

function goToItem(delta) {
  loadItemAt(currentItemIndex + delta);
}

function renderTree() {
  const box = document.getElementById('folderTree');
  box.innerHTML = '';
  if (!treeNodes.length) {
    const empty = document.createElement('div');
    empty.className = 'tree-empty';
    empty.textContent = 'No images yet. Enter a folder path above and click Open.';
    box.appendChild(empty);
    return;
  }
  const ul = renderTreeNodes(treeNodes, '');
  if (ul) box.appendChild(ul);
}

function renderTreeNodes(nodes, prefix) {
  if (!nodes || !nodes.length) return null;
  const ul = document.createElement('ul');
  ul.className = 'tree-list';
  nodes.forEach(n => {
    const li = document.createElement('li');
    li.className = 'tree-node ' + n.type;
    if (n.type === 'dir') {
      const key = prefix + '/' + n.name;
      const open = treeExpanded.has(key);
      if (open) li.classList.add('open');
      li.dataset.dir = key;
      const caret = document.createElement('span');
      caret.className = 'tree-caret';
      caret.textContent = open ? '▾' : '▸';
      const name = document.createElement('span');
      name.className = 'tree-name';
      name.textContent = n.name;
      li.appendChild(caret);
      li.appendChild(name);
      if (open) {
        const sub = renderTreeNodes(n.children, key);
        if (sub) li.appendChild(sub);
      }
    } else {
      if (n.status === 'done') li.classList.add('done');
      li.dataset.item = n.item_id;
      const status = document.createElement('span');
      status.className = 'tree-status';
      status.textContent = n.status === 'done' ? '✓' : '';
      const name = document.createElement('span');
      name.className = 'tree-name';
      name.textContent = n.name;
      li.appendChild(status);
      li.appendChild(name);
    }
    ul.appendChild(li);
  });
  return ul;
}

function updateTreeHighlight(itemId) {
  const box = document.getElementById('folderTree');
  box.querySelectorAll('.tree-node.file.active').forEach(el => el.classList.remove('active'));
  const li = box.querySelector('.tree-node.file[data-item="' + itemId + '"]');
  if (li) {
    li.classList.add('active');
    li.scrollIntoView({ block: 'nearest' });
  }
}

function onTreeClick(e) {
  const li = e.target.closest('li.tree-node');
  if (!li) return;
  if (li.classList.contains('dir')) {
    const key = li.dataset.dir;
    if (treeExpanded.has(key)) treeExpanded.delete(key);
    else treeExpanded.add(key);
    renderTree();
    if (treeItems[currentItemIndex]) updateTreeHighlight(treeItems[currentItemIndex].id);
  } else if (li.classList.contains('file')) {
    const idx = treeItems.findIndex(i => i.id === Number(li.dataset.item));
    if (idx >= 0) loadItemAt(idx);
  }
}

function setTreeStatus(msg) {
  const el = document.getElementById('treeStatus');
  if (el) el.textContent = msg || '';
}

function toggleOperations() {
  document.getElementById('opsModal').style.display = 'flex';
}

function closeOperations() {
  document.getElementById('opsModal').style.display = 'none';
}

function setupSidebarResizer() {
  const resizer = document.getElementById('sidebarResizer');
  resizer.addEventListener('mousedown', (e) => {
    e.preventDefault();
    document.body.classList.add('resizing');
    resizer.classList.add('active');
    const startX = e.clientX;
    const startW = document.querySelector('.sidebar').getBoundingClientRect().width;
    const move = (ev) => {
      const w = Math.min(800, Math.max(180, startW + (ev.clientX - startX)));
      document.documentElement.style.setProperty('--sidebar-width', w + 'px');
    };
    const up = () => {
      document.body.classList.remove('resizing');
      resizer.classList.remove('active');
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
}

function fitCanvasToContainer() {
  const wrap = document.querySelector('.canvas-wrapper');
  if (!wrap) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(100, Math.round(wrap.clientWidth * dpr));
  canvas.height = Math.max(100, Math.round(wrap.clientHeight * dpr));
}

function layoutImage() {
  if (!currentImage) return;
  const dpr = window.devicePixelRatio || 1;
  const pad = 8 * dpr;
  const maxW = canvas.width - pad * 2;
  const maxH = canvas.height - pad * 2;
  imageScale = Math.min(maxW / currentImage.width, maxH / currentImage.height);
  imageOffset.x = (canvas.width - currentImage.width * imageScale) / 2;
  imageOffset.y = (canvas.height - currentImage.height * imageScale) / 2;
  renderCanvas();
}

async function loadImage(item) {
  currentDataItemId = item.id;
  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.onload = () => {
    currentImage = img;
    layoutImage();
  };
  img.onerror = (e) => {
    console.error('Image load error:', e);
    currentImage = null;
    renderCanvas();
  };
  img.src = `${API_BASE}/api/images/${item.id}`;
}

async function loadAnnotationsFromServer() {
  try {
    const r = await fetch(`${API_BASE}/api/data-items/${currentDataItemId}/annotations`);
    if (r.ok) {
      const serverAnns = await r.json();
      annotations = serverAnns.map(x => ({
        ...x.annotation,
        fields: x.fields || {},
        localOnly: false,
        dirty: false
      }));
      selectedAnnotationId = null;
      updateUI();
      renderAnnotationList();
      renderCanvas();
    }
  } catch (e) {
    console.error('Failed to load annotations:', e);
  }
}

function setupCanvas() {
  canvas.addEventListener('mousedown', onMouseDown);
  canvas.addEventListener('mousemove', onMouseMove);
  canvas.addEventListener('mouseup', onMouseUp);
  canvas.addEventListener('click', onClick);
}

function setupEventListeners() {
  // Tool buttons
  document.getElementById('toolSelect').addEventListener('click', () => setTool('select'));
  document.getElementById('toolRect').addEventListener('click', () => setTool('rectangle'));
  document.getElementById('toolPoint').addEventListener('click', () => setTool('point'));
  document.getElementById('toolLine').addEventListener('click', () => setTool('line'));

  // Folder + tree
  document.getElementById('openFolderBtn').addEventListener('click', openFolder);
  document.getElementById('folderPathInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); openFolder(); }
  });
  document.getElementById('folderTree').addEventListener('click', onTreeClick);

  // Navigation
  document.getElementById('prevImgBtn').addEventListener('click', () => goToItem(-1));
  document.getElementById('nextImgBtn').addEventListener('click', () => goToItem(1));
  document.getElementById('markDoneBtn').addEventListener('click', toggleDone);

  // Actions
  document.getElementById('clearAllBtn').addEventListener('click', clearAllAnnotations);
  document.getElementById('resetDbBtn').addEventListener('click', resetEntireDb);

  // Operations toggle
  document.getElementById('operationsToggleBtn').addEventListener('click', toggleOperations);
  document.getElementById('opsCloseBtn').addEventListener('click', closeOperations);
  document.getElementById('opsModal').addEventListener('click', (e) => {
    if (e.target && e.target.id === 'opsModal') closeOperations();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeOperations();
  });

  // Lock/unlock/delete
  document.getElementById('lockBtn').addEventListener('click', () => toggleLock(true));
  document.getElementById('unlockBtn').addEventListener('click', () => toggleLock(false));
  document.getElementById('deleteBtn').addEventListener('click', deleteAnnotation);

  // Field controls (combobox: a single input that autocompletes + accepts typing)
  document.getElementById('addFieldBtn').addEventListener('click', addField);
  document.getElementById('fieldNameInput').addEventListener('input', onFieldNameType);
  document.getElementById('fieldNameInput').addEventListener('change', onFieldNameCommit);
  document.getElementById('fieldNameInput').addEventListener('blur', onFieldNameCommit);

  // Field value + suggestion behavior
  document.getElementById('fieldValue').addEventListener('focus', () => {
    clearTimeout(suggestionTimer);
    suggestionTimer = setTimeout(doSuggest, 120);
  });
  document.getElementById('fieldValue').addEventListener('input', () => {
    clearTimeout(suggestionTimer);
    suggestionTimer = setTimeout(doSuggest, 250);
    updateAddFieldState();
  });
  document.getElementById('fieldValue').addEventListener('keydown', onValueKeydown);
  document.getElementById('fieldValue').addEventListener('blur', () => {
    setTimeout(() => hideSuggestions(), 150);
  });

  // Operations: export + S3
  document.getElementById('exportBtn').addEventListener('click', () => runExport(false));
  document.getElementById('exportS3Btn').addEventListener('click', () => runExport(true));
  document.getElementById('s3SaveBtn').addEventListener('click', saveS3Config);
  document.getElementById('s3TestBtn').addEventListener('click', testS3Connection);
}

function setTool(tool) {
  currentTool = tool;
  const idMap = { select: 'toolSelect', rectangle: 'toolRect', point: 'toolPoint', line: 'toolLine' };
  document.querySelectorAll('.toolbar button').forEach(btn => btn.classList.remove('active'));
  const toolBtn = document.getElementById(idMap[tool]);
  if (toolBtn) toolBtn.classList.add('active');
  
  canvas.style.cursor = tool === 'select' ? 'default' : 'crosshair';
}

function getImgCoords(e) {
  const rect = canvas.getBoundingClientRect();
  const sx = rect.width ? canvas.width / rect.width : 1;
  const sy = rect.height ? canvas.height / rect.height : 1;
  return {
    x: ((e.clientX - rect.left) * sx - imageOffset.x) / imageScale,
    y: ((e.clientY - rect.top) * sy - imageOffset.y) / imageScale
  };
}

function onMouseDown(e) {
  const coords = getImgCoords(e);
  
  if (currentTool !== 'select') {
    // Drawing mode
    drawStart.x = coords.x;
    drawStart.y = coords.y;
    isDrawing = true;
    return;
  }
  
  // Select tool - if no selection, try to select an annotation first
  if (!selectedAnnotationId) {
    for (let i = annotations.length - 1; i >= 0; i--) {
      const ann = annotations[i];
      if (isPointInAnnotation(coords.x, coords.y, ann)) {
        selectAnnotation(ann.id);
        return;
      }
    }
    return;
  }
  
  // Have a selection - check handle interaction
  const ann = annotations.find(a => a.id === selectedAnnotationId);
  const annData = ann.annotation || ann;
  if (!ann || annData.is_locked) return;
  
  const bounds = getHandleBounds(ann);
  if (!bounds) return;
  
  const handle = hitTestHandle(bounds, coords.x, coords.y);
  if (!handle) {
    // Drag from anywhere inside the selected annotation to move it
    if (isPointInAnnotation(coords.x, coords.y, ann)) {
      interactionMode = 'move';
      interactionHandle = 'center';
      interactionStart = { x: coords.x, y: coords.y };
      originalAnnotation = JSON.parse(JSON.stringify(ann));
      isDrawing = true;
    }
    return;
  }
  
  // Start interaction
  interactionMode = handle === 'center' ? 'move' : (handle === 'rotate' ? 'rotate' : 'resize');
  interactionHandle = handle;
  interactionStart = { x: coords.x, y: coords.y };
  
  originalAnnotation = JSON.parse(JSON.stringify(ann));
  
  isDrawing = true;
}

function onMouseMove(e) {
  const coords = getImgCoords(e);
  
  if (isDrawing && currentTool !== 'select') {
    // Drawing new annotation - live preview
    if (currentTool === 'rectangle') {
      currentDrawRect = {
        x: Math.min(drawStart.x, coords.x),
        y: Math.min(drawStart.y, coords.y),
        w: Math.abs(coords.x - drawStart.x),
        h: Math.abs(coords.y - drawStart.y)
      };
      renderCanvas();
    }
    return;
  }
  
  if (isDrawing && currentTool === 'select' && interactionMode) {
    // Interaction with existing annotation (move / resize / rotate)
    const ann = annotations.find(a => a.id === selectedAnnotationId);
    const annData = ann.annotation || ann;
    if (!ann || annData.is_locked) return;
    
    const dx = (coords.x - interactionStart.x);
    const dy = (coords.y - interactionStart.y);
    
    const geom = JSON.parse(ann.geometry_json);
    
    if (interactionMode === 'move') {
      // Move annotation
      switch (annData.annotation_type) {
        case 'rectangle':
          geom.coordinates[0][0] += dx;
          geom.coordinates[0][1] += dy;
          geom.coordinates[1][0] += dx;
          geom.coordinates[1][1] += dy;
          break;
        case 'point':
          geom.coordinates[0] += dx;
          geom.coordinates[1] += dy;
          break;
        case 'line':
          geom.coordinates[0][0] += dx;
          geom.coordinates[0][1] += dy;
          geom.coordinates[1][0] += dx;
          geom.coordinates[1][1] += dy;
          break;
      }
      interactionStart = { x: coords.x, y: coords.y };
      ann.geometry_json = JSON.stringify(geom);
      ann.dirty = true;
      renderCanvas();
    } else if (interactionMode === 'resize') {
      // Resize annotation by dragging a corner handle
      switch (annData.annotation_type) {
        case 'rectangle': {
          const rotRad = (geom.rotation || 0) * Math.PI / 180;
          if (rotRad) {
            const cos = Math.cos(-rotRad);
            const sin = Math.sin(-rotRad);
            const dx = coords.x - interactionStart.x;
            const dy = coords.y - interactionStart.y;
            const ldx = dx * cos - dy * sin;
            const ldy = dx * sin + dy * cos;
            if (interactionHandle === 'tl') {
              geom.coordinates[0][0] += ldx;
              geom.coordinates[0][1] += ldy;
            } else if (interactionHandle === 'tr') {
              geom.coordinates[0][1] += ldy;
              geom.coordinates[1][0] += ldx;
            } else if (interactionHandle === 'bl') {
              geom.coordinates[0][0] += ldx;
              geom.coordinates[1][1] += ldy;
            } else if (interactionHandle === 'br') {
              geom.coordinates[1][0] += ldx;
              geom.coordinates[1][1] += ldy;
            }
          } else {
            if (interactionHandle === 'tl') {
              geom.coordinates[0][0] += (coords.x - interactionStart.x);
              geom.coordinates[0][1] += (coords.y - interactionStart.y);
            } else if (interactionHandle === 'tr') {
              geom.coordinates[0][1] += (coords.y - interactionStart.y);
              geom.coordinates[1][0] += (coords.x - interactionStart.x);
            } else if (interactionHandle === 'bl') {
              geom.coordinates[0][0] += (coords.x - interactionStart.x);
              geom.coordinates[1][1] += (coords.y - interactionStart.y);
            } else if (interactionHandle === 'br') {
              geom.coordinates[1][0] += (coords.x - interactionStart.x);
              geom.coordinates[1][1] += (coords.y - interactionStart.y);
            }
          }
          break;
        }
        case 'line':
          if (interactionHandle === 'tl') {
            geom.coordinates[0][0] += (coords.x - interactionStart.x);
            geom.coordinates[0][1] += (coords.y - interactionStart.y);
          } else if (interactionHandle === 'br') {
            geom.coordinates[1][0] += (coords.x - interactionStart.x);
            geom.coordinates[1][1] += (coords.y - interactionStart.y);
          }
          break;
      }
      interactionStart = { x: coords.x, y: coords.y };
      ann.geometry_json = JSON.stringify(geom);
      ann.dirty = true;
      renderCanvas();
    } else if (interactionMode === 'rotate') {
      // Rotation handle: compute angle from box center to mouse
      // Reference formula: Math.atan2(pos.x - cx, -(pos.y - cy)) * 180 / Math.PI
      // Stored in degrees (matches crop server img.rotate(-angle)); converted to radians when drawing.
      const annot = annotations.find(a => a.id === selectedAnnotationId);
      const bounds = getHandleBounds(annot);
      if (!bounds) return;
      
      const centerX = (bounds.cx - imageOffset.x) / imageScale;
      const centerY = (bounds.cy - imageOffset.y) / imageScale;
      
      const startAngle = Math.atan2(interactionStart.x - centerX, -(interactionStart.y - centerY));
      const currentAngle = Math.atan2(coords.x - centerX, -(coords.y - centerY));
      const angleDelta = currentAngle - startAngle;
      
      const rotGeom = JSON.parse(ann.geometry_json);
      if (!rotGeom.rotation) rotGeom.rotation = 0;
      rotGeom.rotation += angleDelta * (180 / Math.PI);
      
      ann.geometry_json = JSON.stringify(rotGeom);
      ann.dirty = true;
      
      interactionStart = { x: coords.x, y: coords.y };
      renderCanvas();
    }
    return;
  }
  
  if (!isDrawing || currentTool === 'select') return;
  
  // Drawing preview for non-rectangle tools
  if (currentTool === 'line' || currentTool === 'point') {
    renderCanvas();
  }
}

async function onMouseUp(e) {
  if (isDrawing && currentTool !== 'select') {
    // Finish drawing new annotation
    const coords = getImgCoords(e);
    const x = coords.x;
    const y = coords.y;
    
    let geometry = null;
    
    switch (currentTool) {
      case 'rectangle':
        geometry = {
          type: 'rectangle',
          coordinates: [
            [Math.min(drawStart.x, x), Math.min(drawStart.y, y)],
            [Math.max(drawStart.x, x), Math.max(drawStart.y, y)]
          ]
        };
        break;
        
      case 'point':
        geometry = {
          type: 'point',
          coordinates: [drawStart.x, drawStart.y]
        };
        break;
        
      case 'line':
        geometry = {
          type: 'line',
          coordinates: [
            [drawStart.x, drawStart.y],
            [x, y]
          ]
        };
        break;
    }
    
    isDrawing = false;
    currentDrawRect = null;
    
    if (geometry) {
      await createAnnotationOnServer(currentTool, geometry);
    }
    
    renderCanvas();
    return;
  }
  
  if (isDrawing && currentTool === 'select' && interactionMode) {
    // End interaction - save if server-side annotation
    const ann = annotations.find(a => a.id === selectedAnnotationId);
    if (ann && !ann.localOnly) {
      ann.dirty = true;
      const saved = await updateAnnotationOnServer(ann);
      ann.dirty = !saved;
      renderAnnotationList();
    } else if (ann) {
      ann.dirty = true;
    }
    
    interactionMode = null;
    interactionHandle = null;
    originalAnnotation = null;
    isDrawing = false;
    renderCanvas();
    return;
  }
}

function onClick(e) {
  if (currentTool !== 'select') return;
  
  const coords = getImgCoords(e);
  const x = coords.x;
  const y = coords.y;
  
  // Check if clicking on an annotation
  for (let i = annotations.length - 1; i >= 0; i--) {
    const ann = annotations[i];
    if (isPointInAnnotation(x, y, ann)) {
      selectAnnotation(ann.id);
      return;
    }
  }
  
  // Deselect
  selectedAnnotationId = null;
  updateUI();
  renderCanvas();
}

function getHandleBounds(ann) {
  const annData = ann.annotation || ann;
  const geom = JSON.parse(annData.geometry_json);
  
  switch (annData.annotation_type) {
    case 'rectangle': {
      const x1 = imageOffset.x + geom.coordinates[0][0] * imageScale;
      const y1 = imageOffset.y + geom.coordinates[0][1] * imageScale;
      const x2 = imageOffset.x + geom.coordinates[1][0] * imageScale;
      const y2 = imageOffset.y + geom.coordinates[1][1] * imageScale;
      const cx = (x1 + x2) / 2;
      const cy = (y1 + y2) / 2;
      const rotRad = (geom.rotation || 0) * Math.PI / 180;
      let rotatedCorners = null;
      if (rotRad) {
        const cos = Math.cos(rotRad);
        const sin = Math.sin(rotRad);
        const hw = (x2 - x1) / 2;
        const hh = (y2 - y1) / 2;
        const local = [[-hw, -hh], [hw, -hh], [-hw, hh], [hw, hh]];
        rotatedCorners = local.map(([lx, ly]) => ({
          x: cx + lx * cos - ly * sin,
          y: cy + lx * sin + ly * cos
        }));
      }
      const minX = rotatedCorners ? Math.min(...rotatedCorners.map(p => p.x)) : x1;
      const minY = rotatedCorners ? Math.min(...rotatedCorners.map(p => p.y)) : y1;
      const maxX = rotatedCorners ? Math.max(...rotatedCorners.map(p => p.x)) : x2;
      const maxY = rotatedCorners ? Math.max(...rotatedCorners.map(p => p.y)) : y2;
      return { x: minX, y: minY, w: maxX - minX, h: maxY - minY, cx, cy, rotatedCorners, rotation: geom.rotation || 0 };
    }
    case 'point':
      const px = imageOffset.x + geom.coordinates[0] * imageScale;
      const py = imageOffset.y + geom.coordinates[1] * imageScale;
      return { x: px - 8, y: py - 8, w: 16, h: 16, cx: px, cy: py };
    case 'line':
      const lx1 = imageOffset.x + geom.coordinates[0][0] * imageScale;
      const ly1 = imageOffset.y + geom.coordinates[0][1] * imageScale;
      const lx2 = imageOffset.x + geom.coordinates[1][0] * imageScale;
      const ly2 = imageOffset.y + geom.coordinates[1][1] * imageScale;
      return { 
        x: Math.min(lx1, lx2), y: Math.min(ly1, ly2), 
        w: Math.abs(lx2 - lx1), h: Math.abs(ly2 - ly1),
        cx: (lx1+lx2)/2, cy: (ly1+ly2)/2,
        x1: lx1, y1: ly1, x2: lx2, y2: ly2
      };
  }
  return null;
}

function hitTestHandle(bounds, x, y) {
  // x, y are in image coordinates (not canvas)
  // bounds are in canvas coordinates - convert x,y to canvas
  const canvasX = imageOffset.x + x * imageScale;
  const canvasY = imageOffset.y + y * imageScale;
  
  const corners = bounds.rotatedCorners
    ? bounds.rotatedCorners.map((c, i) => ({ x: c.x, y: c.y, name: ['tl', 'tr', 'bl', 'br'][i] }))
    : [
        { x: bounds.x, y: bounds.y, name: 'tl' },
        { x: bounds.x + bounds.w, y: bounds.y, name: 'tr' },
        { x: bounds.x, y: bounds.y + bounds.h, name: 'bl' },
        { x: bounds.x + bounds.w, y: bounds.y + bounds.h, name: 'br' }
      ];
  
  for (const c of corners) {
    if (canvasX >= c.x - 8 && canvasX <= c.x + 8 && canvasY >= c.y - 8 && canvasY <= c.y + 8) {
      return c.name;
    }
  }
  
  if (canvasX >= bounds.cx - 8 && canvasX <= bounds.cx + 8 && canvasY >= bounds.cy - 8 && canvasY <= bounds.cy + 8) {
    return 'center';
  }
  
  const rotateY = bounds.y - 20;
  if (canvasX >= bounds.cx - 8 && canvasX <= bounds.cx + 8 && canvasY >= rotateY - 8 && canvasY <= rotateY + 8) {
    return 'rotate';
  }
  
  return null;
}

function isPointInAnnotation(x, y, ann) {
  const geom = JSON.parse(ann.geometry_json);
  
  switch (ann.annotation_type) {
    case 'rectangle':
      return x >= geom.coordinates[0][0] && 
             x <= geom.coordinates[1][0] && 
             y >= geom.coordinates[0][1] && 
             y <= geom.coordinates[1][1];
             
    case 'point':
      const dx = x - geom.coordinates[0];
      const dy = y - geom.coordinates[1];
      return Math.sqrt(dx * dx + dy * dy) < 10;
      
    case 'line':
      const x1 = geom.coordinates[0][0];
      const y1 = geom.coordinates[0][1];
      const x2 = geom.coordinates[1][0];
      const y2 = geom.coordinates[1][1];
      const len = Math.sqrt((x2-x1)**2 + (y2-y1)**2);
      if (len === 0) return false;
      const dist = Math.abs((y2-y1)*x - (x2-x1)*y + x2*y1 - y2*x1) / len;
      return dist < 5;
      
    default:
      return false;
  }
}

async function createAnnotationOnServer(type, geometry) {
  try {
    const r = await fetch(`${API_BASE}/api/annotations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        data_item_id: currentDataItemId,
        annotation_type: type,
        geometry: { type, coordinates: geometry.coordinates }
      })
    });
    if (r.ok) {
      const created = await r.json();
      const ann = {
        ...created,
        localOnly: false,
        dirty: false,
        fields: {}
      };
      annotations.push(ann);
      selectAnnotation(ann.id);
      renderAnnotationList();
      return;
    }
    const errText = await r.text();
    alert('Failed to save annotation: ' + errText);
    createLocalAnnotation(type, geometry);
  } catch (e) {
    console.error('Create annotation error:', e);
    createLocalAnnotation(type, geometry);
  }
}

function createLocalAnnotation(type, geometry) {
  const geom = { type, coordinates: geometry.coordinates };
  
  const localAnn = {
    id: Date.now(), // temporary ID
    data_item_id: currentDataItemId,
    annotation_type: type,
    geometry_json: JSON.stringify(geom),
    crop_path: null,
    is_locked: false,
    annotation_order: annotations.length,
    localOnly: true,
    dirty: true,
    fields: {} // local fields storage
  };
  
  annotations.push(localAnn);
  selectAnnotation(localAnn.id);
  renderAnnotationList();
  renderCanvas();
}

function selectAnnotation(annId) {
  selectedAnnotationId = annId;
  const ann = annotations.find(a => a.id === annId);
  updateUI();
  renderCanvas();
  
  if (ann) {
    loadAnnotationFields(annId);
    renderCropPreview(ann);
  }
}

function updateUI() {
  const hasSelection = selectedAnnotationId !== null;
  document.getElementById('noSelection').style.display = hasSelection ? 'none' : 'block';
  document.getElementById('fieldGroup').style.display = hasSelection ? 'block' : 'none';
  document.getElementById('annotationControls').style.display = hasSelection ? 'block' : 'none';
  
  renderAnnotationList();
}

async function loadAnnotationFields(annId) {
  try {
    // First check if it's a local annotation
    const localAnn = annotations.find(a => a.id === annId);
    if (localAnn && localAnn.localOnly) {
      // Local annotation - use local fields
      renderFieldPanel(localAnn.fields || {});
      renderCanvas();
      return;
    }
    
    // Server annotation - fetch from API
    const r = await fetch(`${API_BASE}/api/annotations/${annId}`);
    if (r.ok) {
      const data = await r.json();
      const fields = data.fields || {};
      const ann = annotations.find(a => a.id === annId);
      if (ann) ann.fields = fields;
      renderFieldPanel(fields);
      renderCanvas();
      return;
    }
    
    // If not found on server, check local annotations
    const localAnn2 = annotations.find(a => a.id === annId);
    if (localAnn2 && localAnn2.fields) {
      renderFieldPanel(localAnn2.fields);
    }
  } catch (e) {
    console.error('Failed to load fields:', e);
  }
}

function renderFieldPanel(fields) {
  const nameInput = document.getElementById('fieldNameInput');
  const fieldsObj = (fields && typeof fields === 'object') ? fields : {};

  // Combobox options = config fields + user-created fields + fields seen on this annotation.
  const knownNames = new Set(fieldConfigs.map(f => f.name));
  customFieldRegistry.forEach(n => knownNames.add(n));
  Object.keys(fieldsObj).forEach(n => knownNames.add(n));

  const datalist = document.getElementById('fieldNameList');
  datalist.innerHTML = '';
  [...knownNames].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase())).forEach(name => {
    const opt = document.createElement('option');
    opt.value = name;
    datalist.appendChild(opt);
  });

  nameInput.value = '';
  nameInput.disabled = false;

  resetFieldInputs();
  currentSuggestionField = null;
  renderExistingFields(fieldsObj);
  updateAddFieldState();
}

function onFieldNameType() {
  clearTimeout(fieldNameTimer);
  fieldNameTimer = setTimeout(() => {
    const name = document.getElementById('fieldNameInput').value.trim();
    if (!name) { resetFieldInputs(); return; }
    setupValueWidgetForField(name);
  }, 300);
}

function onFieldNameCommit() {
  const name = document.getElementById('fieldNameInput').value.trim();
  if (name) setupValueWidgetForField(name);
}

let lastSetupField = null;

async function setupValueWidgetForField(fieldName) {
  const valueInput = document.getElementById('fieldValue');
  const preserve = fieldName === lastSetupField &&
    (valueInput.value.trim() !== '' || document.activeElement && document.activeElement.id === 'fieldValue');
  const preservedValue = preserve ? valueInput.value : '';

  resetFieldInputs();
  document.getElementById('fieldNameInput').value = fieldName;

  const cfg = fieldConfigs.find(f => f.name === fieldName);
  currentFieldConfig = cfg || null;

  if (cfg && cfg.datatype === 'enum') {
    await loadEnumOptions(cfg);
  } else {
    currentSuggestionBase = [];
    if ((cfg && cfg.provide_suggestions) || (!cfg && customFieldRegistry.includes(fieldName))) {
      currentSuggestionField = fieldName;
    }
  }
  lastSetupField = fieldName;
  if (preserve) valueInput.value = preservedValue;
  updateAddFieldState();
}

async function loadEnumOptions(cfg) {
  // Base options come from the enum config (+ recorded categories on the server).
  let values = enumCache[cfg.name];
  if (!values) {
    try {
      const r = await fetch(`${API_BASE}/api/fields/enum-values/${encodeURIComponent(cfg.name)}`);
      values = r.ok ? await r.json() : (cfg.enum_values || []);
    } catch (e) {
      values = cfg.enum_values || [];
    }
    enumCache[cfg.name] = values;
  }
  currentSuggestionBase = Array.isArray(values) ? values : [];
  // Keep backend suggestions on too (recorded values / annotation mining).
  currentSuggestionField = cfg.name;
}

function loadFieldConfigs() {
  fetch(`${API_BASE}/api/fields/config`)
    .then(r => r.json())
    .then(configs => {
      // Keep only user-facing fields (skip internal / hidden / json fields)
      const visible = configs.filter(f => !(f.hidden === true) && f.datatype !== 'json' && !(f.source && f.internal));
      fieldConfigs = visible.length ? visible : FALLBACK_FIELDS;
    })
    .catch(() => { fieldConfigs = FALLBACK_FIELDS; });
}

function onFieldNameChange() {
  const name = document.getElementById('fieldNameInput').value.trim();
  if (!name) { resetFieldInputs(); return; }
  setupValueWidgetForField(name);
}

function resetFieldInputs() {
  const input = document.getElementById('fieldValue');
  
  input.style.display = '';
  input.type = 'text';
  input.value = '';
  input.placeholder = 'Field value';
  input.disabled = false;
  
  currentFieldConfig = null;
  currentSuggestionBase = [];
  
  hideSuggestions();
  updateAddFieldState();
}

function getCurrentValue() {
  return document.getElementById('fieldValue').value.trim();
}

function updateAddFieldState() {
  const addBtn = document.getElementById('addFieldBtn');
  if (selectedAnnotationId === null) {
    addBtn.disabled = true;
    return;
  }
  
  const fieldName = document.getElementById('fieldNameInput').value.trim();
  const value = getCurrentValue();
  addBtn.disabled = !(fieldName && value);
}

function renderExistingFields(fieldsObj) {
  const box = document.getElementById('existingFields');
  box.innerHTML = '';
  const keys = Object.keys(fieldsObj);
  if (!keys.length) return;
  
  keys.forEach(name => {
    const raw = fieldsObj[name];
    const val = (raw !== null && typeof raw === 'object') ? raw.field_value : raw;
    const chip = document.createElement('div');
    chip.className = 'field-chip';
    chip.innerHTML = `<span class="chip-name">${escHtml(name)}</span><span class="chip-val">${escHtml(val === null || val === undefined ? '' : String(val))}</span>`;
    box.appendChild(chip);
  });
}

function escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function doSuggest() {
  const input = document.getElementById('fieldValue');
  const list = document.getElementById('suggestionList');
  const raw = input.value;
  const v = raw.toLowerCase();
  const minChars = 2;

  const hasBase = currentSuggestionBase && currentSuggestionBase.length > 0;
  const canBackend = !!currentSuggestionField && raw.length >= minChars;
  if (!hasBase && !canBackend) {
    hideSuggestions();
    return;
  }

  const matches = [];
  const seen = new Set();
  (currentSuggestionBase || []).forEach(opt => {
    const s = String(opt);
    if (v && !s.toLowerCase().includes(v)) return;
    const key = s.toLowerCase();
    if (!seen.has(key)) { seen.add(key); matches.push(s); }
  });

  if (canBackend) {
    try {
      const r = await fetch(`${API_BASE}/api/suggestions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field_name: currentSuggestionField, query: raw, limit: 10 })
      });
      if (r.ok) {
        const data = await r.json();
        (data.suggestions || []).forEach(s => {
          if (v && !s.toLowerCase().includes(v)) return;
          const key = s.toLowerCase();
          if (!seen.has(key)) { seen.add(key); matches.push(s); }
        });
      }
    } catch (e) {
      // transient - fall through with base matches
    }
  }

  if (!matches.length) {
    hideSuggestions();
    return;
  }

  list.innerHTML = matches.slice(0, 10).map((m, i) => `<div class="ac-item" data-i="${i}">${escHtml(m)}</div>`).join('');
  list.style.display = 'block';
  list.style.width = input.offsetWidth + 'px';
  list.querySelectorAll('.ac-item').forEach(item => {
    item.addEventListener('mousedown', e => {
      e.preventDefault();
      input.value = matches[Number(item.dataset.i)];
      updateAddFieldState();
      hideSuggestions();
    });
  });
}

function onValueKeydown(e) {
  const list = document.getElementById('suggestionList');
  if (list.style.display === 'none') {
    if (e.key === 'Enter') {
      e.preventDefault();
      addField();
    }
    return;
  }
  
  const items = list.querySelectorAll('.ac-item');
  if (!items.length) return;
  let active = list.querySelector('.ac-item.active');
  let ai = active ? [...items].indexOf(active) : -1;
  
  if (e.key === 'ArrowDown') { e.preventDefault(); ai = Math.min(ai + 1, items.length - 1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); ai = Math.max(ai - 1, 0); }
  else if (e.key === 'Enter' && active) { e.preventDefault(); active.dispatchEvent(new Event('mousedown')); return; }
  else if (e.key === 'Enter') { e.preventDefault(); hideSuggestions(); addField(); return; }
  else if (e.key === 'Escape') { hideSuggestions(); return; }
  else return;
  
  items.forEach(it => it.classList.remove('active'));
  if (items[ai]) items[ai].classList.add('active');
}

function hideSuggestions() {
  const list = document.getElementById('suggestionList');
  if (list) list.style.display = 'none';
}

function recordCategory(fieldName, value) {
  fetch(`${API_BASE}/api/field-categories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ field_name: fieldName, category_value: value, source: 'manual' })
  }).catch(e => console.error('Failed to record category:', e));
}

async function addField() {
  const fieldName = document.getElementById('fieldNameInput').value.trim();
  
  if (!fieldName || !selectedAnnotationId) { updateAddFieldState(); return; }
  
  const value = getCurrentValue();
  if (!value) { updateAddFieldState(); return; }
  
  // Keep user-created fields so they show up for every annotation.
  registerCustomField(fieldName);
  
  const ann = annotations.find(a => a.id === selectedAnnotationId);
  
  if (ann && ann.localOnly) {
    // Local annotation - store field locally
    if (!ann.fields) ann.fields = {};
    ann.fields[fieldName] = value;
    ann.dirty = true;
    recordCategory(fieldName, value);
    resetFieldInputs();
    loadAnnotationFields(selectedAnnotationId);
    renderCanvas();
    return;
  }
  
  const cfg = fieldConfigs.find(f => f.name === fieldName);
  const datatype = (cfg && cfg.datatype) || 'string';
  
  try {
    const r = await fetch(`${API_BASE}/api/annotations/${selectedAnnotationId}/fields`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        field_name: fieldName,
        field_value: value,
        datatype: datatype,
        field_config_json: null
      })
    });
    
    if (r.ok) {
      recordCategory(fieldName, value);
      resetFieldInputs();
      loadAnnotationFields(selectedAnnotationId);
      renderCanvas();
    } else {
      alert('Failed: ' + await r.text());
    }
  } catch (e) {
    console.error('Error:', e);
    alert('Error adding field: ' + e.message);
  }
}

async function toggleLock(lock) {
  if (!selectedAnnotationId) return;
  const ann = annotations.find(a => a.id === selectedAnnotationId);
  if (ann && ann.localOnly) {
    ann.is_locked = lock;
    updateUI();
    renderCanvas();
    return;
  }
  
  try {
    const endpoint = lock ? 'lock' : 'unlock';
    const r = await fetch(`${API_BASE}/api/annotations/${selectedAnnotationId}/${endpoint}`, {
      method: 'POST'
    });
    
    if (r.ok) {
      if (ann) {
        ann.is_locked = lock;
        updateUI();
        renderCanvas();
      }
    }
  } catch (e) {
    console.error('Error:', e);
  }
}

async function deleteAnnotation() {
  if (!selectedAnnotationId) return;
  if (!confirm('Delete this annotation?')) return;
  
  try {
    const ann = annotations.find(a => a.id === selectedAnnotationId);
    
    // If local only, just remove from memory
    if (ann.localOnly) {
      annotations = annotations.filter(a => a.id !== selectedAnnotationId);
      selectedAnnotationId = null;
      updateUI();
      renderAnnotationList();
      renderCanvas();
      return;
    }
    
    const r = await fetch(`${API_BASE}/api/annotations/${selectedAnnotationId}`, { method: 'DELETE' });
    if (r.ok) {
      selectedAnnotationId = null;
      loadAnnotationsFromServer();
    } else {
      alert('Failed: ' + await r.text());
    }
  } catch (e) {
    console.error('Error deleting annotation:', e);
  }
}

async function clearAllAnnotations() {
  if (!confirm('Clear ALL annotations for current image?')) return;
  
  try {
    for (const ann of annotations) {
      if (!ann.localOnly) {
        await fetch(`${API_BASE}/api/annotations/${ann.id}`, { method: 'DELETE' });
      }
    }
    loadAnnotationsFromServer();
  } catch (e) {
    console.error('Error clearing annotations:', e);
  }
}

async function resetEntireDb() {
  if (!confirm('RESET ENTIRE DATABASE? This will delete ALL annotations, fields, and categories. Cannot be undone!')) return;
  
  try {
    const r = await fetch(`${API_BASE}/api/reset-db`, { method: 'POST' });
    if (r.ok) {
      alert('Database reset. Reloading...');
      location.reload();
    } else {
      alert('Failed: ' + await r.text());
    }
  } catch (e) {
    console.error('Error resetting DB:', e);
  }
}

function renderAnnotationList() {
  const listEl = document.getElementById('annotationList');
  listEl.innerHTML = '';
  
  annotations.forEach(ann => {
    const div = document.createElement('div');
    div.className = 'annotation-item' + (ann.id === selectedAnnotationId ? ' selected' : '');
    
    if (!ann.localOnly) {
      const img = document.createElement('img');
      img.className = 'ann-crop';
      img.alt = 'crop';
      img.style.display = 'none';
      img.addEventListener('load', () => { img.style.display = 'block'; });
      img.addEventListener('error', () => { img.style.display = 'none'; });
      img.src = `${API_BASE}/api/images/crop/${ann.id}`;
      div.appendChild(img);
    }
    
    const info = document.createElement('div');
    info.className = 'ann-info';
    info.innerHTML = `
      <strong>${ann.annotation_type || 'unknown'}</strong>
      ${ann.localOnly ? '<span style="color:#f59e0b;font-size:0.6rem;">(local)</span>' : ''}
      ${ann.dirty ? '<span style="color:#3b82f6;font-size:0.6rem;">(unsaved)</span>' : ''}
      <span class="status-badge ${ann.is_locked ? 'status-locked' : 'status-unlocked'}">
        ${ann.is_locked ? 'Locked' : 'Unlocked'}
      </span>
    `;
    div.appendChild(info);
    
    div.addEventListener('click', () => selectAnnotation(ann.id));
    listEl.appendChild(div);
  });
}

function renderCanvas() {
  // Clear
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  
  // Background
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  
  // Draw image if loaded
  if (currentImage) {
    ctx.drawImage(
      currentImage,
      imageOffset.x,
      imageOffset.y,
      currentImage.width * imageScale,
      currentImage.height * imageScale
    );
  }
  
  // Draw annotations
  annotations.forEach(ann => {
    const isSelected = ann.id === selectedAnnotationId;
    drawAnnotation(ann, isSelected);
  });

  // Live crop preview for the selected annotation
  const selAnn = annotations.find(a => a.id === selectedAnnotationId);
  if (selAnn) renderCropPreview(selAnn);
  
  // Draw current drawing
  if (currentDrawRect) {
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 5]);
    const sx = imageOffset.x + currentDrawRect.x * imageScale;
    const sy = imageOffset.y + currentDrawRect.y * imageScale;
    const sw = currentDrawRect.w * imageScale;
    const sh = currentDrawRect.h * imageScale;
    ctx.strokeRect(sx, sy, sw, sh);
    ctx.setLineDash([]);
  }
}

function getAnnotationLabel(ann) {
  const fields = ann.fields;
  if (!fields) return '';
  const pick = (v) => {
    if (v === null || v === undefined) return '';
    return typeof v === 'object' ? (v.field_value ?? v.value ?? '') : v;
  };
  for (const f of fieldConfigs) {
    if (f.internal || f.hidden || f.datatype === 'json') continue;
    const v = pick(fields[f.name]);
    if (String(v).trim() !== '') return String(v);
  }
  for (const k of Object.keys(fields)) {
    const v = pick(fields[k]);
    if (String(v).trim() !== '') return String(v);
  }
  return '';
}

function drawAnnotation(ann, isSelected) {
  const geom = JSON.parse(ann.geometry_json);
  const color = isSelected ? '#3b82f6' : (ann.is_locked ? '#f59e0b' : '#ef4444');
  
  ctx.strokeStyle = color;
  ctx.lineWidth = isSelected ? 3 : 2;
  ctx.fillStyle = color + '33';
  
  let bounds = null;
  
  switch (ann.annotation_type) {
    case 'rectangle': {
      const x1 = imageOffset.x + geom.coordinates[0][0] * imageScale;
      const y1 = imageOffset.y + geom.coordinates[0][1] * imageScale;
      const x2 = imageOffset.x + geom.coordinates[1][0] * imageScale;
      const y2 = imageOffset.y + geom.coordinates[1][1] * imageScale;
      const w = x2 - x1;
      const h = y2 - y1;
      const rotRad = (geom.rotation || 0) * Math.PI / 180;
      if (rotRad) {
        ctx.save();
        ctx.translate((x1 + x2) / 2, (y1 + y2) / 2);
        ctx.rotate(rotRad);
        ctx.fillRect(-w / 2, -h / 2, w, h);
        ctx.strokeRect(-w / 2, -h / 2, w, h);
        ctx.restore();
      } else {
        ctx.fillRect(x1, y1, w, h);
        ctx.strokeRect(x1, y1, w, h);
      }
      bounds = getHandleBounds(ann);
      break;
    }
      
    case 'point':
      const px = imageOffset.x + geom.coordinates[0] * imageScale;
      const py = imageOffset.y + geom.coordinates[1] * imageScale;
      ctx.beginPath();
      ctx.arc(px, py, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      bounds = { x: px - 8, y: py - 8, w: 16, h: 16, cx: px, cy: py };
      break;
      
    case 'line':
      const lx1 = imageOffset.x + geom.coordinates[0][0] * imageScale;
      const ly1 = imageOffset.y + geom.coordinates[0][1] * imageScale;
      const lx2 = imageOffset.x + geom.coordinates[1][0] * imageScale;
      const ly2 = imageOffset.y + geom.coordinates[1][1] * imageScale;
      ctx.beginPath();
      ctx.moveTo(lx1, ly1);
      ctx.lineTo(lx2, ly2);
      ctx.stroke();
      bounds = { 
        x: Math.min(lx1, lx2), 
        y: Math.min(ly1, ly2), 
        w: Math.abs(lx2 - lx1), 
        h: Math.abs(ly2 - ly1),
        cx: (lx1+lx2)/2, 
        cy: (ly1+ly2)/2,
        x1: lx1, y1: ly1, x2: lx2, y2: ly2
      };
      break;
  }
  
  // Draw handles for selected annotation
  if (isSelected && bounds && !ann.is_locked) {
    drawHandles(bounds);
  }

  // Field-value label
  const label = getAnnotationLabel(ann);
  if (label && bounds) {
    ctx.font = '12px sans-serif';
    const tw = ctx.measureText(label).width;
    const labelTop = bounds.y - (isSelected ? 50 : 26);
    const lx = bounds.cx - tw / 2 - 6;
    ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
    ctx.beginPath();
    ctx.roundRect(lx, labelTop, tw + 12, 18, 3);
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.fillText(label, bounds.cx, labelTop + 13);
  }
  
  return bounds;
}

function drawHandles(bounds) {
  const handleSize = 8;
  ctx.fillStyle = '#3b82f6';
  ctx.strokeStyle = 'white';
  ctx.lineWidth = 2;
  
  // Corner handles
  const corners = bounds.rotatedCorners
    ? bounds.rotatedCorners
    : [
        { x: bounds.x, y: bounds.y },
        { x: bounds.x + bounds.w, y: bounds.y },
        { x: bounds.x, y: bounds.y + bounds.h },
        { x: bounds.x + bounds.w, y: bounds.y + bounds.h }
      ];
  
  corners.forEach(h => {
    ctx.fillRect(h.x - handleSize/2, h.y - handleSize/2, handleSize, handleSize);
    ctx.strokeRect(h.x - handleSize/2, h.y - handleSize/2, handleSize, handleSize);
  });
  
  // Center move handle
  ctx.fillStyle = '#3b82f6';
  ctx.beginPath();
  ctx.arc(bounds.cx, bounds.cy, 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  
  // Rotate handle (above top-center)
  const rotateY = bounds.y - 20;
  ctx.fillStyle = '#f59e0b';
  ctx.beginPath();
  ctx.arc(bounds.cx, rotateY, 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  
  // Label
  ctx.fillStyle = '#3b82f6';
  ctx.font = '12px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Rotate', bounds.cx, rotateY - 12);
}

function renderCropPreview(ann) {
  const cropCanvas = document.getElementById('cropCanvas');
  const cropPreview = document.getElementById('cropPreview');
  if (!currentImage || !cropCanvas) {
    cropPreview.style.display = 'none';
    return;
  }

  let geom;
  try { geom = JSON.parse(ann.geometry_json); }
  catch (e) { cropPreview.style.display = 'none'; return; }

  let x1, y1, x2, y2;
  switch (ann.annotation_type) {
    case 'rectangle':
      x1 = geom.coordinates[0][0]; y1 = geom.coordinates[0][1];
      x2 = geom.coordinates[1][0]; y2 = geom.coordinates[1][1];
      break;
    case 'point':
      x1 = geom.coordinates[0] - 15; y1 = geom.coordinates[1] - 15;
      x2 = geom.coordinates[0] + 15; y2 = geom.coordinates[1] + 15;
      break;
    case 'line':
      x1 = geom.coordinates[0][0]; y1 = geom.coordinates[0][1];
      x2 = geom.coordinates[1][0]; y2 = geom.coordinates[1][1];
      if (x1 > x2) { const t = x1; x1 = x2; x2 = t; }
      if (y1 > y2) { const t = y1; y1 = y2; y2 = t; }
      x1 -= 10; y1 -= 10; x2 += 10; y2 += 10;
      break;
    default:
      cropPreview.style.display = 'none';
      return;
  }

  const w = x2 - x1;
  const h = y2 - y1;
  if (w <= 0 || h <= 0) { cropPreview.style.display = 'none'; return; }

  const cctx = cropCanvas.getContext('2d');
  cctx.clearRect(0, 0, cropCanvas.width, cropCanvas.height);
  cctx.fillStyle = '#f1f5f9';
  cctx.fillRect(0, 0, cropCanvas.width, cropCanvas.height);

  const rotRad = (geom.rotation || 0) * Math.PI / 180;
  const scale = Math.min(cropCanvas.width / w, cropCanvas.height / h);

  cctx.save();
  cctx.translate(cropCanvas.width / 2, cropCanvas.height / 2);
  if (rotRad) cctx.rotate(rotRad);
  cctx.drawImage(
    currentImage, x1, y1, w, h,
    -w * scale / 2, -h * scale / 2, w * scale, h * scale
  );
  cctx.restore();

  cropPreview.style.display = 'block';
}

async function updateAnnotationOnServer(ann) {
  const geom = JSON.parse(ann.geometry_json);
  
  try {
    const r = await fetch(`${API_BASE}/api/annotations/${ann.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        geometry: {
          type: ann.annotation_type,
          coordinates: geom.coordinates,
          rotation: geom.rotation || 0
        }
      })
    });
    
    if (!r.ok) {
      console.error('Failed to update annotation:', await r.text());
      return false;
    }
    return true;
  } catch (e) {
    console.error('Error updating annotation:', e);
    return false;
  }
}

// ===== Export + S3 =====

function buildS3Config() {
  return {
    enabled: true,
    bucket: document.getElementById('s3Bucket').value.trim(),
    region: document.getElementById('s3Region').value.trim() || 'us-east-1',
    prefix: 'datasets/',
    multipart_threshold_mb: 100,
    multipart_chunksize_mb: 50,
    fetch_on_startup: false,
    fetch: { exports: true, snapshots: true, cursor: true, verify_checksums: true },
    push: { exports: true, snapshots: true, cursor: true, overwrite: false },
    max_bandwidth_mbps: 0,
    access_key_id: document.getElementById('s3AccessKey').value.trim(),
    secret_access_key: document.getElementById('s3SecretKey').value.trim(),
    endpoint_url: document.getElementById('s3Endpoint').value.trim()
  };
}

function persistS3Config() {
  const data = {
    region: document.getElementById('s3Region').value.trim(),
    accessKey: document.getElementById('s3AccessKey').value.trim(),
    secretKey: document.getElementById('s3SecretKey').value.trim(),
    bucket: document.getElementById('s3Bucket').value.trim(),
    endpoint: document.getElementById('s3Endpoint').value.trim()
  };
  localStorage.setItem('datasetAnnotatorS3', JSON.stringify(data));
}

function loadS3ConfigFromStorage() {
  try {
    const raw = localStorage.getItem('datasetAnnotatorS3');
    if (!raw) return;
    const d = JSON.parse(raw);
    if (d.region) document.getElementById('s3Region').value = d.region;
    if (d.accessKey) document.getElementById('s3AccessKey').value = d.accessKey;
    if (d.secretKey) document.getElementById('s3SecretKey').value = d.secretKey;
    if (d.bucket) document.getElementById('s3Bucket').value = d.bucket;
    if (d.endpoint) document.getElementById('s3Endpoint').value = d.endpoint;
  } catch (e) {
    console.error('Failed to load S3 config:', e);
  }
}

function setExportStatus(msg) {
  document.getElementById('exportStatus').textContent = msg || '';
}

async function saveS3Config() {
  setExportStatus('Saving S3 config...');
  try {
    const r = await fetch(`${API_BASE}/api/s3/save-config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: buildS3Config() })
    });
    const data = await r.json();
    if (r.ok && data.success) {
      persistS3Config();
      setExportStatus(data.message || 'S3 config saved');
    } else {
      setExportStatus('Failed: ' + (data.message || await r.text()));
    }
  } catch (e) {
    setExportStatus('S3 config error: ' + e.message);
  }
}

async function testS3Connection() {
  setExportStatus('Testing S3 connection...');
  try {
    const r = await fetch(`${API_BASE}/api/s3/test-connection`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: buildS3Config() })
    });
    const data = await r.json();
    setExportStatus(data.message || (data.success ? 'Connected' : 'Failed'));
  } catch (e) {
    setExportStatus('S3 test error: ' + e.message);
  }
}

async function runExport(pushS3) {
  if (!currentDatasetId) {
    setExportStatus('No dataset loaded');
    return;
  }
  
  setExportStatus(pushS3 ? 'Configuring S3 then exporting...' : 'Running full export...');
  
  try {
    if (pushS3) {
      const saveRes = await fetch(`${API_BASE}/api/s3/save-config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: buildS3Config() })
      });
      const saveData = await saveRes.json();
      if (!saveRes.ok || !saveData.success) {
        setExportStatus('S3 config save failed: ' + (saveData.message || ''));
        return;
      }
      persistS3Config();
      setExportStatus('Exporting & uploading to S3...');
    }
    
    const r = await fetch(`${API_BASE}/api/export/full`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_id: currentDatasetId, type: 'full', push_s3: pushS3, formats: ['parquet'] })
    });
    const data = await r.json();
    if (!r.ok) {
      setExportStatus('Export failed: ' + (data.message || ''));
      return;
    }
    pollExportStatus(data.export_id);
  } catch (e) {
    setExportStatus('Export error: ' + e.message);
  }
}

async function pollExportStatus(exportId) {
  const tries = 30;
  for (let i = 0; i < tries; i++) {
    await new Promise(res => setTimeout(res, 2000));
    try {
      const r = await fetch(`${API_BASE}/api/export/status/${exportId}`);
      if (!r.ok) continue;
      const st = await r.json();
      if (st.status === 'completed') {
        const paths = (st.output_paths || []).slice(0, 3).join('\n');
        setExportStatus(`Export complete! ${paths ? '\n' + paths : ''}`);
        return;
      }
      if (st.status === 'failed') {
        setExportStatus('Export failed: ' + (st.error || 'unknown error'));
        return;
      }
      setExportStatus(`Exporting... ${Math.round((st.progress || 0) * 100)}%`);
    } catch (e) {
      // transient poll errors - keep waiting
    }
  }
  setExportStatus('Export still running - check server logs.');
}