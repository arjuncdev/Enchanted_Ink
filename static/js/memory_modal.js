/**
 * Memory Sanctum Controller
 * Handles user inspection, deletion, and privacy purging of long-term episodic memories.
 */
class MemorySanctumModal {
  constructor(overlayElement, listContainer) {
    this.overlay = overlayElement;
    this.listContainer = listContainer;
  }

  open() {
    this.overlay.classList.add('open');
    this.loadMemories();
  }

  close() {
    this.overlay.classList.remove('open');
  }

  async loadMemories() {
    this.listContainer.innerHTML = '<div style="color: #7a5e3f; font-style: italic; padding: 20px; text-align: center;">Consulting the diary memory bank...</div>';
    try {
      const res = await fetch('/api/v1/memories');
      const memories = await res.json();

      if (memories.length === 0) {
        this.listContainer.innerHTML = '<div style="color: #7a5e3f; font-style: italic; padding: 30px; text-align: center;">No memories slumber in the pages yet. Inscribe your thoughts, and the book shall remember.</div>';
        return;
      }

      this.listContainer.innerHTML = '';
      memories.forEach(mem => {
        const card = document.createElement('div');
        card.className = 'memory-card';
        card.innerHTML = `
          <div class="memory-info">
            <div class="memory-summary">${mem.summary}</div>
            <div class="memory-decay">
              <span class="decay-badge">Salience: ${mem.salience_pct}%</span>
              <span>Inscribed: ${mem.created_at_iso}</span>
            </div>
          </div>
          <button class="btn-del" title="Erase this memory from the diary" onclick="window.memoryModal.deleteMemory(${mem.id})">Erase</button>
        `;
        this.listContainer.appendChild(card);
      });
    } catch (e) {
      this.listContainer.innerHTML = '<div style="color: #a84646; padding: 20px;">Could not retrieve memories from backend.</div>';
    }
  }

  async deleteMemory(id) {
    if (!confirm('Erase this specific memory forever from the diary?')) return;
    try {
      await fetch(`/api/v1/memories/${id}`, { method: 'DELETE' });
      this.loadMemories();
    } catch (e) {
      alert('Failed to erase memory.');
    }
  }

  async purgeAll() {
    if (!confirm('WARNING: Purge all episodic memories and pages from the diary? This cannot be undone.')) return;
    try {
      await fetch('/api/v1/memories/purge', { method: 'POST' });
      this.loadMemories();
      if (window.app) window.app.onMemoriesPurged();
    } catch (e) {
      alert('Failed to purge memories.');
    }
  }
}

window.MemorySanctumModal = MemorySanctumModal;
