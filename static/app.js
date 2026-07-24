// Agent Run Panel: consumes the /api/run-pipeline SSE stream live. This is
// the one screen that genuinely needs JavaScript — a static page can't
// reflect a live, server-sent stream of per-agent status updates.

function setStatus(card, state, text) {
  const pill = card.querySelector('[data-role="status-pill"]');
  pill.className = 'status-pill status-' + state;
  pill.textContent = text;
}

function setDownloadsHidden(card, hidden) {
  card.querySelectorAll('[data-role="download"]').forEach((el) => { el.hidden = hidden; });
}

function handleEvent(evt) {
  if (evt.agent_name === '__pipeline__') return;
  const card = document.querySelector('.agent-card[data-agent="' + CSS.escape(evt.agent_name) + '"]');
  if (!card) return;
  if (evt.status === 'running') {
    setStatus(card, 'running', 'Running…');
  } else if (evt.status === 'done') {
    setStatus(card, 'done', 'Done');
    setDownloadsHidden(card, false);
  }
}

async function runPipeline() {
  const btn = document.getElementById('run-pipeline-btn');
  const statusLine = document.getElementById('pipeline-status-line');
  btn.disabled = true;
  statusLine.textContent = 'Running pipeline…';

  document.querySelectorAll('.agent-card').forEach((card) => {
    setStatus(card, 'pending', 'Pending');
    setDownloadsHidden(card, true);
  });

  try {
    const resp = await fetch('/api/run-pipeline', { method: 'POST' });
    if (!resp.ok || !resp.body) {
      throw new Error('HTTP ' + resp.status);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        try {
          handleEvent(JSON.parse(line.slice(5).trim()));
        } catch (e) {
          // ignore malformed chunks
        }
      }
    }
    statusLine.textContent = 'Pipeline finished — see Dashboard and Insights & Recommendations for results.';
  } catch (err) {
    statusLine.textContent = 'Pipeline failed to run: ' + err;
  } finally {
    btn.disabled = false;
  }
}

async function resetPipeline() {
  const confirmed = confirm(
    'This deletes every generated agent output file and both Excel ' +
    'reports (output/agents/ and output/reports/). Source data in ' +
    'input/ is untouched. Continue?'
  );
  if (!confirmed) return;

  const btn = document.getElementById('reset-pipeline-btn');
  const runBtn = document.getElementById('run-pipeline-btn');
  const statusLine = document.getElementById('pipeline-status-line');
  btn.disabled = true;
  runBtn.disabled = true;
  statusLine.textContent = 'Clearing output…';

  try {
    const resp = await fetch('/api/reset-pipeline', { method: 'POST' });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    document.querySelectorAll('.agent-card').forEach((card) => {
      setStatus(card, 'pending', 'Pending');
      setDownloadsHidden(card, true);
    });
    statusLine.textContent = 'Output cleared — run the pipeline to regenerate results.';
  } catch (err) {
    statusLine.textContent = 'Reset failed: ' + err;
  } finally {
    btn.disabled = false;
    runBtn.disabled = false;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('run-pipeline-btn');
  if (btn) btn.addEventListener('click', runPipeline);
  const resetBtn = document.getElementById('reset-pipeline-btn');
  if (resetBtn) resetBtn.addEventListener('click', resetPipeline);
});
