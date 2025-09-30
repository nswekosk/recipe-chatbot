/* global __FILES__ */
(function () {
  const files = window.__FILES__ || [];
  let currentIndex = 0;
  let currentFilename = null;
  let currentVerdict = null; // 'up' | 'down' | null

  const elInitial = document.getElementById('initial_query');
  const elAssistant = document.getElementById('assistant_output');
  const elFeedback = document.getElementById('feedback');
  const elIndex = document.getElementById('meta-index');
  const elTotal = document.getElementById('meta-total');
  const elVerdictPill = document.getElementById('verdict-pill');

  function normalizeMarkdown(md) {
    if (!md) return '';
    let text = String(md)
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n');
    // Trim trailing spaces on each line
    text = text.split('\n').map((line) => line.replace(/\s+$/g, '')).join('\n');
    // Collapse 3+ blank lines to a single blank line
    text = text.replace(/\n{3,}/g, '\n\n');
    return text.trim();
  }

  function setVerdict(v) {
    currentVerdict = v;
    elVerdictPill.className = 'pill ' + (v === 'up' ? 'up' : v === 'down' ? 'down' : '');
    elVerdictPill.textContent = v === 'up' ? 'Thumbs Up' : v === 'down' ? 'Thumbs Down' : 'No verdict';
  }

  async function load(index) {
    if (!files.length) return;
    currentIndex = Math.max(0, Math.min(index, files.length - 1));
    const resp = await fetch(`/api/trace/${currentIndex}`);
    if (!resp.ok) return;
    const data = await resp.json();
    currentFilename = data.filename;
    elInitial.textContent = data.initial_query || '';
    const md = normalizeMarkdown(data.assistant_output || '');
    const unsafeHtml = (window.marked ? window.marked.parse(md) : md);
    const safeHtml = window.DOMPurify ? window.DOMPurify.sanitize(unsafeHtml) : unsafeHtml;
    elAssistant.innerHTML = safeHtml;
    elIndex.textContent = String(data.index + 1);
    elTotal.textContent = String(data.total);
    const existing = data.existing_label || null;
    if (existing) {
      elFeedback.value = existing.feedback || '';
      setVerdict(existing.verdict || null);
    } else {
      elFeedback.value = '';
      setVerdict(null);
    }
  }

  async function refreshFeedbacks() {
    const resp = await fetch('/api/labels');
    if (!resp.ok) return;
    const { labels } = await resp.json();
    const tbody = document.querySelector('#feedbacks-table tbody');
    tbody.innerHTML = '';
    (labels || []).forEach((row) => {
      const tr = document.createElement('tr');
      const verdictCell = document.createElement('td');
      const pill = document.createElement('span');
      pill.className = 'pill ' + (row.verdict === 'up' ? 'up' : 'down');
      pill.textContent = row.verdict === 'up' ? 'Up' : 'Down';
      verdictCell.appendChild(pill);
      tr.appendChild(td(row.filename));
      tr.appendChild(verdictCell);
      tr.appendChild(td(row.feedback));
      tr.appendChild(td(row.saved_at));
      tbody.appendChild(tr);
    });
  }

  function td(text) {
    const el = document.createElement('td');
    el.textContent = text || '';
    return el;
  }

  async function save() {
    if (!currentFilename) return;
    const body = {
      filename: currentFilename,
      index: currentIndex,
      feedback: elFeedback.value || '',
      verdict: currentVerdict,
    };
    const resp = await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      await refreshFeedbacks();
    }
  }

  async function exportCSV() {
    // Trigger a download by navigating to export endpoint
    window.location.href = '/api/export';
  }

  // Buttons
  document.getElementById('btn-prev').addEventListener('click', () => {
    load(currentIndex - 1);
  });
  document.getElementById('btn-next').addEventListener('click', () => {
    load(currentIndex + 1);
  });
  document.getElementById('btn-save').addEventListener('click', save);
  document.getElementById('btn-export').addEventListener('click', exportCSV);
  document.getElementById('thumb-up').addEventListener('click', () => setVerdict('up'));
  document.getElementById('thumb-down').addEventListener('click', () => setVerdict('down'));

  // Hotkeys
  window.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      load(currentIndex - 1);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      load(currentIndex + 1);
    } else if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
      e.preventDefault();
      save();
    }
  });

  // Init
  load(0).then(refreshFeedbacks);
})();


