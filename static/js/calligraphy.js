/**
 * Progressive Calligraphy Renderer
 * Animates the diary's response onto the parchment stroke-by-stroke
 * using cursive dynamics, adaptive font sizing to prevent cutoff,
 * and procedural quill audio.
 */
class CalligraphyRenderer {
  constructor(canvasElement) {
    this.canvas = canvasElement;
    this.ctx = canvasElement.getContext('2d');
    this.isRendering = false;
    this.animationId = null;
    this.timeoutId = null;

    this._resizeCanvas();
    window.addEventListener('resize', () => this._resizeCanvas());
  }

  _resizeCanvas() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.canvas.style.width = `${rect.width}px`;
    this.canvas.style.height = `${rect.height}px`;
    this.ctx.scale(dpr, dpr);
  }

  clear() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
    if (this.timeoutId) {
      clearTimeout(this.timeoutId);
      this.timeoutId = null;
    }
    this.isRendering = false;
    const rect = this.canvas.getBoundingClientRect();
    this.ctx.clearRect(0, 0, rect.width, rect.height);
  }

  _wrapText(text, fontSize, maxWidth) {
    this.ctx.font = `${fontSize}px "Dancing Script", cursive`;
    const paragraphs = text.split('\n');
    const lines = [];

    for (const paragraph of paragraphs) {
      const words = paragraph.trim().split(/\s+/);
      let currentLine = '';

      for (const word of words) {
        if (!word) continue;
        const testLine = currentLine.length === 0 ? word : currentLine + ' ' + word;
        const metrics = this.ctx.measureText(testLine);

        if (metrics.width > maxWidth && currentLine.length > 0) {
          lines.push(currentLine);
          currentLine = word;
        } else {
          currentLine = testLine;
        }
      }
      if (currentLine.length > 0) {
        lines.push(currentLine);
      }
    }
    return lines;
  }

  animateText(text, onComplete) {
    this.clear();
    this._resizeCanvas();
    this.isRendering = true;

    const rect = this.canvas.getBoundingClientRect();
    const startX = 28;
    const startY = 38;
    const maxLineWidth = Math.max(rect.width - 56, 180);
    const availableHeight = Math.max(rect.height - startY - 24, 160);

    // Dynamic adaptive font-sizing to guarantee the response never cuts off
    let fontSize = 22;
    let lineHeight = Math.round(fontSize * 1.35);
    let lines = this._wrapText(text, fontSize, maxLineWidth);

    // Iteratively scale down until the text fits comfortably inside availableHeight
    while (lines.length * lineHeight > availableHeight && fontSize > 12) {
      fontSize -= 1.0;
      lineHeight = Math.round(fontSize * 1.32);
      lines = this._wrapText(text, fontSize, maxLineWidth);
    }

    // If still slightly tall, compress lineHeight proportionally
    if (lines.length * lineHeight > availableHeight && lines.length > 0) {
      lineHeight = Math.max(Math.floor(availableHeight / lines.length), 13);
    }

    // Set font for drawing
    this.ctx.font = `${fontSize}px "Dancing Script", cursive`;

    // Progressive writing state
    let lineIdx = 0;
    let charIdx = 0;
    let currentX = startX;
    let currentY = startY;

    const renderStep = () => {
      if (!this.isRendering) return;

      if (lineIdx >= lines.length) {
        this.isRendering = false;
        if (onComplete) onComplete();
        return;
      }

      const activeLine = lines[lineIdx];
      const char = activeLine[charIdx];

      // Draw character with subtle calligraphic ink effect
      this.ctx.save();
      this.ctx.font = `${fontSize}px "Dancing Script", cursive`;
      // Tom Riddle's black-indigo ink with delicate shadow bleed
      this.ctx.fillStyle = '#0f172a';
      this.ctx.shadowColor = 'rgba(15, 23, 42, 0.28)';
      this.ctx.shadowBlur = 1.0;

      this.ctx.fillText(char, currentX, currentY);
      this.ctx.restore();

      // Audio scratch feedback on ink stroke
      if (window.diaryAudio && char.trim().length > 0 && Math.random() < 0.6) {
        window.diaryAudio.playQuillStroke(0.06, 0.35);
      }

      const charWidth = this.ctx.measureText(char).width;
      currentX += charWidth;
      charIdx++;

      if (charIdx >= activeLine.length) {
        lineIdx++;
        charIdx = 0;
        currentX = startX;
        currentY += lineHeight;
      }

      // Variable quill writing velocity (smooth, expressive, never sluggish)
      let delay = 18 + Math.random() * 14;
      if (char === ' ') delay = 22;
      if (['.', '!', '?', ';', ':'].includes(char)) delay = 85;
      if ([',', '—', '-'].includes(char)) delay = 50;

      this.timeoutId = setTimeout(() => {
        this.animationId = requestAnimationFrame(renderStep);
      }, delay);
    };

    this.animationId = requestAnimationFrame(renderStep);
  }

  renderStaticText(text) {
    this.clear();
    this._resizeCanvas();

    if (!text || text.trim().length === 0) return;

    const rect = this.canvas.getBoundingClientRect();
    const startX = 28;
    const startY = 38;
    const maxLineWidth = Math.max(rect.width - 56, 180);
    const availableHeight = Math.max(rect.height - startY - 24, 160);

    let fontSize = 22;
    let lineHeight = Math.round(fontSize * 1.35);
    let lines = this._wrapText(text, fontSize, maxLineWidth);

    while (lines.length * lineHeight > availableHeight && fontSize > 12) {
      fontSize -= 1.0;
      lineHeight = Math.round(fontSize * 1.32);
      lines = this._wrapText(text, fontSize, maxLineWidth);
    }

    if (lines.length * lineHeight > availableHeight && lines.length > 0) {
      lineHeight = Math.max(Math.floor(availableHeight / lines.length), 13);
    }

    this.ctx.save();
    this.ctx.font = `${fontSize}px "Dancing Script", cursive`;
    this.ctx.fillStyle = '#0f172a';
    this.ctx.shadowColor = 'rgba(15, 23, 42, 0.28)';
    this.ctx.shadowBlur = 1.0;

    let currentY = startY;
    for (const line of lines) {
      this.ctx.fillText(line, startX, currentY);
      currentY += lineHeight;
    }
    this.ctx.restore();
  }
}

window.CalligraphyRenderer = CalligraphyRenderer;
