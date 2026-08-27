import {request, setStatus} from './api.js';
import {currentProject} from './projects.js';

let activeRun = null;
let pollTimer = null;

export function currentRun() { return activeRun; }

export function configureRunPermissions(project) {
  const allowed = Boolean(project && ['owner', 'editor'].includes(project.role));
  document.querySelector('#question-form button[type="submit"]').disabled = !allowed;
  document.getElementById('research-question').disabled = !allowed;
  document.getElementById('review-depth').disabled = !allowed;
}

function renderRun(run) {
  activeRun = run;
  document.getElementById('run-panel').hidden = false;
  document.getElementById('run-question').textContent = run.question;
  document.getElementById('run-status').textContent = run.status.replaceAll('_', ' ');
  document.getElementById('run-progress').textContent = {
    queued: 'The review is queued for analysis.',
    running: 'Sci-Search is discovering, acquiring, and analyzing evidence.',
    completed: 'The review is complete. Inspect the evidence and download the research package.',
    failed: 'The review stopped after an error. You can retry it safely.',
    cancel_requested: 'Cancellation requested. The worker will stop at the next safe checkpoint.',
    cancelled: 'The review was cancelled.',
  }[run.status] || `Review status: ${run.status}`;
  document.getElementById('cancel-run').hidden = !['queued', 'running'].includes(run.status);
  document.getElementById('retry-run').hidden = run.status !== 'failed';
}

async function pollRun(delay = 1500) {
  if (!activeRun || !['queued', 'running', 'cancel_requested'].includes(activeRun.status)) return;
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    try {
      const project = currentProject();
      if (!project) return;
      renderRun(await request(`/api/v1/projects/${project.id}/runs/${activeRun.id}`));
      pollRun(Math.min(delay * 1.5, 10000));
    } catch (error) { setStatus(error.message, 'error'); }
  }, delay);
}

export async function startRun(question, reviewDepth) {
  const project = currentProject();
  if (!project) throw new Error('Create or select a project first');
  const run = await request(`/api/v1/projects/${project.id}/runs`, {
    method: 'POST',
    body: {question, review_depth: reviewDepth, idempotency_key: crypto.randomUUID()},
  });
  renderRun(run);
  setStatus('Review started. You can leave this page and return later.');
  pollRun();
}

export function initializeRuns() {
  document.getElementById('question-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await startRun(
        document.getElementById('research-question').value.trim(),
        document.getElementById('review-depth').value,
      );
    } catch (error) { setStatus(error.message, 'error'); }
  });
  document.getElementById('cancel-run').addEventListener('click', async () => {
    const project = currentProject();
    if (!project || !activeRun) return;
    renderRun(await request(`/api/v1/projects/${project.id}/runs/${activeRun.id}/cancel`, {method: 'POST'}));
  });
  document.getElementById('retry-run').addEventListener('click', async () => {
    const project = currentProject();
    if (!project || !activeRun) return;
    renderRun(await request(`/api/v1/projects/${project.id}/runs/${activeRun.id}/retry`, {method: 'POST'}));
    pollRun();
  });
}
