/**
 * =========================================================================
 * ENCHANTED INK — AI WHITEBOARD CONTROLLER
 * High-Productivity Spatial Canvas with Krita-Inspired Inking Engine
 * Selective @board Ink Dissolution & Native Visual AI Generation
 * =========================================================================
 */

// Defensive patches for Fabric.js v5 stability
if (typeof fabric !== 'undefined' && fabric.util) {
  if (fabric.util.stylesToArray) {
    const origStylesToArray = fabric.util.stylesToArray;
    fabric.util.stylesToArray = function(styles, text) {
      if (!styles || typeof styles !== 'object') return [];
      try {
        return origStylesToArray.call(this, styles, text);
      } catch (err) {
        return [];
      }
    };
  }
}

// =========================================================================
// KRITA-INSPIRED DIGITAL INKING ENGINE (github.com/kde/krita)
// Midpoint Quadratic Bézier Smoothing + Pointer Pressure + Strict Button Checks
// =========================================================================

class KritaInkingEngine {
  constructor(app) {
    this.app = app;
    this.canvas = app.canvas;
    this.isDrawing = false;
    this.currentPointerId = null;
    this.rawPoints = [];
    this.smoothedPoints = [];

    this.bindEvents();
  }

  bindEvents() {
    const el = this.canvas.upperCanvasEl;
    if (!el) return;

    el.addEventListener('pointerdown', (e) => this.onPointerDown(e));
    el.addEventListener('pointermove', (e) => this.onPointerMove(e));
    el.addEventListener('pointerup', (e) => this.onPointerUp(e));
    el.addEventListener('pointercancel', (e) => this.onPointerUp(e));
    el.addEventListener('lostpointercapture', (e) => this.onPointerUp(e));

    // Global window release ensures stroke never gets stuck if mouse released outside canvas
    window.addEventListener('pointerup', (e) => {
      if (this.isDrawing) this.finishStroke(e);
    });
    window.addEventListener('blur', () => {
      if (this.isDrawing) this.finishStroke();
    });
  }

  onPointerDown(e) {
    // Only draw when the active tool is 'pen'
    if (this.app.currentTool !== 'pen') return;

    // Disallow if spacebar held (panning) or if not the primary button (left click = 0)
    if (this.app.isSpacePressed || (e.button !== 0 && e.pointerType !== 'pen')) return;

    this.isDrawing = true;
    this.currentPointerId = e.pointerId;
    try {
      e.target.setPointerCapture(e.pointerId);
    } catch (_) {}

    const pt = this.canvas.getPointer(e);
    const pressure = (e.pressure && e.pressure > 0) ? e.pressure : 0.5;
    const ptData = { x: pt.x, y: pt.y, pressure, time: Date.now() };

    this.rawPoints = [ptData];
    this.smoothedPoints = [{ x: pt.x, y: pt.y, pressure }];

    // Render initial mark
    this.renderLive(this.smoothedPoints, true);
  }

  onPointerMove(e) {
    if (!this.isDrawing) return;

    // CRITICAL FIX: If no button is pressed down (e.buttons === 0), terminate stroke immediately!
    // This permanently prevents drawing while just moving the mouse without clicking.
    if (e.buttons === 0) {
      this.finishStroke(e);
      return;
    }

    const pt = this.canvas.getPointer(e);
    const pressure = (e.pressure && e.pressure > 0) ? e.pressure : 0.5;
    const ptData = { x: pt.x, y: pt.y, pressure, time: Date.now() };
    this.rawPoints.push(ptData);

    // Krita Stabilizer: Distance-Weighted Smoothing (Exponential Moving Average)
    const prev = this.smoothedPoints[this.smoothedPoints.length - 1];
    const alpha = 0.65; // Smoothing factor balancing responsiveness and smoothness
    const smoothX = prev.x + (pt.x - prev.x) * alpha;
    const smoothY = prev.y + (pt.y - prev.y) * alpha;

    this.smoothedPoints.push({ x: smoothX, y: smoothY, pressure });

    // Render live quadratic Bézier curve on Fabric's upper canvas context
    this.renderLive(this.smoothedPoints, false);
  }

  onPointerUp(e) {
    if (!this.isDrawing) return;
    this.finishStroke(e);
  }

  finishStroke(e) {
    if (!this.isDrawing) return;
    this.isDrawing = false;

    if (this.currentPointerId !== null) {
      try {
        this.canvas.upperCanvasEl.releasePointerCapture(this.currentPointerId);
      } catch (_) {}
      this.currentPointerId = null;
    }

    // Clear live preview from upper canvas
    this.canvas.clearContext(this.canvas.contextTop);

    if (this.smoothedPoints.length < 1) return;

    // Single click dot handling
    if (this.smoothedPoints.length === 1) {
      const p = this.smoothedPoints[0];
      this.smoothedPoints.push({ x: p.x + 0.5, y: p.y + 0.5, pressure: p.pressure });
    }

    // Generate Krita Midpoint Quadratic Bézier SVG Path
    const svgPath = this.pointsToSvgPath(this.smoothedPoints);
    if (!svgPath) return;

    const strokeColor = this.app.activeColor || '#4f46e5';
    const strokeWidth = parseInt(this.app.activeStrokeWidth || 2) * 1.5;

    // Create permanent vector Fabric.Path
    const path = new fabric.Path(svgPath, {
      fill: null,
      stroke: strokeColor,
      strokeWidth: strokeWidth,
      strokeLineCap: 'round',
      strokeLineJoin: 'round',
      selectable: true,
      evented: true,
      isStroke: true,
      id: `stroke_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
      rawPoints: this.rawPoints.slice() // Preserve raw coordinates for handwriting recognition
    });

    // Add permanently onto the canvas. Earlier strokes remain completely intact!
    this.canvas.add(path);
    this.canvas.requestRenderAll();
    this.app.pushHistoryState();

    this.rawPoints = [];
    this.smoothedPoints = [];
  }

  pointsToSvgPath(points) {
    if (!points || points.length === 0) return '';
    if (points.length === 1) {
      return `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)} L ${(points[0].x + 0.2).toFixed(1)} ${(points[0].y + 0.2).toFixed(1)}`;
    }

    let d = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)} `;
    for (let i = 1; i < points.length - 1; i++) {
      const xc = (points[i].x + points[i + 1].x) / 2;
      const yc = (points[i].y + points[i + 1].y) / 2;
      d += `Q ${points[i].x.toFixed(1)} ${points[i].y.toFixed(1)}, ${xc.toFixed(1)} ${yc.toFixed(1)} `;
    }
    const last = points[points.length - 1];
    const secondLast = points[points.length - 2];
    d += `Q ${secondLast.x.toFixed(1)} ${secondLast.y.toFixed(1)}, ${last.x.toFixed(1)} ${last.y.toFixed(1)}`;
    return d;
  }

  renderLive(points, isStart = false) {
    const ctx = this.canvas.contextTop;
    if (!ctx) return;

    this.canvas.clearContext(ctx);
    if (points.length < 1) return;

    ctx.save();
    this.canvas._saveAndTransform(ctx);

    const strokeColor = this.app.activeColor || '#4f46e5';
    const strokeWidth = parseInt(this.app.activeStrokeWidth || 2) * 1.5;

    ctx.strokeStyle = strokeColor;
    ctx.fillStyle = strokeColor;
    ctx.lineWidth = strokeWidth;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    if (points.length === 1 || isStart) {
      ctx.beginPath();
      ctx.arc(points[0].x, points[0].y, strokeWidth / 2, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length - 1; i++) {
        const xc = (points[i].x + points[i + 1].x) / 2;
        const yc = (points[i].y + points[i + 1].y) / 2;
        ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
      }
      const last = points[points.length - 1];
      const secondLast = points[points.length - 2];
      ctx.quadraticCurveTo(secondLast.x, secondLast.y, last.x, last.y);
      ctx.stroke();
    }

    ctx.restore();
  }
}

// =========================================================================
// MAIN WHITEBOARD APPLICATION CONTROLLER
// =========================================================================

class WhiteboardApp {
  constructor() {
    this.canvas = null;
    this.kritaPen = null;
    this.currentTool = 'select'; // 'select', 'pan', 'pen', 'eraser', 'text', 'sticky', 'rect', 'ellipse', 'arrow'
    this.activeColor = '#4f46e5';
    this.activeFill = '#ffffff';
    this.activeStrokeWidth = 2;
    
    this.isPanning = false;
    this.lastPanPos = { x: 0, y: 0 };
    this.isSpacePressed = false;
    
    this.isDrawingShape = false;
    this.shapeStart = { x: 0, y: 0 };
    this.tempShape = null;

    this.undoStack = [];
    this.redoStack = [];
    this.isHistoryLocked = false;
    this.historyDebounceTimer = null;

    this.currentBoardId = 'default';
    this.boardName = 'Main Whiteboard';
    this.lastAiBatchId = null;

    this.init();
  }

  // =========================================================================
  // INITIALIZATION
  // =========================================================================

  init() {
    this.initCanvas();
    this.initWindowResize();
    this.initPanAndZoom();
    this.initToolHandlers();
    this.initShapeCreation();
    this.initAiCommandBar();
    this.initSelectionEvents();
    this.initKeyboardShortcuts();
    this.initStorageAndPersistence();
    this.initExportImport();
    this.checkGeminiConfig();
  }

  initCanvas() {
    const el = document.getElementById('whiteboardCanvas');
    if (!el) return;

    this.canvas = new fabric.Canvas('whiteboardCanvas', {
      width: window.innerWidth,
      height: window.innerHeight,
      isDrawingMode: false, // Disables Fabric's buggy built-in brush in favor of Krita engine
      selection: true,
      preserveObjectStacking: true,
      stopContextMenu: true,
      fireRightClick: true
    });

    // Initialize Krita-style stroke engine
    this.kritaPen = new KritaInkingEngine(this);

    // Canvas background dot grid synchronization
    this.canvas.on('after:render', () => {
      this.syncDotGridBackground();
    });

    // Track state changes for Undo/Redo & Autosave
    this.canvas.on('object:added', (e) => {
      if (!this.isHistoryLocked && !e.target.isTemporary) this.pushHistoryState();
    });
    this.canvas.on('object:modified', () => {
      if (!this.isHistoryLocked) this.pushHistoryState();
    });
    this.canvas.on('object:removed', () => {
      if (!this.isHistoryLocked) this.pushHistoryState();
    });
  }

  initWindowResize() {
    window.addEventListener('resize', () => {
      if (this.canvas) {
        this.canvas.setWidth(window.innerWidth);
        this.canvas.setHeight(window.innerHeight);
        this.canvas.renderAll();
      }
    });
  }

  // =========================================================================
  // PAN & ZOOM ENGINE
  // =========================================================================

  initPanAndZoom() {
    const container = document.getElementById('canvasContainer');

    // Mouse Wheel Zoom
    this.canvas.on('mouse:wheel', (opt) => {
      const delta = opt.e.deltaY;
      let zoom = this.canvas.getZoom();
      zoom *= 0.999 ** delta;
      zoom = Math.min(Math.max(zoom, 0.15), 4.0); // Clamp zoom between 15% and 400%

      const point = { x: opt.e.offsetX, y: opt.e.offsetY };
      this.canvas.zoomToPoint(point, zoom);
      this.updateZoomDisplay();
      opt.e.preventDefault();
      opt.e.stopPropagation();
    });

    // Spacebar key for temporary pan
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Space' && !this.isSpacePressed && !this.isEditingText()) {
        this.isSpacePressed = true;
        if (container) container.classList.add('panning');
      }
    });

    window.addEventListener('keyup', (e) => {
      if (e.code === 'Space') {
        this.isSpacePressed = false;
        if (container && this.currentTool !== 'pan') container.classList.remove('panning');
      }
    });

    // Mouse down / move / up for panning
    this.canvas.on('mouse:down', (opt) => {
      const evt = opt.e;
      // Pan if Space pressed, middle mouse button (button 1), or current tool is 'pan'
      if (this.isSpacePressed || evt.button === 1 || this.currentTool === 'pan') {
        this.isPanning = true;
        this.lastPanPos = { x: evt.clientX, y: evt.clientY };
        this.canvas.selection = false;
        if (container) container.classList.add('panning');
      }
    });

    this.canvas.on('mouse:move', (opt) => {
      if (this.isPanning) {
        const evt = opt.e;
        const vpt = this.canvas.viewportTransform;
        vpt[4] += evt.clientX - this.lastPanPos.x;
        vpt[5] += evt.clientY - this.lastPanPos.y;
        this.lastPanPos = { x: evt.clientX, y: evt.clientY };
        this.canvas.requestRenderAll();
      }
    });

    this.canvas.on('mouse:up', () => {
      if (this.isPanning) {
        this.isPanning = false;
        if (this.currentTool === 'select' && !this.isSpacePressed) {
          this.canvas.selection = true;
        }
        if (container && !this.isSpacePressed && this.currentTool !== 'pan') {
          container.classList.remove('panning');
        }
      }
    });

    // Zoom Controls in UI
    document.getElementById('btnZoomIn')?.addEventListener('click', () => this.zoomStep(1.2));
    document.getElementById('btnZoomOut')?.addEventListener('click', () => this.zoomStep(0.8));
    document.getElementById('btnZoomReset')?.addEventListener('click', () => this.resetZoom());
    document.getElementById('btnFitContent')?.addEventListener('click', () => this.fitToContent());
  }

  zoomStep(factor) {
    let zoom = this.canvas.getZoom() * factor;
    zoom = Math.min(Math.max(zoom, 0.15), 4.0);
    const center = { x: this.canvas.width / 2, y: this.canvas.height / 2 };
    this.canvas.zoomToPoint(center, zoom);
    this.updateZoomDisplay();
  }

  resetZoom() {
    this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    this.updateZoomDisplay();
  }

  fitToContent() {
    const objects = this.canvas.getObjects();
    if (objects.length === 0) {
      this.resetZoom();
      return;
    }

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    objects.forEach(obj => {
      const b = obj.getBoundingRect(true, true);
      minX = Math.min(minX, b.left);
      minY = Math.min(minY, b.top);
      maxX = Math.max(maxX, b.left + b.width);
      maxY = Math.max(maxY, b.top + b.height);
    });

    const contentWidth = maxX - minX;
    const contentHeight = maxY - minY;
    const padding = 80;

    const scaleX = (this.canvas.width - padding * 2) / contentWidth;
    const scaleY = (this.canvas.height - padding * 2) / contentHeight;
    let zoom = Math.min(scaleX, scaleY, 1.5);
    zoom = Math.max(zoom, 0.2);

    const vpLeft = (this.canvas.width - contentWidth * zoom) / 2 - minX * zoom;
    const vpTop = (this.canvas.height - contentHeight * zoom) / 2 - minY * zoom;

    this.canvas.setViewportTransform([zoom, 0, 0, zoom, vpLeft, vpTop]);
    this.updateZoomDisplay();
  }

  updateZoomDisplay() {
    const label = document.getElementById('zoomPercentageLabel');
    if (label) {
      label.textContent = `${Math.round(this.canvas.getZoom() * 100)}%`;
    }
  }

  syncDotGridBackground() {
    const container = document.getElementById('canvasContainer');
    if (!container || !this.canvas) return;
    const vpt = this.canvas.viewportTransform;
    const zoom = vpt[0];
    const panX = vpt[4];
    const panY = vpt[5];

    // Scale dot spacing proportionally with zoom
    const gridSize = 24 * zoom;
    container.style.backgroundSize = `${gridSize}px ${gridSize}px`;
    container.style.backgroundPosition = `${panX}px ${panY}px`;
  }

  // =========================================================================
  // TOOL STATE MACHINE
  // =========================================================================

  setTool(tool) {
    this.currentTool = tool;

    // Update active class on toolbar buttons
    document.querySelectorAll('.tool-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tool === tool);
    });

    const container = document.getElementById('canvasContainer');
    if (container) {
      container.classList.toggle('crosshair', ['pen', 'rect', 'ellipse', 'arrow'].includes(tool));
      container.classList.toggle('panning', tool === 'pan');
    }

    if (!this.canvas) return;

    // Keep Fabric's buggy built-in isDrawingMode false
    this.canvas.isDrawingMode = false;

    if (tool === 'pen') {
      this.canvas.selection = false;
      this.canvas.defaultCursor = 'crosshair';
      this.canvas.hoverCursor = 'crosshair';
      this.canvas.discardActiveObject();
      this.canvas.requestRenderAll();
    } else if (tool === 'select') {
      this.canvas.selection = true;
      this.canvas.defaultCursor = 'default';
      this.canvas.hoverCursor = 'move';
    } else if (tool === 'pan') {
      this.canvas.selection = false;
      this.canvas.defaultCursor = 'grab';
      this.canvas.hoverCursor = 'grab';
    } else {
      // Shape / Text / Sticky tools
      this.canvas.selection = false;
      this.canvas.defaultCursor = 'crosshair';
      this.canvas.hoverCursor = 'crosshair';
      this.canvas.discardActiveObject();
      this.canvas.requestRenderAll();
    }
  }

  initToolHandlers() {
    // Toolbar buttons click
    document.querySelectorAll('.tool-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tool = btn.dataset.tool;
        if (tool === 'brush-settings') {
          this.toggleBrushSettingsPanel();
        } else if (tool) {
          this.setTool(tool);
        }
      });
    });

    // Palette Swatches
    document.querySelectorAll('.color-swatch').forEach(swatch => {
      swatch.addEventListener('click', () => {
        const color = swatch.dataset.color;
        this.activeColor = color;
        document.querySelectorAll('.color-swatch').forEach(s => s.classList.remove('active'));
        swatch.classList.add('active');
        this.applyColorToSelectedObjects(color);
      });
    });

    // Stroke width options
    document.querySelectorAll('.stroke-width-opt').forEach(opt => {
      opt.addEventListener('click', () => {
        const w = opt.dataset.width;
        this.activeStrokeWidth = parseInt(w);
        document.querySelectorAll('.stroke-width-opt').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
      });
    });

    // Undo / Redo in top bar
    document.getElementById('btnUndo')?.addEventListener('click', () => this.undo());
    document.getElementById('btnRedo')?.addEventListener('click', () => this.redo());

    // Clear board
    document.getElementById('btnClearCanvas')?.addEventListener('click', () => {
      if (confirm('Clear the entire board? This action can be undone.')) {
        this.canvas.clear();
        this.pushHistoryState();
      }
    });

    // Convert handwriting button in toolbar
    document.getElementById('btnHandwritingToText')?.addEventListener('click', () => {
      this.convertSelectedStrokesToText();
    });
  }

  toggleBrushSettingsPanel() {
    const panel = document.getElementById('brushSettingsPanel');
    if (panel) {
      panel.classList.toggle('open');
    }
  }

  // =========================================================================
  // SHAPE & OBJECT CREATION
  // =========================================================================

  initShapeCreation() {
    this.canvas.on('mouse:down', (opt) => {
      // Pen is handled exclusively by KritaInkingEngine
      if (this.isPanning || this.isSpacePressed || this.currentTool === 'pen') return;

      const pointer = this.canvas.getPointer(opt.e);
      this.shapeStart = { x: pointer.x, y: pointer.y };

      // Direct Click for Text Tool
      if (this.currentTool === 'text') {
        this.addTextObject(pointer.x, pointer.y);
        this.setTool('select');
        return;
      }

      // Direct Click for Sticky Note Tool
      if (this.currentTool === 'sticky') {
        this.addStickyNoteObject(pointer.x, pointer.y);
        this.setTool('select');
        return;
      }

      // Eraser Tool click
      if (this.currentTool === 'eraser' && opt.target) {
        this.canvas.remove(opt.target);
        this.pushHistoryState();
        return;
      }

      // Interactive Shape Dragging (Rect, Ellipse, Arrow)
      if (['rect', 'ellipse', 'arrow'].includes(this.currentTool)) {
        this.isDrawingShape = true;
        this.tempShape = this.createTemporaryShape(this.currentTool, pointer.x, pointer.y);
        if (this.tempShape) {
          this.canvas.add(this.tempShape);
        }
      }
    });

    this.canvas.on('mouse:move', (opt) => {
      if (!this.isDrawingShape || !this.tempShape) return;
      const pointer = this.canvas.getPointer(opt.e);
      this.updateTemporaryShape(this.currentTool, pointer.x, pointer.y);
      this.canvas.renderAll();
    });

    this.canvas.on('mouse:up', () => {
      if (this.isDrawingShape && this.tempShape) {
        this.isDrawingShape = false;
        this.tempShape.isTemporary = false;
        this.tempShape.setCoords();
        this.pushHistoryState();
        this.tempShape = null;
        this.setTool('select');
      }
    });
  }

  createTemporaryShape(type, x, y) {
    if (type === 'rect') {
      return new fabric.Rect({
        left: x,
        top: y,
        width: 1,
        height: 1,
        fill: '#ffffff',
        stroke: this.activeColor,
        strokeWidth: this.activeStrokeWidth,
        rx: 8,
        ry: 8,
        isTemporary: true
      });
    } else if (type === 'ellipse') {
      return new fabric.Ellipse({
        left: x,
        top: y,
        rx: 1,
        ry: 1,
        fill: '#ffffff',
        stroke: this.activeColor,
        strokeWidth: this.activeStrokeWidth,
        isTemporary: true
      });
    } else if (type === 'arrow') {
      return new fabric.Line([x, y, x, y], {
        stroke: this.activeColor,
        strokeWidth: Math.max(this.activeStrokeWidth, 2),
        selectable: true,
        isArrow: true,
        isTemporary: true
      });
    }
    return null;
  }

  updateTemporaryShape(type, currentX, currentY) {
    if (!this.tempShape) return;
    const sx = this.shapeStart.x;
    const sy = this.shapeStart.y;

    if (type === 'rect') {
      const left = Math.min(sx, currentX);
      const top = Math.min(sy, currentY);
      const width = Math.abs(currentX - sx);
      const height = Math.abs(currentY - sy);
      this.tempShape.set({ left, top, width, height });
    } else if (type === 'ellipse') {
      const rx = Math.abs(currentX - sx) / 2;
      const ry = Math.abs(currentY - sy) / 2;
      const left = Math.min(sx, currentX);
      const top = Math.min(sy, currentY);
      this.tempShape.set({ left, top, rx, ry });
    } else if (type === 'arrow') {
      this.tempShape.set({ x2: currentX, y2: currentY });
    }
  }

  addTextObject(x, y, initialText = 'Type your thought here...') {
    const text = new fabric.Textbox(initialText, {
      left: x,
      top: y,
      width: 220,
      fontSize: 16,
      fontFamily: 'Inter, sans-serif',
      fill: '#0f172a',
      editable: true,
      borderColor: '#4f46e5',
      cornerColor: '#4f46e5',
      cornerSize: 8,
      transparentCorners: false
    });
    this.canvas.add(text);
    this.canvas.setActiveObject(text);
    text.enterEditing();
    text.selectAll();
    this.canvas.renderAll();
    this.pushHistoryState();
  }

  addStickyNoteObject(x, y, textContent = 'New Note', noteFill = '#fef08a', noteTitle = '') {
    const width = 220;
    const height = 180;

    const bgRect = new fabric.Rect({
      left: x,
      top: y,
      width: width,
      height: height,
      fill: noteFill,
      stroke: '#ca8a04',
      strokeWidth: 1.5,
      rx: 6,
      ry: 6,
      shadow: new fabric.Shadow({
        color: 'rgba(0,0,0,0.08)',
        blur: 8,
        offsetX: 0,
        offsetY: 4
      })
    });

    const fullText = noteTitle ? `${noteTitle}\n\n${textContent}` : textContent;
    const text = new fabric.Textbox(fullText, {
      left: x + 14,
      top: y + 14,
      width: width - 28,
      fontSize: 14,
      fontFamily: 'Inter, sans-serif',
      fill: '#1e293b',
      lineHeight: 1.3
    });

    const stickyGroup = new fabric.Group([bgRect, text], {
      left: x,
      top: y,
      isStickyNote: true
    });

    this.canvas.add(stickyGroup);
    this.canvas.setActiveObject(stickyGroup);
    this.canvas.renderAll();
    this.pushHistoryState();
  }

  // =========================================================================
  // SELECTION & CONTEXT TOOLBAR
  // =========================================================================

  initSelectionEvents() {
    this.canvas.on('selection:created', (e) => this.updateContextToolbar(e.selected));
    this.canvas.on('selection:updated', (e) => this.updateContextToolbar(e.selected));
    this.canvas.on('selection:cleared', () => this.hideContextToolbar());

    // Context toolbar buttons
    document.getElementById('ctxBtnDuplicate')?.addEventListener('click', () => this.duplicateSelectedObjects());
    document.getElementById('ctxBtnDelete')?.addEventListener('click', () => this.deleteSelectedObjects());
    document.getElementById('ctxBtnHtr')?.addEventListener('click', () => this.convertSelectedStrokesToText());

    document.querySelectorAll('.ctx-color-swatch').forEach(swatch => {
      swatch.addEventListener('click', () => {
        const color = swatch.dataset.color;
        this.applyColorToSelectedObjects(color);
      });
    });
  }

  updateContextToolbar(selectedObjects) {
    const bar = document.getElementById('contextToolbar');
    if (!bar || !selectedObjects || selectedObjects.length === 0) return;

    const activeObj = this.canvas.getActiveObject();
    if (!activeObj) return;

    const bound = activeObj.getBoundingRect();
    bar.style.left = `${bound.left + bound.width / 2}px`;
    bar.style.top = `${bound.top - 10}px`;
    bar.classList.add('visible');

    // Show or hide handwriting recognition button if paths are selected
    const hasPath = selectedObjects.some(o => o.type === 'path' || o.isStroke);
    const htrBtn = document.getElementById('ctxBtnHtr');
    if (htrBtn) {
      htrBtn.style.display = hasPath ? 'inline-flex' : 'none';
    }
  }

  hideContextToolbar() {
    const bar = document.getElementById('contextToolbar');
    if (bar) bar.classList.remove('visible');
  }

  applyColorToSelectedObjects(color) {
    const activeObj = this.canvas.getActiveObject();
    if (!activeObj) return;

    if (activeObj.type === 'activeSelection') {
      activeObj.getObjects().forEach(obj => this.applyColorToObject(obj, color));
    } else {
      this.applyColorToObject(activeObj, color);
    }
    this.canvas.requestRenderAll();
    this.pushHistoryState();
  }

  applyColorToObject(obj, color) {
    if (obj.isStickyNote && obj._objects) {
      obj._objects[0].set('fill', color);
    } else if (obj.type === 'path' || obj.isArrow || obj.type === 'line' || obj.isStroke) {
      obj.set('stroke', color);
    } else if (obj.type === 'textbox' || obj.type === 'i-text') {
      obj.set('fill', color);
    } else {
      obj.set('stroke', color);
    }
  }

  duplicateSelectedObjects() {
    const active = this.canvas.getActiveObject();
    if (!active) return;
    active.clone((cloned) => {
      this.canvas.discardActiveObject();
      cloned.set({
        left: cloned.left + 24,
        top: cloned.top + 24,
        evented: true
      });
      if (cloned.type === 'activeSelection') {
        cloned.canvas = this.canvas;
        cloned.forEachObject((obj) => this.canvas.add(obj));
        cloned.setCoords();
      } else {
        this.canvas.add(cloned);
      }
      this.canvas.setActiveObject(cloned);
      this.canvas.requestRenderAll();
      this.pushHistoryState();
    });
  }

  deleteSelectedObjects() {
    const active = this.canvas.getActiveObject();
    if (!active) return;

    if (active.type === 'activeSelection') {
      active.getObjects().forEach(obj => this.canvas.remove(obj));
      this.canvas.discardActiveObject();
    } else {
      this.canvas.remove(active);
    }
    this.hideContextToolbar();
    this.canvas.requestRenderAll();
    this.pushHistoryState();
  }

  // =========================================================================
  // SELECTIVE @BOARD INK DISSOLUTION ENGINE
  // Dissolves ONLY the ink in the area where @board is mentioned
  // All other user notes, drawings, and shapes remain completely intact!
  // =========================================================================

  dissolveBoardInk(targetObjects, onComplete) {
    if (!targetObjects || targetObjects.length === 0) {
      if (onComplete) onComplete();
      return;
    }

    const list = Array.isArray(targetObjects) ? targetObjects : [targetObjects];
    let remaining = list.length;

    list.forEach(obj => {
      // Smooth enchanted fade animation
      fabric.util.animate({
        startValue: obj.opacity !== undefined ? obj.opacity : 1.0,
        endValue: 0.0,
        duration: 380,
        onChange: (val) => {
          obj.set('opacity', val);
          this.canvas.requestRenderAll();
        },
        onComplete: () => {
          this.canvas.remove(obj);
          remaining--;
          if (remaining <= 0) {
            this.canvas.discardActiveObject();
            this.canvas.requestRenderAll();
            this.pushHistoryState();
            if (onComplete) onComplete();
          }
        }
      });
    });
  }

  // =========================================================================
  // THE @BOARD AI ENGINE & INTERACTION
  // =========================================================================

  initAiCommandBar() {
    const input = document.getElementById('aiCommandInput');
    const submitBtn = document.getElementById('btnSubmitAiCommand');
    const undoAiBtn = document.getElementById('btnUndoAiInsert');
    const dismissBannerBtn = document.getElementById('btnDismissAiBanner');

    // Enter key submit
    input?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.executeAiCommand();
      }
    });

    submitBtn?.addEventListener('click', () => this.executeAiCommand());
    undoAiBtn?.addEventListener('click', () => this.undoLastAiInsert());
    dismissBannerBtn?.addEventListener('click', () => this.hideAiNotificationBanner());

    // Prompt chips click
    document.querySelectorAll('.prompt-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const prompt = chip.dataset.prompt;
        if (input) {
          input.value = `@board ${prompt}`;
          input.focus();
        }
      });
    });
  }

  async executeAiCommand(overrideCommand = null, overrideInsertionPoint = null) {
    const input = document.getElementById('aiCommandInput');
    const submitBtn = document.getElementById('btnSubmitAiCommand');

    let command = overrideCommand || (input ? input.value.trim() : '');
    if (!command) {
      if (input) input.focus();
      return;
    }

    // Ensure @board tag
    if (!command.toLowerCase().includes('@board')) {
      command = `@board ${command}`;
    }

    // Determine target objects to dissolve: ONLY those where @board is mentioned!
    const active = this.canvas.getActiveObject();
    let targetsToDissolve = [];

    if (active) {
      // If user had specific objects selected when running @board, dissolve only those
      targetsToDissolve = active.type === 'activeSelection' ? active.getObjects().slice() : [active];
    } else {
      // Search for any existing text or sticky note explicitly containing "@board"
      this.canvas.getObjects().forEach(obj => {
        let txt = '';
        if (obj.text) txt = obj.text;
        else if (obj.isStickyNote && obj._objects && obj._objects[1]) txt = obj._objects[1].text;
        if (txt && txt.toLowerCase().includes('@board')) {
          targetsToDissolve.push(obj);
        }
      });
    }

    // Dissolve ONLY the @board prompt area! Everything else remains intact.
    if (targetsToDissolve.length > 0) {
      this.dissolveBoardInk(targetsToDissolve);
    }

    // Determine scope and context
    const scopeSelect = document.getElementById('aiScopeSelect');
    const scope = scopeSelect ? scopeSelect.value : 'all';
    const boardContext = this.extractBoardContext(scope === 'selected');

    // Determine smart insertion point
    const insertionPoint = overrideInsertionPoint || this.calculateSmartInsertionPoint();

    // Show loading state
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<div class="spinner"></div>';
    }

    try {
      const response = await fetch('/api/board/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          command: command,
          board_context: boardContext,
          insertion_point: insertionPoint
        })
      });

      const data = await response.json();
      if (data && data.objects && data.objects.length > 0) {
        this.renderAiObjects(data.batch_id, data.objects, data.summary);
        if (input && !overrideCommand) input.value = '';
      } else {
        alert(data.summary || 'AI was unable to generate visual objects for this request.');
      }
    } catch (err) {
      console.error('[WhiteboardApp] AI Command Error:', err);
      alert('Error contacting AI whiteboard service. Please check your network connection.');
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M5 12h14M12 5l7 7-7 7"/>
          </svg>
        `;
      }
    }
  }

  extractBoardContext(selectedOnly = false) {
    const objects = this.canvas.getObjects();
    const active = this.canvas.getActiveObject();
    const context = {
      selected_text: [],
      existing_notes: []
    };

    const targetList = (selectedOnly && active)
      ? (active.type === 'activeSelection' ? active.getObjects() : [active])
      : objects;

    targetList.forEach(obj => {
      let t = '';
      if (obj.text) t = obj.text;
      else if (obj.isStickyNote && obj._objects && obj._objects[1]) t = obj._objects[1].text;
      
      if (t && t.trim()) {
        if (selectedOnly) context.selected_text.push(t.trim());
        else context.existing_notes.push(t.trim());
      }
    });

    return context;
  }

  calculateSmartInsertionPoint() {
    const active = this.canvas.getActiveObject();
    if (active) {
      const b = active.getBoundingRect(true, true);
      return { x: b.left + b.width + 60, y: b.top };
    }

    const objects = this.canvas.getObjects();
    if (objects.length > 0) {
      let maxX = -Infinity;
      let avgY = 0;
      objects.forEach(obj => {
        const b = obj.getBoundingRect(true, true);
        maxX = Math.max(maxX, b.left + b.width);
        avgY += b.top;
      });
      return { x: maxX + 80, y: Math.max(avgY / objects.length, 100) };
    }

    // Centered in current viewport if canvas is empty
    const vpt = this.canvas.viewportTransform;
    const zoom = vpt[0];
    const centerX = (-vpt[4] + this.canvas.width / 2) / zoom;
    const centerY = (-vpt[5] + this.canvas.height / 2) / zoom;

    return { x: Math.max(centerX - 300, 100), y: Math.max(centerY - 180, 100) };
  }

  renderAiObjects(batchId, objectsData, summaryText) {
    this.lastAiBatchId = batchId;
    const createdObjects = [];
    const idMap = {};

    // Phase 1: Create Nodes (Rectangles, Ellipses, Sticky Notes, Text)
    objectsData.forEach(item => {
      let fabricObj = null;

      if (item.type === 'text') {
        fabricObj = new fabric.Textbox(item.text || 'Text', {
          left: item.x,
          top: item.y,
          width: item.width || 400,
          fontSize: item.font_size || 20,
          fontWeight: 'bold',
          fill: item.fill || '#0f172a',
          fontFamily: 'Inter, sans-serif'
        });
      } else if (item.type === 'sticky_note') {
        const bg = new fabric.Rect({
          left: item.x,
          top: item.y,
          width: item.width || 240,
          height: item.height || 180,
          fill: item.fill || '#fef08a',
          stroke: item.stroke || '#ca8a04',
          strokeWidth: 1.5,
          rx: 6,
          ry: 6,
          shadow: new fabric.Shadow({ color: 'rgba(0,0,0,0.08)', blur: 8, offsetX: 0, offsetY: 4 })
        });
        const fullContent = item.title ? `${item.title}\n\n${item.text}` : (item.text || '');
        const tb = new fabric.Textbox(fullContent, {
          left: item.x + 14,
          top: item.y + 14,
          width: (item.width || 240) - 28,
          fontSize: item.font_size || 14,
          fontFamily: 'Inter, sans-serif',
          fill: '#1e293b',
          lineHeight: 1.3
        });
        fabricObj = new fabric.Group([bg, tb], {
          left: item.x,
          top: item.y,
          isStickyNote: true
        });
      } else if (item.type === 'ellipse') {
        const rx = (item.width || 180) / 2;
        const ry = (item.height || 75) / 2;
        const ellipse = new fabric.Ellipse({
          left: item.x,
          top: item.y,
          rx: rx,
          ry: ry,
          fill: item.fill || '#ffffff',
          stroke: item.stroke || '#2563eb',
          strokeWidth: item.stroke_width || 2,
          shadow: new fabric.Shadow({ color: 'rgba(0,0,0,0.05)', blur: 6, offsetX: 0, offsetY: 2 })
        });
        const text = new fabric.Textbox(item.text || '', {
          left: item.x + 10,
          top: item.y + ry - 16,
          width: (item.width || 180) - 20,
          fontSize: item.font_size || 13,
          textAlign: 'center',
          fontFamily: 'Inter, sans-serif',
          fill: '#0f172a'
        });
        fabricObj = new fabric.Group([ellipse, text], {
          left: item.x,
          top: item.y
        });
      } else if (item.type === 'rectangle') {
        const rect = new fabric.Rect({
          left: item.x,
          top: item.y,
          width: item.width || 180,
          height: item.height || 75,
          fill: item.fill || '#ffffff',
          stroke: item.stroke || '#2563eb',
          strokeWidth: item.stroke_width || 2,
          rx: 8,
          ry: 8,
          shadow: new fabric.Shadow({ color: 'rgba(0,0,0,0.05)', blur: 6, offsetX: 0, offsetY: 2 })
        });
        const text = new fabric.Textbox(item.text || '', {
          left: item.x + 12,
          top: item.y + 12,
          width: (item.width || 180) - 24,
          fontSize: item.font_size || 13,
          fontFamily: 'Inter, sans-serif',
          fill: '#0f172a',
          lineHeight: 1.2
        });
        fabricObj = new fabric.Group([rect, text], {
          left: item.x,
          top: item.y
        });
      }

      if (fabricObj) {
        fabricObj.aiBatchId = batchId;
        fabricObj.originalId = item.id;
        idMap[item.id] = fabricObj;
        createdObjects.push(fabricObj);
        this.canvas.add(fabricObj);
      }
    });

    // Phase 2: Create Connectors & Arrows
    objectsData.filter(i => i.type === 'arrow' || i.type === 'connector').forEach(arrowItem => {
      let x1 = arrowItem.x;
      let y1 = arrowItem.y;
      let x2 = arrowItem.x + (arrowItem.width || 60);
      let y2 = arrowItem.y + (arrowItem.height || 0);

      // If connected by from_id / to_id, anchor to node centers
      if (arrowItem.from_id && arrowItem.to_id && idMap[arrowItem.from_id] && idMap[arrowItem.to_id]) {
        const src = idMap[arrowItem.from_id];
        const dst = idMap[arrowItem.to_id];
        const sb = src.getBoundingRect(true, true);
        const db = dst.getBoundingRect(true, true);

        x1 = sb.left + sb.width;
        y1 = sb.top + sb.height / 2;
        x2 = db.left;
        y2 = db.top + db.height / 2;

        // If vertical layout
        if (Math.abs(db.top - sb.top) > Math.abs(db.left - sb.left)) {
          x1 = sb.left + sb.width / 2;
          y1 = sb.top + sb.height;
          x2 = db.left + db.width / 2;
          y2 = db.top;
        }
      }

      const arrow = this.createArrowObject(x1, y1, x2, y2, arrowItem.stroke || '#2563eb', arrowItem.label);
      arrow.aiBatchId = batchId;
      createdObjects.push(arrow);
      this.canvas.add(arrow);
    });

    this.canvas.requestRenderAll();
    this.pushHistoryState();

    // Select all newly created objects so user can move or style them together
    if (createdObjects.length > 0) {
      const selection = new fabric.ActiveSelection(createdObjects, { canvas: this.canvas });
      this.canvas.setActiveObject(selection);
      this.canvas.requestRenderAll();
    }

    // Show Undo AI Insert Banner
    this.showAiNotificationBanner(batchId, createdObjects.length, summaryText);
  }

  createArrowObject(x1, y1, x2, y2, color = '#2563eb', label = '') {
    const line = new fabric.Line([x1, y1, x2, y2], {
      stroke: color,
      strokeWidth: 2,
      selectable: false
    });

    const angle = Math.atan2(y2 - y1, x2 - x1) * (180 / Math.PI);
    const head = new fabric.Triangle({
      left: x2,
      top: y2,
      originX: 'center',
      originY: 'center',
      pointType: 'arrow_start',
      angle: angle + 90,
      width: 12,
      height: 12,
      fill: color,
      selectable: false
    });

    const parts = [line, head];
    if (label) {
      const midX = (x1 + x2) / 2;
      const midY = (y1 + y2) / 2 - 14;
      const text = new fabric.Text(label, {
        left: midX,
        top: midY,
        fontSize: 11,
        fontFamily: 'Inter, sans-serif',
        fill: color,
        backgroundColor: '#ffffff',
        originX: 'center',
        originY: 'center'
      });
      parts.push(text);
    }

    return new fabric.Group(parts, {
      isArrow: true,
      selectable: true
    });
  }

  showAiNotificationBanner(batchId, count, summary) {
    const banner = document.getElementById('aiNotificationBanner');
    const msg = document.getElementById('aiBannerMessage');
    if (banner && msg) {
      msg.textContent = `✨ AI placed ${count} visual objects onto the board: "${summary.substring(0, 60)}..."`;
      banner.classList.add('visible');
    }
  }

  hideAiNotificationBanner() {
    const banner = document.getElementById('aiNotificationBanner');
    if (banner) banner.classList.remove('visible');
  }

  undoLastAiInsert() {
    if (!this.lastAiBatchId) return;
    const objects = this.canvas.getObjects().filter(o => o.aiBatchId === this.lastAiBatchId);
    if (objects.length > 0) {
      objects.forEach(obj => this.canvas.remove(obj));
      this.canvas.discardActiveObject();
      this.canvas.requestRenderAll();
      this.pushHistoryState();
      this.hideAiNotificationBanner();
      this.lastAiBatchId = null;
    }
  }

  // =========================================================================
  // HANDWRITING TO TEXT RECOGNITION (HTR)
  // Selective @board detection: dissolves ONLY the handwritten strokes
  // that formed the @board instruction!
  // =========================================================================

  async convertSelectedStrokesToText() {
    const active = this.canvas.getActiveObject();
    if (!active) {
      alert('Please select the handwritten strokes on the canvas first.');
      return;
    }

    const selectedList = active.type === 'activeSelection' ? active.getObjects() : [active];
    const pathObjects = selectedList.filter(o => o.type === 'path' || o.isStroke);

    if (pathObjects.length === 0) {
      alert('No handwritten strokes found in the current selection.');
      return;
    }

    // Collect coordinates from raw points preserved on the path
    const strokes = [];
    pathObjects.forEach(p => {
      let pts = [];
      if (p.rawPoints && p.rawPoints.length > 0) {
        pts = p.rawPoints.map(pt => ({ x: pt.x, y: pt.y, pressure: pt.pressure || 0.5 }));
      } else if (p.path) {
        p.path.forEach(seg => {
          if (seg.length >= 3) {
            pts.push({ x: p.left + seg[1], y: p.top + seg[2] });
          }
        });
      }
      if (pts.length > 0) strokes.push({ points: pts });
    });

    const bound = active.getBoundingRect(true, true);

    try {
      const resp = await fetch('/api/board/htr', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strokes: strokes,
          canvas_width: Math.round(this.canvas.width),
          canvas_height: Math.round(this.canvas.height)
        })
      });

      const data = await resp.json();
      if (data && data.text) {
        // If recognized text contains @board:
        // ONLY the strokes that formed @board dissolve!
        // All other notes/drawings on the board remain intact!
        if (data.text.toLowerCase().includes('@board')) {
          this.dissolveBoardInk(pathObjects, () => {
            const input = document.getElementById('aiCommandInput');
            if (input) input.value = data.text;
            this.executeAiCommand(data.text, { x: bound.left, y: bound.top });
          });
          return;
        }

        // Otherwise replace strokes with clean digital text box
        pathObjects.forEach(p => this.canvas.remove(p));
        this.canvas.discardActiveObject();
        this.addTextObject(bound.left, bound.top, data.text);
      } else {
        alert('Could not clearly recognize handwriting. Try writing with clear strokes.');
      }
    } catch (err) {
      console.error('[WhiteboardApp] HTR Recognition error:', err);
      alert('Handwriting recognition failed to connect.');
    }
  }

  // =========================================================================
  // UNDO / REDO ENGINE
  // =========================================================================

  pushHistoryState() {
    if (this.isHistoryLocked) return;

    clearTimeout(this.historyDebounceTimer);
    this.historyDebounceTimer = setTimeout(() => {
      if (this.isHistoryLocked || !this.canvas) return;

      const json = JSON.stringify(this.canvas.toJSON(['id', 'aiBatchId', 'isStickyNote', 'isArrow', 'isStroke', 'rawPoints']));
      
      // Prevent duplicate states
      if (this.undoStack.length > 0 && this.undoStack[this.undoStack.length - 1] === json) {
        return;
      }

      this.undoStack.push(json);
      if (this.undoStack.length > 40) this.undoStack.shift();
      this.redoStack = []; // Clear redo stack on new action
      
      this.updateUndoRedoButtonState();
      this.triggerAutosave();
    }, 80);
  }

  undo() {
    if (this.undoStack.length <= 1) return;
    this.isHistoryLocked = true;
    
    const currentState = this.undoStack.pop();
    this.redoStack.push(currentState);

    const prevState = this.undoStack[this.undoStack.length - 1];
    this.canvas.loadFromJSON(prevState, () => {
      this.canvas.renderAll();
      this.isHistoryLocked = false;
      this.updateUndoRedoButtonState();
      this.triggerAutosave();
    });
  }

  redo() {
    if (this.redoStack.length === 0) return;
    this.isHistoryLocked = true;

    const nextState = this.redoStack.pop();
    this.undoStack.push(nextState);

    this.canvas.loadFromJSON(nextState, () => {
      this.canvas.renderAll();
      this.isHistoryLocked = false;
      this.updateUndoRedoButtonState();
      this.triggerAutosave();
    });
  }

  updateUndoRedoButtonState() {
    const btnUndo = document.getElementById('btnUndo');
    const btnRedo = document.getElementById('btnRedo');
    if (btnUndo) btnUndo.disabled = this.undoStack.length <= 1;
    if (btnRedo) btnRedo.disabled = this.redoStack.length === 0;
  }

  // =========================================================================
  // STORAGE & PERSISTENCE
  // =========================================================================

  initStorageAndPersistence() {
    // Board title input
    const titleInput = document.getElementById('boardTitleInput');
    titleInput?.addEventListener('change', () => {
      this.boardName = titleInput.value.trim() || 'Untitled Board';
      this.triggerAutosave(true);
    });

    // Board Switcher / List Modal
    document.getElementById('btnOpenBoardManager')?.addEventListener('click', () => {
      this.openBoardManagerModal();
    });
    document.getElementById('btnNewBoard')?.addEventListener('click', () => {
      this.createNewBoard();
    });

    // Load initial board
    this.loadBoard(this.currentBoardId);
  }

  async loadBoard(boardId) {
    this.isHistoryLocked = true;
    try {
      const resp = await fetch(`/api/board/${boardId}`);
      if (resp.ok) {
        const board = await resp.json();
        this.currentBoardId = board.id;
        this.boardName = board.name;
        
        const titleInput = document.getElementById('boardTitleInput');
        if (titleInput) titleInput.value = this.boardName;

        if (board.data && board.data.objects) {
          this.canvas.loadFromJSON(board.data, () => {
            this.canvas.renderAll();
            this.isHistoryLocked = false;
            this.pushHistoryState();
            this.setSaveStatus(true);
          });
          return;
        }
      }
    } catch (e) {
      console.warn('[WhiteboardApp] Backend load failed, checking localStorage fallback...', e);
    }

    // LocalStorage Fallback
    const local = localStorage.getItem(`enchanted_board_${boardId}`);
    if (local) {
      try {
        const data = JSON.parse(local);
        this.canvas.loadFromJSON(data, () => {
          this.canvas.renderAll();
          this.isHistoryLocked = false;
          this.pushHistoryState();
          this.setSaveStatus(true);
        });
        return;
      } catch (err) {
        console.error('[WhiteboardApp] Local parse error:', err);
      }
    }

    this.isHistoryLocked = false;
    this.pushHistoryState();
    this.setSaveStatus(true);
  }

  triggerAutosave(immediate = false) {
    this.setSaveStatus(false);
    clearTimeout(this.autosaveTimer);
    
    const delay = immediate ? 0 : 2500;
    this.autosaveTimer = setTimeout(() => {
      this.saveCurrentBoard();
    }, delay);
  }

  async saveCurrentBoard() {
    if (!this.canvas) return;
    const boardData = this.canvas.toJSON(['id', 'aiBatchId', 'isStickyNote', 'isArrow', 'isStroke', 'rawPoints']);
    
    // Save locally
    localStorage.setItem(`enchanted_board_${this.currentBoardId}`, JSON.stringify(boardData));

    // Save to backend SQLite
    try {
      const resp = await fetch(`/api/board/${this.currentBoardId}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: this.boardName,
          data: boardData
        })
      });
      if (resp.ok) {
        this.setSaveStatus(true);
      }
    } catch (e) {
      console.warn('[WhiteboardApp] Backend save failed, kept in local storage:', e);
      this.setSaveStatus(true);
    }
  }

  setSaveStatus(isSaved) {
    const dot = document.getElementById('saveStatusDot');
    const label = document.getElementById('saveStatusText');
    if (dot && label) {
      dot.className = isSaved ? 'save-dot' : 'save-dot unsaved';
      label.textContent = isSaved ? 'Saved' : 'Saving...';
    }
  }

  async openBoardManagerModal() {
    const modal = document.getElementById('boardManagerModal');
    const list = document.getElementById('boardListContainer');
    if (!modal || !list) return;

    modal.classList.add('open');
    list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8;">Loading boards...</div>';

    try {
      const resp = await fetch('/api/board/list');
      const data = await resp.json();
      list.innerHTML = '';

      (data.boards || []).forEach(b => {
        const item = document.createElement('div');
        item.className = `board-item-row ${b.id === this.currentBoardId ? 'active' : ''}`;
        item.innerHTML = `
          <div>
            <div class="board-item-name">${b.name}</div>
            <div class="board-item-meta">ID: ${b.id}</div>
          </div>
          <button class="btn-icon" data-del="${b.id}" title="Delete Board" ${b.id === 'default' ? 'disabled' : ''}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            </svg>
          </button>
        `;
        item.addEventListener('click', (e) => {
          if (e.target.closest('button[data-del]')) {
            this.deleteBoard(b.id);
            return;
          }
          this.loadBoard(b.id);
          modal.classList.remove('open');
        });
        list.appendChild(item);
      });
    } catch (err) {
      list.innerHTML = '<div style="padding:20px;color:#ef4444;">Failed to load board list.</div>';
    }
  }

  async createNewBoard() {
    const name = prompt('Enter a name for the new whiteboard:', 'Design Board');
    if (!name) return;

    try {
      const resp = await fetch('/api/board/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name })
      });
      const data = await resp.json();
      if (data && data.id) {
        this.canvas.clear();
        this.currentBoardId = data.id;
        this.boardName = data.name;
        const titleInput = document.getElementById('boardTitleInput');
        if (titleInput) titleInput.value = this.boardName;
        this.pushHistoryState();
        document.getElementById('boardManagerModal')?.classList.remove('open');
      }
    } catch (err) {
      alert('Failed to create new board.');
    }
  }

  async deleteBoard(boardId) {
    if (!confirm('Are you sure you want to delete this board?')) return;
    try {
      await fetch(`/api/board/${boardId}`, { method: 'DELETE' });
      this.openBoardManagerModal();
    } catch (err) {
      alert('Failed to delete board.');
    }
  }

  // =========================================================================
  // EXPORT & IMPORT
  // =========================================================================

  initExportImport() {
    // Export PNG
    document.getElementById('btnExportPng')?.addEventListener('click', () => {
      this.exportToPng();
    });

    // Export JSON
    document.getElementById('btnExportJson')?.addEventListener('click', () => {
      this.exportToJson();
    });

    // Import JSON
    const fileInput = document.getElementById('importJsonInput');
    document.getElementById('btnImportJson')?.addEventListener('click', () => {
      fileInput?.click();
    });

    fileInput?.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (evt) => {
        try {
          const json = JSON.parse(evt.target.result);
          this.canvas.loadFromJSON(json, () => {
            this.canvas.renderAll();
            this.pushHistoryState();
            alert('Board successfully imported!');
          });
        } catch (err) {
          alert('Invalid JSON board file.');
        }
      };
      reader.readAsText(file);
    });
  }

  exportToPng() {
    if (!this.canvas) return;
    this.canvas.discardActiveObject();
    this.canvas.renderAll();

    const dataUrl = this.canvas.toDataURL({
      format: 'png',
      multiplier: 2,
      enableRetinaScaling: true
    });

    const link = document.createElement('a');
    link.download = `${this.boardName.replace(/\s+/g, '_')}_whiteboard.png`;
    link.href = dataUrl;
    link.click();
  }

  exportToJson() {
    if (!this.canvas) return;
    const jsonStr = JSON.stringify(this.canvas.toJSON(['id', 'aiBatchId', 'isStickyNote', 'isArrow', 'isStroke', 'rawPoints']), null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.download = `${this.boardName.replace(/\s+/g, '_')}_board.json`;
    link.href = url;
    link.click();
    URL.revokeObjectURL(url);
  }

  // =========================================================================
  // KEYBOARD SHORTCUTS
  // =========================================================================

  initKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      // Ignore if typing in text inputs
      if (this.isEditingText()) return;

      const isCtrl = e.ctrlKey || e.metaKey;

      if (isCtrl && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) this.redo();
        else this.undo();
      } else if (isCtrl && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        this.redo();
      } else if (isCtrl && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const input = document.getElementById('aiCommandInput');
        if (input) {
          input.focus();
          input.select();
        }
      } else if (isCtrl && e.key.toLowerCase() === 'd') {
        e.preventDefault();
        this.duplicateSelectedObjects();
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        this.deleteSelectedObjects();
      } else if (e.key.toLowerCase() === 'v') {
        this.setTool('select');
      } else if (e.key.toLowerCase() === 'h') {
        this.setTool('pan');
      } else if (e.key.toLowerCase() === 'p') {
        this.setTool('pen');
      } else if (e.key.toLowerCase() === 'e') {
        this.setTool('eraser');
      } else if (e.key.toLowerCase() === 't') {
        this.setTool('text');
      } else if (e.key.toLowerCase() === 's') {
        this.setTool('sticky');
      } else if (e.key.toLowerCase() === 'r') {
        this.setTool('rect');
      } else if (e.key.toLowerCase() === 'o') {
        this.setTool('ellipse');
      } else if (e.key.toLowerCase() === 'a') {
        this.setTool('arrow');
      }
    });
  }

  isEditingText() {
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return true;
    if (this.canvas) {
      const activeObj = this.canvas.getActiveObject();
      if (activeObj && activeObj.isEditing) return true;
    }
    return false;
  }

  // =========================================================================
  // GEMINI CONFIG MODAL & STATUS
  // =========================================================================

  async checkGeminiConfig() {
    try {
      const resp = await fetch('/api/board/config/status');
      const data = await resp.json();
      const dot = document.getElementById('geminiConfigDot');
      const label = document.getElementById('geminiConfigLabel');
      if (dot && label) {
        dot.className = data.configured ? 'save-dot' : 'save-dot unsaved';
        label.textContent = data.configured ? 'AI Ready' : 'Configure API';
      }
    } catch (e) {
      console.warn('Failed to check Gemini status');
    }

    document.getElementById('btnOpenSettings')?.addEventListener('click', () => {
      document.getElementById('settingsModal')?.classList.add('open');
    });

    document.getElementById('btnSaveApiKey')?.addEventListener('click', async () => {
      const keyInput = document.getElementById('inputApiKey');
      const key = keyInput ? keyInput.value.trim() : '';
      if (!key) return;
      try {
        const resp = await fetch('/api/board/config/key', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: key })
        });
        const data = await resp.json();
        if (data.status === 'saved') {
          alert('Gemini API Key saved successfully!');
          document.getElementById('settingsModal')?.classList.remove('open');
          this.checkGeminiConfig();
        }
      } catch (err) {
        alert('Failed to save API key.');
      }
    });

    // Close buttons on all modals
    document.querySelectorAll('.modal-close-btn, [data-modal-close]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.remove('open'));
      });
    });
  }
}

// Instantiate on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  window.app = new WhiteboardApp();
});
