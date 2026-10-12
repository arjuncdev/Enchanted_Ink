/**
 * Interactive Ink Canvas Engine
 * Handles natural freehand stylus/mouse input, Bezier curve smoothing,
 * pressure sensitivity, and ink absorption into the parchment.
 */
class InkCanvasEngine {
  constructor(canvasElement) {
    this.canvas = canvasElement;
    this.ctx = canvasElement.getContext('2d');
    this.strokes = []; // Array of stroke paths: [{points: [{x, y, pressure}], color, isErasing}]
    this.currentStroke = null;
    this.isDrawing = false;
    this.isEraser = false;
    this.absorbedStrokes = [];
    
    // Auto-absorption debounce timer
    this.restTimer = null;
    this.onPenRestCallback = null;

    this._resizeCanvas();
    window.addEventListener('resize', () => this._resizeCanvas());
    this._attachEvents();
  }

  _resizeCanvas() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.canvas.style.width = `${rect.width}px`;
    this.canvas.style.height = `${rect.height}px`;
    this.ctx.scale(dpr, dpr);
    this.redraw();
  }

  _attachEvents() {
    this.canvas.addEventListener('pointerdown', (e) => this._onPointerDown(e));
    this.canvas.addEventListener('pointermove', (e) => this._onPointerMove(e));
    this.canvas.addEventListener('pointerup', (e) => this._onPointerUp(e));
    this.canvas.addEventListener('pointercancel', (e) => this._onPointerUp(e));
  }

  _getCoordinates(e) {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      pressure: e.pressure && e.pressure > 0 ? e.pressure : 0.5,
      time: Date.now()
    };
  }

  _onPointerDown(e) {
    // Only allow pen or primary mouse/touch
    if (e.pointerType === 'touch' && !e.isPrimary) return;
    
    this.isDrawing = true;
    this.canvas.setPointerCapture(e.pointerId);
    
    // Clear rest timer
    if (this.restTimer) clearTimeout(this.restTimer);

    const pt = this._getCoordinates(e);
    this.currentStroke = {
      points: [pt],
      isEraser: this.isEraser,
      absorbed: false,
      opacity: 1.0
    };
    this.strokes.push(this.currentStroke);

    if (window.diaryAudio) {
      window.diaryAudio.playQuillStroke(0.08, 0.3);
    }
  }

  _onPointerMove(e) {
    if (!this.isDrawing || !this.currentStroke) return;
    const pt = this._getCoordinates(e);
    this.currentStroke.points.push(pt);

    // Audio scratch feedback
    if (window.diaryAudio && Math.random() < 0.25) {
      window.diaryAudio.playQuillStroke(0.06, pt.pressure);
    }

    this.redraw();
  }

  _onPointerUp(e) {
    if (!this.isDrawing) return;
    this.isDrawing = false;
    this.currentStroke = null;

    // Trigger ink absorption animation after 1.2s rest
    if (this.restTimer) clearTimeout(this.restTimer);
    this.restTimer = setTimeout(() => {
      this.absorbInk();
      if (this.onPenRestCallback) {
        this.onPenRestCallback();
      }
    }, 1200);
  }

  vanishInk(onComplete) {
    // Smoothly dissolves the user's ink completely into the parchment (Harry Potter style)
    if (this.strokes.length === 0) {
      if (onComplete) onComplete();
      return;
    }

    if (window.diaryAudio) {
      window.diaryAudio.playInkAbsorption();
    }

    let step = 0;
    const totalSteps = 20;
    const interval = setInterval(() => {
      step++;
      let anyRemaining = false;

      this.strokes.forEach(stroke => {
        if (stroke.opacity > 0.02) {
          stroke.opacity = Math.max(0, stroke.opacity - 0.05);
          anyRemaining = true;
        } else {
          stroke.opacity = 0;
        }
      });
      this.redraw();

      if (step >= totalSteps || !anyRemaining) {
        clearInterval(interval);
        // Completely clear the canvas strokes array so it is 100% invisible!
        this.strokes = [];
        this.redraw();
        if (onComplete) onComplete();
      }
    }, 30);
  }

  absorbInk() {
    // Subtle initial settling of ink on the paper
    this.redraw();
  }

  redraw() {
    const rect = this.canvas.getBoundingClientRect();
    this.ctx.clearRect(0, 0, rect.width, rect.height);

    for (const stroke of this.strokes) {
      if (stroke.points.length < 1) continue;

      this.ctx.save();
      if (stroke.isEraser) {
        this.ctx.globalCompositeOperation = 'destination-out';
        this.ctx.strokeStyle = 'rgba(0,0,0,1)';
        this.ctx.lineWidth = 20;
      } else {
        this.ctx.globalCompositeOperation = 'source-over';
        // Deep antique indigo-sepia ink
        this.ctx.strokeStyle = `rgba(26, 22, 43, ${stroke.opacity})`;
        this.ctx.fillStyle = `rgba(26, 22, 43, ${stroke.opacity})`;
      }

      this.ctx.lineCap = 'round';
      this.ctx.lineJoin = 'round';

      const pts = stroke.points;
      if (pts.length === 1) {
        this.ctx.beginPath();
        this.ctx.arc(pts[0].x, pts[0].y, Math.max(pts[0].pressure * 3, 1.5), 0, Math.PI * 2);
        this.ctx.fill();
      } else {
        // Draw smoothed Bezier curves between points
        for (let i = 0; i < pts.length - 1; i++) {
          const p1 = pts[i];
          const p2 = pts[i + 1];
          const midX = (p1.x + p2.x) / 2;
          const midY = (p1.y + p2.y) / 2;

          this.ctx.lineWidth = stroke.isEraser ? 22 : Math.max(p1.pressure * 4.5, 1.8);
          this.ctx.beginPath();
          if (i === 0) {
            this.ctx.moveTo(p1.x, p1.y);
            this.ctx.lineTo(midX, midY);
          } else {
            const prevMidX = (pts[i - 1].x + p1.x) / 2;
            const prevMidY = (pts[i - 1].y + p1.y) / 2;
            this.ctx.moveTo(prevMidX, prevMidY);
            this.ctx.quadraticCurveTo(p1.x, p1.y, midX, midY);
          }
          this.ctx.stroke();
        }
      }
      this.ctx.restore();
    }
  }

  setEraser(active) {
    this.isEraser = active;
  }

  clear() {
    this.strokes = [];
    this.redraw();
  }

  undo() {
    if (this.strokes.length > 0) {
      this.strokes.pop();
      this.redraw();
    }
  }

  hasInk() {
    return this.strokes.some(s => !s.isEraser && s.points.length > 0);
  }

  exportStrokes() {
    return this.strokes
      .filter(s => !s.isEraser && s.points.length > 0)
      .map(s => ({
        isEraser: false,
        points: s.points.map(p => ({
          x: Math.round(p.x),
          y: Math.round(p.y),
          pressure: p.pressure || 0.5,
          time: p.time || Date.now()
        }))
      }));
  }

  exportBase64PNG() {
    return this.canvas.toDataURL('image/png');
  }
}

window.InkCanvasEngine = InkCanvasEngine;
