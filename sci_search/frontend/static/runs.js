import {request, setStatus} from './api.js';
import {currentProject, onProjectChange} from './projects.js';
import {openDashboard, refreshHistory, clearDashboard, beginNewSearch} from './history.js';
import {loadEvidence} from './evidence.js';
import {loadExports} from './exports.js';
import {loadValidation} from './validation.js';

let activeRun = null;
let pollTimer = null;
let questionBrief = null;
let interpretationVersion = 0;
let modelsLoaded = false;
let modelLoadVersion = 0;

const modelLabel = choice => choice ? `${choice.provider === 'openai' ? 'OpenAI' : 'Mistral'} · ${choice.model}` : 'Not recorded';
function selectedModel() {
  const value = document.getElementById('analysis-model').value;
  return value ? JSON.parse(value) : null;
}
async function loadModels(project) {
  const version = ++modelLoadVersion;
  modelsLoaded = false;
  const select = document.getElementById('analysis-model');
  const previous = select.value;
  select.replaceChildren(new Option('Loading models…', ''));
  configureRunPermissions(project);
  if (!project) { select.replaceChildren(new Option('Select a project first', '')); return; }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const catalog = await request(`/api/v1/projects/${project.id}/runs/models`, {signal: controller.signal});
    if (version !== modelLoadVersion || currentProject()?.id !== project.id) return;
    select.replaceChildren();
    const available = catalog.items.filter(item => item.available);
    if (!available.length) {
      select.append(new Option(`Server default · ${modelLabel(catalog.default)} (AI unavailable)`, ''));
    }
    for (const item of catalog.items) {
      const choice = {provider: item.provider, model: item.model};
      const option = new Option(modelLabel(choice) + (item.available ? '' : ' (not configured)'), JSON.stringify(choice));
      option.disabled = !item.available;
      select.append(option);
    }
    const candidates = [previous, JSON.stringify(catalog.default), ...available.map(item => JSON.stringify({provider: item.provider, model: item.model})), ''];
    select.value = candidates.find(value => [...select.options].some(option => option.value === value && !option.disabled)) ?? '';
    document.getElementById('analysis-model-help').textContent = available.length
      ? 'Used for question interpretation and research analysis. Your choice is saved with this review.'
      : 'No AI provider is configured. Research will use extractive analysis.';
    modelsLoaded = true;
    configureRunPermissions(project);
  } catch (error) {
    if (version !== modelLoadVersion) return;
    select.replaceChildren(new Option('Models could not be loaded', ''));
    setStatus(error.name === 'AbortError' ? 'Loading models timed out. Refresh the page to retry.' : error.message, 'error');
  } finally { clearTimeout(timeout); }
}

function clearBrief() {
  interpretationVersion += 1;
  questionBrief = null;
  document.getElementById("question-brief").hidden = true;
}


export function currentRun() { return activeRun; }

export function clearRun() {
  clearBrief();
  clearTimeout(pollTimer);
  activeRun = null;
  document.getElementById('run-panel').hidden = true;
  document.getElementById('research-question').value = '';
  loadEvidence(null); loadValidation(null); loadExports(null);
}

export function configureRunPermissions(project) {
  const allowed = !document.getElementById('workspace-preview-notice') &&
    Boolean(project && ['owner', 'editor'].includes(project.role));
  document.querySelector('#question-form button[type="submit"]').disabled = !allowed || !modelsLoaded;
  document.getElementById('analysis-model').disabled = !allowed || !modelsLoaded;
  document.getElementById('research-question').disabled = !allowed;
  document.getElementById('review-depth').disabled = !allowed;
}

function renderRun(run, loadDashboard = true) {
  const previousStatus = activeRun?.status;
  const previousId = activeRun?.id;
  activeRun = run;
  if (run.id !== previousId || run.status !== previousStatus) {
    if (run.status !== 'completed') {
      loadEvidence(null);
      loadExports(null);
      loadValidation(null);
    }
  }
  if (run.status === 'completed' && (previousStatus !== 'completed' || previousId !== run.id)) {
    const project = currentProject();
    loadEvidence(project);
    loadExports(project);
    loadValidation(project);
    if (loadDashboard) { openDashboard(project.id, run.id); refreshHistory(); }
  }
  document.getElementById('evidence').hidden = false;
  document.getElementById('validation').hidden = run.status !== 'completed';
  document.getElementById('exports').hidden = run.status !== 'completed';
  document.getElementById('run-panel').hidden = false;
  document.getElementById('run-question').textContent = run.question;
  document.getElementById('run-model').textContent = `Selected model: ${modelLabel(run.analysis_selection)}`;
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
      const runId = activeRun.id;
      const run = await request(`/api/v1/projects/${project.id}/runs/${runId}`);
      if (currentProject()?.id !== project.id || activeRun?.id !== runId) return;
      renderRun(run);
      pollRun(Math.min(delay * 1.5, 10000));
    } catch (error) { setStatus(error.message, 'error'); }
  }, delay);
}

export function selectRun(run, {loadDashboard = false} = {}) {
  clearTimeout(pollTimer);
  renderRun(run, loadDashboard);
  pollRun();
}

export async function startRun(question, reviewDepth, brief = null) {
  const project = currentProject();
  if (!project) throw new Error('Create or select a project first');
  document.body.classList.remove('compose-open');
  clearDashboard();
  loadEvidence(null);
  loadExports(null);
  loadValidation(null);
  const run = await request(`/api/v1/projects/${project.id}/runs`, {
    method: 'POST',
    body: {question, question_brief: brief, review_depth: reviewDepth, analysis_selection: selectedModel(), idempotency_key: crypto.randomUUID()},
  });
  if (currentProject()?.id !== project.id) return;
  renderRun(run);
  refreshHistory();
  setStatus(document.getElementById('local-research-notice')
    ? 'Review started. Your search is saved; real research can take several minutes.'
    : 'Review started. Keep this tab open to follow progress.');
  pollRun();
}

export function initializeRuns() {
  document.getElementById('new-search').onclick = () => {
    const project = currentProject();
    if (!project) return;
    beginNewSearch(project.id);
    document.getElementById('research').scrollIntoView({block: 'start'});
    document.getElementById('research-question').focus();
  };
  window.addEventListener('workspace-logout', () => { clearBrief(); clearTimeout(pollTimer); activeRun = null; });
  onProjectChange((project) => {
    clearBrief();
    loadModels(project);
    clearTimeout(pollTimer);
    activeRun = null;
    document.getElementById('run-panel').hidden = true;
  });
  document.getElementById('research-question').addEventListener('input', clearBrief);
  document.getElementById('analysis-model').addEventListener('change', clearBrief);
  document.getElementById('question-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const project = currentProject();
      if (!project) throw new Error('Create or select a project first');
      clearBrief();
      const version = interpretationVersion;
      setStatus('Interpreting your question…');
      const brief = await request(`/api/v1/projects/${project.id}/runs/interpret`, {
        method: 'POST', body: {question: document.getElementById('research-question').value.trim(), analysis_selection: selectedModel()},
      });
      if (version !== interpretationVersion || currentProject()?.id !== project.id) return;
      questionBrief = brief;
      document.getElementById('brief-question').textContent = brief.interpreted_question;
      document.getElementById('brief-objective').textContent = brief.objective;
      document.getElementById('brief-method').textContent = brief.provider
        ? `Interpreted with ${modelLabel(brief)} — check the scope and assumptions before approving.`
        : 'Automatic research brief — AI interpretation is unavailable; check the scope before approving.';
      const details = document.getElementById('brief-details');
      details.replaceChildren();
      for (const [label, values] of [
        ['Evidence scope', brief.evidence_scope], ['Assumptions', brief.assumptions],
        ['Exclusions', brief.exclusions], ['Clarification', brief.clarification_question ? [brief.clarification_question] : []],
      ]) {
        if (!values?.length) continue;
        const heading = document.createElement('h3'); heading.textContent = label;
        const list = document.createElement('ul');
        for (const value of values) { const item = document.createElement('li'); item.textContent = value; list.append(item); }
        details.append(heading, list);
      }
      document.getElementById('approve-question').disabled = false;
      document.getElementById('question-brief').hidden = false;
      setStatus('Review the interpretation below. Research starts only when you approve.');
    } catch (error) { setStatus(error.message, 'error'); }
  });
  document.getElementById('approve-question').addEventListener('click', async () => {
    if (!questionBrief) return;
    const button = document.getElementById('approve-question');
    button.disabled = true;
    const brief = questionBrief;
    try {
      await startRun(brief.original_question, document.getElementById('review-depth').value, brief);
      if (questionBrief === brief) clearBrief();
    } catch (error) { setStatus(error.message, 'error'); }
    finally { button.disabled = false; }
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
