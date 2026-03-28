/**
 * MyYahooEmails Dashboard — JS helpers
 */

// ─── Perspective switching ────────────────────────────────────────────────
document.addEventListener('htmx:afterRequest', function (evt) {
  if (evt.detail.pathInfo && evt.detail.pathInfo.requestPath === '/set-perspective') {
    location.reload();
  }
});

// ─── Text selection → save to quote bank (book perspective only) ──────────
document.addEventListener('mouseup', function () {
  const perspective = document.body.dataset.perspective;
  if (perspective !== 'book') return;

  const selection = window.getSelection();
  if (!selection || selection.toString().trim().length < 10) return;

  const emailBody = document.getElementById('email-body');
  if (!emailBody || !emailBody.contains(selection.anchorNode)) return;

  const selectedText = selection.toString().trim();

  // Remove previous floating button
  const existing = document.getElementById('quote-save-btn');
  if (existing) existing.remove();

  const btn = document.createElement('button');
  btn.id = 'quote-save-btn';
  btn.textContent = 'Save Quote';
  btn.className = 'quote-save-floating';

  const range = selection.getRangeAt(0);
  const rect = range.getBoundingClientRect();
  btn.style.position = 'fixed';
  btn.style.top = Math.max(10, rect.top - 44) + 'px';
  btn.style.left = rect.left + 'px';
  btn.style.zIndex = '9999';

  btn.addEventListener('click', function () {
    const quoteText = document.getElementById('quote-text');
    const quoteForm = document.getElementById('quote-form');
    if (quoteText) quoteText.value = selectedText;
    if (quoteForm) {
      quoteForm.style.display = 'block';
      quoteForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    btn.remove();
    if (window.getSelection) window.getSelection().removeAllRanges();
  });

  document.body.appendChild(btn);
});

// ─── Hide quote-save button on click elsewhere ────────────────────────────
document.addEventListener('mousedown', function (e) {
  const btn = document.getElementById('quote-save-btn');
  if (btn && e.target !== btn) btn.remove();
});

// ─── Notes tab switching ─────────────────────────────────────────────────
document.addEventListener('click', function (e) {
  if (!e.target.matches('.notes-tab')) return;
  const tabs = e.target.closest('.notes-tabs');
  if (!tabs) return;
  tabs.querySelectorAll('.notes-tab').forEach(function (t) {
    t.classList.remove('active');
  });
  e.target.classList.add('active');

  const target = e.target.dataset.target;
  const panel = e.target.closest('.notes-panel');
  if (!panel || !target) return;

  panel.querySelectorAll('.notes-content').forEach(function (c) {
    c.style.display = c.dataset.perspective === target ? 'block' : 'none';
  });

  // Update the hidden perspective field in the add-note form
  const perspInput = panel.querySelector('input[name="perspective"]');
  if (perspInput) perspInput.value = target;

  // Update category select options based on perspective
  const catSelect = panel.querySelector('select[name="category"]');
  if (catSelect && target) {
    updateCategoryOptions(catSelect, target);
  }
});

function updateCategoryOptions(select, perspective) {
  const legalCats = [
    ['evidence', 'Evidence'],
    ['lawyer_review', 'Lawyer Review'],
    ['contradiction_note', 'Contradiction Note'],
    ['court_relevance', 'Court Relevance'],
    ['strategy', 'Strategy'],
    ['general', 'General'],
  ];
  const bookCats = [
    ['narrative_context', 'Narrative Context'],
    ['character_insight', 'Character Insight'],
    ['chapter_note', 'Chapter Note'],
    ['emotional_significance', 'Emotional Significance'],
    ['quote_context', 'Quote Context'],
    ['general', 'General'],
  ];

  const cats = perspective === 'book' ? bookCats : legalCats;
  const current = select.value;
  // Remove old options first
  while (select.options.length > 0) {
    select.remove(0);
  }
  cats.forEach(function (pair) {
    const opt = document.createElement('option');
    opt.value = pair[0];
    opt.textContent = pair[1];
    if (pair[0] === current) opt.selected = true;
    select.appendChild(opt);
  });
}

// ─── HTMX loading bar ────────────────────────────────────────────────────
document.addEventListener('htmx:beforeRequest', function () {
  const bar = document.getElementById('loading-bar');
  if (bar) bar.classList.add('htmx-request');
});

document.addEventListener('htmx:afterRequest', function () {
  const bar = document.getElementById('loading-bar');
  if (bar) bar.classList.remove('htmx-request');
});

// ─── Sidebar mobile toggle ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  const toggleBtn = document.getElementById('sidebar-toggle');
  const sidebar = document.querySelector('.sidebar');
  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener('click', function () {
      sidebar.classList.toggle('open');
    });
  }

  // Close sidebar when clicking outside on mobile
  document.addEventListener('click', function (e) {
    if (window.innerWidth > 900) return;
    if (sidebar && sidebar.classList.contains('open')) {
      if (!sidebar.contains(e.target) && e.target !== toggleBtn) {
        sidebar.classList.remove('open');
      }
    }
  });

  // Animate tone/progress bars on initial load
  animateToneBars();
});

// ─── Email modal (timeline "View email" links) ────────────────────────────
function openTimelineEmailModal(emailId) {
  var overlay = document.getElementById('email-modal-overlay');
  var modal = document.getElementById('email-modal');
  if (!overlay || !modal) return;
  // Show loading state using safe DOM methods (no innerHTML)
  while (modal.firstChild) modal.removeChild(modal.firstChild);
  var loadingDiv = document.createElement('div');
  loadingDiv.style.cssText = 'padding:2rem;text-align:center;color:var(--text-secondary)';
  loadingDiv.textContent = 'Loading\u2026';
  modal.appendChild(loadingDiv);
  overlay.classList.add('open');
  // Delegate actual content swap to HTMX (handles sanitisation + attribute processing)
  htmx.ajax('GET', '/emails/' + emailId, { target: '#email-modal', swap: 'innerHTML' });
}

function closeEmailModal() {
  var overlay = document.getElementById('email-modal-overlay');
  if (overlay) overlay.classList.remove('open');
}

// ─── Keyboard shortcuts ───────────────────────────────────────────────────
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    closeEmailModal();
    const detail = document.getElementById('detail-panel');
    if (detail) {
      while (detail.firstChild) {
        detail.removeChild(detail.firstChild);
      }
    }
  }
});

// ─── Tone bar animation ───────────────────────────────────────────────────
document.addEventListener('htmx:afterSwap', function () {
  animateToneBars();
});

function animateToneBars() {
  document.querySelectorAll('.tone-bar-fill[data-value]').forEach(function (bar) {
    const val = parseFloat(bar.dataset.value) || 0;
    bar.style.width = (val * 100).toFixed(1) + '%';
  });
  document.querySelectorAll('.progress-fill[data-value]').forEach(function (bar) {
    const val = parseFloat(bar.dataset.value) || 0;
    bar.style.width = val.toFixed(1) + '%';
  });
}
