/**
 * MyYahooEmails Dashboard — JS helpers
 */

// ─── Workspace configuration ─────────────────────────────────────────────
var WORKSPACE_CONFIG = {
  'correspondence':  { perspective: 'legal', corpus: 'all',      defaultUrl: '/emails/' },
  'case-analysis':   { perspective: 'legal', corpus: 'personal', defaultUrl: '/' },
  'legal-strategy':  { perspective: 'legal', corpus: 'legal',    defaultUrl: '/procedures/' },
  'book':            { perspective: 'book',  corpus: 'personal', defaultUrl: '/narrative' }
};

// Page → workspace mapping (mirrors base.html _ws_map)
var PAGE_WS_MAP = {
  'emails': 'correspondence', 'contacts': 'correspondence',
  'dashboard': 'case-analysis', 'timeline': 'case-analysis',
  'analysis': 'case-analysis', 'contradictions': 'case-analysis',
  'manipulation': 'case-analysis', 'reports': 'case-analysis',
  'procedures': 'legal-strategy', 'invoices': 'legal-strategy',
  'narrative': 'book', 'chapters': 'book', 'themes': 'book',
  'quotes': 'book', 'pivotal': 'book'
};

function setCookie(name, value) {
  document.cookie = name + '=' + value + ';path=/;max-age=2592000;SameSite=Lax';
}

function getCookie(name) {
  var match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
  return match ? match[2] : null;
}

// ─── Workspace switching ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  var tabs = document.getElementById('ws-tabs');
  if (tabs) {
    tabs.addEventListener('click', function (e) {
      var tab = e.target.closest('.ws-tab');
      if (!tab) return;

      var ws = tab.dataset.workspace;
      var config = WORKSPACE_CONFIG[ws];
      if (!config) return;

      // Set all three cookies
      setCookie('workspace', ws);
      setCookie('perspective', config.perspective);
      setCookie('corpus', config.corpus);

      // Navigate to workspace default page
      window.location.href = tab.dataset.default || config.defaultUrl;
    });
  }

  // Sync workspace cookie to current page on load (handles direct URL navigation)
  var page = document.body.dataset.page || 'dashboard';
  var expectedWs = PAGE_WS_MAP[page] || getCookie('workspace') || 'case-analysis';
  var config = WORKSPACE_CONFIG[expectedWs];
  if (config) {
    setCookie('workspace', expectedWs);
    setCookie('perspective', config.perspective);
    // Only set corpus if no explicit corpus in URL (user may have filtered)
    if (!window.location.search.includes('corpus=')) {
      setCookie('corpus', config.corpus);
    }
  }
});

// ─── Text selection → save to quote bank (book workspace only) ──────────
document.addEventListener('mouseup', function () {
  var workspace = document.body.dataset.workspace;
  if (workspace !== 'book') return;

  var selection = window.getSelection();
  if (!selection || selection.toString().trim().length < 10) return;

  var emailBody = document.getElementById('email-body');
  if (!emailBody || !emailBody.contains(selection.anchorNode)) return;

  var selectedText = selection.toString().trim();

  // Remove previous floating button
  var existing = document.getElementById('quote-save-btn');
  if (existing) existing.remove();

  var btn = document.createElement('button');
  btn.id = 'quote-save-btn';
  btn.textContent = 'Save Quote';
  btn.className = 'quote-save-floating';

  var range = selection.getRangeAt(0);
  var rect = range.getBoundingClientRect();
  btn.style.position = 'fixed';
  btn.style.top = Math.max(10, rect.top - 44) + 'px';
  btn.style.left = rect.left + 'px';
  btn.style.zIndex = '9999';

  btn.addEventListener('click', function () {
    var quoteText = document.getElementById('quote-text');
    var quoteForm = document.getElementById('quote-form');
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
  var btn = document.getElementById('quote-save-btn');
  if (btn && e.target !== btn) btn.remove();
});

// ─── Notes tab switching ─────────────────────────────────────────────────
document.addEventListener('click', function (e) {
  if (!e.target.matches('.notes-tab')) return;
  var tabs = e.target.closest('.notes-tabs');
  if (!tabs) return;
  tabs.querySelectorAll('.notes-tab').forEach(function (t) {
    t.classList.remove('active');
  });
  e.target.classList.add('active');

  var target = e.target.dataset.target;
  var panel = e.target.closest('.notes-panel');
  if (!panel || !target) return;

  panel.querySelectorAll('.notes-content').forEach(function (c) {
    c.style.display = c.dataset.perspective === target ? 'block' : 'none';
  });

  // Update the hidden perspective field in the add-note form
  var perspInput = panel.querySelector('input[name="perspective"]');
  if (perspInput) perspInput.value = target;

  // Update category select options based on perspective
  var catSelect = panel.querySelector('select[name="category"]');
  if (catSelect && target) {
    updateCategoryOptions(catSelect, target);
  }
});

function updateCategoryOptions(select, perspective) {
  var legalCats = [
    ['evidence', 'Evidence'],
    ['lawyer_review', 'Lawyer Review'],
    ['contradiction_note', 'Contradiction Note'],
    ['court_relevance', 'Court Relevance'],
    ['strategy', 'Strategy'],
    ['general', 'General'],
  ];
  var bookCats = [
    ['narrative_context', 'Narrative Context'],
    ['character_insight', 'Character Insight'],
    ['chapter_note', 'Chapter Note'],
    ['emotional_significance', 'Emotional Significance'],
    ['quote_context', 'Quote Context'],
    ['general', 'General'],
  ];

  var cats = perspective === 'book' ? bookCats : legalCats;
  var current = select.value;
  while (select.options.length > 0) {
    select.remove(0);
  }
  cats.forEach(function (pair) {
    var opt = document.createElement('option');
    opt.value = pair[0];
    opt.textContent = pair[1];
    if (pair[0] === current) opt.selected = true;
    select.appendChild(opt);
  });
}

// ─── HTMX loading bar ────────────────────────────────────────────────────
document.addEventListener('htmx:beforeRequest', function () {
  var bar = document.getElementById('loading-bar');
  if (bar) bar.classList.add('htmx-request');
});

document.addEventListener('htmx:afterRequest', function () {
  var bar = document.getElementById('loading-bar');
  if (bar) bar.classList.remove('htmx-request');
});

// ─── Sidebar mobile toggle ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  var toggleBtn = document.getElementById('sidebar-toggle');
  var sidebar = document.querySelector('.sidebar');
  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener('click', function () {
      sidebar.classList.toggle('open');
    });
  }

  // Close sidebar when clicking outside on mobile
  document.addEventListener('click', function (e) {
    if (window.innerWidth > 768) return;
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
  while (modal.firstChild) modal.removeChild(modal.firstChild);
  var loadingDiv = document.createElement('div');
  loadingDiv.style.cssText = 'padding:2rem;text-align:center;color:var(--text-secondary)';
  loadingDiv.textContent = 'Loading\u2026';
  modal.appendChild(loadingDiv);
  overlay.classList.add('open');
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
    var detail = document.getElementById('detail-panel');
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
    var val = parseFloat(bar.dataset.value) || 0;
    bar.style.width = (val * 100).toFixed(1) + '%';
  });
  document.querySelectorAll('.progress-fill[data-value]').forEach(function (bar) {
    var val = parseFloat(bar.dataset.value) || 0;
    bar.style.width = val.toFixed(1) + '%';
  });
}
