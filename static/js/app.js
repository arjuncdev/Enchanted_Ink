/**
 * Enchanted Ink — Main Application Controller
 */
class EnchantedInkApp {
  constructor() {
    this.currentPage = 1;
    this.activePersona = 'regular_qa';
    this.isCandleLit = true;

    // Components
    this.canvasEngine = new InkCanvasEngine(document.getElementById('inkCanvas'));
    this.calligraphyRenderer = new CalligraphyRenderer(document.getElementById('calligraphyCanvas'));
    this.memoryModal = new MemorySanctumModal(
      document.getElementById('memoryModalOverlay'),
      document.getElementById('memoryListContainer')
    );
    window.memoryModal = this.memoryModal;

    this.historyContainer = document.getElementById('historyContainer');
    this.statusText = document.getElementById('statusText');
    this.confidenceMeter = document.getElementById('confidenceMeter');
    this.clarificationBanner = document.getElementById('clarificationBanner');
    this.clarificationPromptText = document.getElementById('clarificationPromptText');
    this.clarificationInput = document.getElementById('clarificationInput');

    // Gemini modal elements
    this.geminiModal = document.getElementById('geminiModalOverlay');
    this.geminiStatusLabel = document.getElementById('geminiStatusLabel');
    this.geminiApiKeyInput = document.getElementById('geminiApiKeyInput');
    this.geminiKeyStatusMsg = document.getElementById('geminiKeyStatusMsg');

    this._bindEvents();
    this._loadPageHistory();
    this.checkGeminiStatus();

    // Hook pen rest callback from canvas engine
    this.canvasEngine.onPenRestCallback = () => {
      this.statusText.textContent = "The parchment is absorbing your ink... Press Submit when ready.";
    };
  }

  _bindEvents() {
    // Toolbar buttons
    document.getElementById('btnPen').addEventListener('click', () => {
      this.canvasEngine.setEraser(false);
      document.getElementById('btnPen').classList.add('active');
      document.getElementById('btnEraser').classList.remove('active');
    });

    document.getElementById('btnEraser').addEventListener('click', () => {
      this.canvasEngine.setEraser(true);
      document.getElementById('btnEraser').classList.add('active');
      document.getElementById('btnPen').classList.remove('active');
    });

    document.getElementById('btnClear').addEventListener('click', () => {
      this.canvasEngine.clear();
      this.calligraphyRenderer.clear();
      this.clarificationBanner.classList.remove('active');
      this.statusText.textContent = "Write upon the parchment...";
    });

    document.getElementById('btnUndo').addEventListener('click', () => {
      this.canvasEngine.undo();
    });

    document.getElementById('btnSubmitTurn').addEventListener('click', () => {
      this.submitWritingTurn();
    });

    // Page turns
    document.getElementById('btnNextPage').addEventListener('click', () => this.turnPage(1));
    document.getElementById('btnPrevPage').addEventListener('click', () => this.turnPage(-1));

    // Mode Switcher Buttons (Tom Riddle vs Regular Q&A)
    const btnModeTomRiddle = document.getElementById('btnModeTomRiddle');
    const btnModeRegularQA = document.getElementById('btnModeRegularQA');
    const personaSelect = document.getElementById('personaSelect');

    if (btnModeTomRiddle) {
      btnModeTomRiddle.addEventListener('click', () => this.setMode('tom_riddle'));
    }
    if (btnModeRegularQA) {
      btnModeRegularQA.addEventListener('click', () => this.setMode('regular_qa'));
    }

    // Persona selector dropdown
    if (personaSelect) {
      personaSelect.addEventListener('change', (e) => {
        this.setMode(e.target.value);
      });
    }

    // Candlelight toggle
    document.getElementById('btnCandle').addEventListener('click', () => {
      this.isCandleLit = !this.isCandleLit;
      const overlay = document.querySelector('.candle-overlay');
      overlay.classList.toggle('extinguished', !this.isCandleLit);
      document.getElementById('btnCandle').classList.toggle('active', this.isCandleLit);
    });

    // Memory Sanctum modal
    document.getElementById('btnOpenMemory').addEventListener('click', () => {
      this.memoryModal.open();
    });
    document.getElementById('btnCloseMemory').addEventListener('click', () => {
      this.memoryModal.close();
    });
    document.getElementById('btnPurgeMemories').addEventListener('click', () => {
      this.memoryModal.purgeAll();
    });

    // Gemini Modal
    document.getElementById('btnGeminiConfig').addEventListener('click', () => {
      this.geminiModal.classList.add('open');
    });
    document.getElementById('btnCloseGeminiModal').addEventListener('click', () => {
      this.geminiModal.classList.remove('open');
    });
    document.getElementById('btnSaveGeminiKey').addEventListener('click', () => {
      this.saveGeminiKey();
    });

    // Clarification actions
    const btnClarifySubmit = document.getElementById('btnClarifySubmit');
    if (btnClarifySubmit) {
      btnClarifySubmit.addEventListener('click', () => {
        const hint = this.clarificationInput.value.trim();
        if (hint.length > 0) {
          this.submitWritingTurn(hint);
          this.clarificationBanner.classList.remove('active');
          this.clarificationInput.value = '';
        }
      });
    }

    const btnClarifyDismiss = document.getElementById('btnClarifyDismiss');
    if (btnClarifyDismiss) {
      btnClarifyDismiss.addEventListener('click', () => {
        this.clarificationBanner.classList.remove('active');
        this.statusText.textContent = "The page has spoken.";
      });
    }

    // Settings / Personas modal
    const settingsModal = document.getElementById('settingsModalOverlay');
    const btnSettings = document.getElementById('btnSettingsMenu');
    const btnCloseSettings = document.getElementById('btnCloseSettingsModal');

    if (btnSettings && settingsModal) {
      btnSettings.addEventListener('click', () => settingsModal.classList.add('open'));
    }
    if (btnCloseSettings && settingsModal) {
      btnCloseSettings.addEventListener('click', () => settingsModal.classList.remove('open'));
    }

    document.querySelectorAll('.persona-card-option').forEach(card => {
      card.addEventListener('click', () => {
        const p = card.getAttribute('data-persona');
        if (p) {
          this.setMode(p);
          document.querySelectorAll('.persona-card-option').forEach(c => c.classList.toggle('active', c === card));
          if (settingsModal) settingsModal.classList.remove('open');
        }
      });
    });
  }

  async checkGeminiStatus() {
    try {
      const res = await fetch('/api/v1/config/gemini-status');
      const data = await res.json();
      if (data.configured) {
        if (this.geminiStatusLabel) this.geminiStatusLabel.textContent = "ACTIVE";
      } else {
        if (this.geminiStatusLabel) this.geminiStatusLabel.textContent = "OFFLINE";
      }
    } catch (e) {
      if (this.geminiStatusLabel) this.geminiStatusLabel.textContent = "OFFLINE";
    }
  }

  async saveGeminiKey() {
    const key = this.geminiApiKeyInput.value.trim();
    if (!key) {
      alert("Please enter a valid Gemini API Key.");
      return;
    }

    try {
      const res = await fetch('/api/v1/config/gemini-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key })
      });
      const data = await res.json();
      if (data.configured) {
        this.geminiKeyStatusMsg.style.display = 'block';
        this.geminiKeyStatusMsg.style.color = '#2d6a4f';
        this.geminiKeyStatusMsg.textContent = "✦ Gemini Activated! Tom Riddle is fully conscious.";
        this.checkGeminiStatus();
        setTimeout(() => {
          this.geminiModal.classList.remove('open');
          this.geminiKeyStatusMsg.style.display = 'none';
        }, 1200);
      } else {
        this.geminiKeyStatusMsg.style.display = 'block';
        this.geminiKeyStatusMsg.style.color = '#b91c1c';
        this.geminiKeyStatusMsg.textContent = "Could not activate key. Please verify.";
      }
    } catch (e) {
      alert("Error saving key.");
    }
  }

  async submitWritingTurn(explicitTextHint = null) {
    if (!this.canvasEngine.hasInk() && !explicitTextHint) {
      this.statusText.textContent = "The page is untouched. Draw strokes with the quill first.";
      return;
    }

    // Capture the data before vanishing
    const imageBase64 = this.canvasEngine.exportBase64PNG();
    const strokes = this.canvasEngine.exportStrokes();

    this.statusText.innerHTML = '<span class="quill-pulsing">✦ The diary drinks your ink...</span>';

    // 1. Vanish the user's written ink completely (Harry Potter style: ink sinks into parchment!)
    this.canvasEngine.vanishInk();

    try {
      const response = await fetch('/api/v1/process-turn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          page_number: this.currentPage,
          image_base64: imageBase64,
          stroke_data: strokes,
          user_text_hint: explicitTextHint,
          persona_id: this.activePersona
        })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Server returned ${response.status}: ${errorText.substring(0, 80)}`);
      }

      const data = await response.json();

      // Update confidence meter with recognized transcription if element exists
      if (this.confidenceMeter) {
        const confPct = Math.round((data.confidence || 0) * 100);
        const recognized = data.transcription ? `Ink: "${data.transcription}" (${confPct}%)` : `Ink: ${confPct}%`;
        this.confidenceMeter.textContent = recognized;
      }

      if (data.clarification_required) {
        // Show diegetic clarification prompt
        if (this.clarificationPromptText) this.clarificationPromptText.textContent = data.ai_reply;
        if (this.clarificationBanner) this.clarificationBanner.classList.add('active');
        if (this.statusText) this.statusText.textContent = `The diary seeks clarity: "${data.transcription || 'unclear ink'}"`;
        if (window.diaryAudio) window.diaryAudio.playPageTurn();
        return;
      }

      if (this.clarificationBanner) this.clarificationBanner.classList.remove('active');
      if (this.statusText) this.statusText.textContent = "The diary answers in a flowing hand...";

      // Record to chronicle immediately so full text is visible on the left page without delay
      this._recordToHistory(data.transcription || explicitTextHint, data.ai_reply, this.activePersona);

      // Clear previous calligraphy and animate the new response onto the clean page
      this.calligraphyRenderer.clear();
      this.calligraphyRenderer.animateText(data.ai_reply, () => {
        if (this.statusText) this.statusText.textContent = "The page has spoken.";
      });

    } catch (e) {
      console.error("Turn submission error:", e);
      this.statusText.textContent = `The binding wavers: ${e.message || "Connection interrupted. Try again."}`;
    }
  }

  _formatTime() {
    const d = new Date();
    let hours = d.getHours();
    const minutes = d.getMinutes().toString().padStart(2, '0');
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12;
    return `${hours}:${minutes} ${ampm}`;
  }

  _recordToHistory(userText, aiReply, personaId = null) {
    const persona = personaId || this.activePersona;
    const timeStr = this._formatTime();
    const aiAuthorLabel = persona === 'regular_qa' ? 'AI Assistant' : (persona === 'tom_riddle' ? 'Tom Riddle' : 'The Diary');

    // Add divider ornament if not empty
    if (this.historyContainer.children.length > 0) {
      const divider = document.createElement('div');
      divider.className = 'turn-divider-ornament';
      divider.innerHTML = '<span>❧◆❧</span>';
      this.historyContainer.appendChild(divider);
    }

    // 1. User entry block
    if (userText && userText.trim().length > 0) {
      const userTurn = document.createElement('div');
      userTurn.className = 'history-turn';
      userTurn.innerHTML = `
        <div class="turn-meta-header">
          <span class="author-label">You</span>
          <span class="meta-dot">•</span>
          <span class="timestamp-label">${timeStr}</span>
        </div>
        <div class="user-entry-record">${userText}</div>
      `;
      this.historyContainer.appendChild(userTurn);
    }

    // 2. AI response block
    if (aiReply && aiReply.trim().length > 0) {
      const aiTurn = document.createElement('div');
      aiTurn.className = 'history-turn';
      aiTurn.innerHTML = `
        <div class="turn-meta-header ai-meta">
          <span class="ai-sparkle-icon">✦</span>
          <span class="author-label">${aiAuthorLabel}</span>
          <span class="meta-dot">•</span>
          <span class="timestamp-label">${timeStr}</span>
        </div>
        <div class="ai-entry-record" data-persona="${persona}">${aiReply}</div>
      `;
      this.historyContainer.appendChild(aiTurn);
    }

    this.historyContainer.scrollTop = this.historyContainer.scrollHeight;
  }

  async _loadPageHistory() {
    try {
      const res = await fetch('/api/v1/pages');
      const pages = await res.json();
      if (pages && pages.length > 0) {
        this.historyContainer.innerHTML = '';
        pages.forEach(p => {
          this._recordToHistory(p.user_text, p.ai_reply, p.persona);
        });
        const lastPage = pages[pages.length - 1];
        if (lastPage && lastPage.ai_reply) {
          this.calligraphyRenderer.renderStaticText(lastPage.ai_reply);
        }
      }
    } catch (e) {}
  }

  turnPage(delta) {
    if (this.currentPage + delta < 1) return;
    this.currentPage += delta;
    document.getElementById('pageNumLeft').textContent = `Page ${this.currentPage * 2 - 1}`;
    document.getElementById('pageNumRight').textContent = `Page ${this.currentPage * 2}`;

    if (window.diaryAudio) {
      window.diaryAudio.playPageTurn();
    }

    this.canvasEngine.clear();
    this.calligraphyRenderer.clear();
    this.clarificationBanner.classList.remove('active');
    this.statusText.textContent = `Turned to Page ${this.currentPage * 2}. Write freely...`;
  }

  setMode(personaId) {
    this.activePersona = personaId;

    // Sync select dropdown
    const personaSelect = document.getElementById('personaSelect');
    if (personaSelect && personaSelect.value !== personaId) {
      personaSelect.value = personaId;
    }

    // Toggle mode button active styles
    const btnTom = document.getElementById('btnModeTomRiddle');
    const btnQA = document.getElementById('btnModeRegularQA');
    if (btnTom) btnTom.classList.toggle('active', personaId === 'tom_riddle');
    if (btnQA) btnQA.classList.toggle('active', personaId === 'regular_qa');

    // Sync settings modal options
    document.querySelectorAll('.persona-card-option').forEach(c => {
      c.classList.toggle('active', c.getAttribute('data-persona') === personaId);
    });

    // Update header on right page
    const inkStatusHeader = document.getElementById('inkStatusHeader');
    if (inkStatusHeader) {
      if (personaId === 'regular_qa') {
        inkStatusHeader.textContent = "INK: AI RESPONSE";
      } else if (personaId === 'tom_riddle') {
        inkStatusHeader.textContent = "INK: TOM RIDDLE'S RESPONSE";
      } else {
        inkStatusHeader.textContent = "INK: AI RESPONSE";
      }
    }

    // Descriptive status prompt
    if (personaId === 'regular_qa') {
      this.statusText.textContent = "Mode active: 💡 Regular Q&A Assistant (Normal Questions)";
    } else if (personaId === 'tom_riddle') {
      this.statusText.textContent = "Mode active: 🐍 Tom Riddle (The Enchanted Diary Spirit)";
    } else if (personaSelect && personaSelect.selectedIndex >= 0) {
      this.statusText.textContent = `Presence shifted to ${personaSelect.options[personaSelect.selectedIndex].text}`;
    }

    if (window.diaryAudio) {
      window.diaryAudio.playQuillStroke(0.05, 0.25);
    }
  }

  onMemoriesPurged() {
    this.historyContainer.innerHTML = '<div style="color: #7a5e3f; font-style: italic; padding: 20px;">The diary memories have been wiped clean.</div>';
    this.statusText.textContent = "All memories erased. The book is anew.";
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.app = new EnchantedInkApp();
});
