/* app.js - Simple plain JS frontend for Dataset Annotator */

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
let currentPage = 1;

// Interaction state
let interactionMode = null; // 'move', 'resize', 'rotate', null
let interactionHandle = null;
let interactionStart = { x: 0, y: 0 };
let originalAnnotation = null;

// Initialize
document.addEventListener('DOMContentLoaded', init);

async function init() {
  canvas = document.getElementById('canvas');
  ctx = canvas.getContext('2d');
  
  await loadDatasets();
  setupCanvas();
  setupEventListeners();
  renderCanvas();
}

async function loadDatasets() {
  try {
    const r = await fetch('http://localhost:8080/api/datasets');
    if (r.ok) {
      const data = await r.json();
      if (data.datasets && data.datasets.length > 0) {
        currentDatasetId = data.datasets[0].id;
        document.getElementById('datasetPath').textContent = data.datasets[0].name || 'Dataset';
        document.getElementById('newAnnotationBtn').disabled = false;
        await loadDataItems(currentDatasetId);
      }
    }
  } catch (e) {
    console.error('Failed to load datasets:', e);
  }
}

async function loadDataItems(datasetId) {
  try {
    const r = await fetch(`http://localhost:8080/api/datasets/${datasetId}/items?page=1&page_size=1`);
    if (r.ok) {
      const data = await r.json();
      totalItems = data.total || 0;
      currentPage = 1;
      updateNavButtons();
      if (data.items && data.items.length > 0) {
        currentDataItemId = data.items[0].id;
        await loadImage(data.items[0]);
        await loadAnnotationsFromServer();
      }
    }
  } catch (e) {
    console.error('Failed to load data items:', e);
  }
}

async function loadItem(page) {
  if (page < 1 || page > Math.ceil(totalItems / 1)) return;
  
  try {
    const r = await fetch(`http://localhost:8080/api/datasets/${currentDatasetId}/items?page=${page}&page_size=1`);
    if (r.ok) {
      const data = await r.json();
      if (data.items && data.items.length > 0) {
        currentPage = page;
        updateNavButtons();
        currentDataItemId = data.items[0].id;
        await loadImage(data.items[0]);
        await loadAnnotationsFromServer();
      }
    }
  } catch (e) {
    console.error('Failed to load item:', e);
  }
}

function updateNavButtons() {
  document.getElementById('prevItemBtn').disabled = currentPage <= 1;
  document.getElementById('nextItemBtn').disabled = currentPage >= totalItems;
}

async function loadImage(item) {
  currentDataItemId = item.id;
  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.onload = () => {
    console.log('Image loaded:', img.width, 'x', img.height);
    currentImage = img;
    const maxW = canvas.width - 40;
    const maxH = canvas.height - 40;
    imageScale = Math.min(maxW / img.width, maxH / img.height, 1);
    imageOffset.x = (canvas.width - img.width * imageScale) / 2;
    imageOffset.y = (canvas.height - img.height * imageScale) / 2;
    console.log('imageScale:', imageScale, 'imageOffset:', imageOffset);
    renderCanvas();
  };
  img.onerror = (e) => {
    console.error('Image load error:', e);
    currentImage = null;
    renderCanvas();
  };
  img.src = `http://localhost:8080/api/images/${item.id}`;
  console.log('Loading image from:', img.src);
}

async function loadAnnotationsFromServer() {
  try {
    const r = await fetch(`http://localhost:8080/api/data-items/${currentDataItemId}/annotations`);
    if (r.ok) {
      const serverAnns = await r.json();
      // Keep local copy in memory
      annotations = serverAnns.map(ann => ({
        ...ann,
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

  // Navigation
  document.getElementById('prevItemBtn').addEventListener('click', () => loadItem(currentPage - 1));
  document.getElementById('nextItemBtn').addEventListener('click', () => loadItem(currentPage + 1));

  // Actions
  document.getElementById('newAnnotationBtn').addEventListener('click', createNewAnnotation);
  document.getElementById('clearAllBtn').addEventListener('click', clearAllAnnotations);
  document.getElementById('resetDbBtn').addEventListener('click', resetEntireDb);

  // Lock/unlock/delete
  document.getElementById('lockBtn').addEventListener('click', () => toggleLock(true));
  document.getElementById('unlockBtn').addEventListener('click', () => toggleLock(false));
  document.getElementById('deleteBtn').addEventListener('click', deleteAnnotation);

  // Field controls
  document.getElementById('addFieldBtn').addEventListener('click', addField);

  // Field name change
  document.getElementById('fieldNameSelect').addEventListener('change', (e) => {
    document.getElementById('fieldValue').placeholder = `Value for ${e.target.value}`;
  });
}

function setTool(tool) {
  currentTool = tool;
  document.querySelectorAll('.toolbar button').forEach(btn => btn.classList.remove('active'));
  document.getElementById(`tool${tool.charAt(0).toUpperCase() + tool.slice(1)}`)?.classList.add('active');
  document.getElementById('toolSelect')?.classList.toggle('active', tool === 'select');
  
  canvas.style.cursor = tool === 'select' ? 'default' : 'crosshair';
}

function getImgCoords(e) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (e.clientX - rect.left - imageOffset.x) / imageScale,
    y: (e.clientY - rect.top - imageOffset.y) / imageScale
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
    // Drawing new annotation
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
    // Interaction with existing annotation
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
      // Resize annotation
      switch (annData.annotation_type) {
        case 'rectangle':
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
          break;
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
      const ann2 = annotations.find(a => a.id === selectedAnnotationId);
      const bounds = getHandleBounds(ann2);
      if (!bounds) return;
      
      const centerX = (bounds.cx - imageOffset.x) / imageScale;
      const centerY = (bounds.cy - imageOffset.y) / imageScale;
      
      const startAngle = Math.atan2(interactionStart.x - centerX, -(interactionStart.y - centerY));
      const currentAngle = Math.atan2(coords.x - centerX, -(coords.y - centerY));
      const angleDelta = currentAngle - startAngle;
      
      const geom = JSON.parse(ann.geometry_json);
      if (!geom.rotation) geom.rotation = 0;
      geom.rotation += angleDelta;
      
      ann.geometry_json = JSON.stringify(geom);
      ann.dirty = true;
      
      interactionStart = { x: coords.x, y: coords.y };
renderCanvas();
  }
  
  if (!isDrawing || currentTool === 'select') return;
  
  if (currentTool === 'point') {
      if (!ann) return;
      
      const bounds = getHandleBounds(ann);
      if (!bounds) return;
      
      // bounds are in canvas coordinates, convert to image coordinates
      const centerX = (bounds.cx - imageOffset.x) / imageScale;
      const centerY = (bounds.cy - imageOffset.y) / imageScale;
      
      // Reference: Math.atan2(pos.x - cx, -(pos.y - cy))
      const startAngle = Math.atan2(interactionStart.x - centerX, -(interactionStart.y - centerY));
      const currentAngle = Math.atan2(coords.x - centerX, -(coords.y - centerY));
      const angleDelta = currentAngle - startAngle;
      
      const geom = JSON.parse(ann.geometry_json);
      if (!geom.rotation) geom.rotation = 0;
      geom.rotation += angleDelta;
      
      ann.geometry_json = JSON.stringify(geom);
      ann.dirty = true;
      
      interactionStart = { x: coords.x, y: coords.y };
      renderCanvas();
    }
    return;
  }

function onMouseUp(e) {
  if (isDrawing && currentTool !== 'select') {
    // Finish drawing new annotation
    const coords = getCanvasCoords(e);
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
      createLocalAnnotation(currentTool, geometry);
    }
    
    renderCanvas();
    return;
  }
  
  if (isDrawing && currentTool === 'select' && interactionMode) {
    // End interaction - mark as dirty
    const ann = annotations.find(a => a.id === selectedAnnotationId);
    if (ann) {
      ann.dirty = true;
    }
    
    interactionMode = null;
    interactionHandle = null;
    originalAnnotation = null;
    isDrawing = false;
    renderCanvas();
    return;
  }
  
  if (!isDrawing || currentTool === 'select') return;
  
  const coords = getCanvasCoords(e);
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
    createLocalAnnotation(currentTool, geometry);
  }
  
  renderCanvas();
}

function onClick(e) {
  if (currentTool !== 'select') return;
  
  const coords = getCanvasCoords(e);
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
  
  console.log('getHandleBounds:', { annType: annData.annotation_type, geom });
  
  switch (annData.annotation_type) {
    case 'rectangle':
      const x1 = imageOffset.x + geom.coordinates[0][0] * imageScale;
      const y1 = imageOffset.y + geom.coordinates[0][1] * imageScale;
      const x2 = imageOffset.x + geom.coordinates[1][0] * imageScale;
      const y2 = imageOffset.y + geom.coordinates[1][1] * imageScale;
      return { x: x1, y: y1, w: x2 - x1, h: y2 - y1, cx: (x1+x2)/2, cy: (y1+y2)/2 };
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
  
  console.log('hitTestHandle:', { bounds, x, y, canvasX, canvasY, imageScale, imageOffset });
  
  const corners = [
    { x: bounds.x, y: bounds.y, name: 'tl' },
    { x: bounds.x + bounds.w, y: bounds.y, name: 'tr' },
    { x: bounds.x, y: bounds.y + bounds.h, name: 'bl' },
    { x: bounds.x + bounds.w, y: bounds.y + bounds.h, name: 'br' }
  ];
  
  for (const c of corners) {
    if (canvasX >= c.x - 8 && canvasX <= c.x + 8 && canvasY >= c.y - 8 && canvasY <= c.y + 8) {
      console.log('Hit corner:', c.name);
      return c.name;
    }
  }
  
  if (canvasX >= bounds.cx - 8 && canvasX <= bounds.cx + 8 && canvasY >= bounds.cy - 8 && canvasY <= bounds.cy + 8) {
    console.log('Hit center');
    return 'center';
  }
  
  const rotateY = bounds.y - 20;
  if (canvasX >= bounds.cx - 8 && canvasX <= bounds.cx + 8 && canvasY >= rotateY - 8 && canvasY <= rotateY + 8) {
    console.log('Hit rotate');
    return 'rotate';
  }
  
  console.log('No hit');
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

async function createLocalAnnotation(type, geometry) {
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
    is_locked: false,
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
    loadCropPreview(ann);
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
      return;
    }
    
    // Server annotation - fetch from API
    const r = await fetch(`http://localhost:8080/api/annotations/${annId}`);
    if (r.ok) {
      const data = await r.json();
      const fields = data.fields || {};
      renderFieldPanel(fields);
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
  const selectEl = document.getElementById('fieldNameSelect');
  const valueInput = document.getElementById('fieldValue');
  const addBtn = document.getElementById('addFieldBtn');
  
  selectEl.innerHTML = '<option value="">Select field...</option>';
  
  // Predefined field names from config (dataset_config.yaml)
  const predefinedFields = [
    'Text', 'Type', 'Dosage', 'Frequency', 'Route', 'Confidence', 'Notes'
  ];
  
  // Always include all predefined fields in the dropdown
  predefinedFields.forEach(fieldName => {
    const opt = document.createElement('option');
    opt.value = fieldName;
    opt.textContent = fieldName;
    selectEl.appendChild(opt);
  });
  
  // Add existing field values if present
  if (fields && Object.keys(fields).length > 0) {
    Object.keys(fields).forEach(fieldName => {
      // Skip if already added from predefined
      if (!Array.from(selectEl.options).some(o => o.value === fieldName)) {
        const opt = document.createElement('option');
        opt.value = fieldName;
        opt.textContent = fieldName;
        selectEl.appendChild(opt);
      }
    });
  }
  
  valueInput.disabled = false;
  addBtn.disabled = false;
}

async function addField() {
  const fieldName = document.getElementById('fieldNameSelect').value;
  const fieldValue = document.getElementById('fieldValue').value;
  
  if (!fieldName || !fieldValue || !selectedAnnotationId) return;
  
  const ann = annotations.find(a => a.id === selectedAnnotationId);
  
  if (ann && ann.localOnly) {
    // Local annotation - store field locally
    if (!ann.fields) ann.fields = {};
    ann.fields[fieldName] = fieldValue;
    ann.dirty = true;
    document.getElementById('fieldValue').value = '';
    loadAnnotationFields(selectedAnnotationId);
    renderCanvas();
    return;
  }
  
  try {
    const r = await fetch(`http://localhost:8080/api/annotations/${selectedAnnotationId}/fields`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        field_name: fieldName,
        field_value: fieldValue
      })
    });
    
    if (r.ok) {
      document.getElementById('fieldValue').value = '';
      loadAnnotationFields(selectedAnnotationId);
    } else {
      alert('Failed: ' + await r.text());
    }
  } catch (e) {
    console.error('Error:', e);
  }
}

async function toggleLock(lock) {
  if (!selectedAnnotationId) return;
  
  try {
    const endpoint = lock ? 'lock' : 'unlock';
    const r = await fetch(`http://localhost:8080/api/annotations/${selectedAnnotationId}/${endpoint}`, {
      method: 'POST'
    });
    
    if (r.ok) {
      // Update local annotation instead of reloading from server
      const ann = annotations.find(a => a.id === selectedAnnotationId);
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
    
    const r = await fetch(`http://localhost:8080/api/annotations/${selectedAnnotationId}`, { method: 'DELETE' });
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
        await fetch(`http://localhost:8080/api/annotations/${ann.id}`, { method: 'DELETE' });
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
    const r = await fetch('http://localhost:8080/api/reset-db', { method: 'POST' });
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

function createNewAnnotation() {
  setTool('rectangle');
  alert('Click and drag on the image to create a rectangle annotation');
}

function renderAnnotationList() {
  const listEl = document.getElementById('annotationList');
  listEl.innerHTML = '';
  
  annotations.forEach(ann => {
    const div = document.createElement('div');
    div.className = 'annotation-item' + (ann.id === selectedAnnotationId ? ' selected' : '');
    div.innerHTML = `
      <strong>${ann.annotation_type || 'unknown'}</strong>
      ${ann.localOnly ? '<span style="color:#f59e0b;font-size:0.6rem;">(local)</span>' : ''}
      ${ann.dirty ? '<span style="color:#3b82f6;font-size:0.6rem;">(unsaved)</span>' : ''}
      <span class="status-badge ${ann.is_locked ? 'status-locked' : 'status-unlocked'}">
        ${ann.is_locked ? 'Locked' : 'Unlocked'}
      </span>
    `;
    div.addEventListener('click', () => selectAnnotation(ann.id));
    listEl.appendChild(div);
  });
}

function renderCanvas() {
  console.log('renderCanvas:', { currentImage: !!currentImage, annotations: annotations.length, imageScale, imageOffset });
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

function drawAnnotation(ann, isSelected) {
  const geom = JSON.parse(ann.geometry_json);
  const color = isSelected ? '#3b82f6' : (ann.is_locked ? '#f59e0b' : '#ef4444');
  
  ctx.strokeStyle = color;
  ctx.lineWidth = isSelected ? 3 : 2;
  ctx.fillStyle = color + '33';
  
  let bounds = null;
  
  switch (ann.annotation_type) {
    case 'rectangle':
      const x1 = imageOffset.x + geom.coordinates[0][0] * imageScale;
      const y1 = imageOffset.y + geom.coordinates[0][1] * imageScale;
      const x2 = imageOffset.x + geom.coordinates[1][0] * imageScale;
      const y2 = imageOffset.y + geom.coordinates[1][1] * imageScale;
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      bounds = { x: x1, y: y1, w: x2 - x1, h: y2 - y1, cx: (x1+x2)/2, cy: (y1+y2)/2 };
      break;
      
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
  
  return bounds;
}

function drawHandles(bounds) {
  const handleSize = 8;
  ctx.fillStyle = '#3b82f6';
  ctx.strokeStyle = 'white';
  ctx.lineWidth = 2;
  
  // Corner handles
  const handles = [
    { x: bounds.x, y: bounds.y, name: 'tl' },
    { x: bounds.x + bounds.w, y: bounds.y, name: 'tr' },
    { x: bounds.x, y: bounds.y + bounds.h, name: 'bl' },
    { x: bounds.x + bounds.w, y: bounds.y + bounds.h, name: 'br' }
  ];
  
  handles.forEach(h => {
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

async function loadCropPreview(ann) {
  const cropCanvas = document.getElementById('cropCanvas');
  const cropPreview = document.getElementById('cropPreview');
  
  // For local annotations, try to generate crop from geometry
  if (ann.localOnly) {
    const geom = JSON.parse(ann.geometry_json);
    cropPreview.style.display = 'none';
    return; // Can't fetch crop for local annotations without server
  }
  
  if (!ann.crop_path) {
    cropPreview.style.display = 'none';
    return;
  }
  
  try {
    const r = await fetch(`http://localhost:8080/api/images/crop/${ann.id}`);
    if (!r.ok) {
      cropPreview.style.display = 'none';
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    
    const img = new Image();
    img.onload = () => {
      const ctx = cropCanvas.getContext('2d');
      ctx.clearRect(0, 0, cropCanvas.width, cropCanvas.height);
      
      const scale = Math.min(cropCanvas.width / img.width, cropCanvas.height / img.height);
      const dw = img.width * scale;
      const dh = img.height * scale;
      const dx = (cropCanvas.width - dw) / 2;
      const dy = (cropCanvas.height - dh) / 2;
      
      ctx.drawImage(img, dx, dy, dw, dh);
      cropPreview.style.display = 'block';
    };
    img.src = url;
  } catch (e) {
    console.error('Failed to load crop preview:', e);
    cropPreview.style.display = 'none';
  }
}

async function updateAnnotationOnServer(ann) {
  const geom = JSON.parse(ann.geometry_json);
  
  try {
    const r = await fetch(`http://localhost:8080/api/annotations/${ann.id}`, {
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
    }
  } catch (e) {
    console.error('Error updating annotation:', e);
  }
}