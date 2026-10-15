import {request, setStatus, providerLabel} from './api.js';
import {currentProject, onProjectChange} from './projects.js';
import {openDashboard, refreshHistory, clearDashboard, beginNewSearch} from './history.js';
import {loadEvidence} from './evidence.js';
import {loadExports} from './exports.js';
import {loadValidation} from './validation.js';
import {renderChoices} from './question_choices.js';

let activeRun = null;
let pollTimer = null;
let questionBrief = null;
let interpretationVersion = 0;
let modelsLoaded = false;
let modelLoadVersion = 0;
let activityTimer = null;
const activeStatuses = ['queued', 'running', 'cancel_requested'];
const stageLabels = {queued: 'Waiting for a research worker', planning: 'Preparing the research', discovering: 'Finding sources', screening: 'Checking relevance', acquiring: 'Collecting and processing sources', coverage_search: 'Looking for missing evidence', analyzing: 'Analysing the evidence', complete: 'Research finished', failed: 'Research stopped', cancelled: 'Research cancelled'};
const counterLabels = {queries_planned: 'Search queries', records_retrieved: 'Search results', unique_candidates: 'Publications found', selected_candidates: 'Publications selected', full_texts_acquired: 'Full texts acquired', full_texts_included: 'Studies included', acquisition_attempts: 'Download attempts'};
function approvalStatus(message, kind = 'info') {
  const target = document.getElementById('approval-status');
  target.textContent = message;
  target.classList.toggle('error', kind === 'error');
}
function duration(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
function updateActivityTiming() {
  if (!activeRun) return;
  const progress = activeRun.progress || {};
  const started = Date.parse(progress.started_at || activeRun.created_at);
  const now = activeStatuses.includes(activeRun.status) ? Date.now() : Date.parse(activeRun.updated_at) || Date.now();
  const updated = Date.parse(progress.updated_at);
  let text = Number.isFinite(started) ? `Elapsed: ${duration(now - started)}.` : '';
  if (Number.isFinite(updated) && activeStatuses.includes(activeRun.status)) {
    text += ` Last activity update ${duration(Date.now() - updated)} ago.`;
    if (Date.now() - updated > 30000) text += ' Waiting for the current operation to report its outcome.';
  }
  document.getElementById('run-timing').textContent = text;
}
function renderActivity(run) {
  const progress = run.progress || {};
  document.getElementById('run-stage').textContent = stageLabels[progress.stage] || '';
  const activity = document.getElementById('run-activity');
  activity.replaceChildren();
  for (const event of (progress.events || []).slice(-12).reverse()) {
    const row = document.createElement('li');
    const time = new Date(event.at);
    row.textContent = `${Number.isNaN(time.getTime()) ? '' : time.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'}) + ' · '}${event.message}`;
    activity.append(row);
  }
  document.getElementById('run-activity-details').hidden = !activity.children.length;
  const counters = document.getElementById('run-counters'); counters.replaceChildren();
  for (const [key, label] of Object.entries(counterLabels)) {
    if (typeof progress.counters?.[key] !== 'number') continue;
    const item = document.createElement('span'); item.textContent = `${label}: ${progress.counters[key]}`;
    counters.append(item);
  }
  updateActivityTiming();
  clearInterval(activityTimer);
  if (activeStatuses.includes(run.status)) activityTimer = setInterval(updateActivityTiming, 1000);
}

const modelLabel = choice => choice ? `${providerLabel(choice.provider)} · ${choice.model}` : 'Not recorded';
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
    const preferredCodex = catalog.default.provider === 'codex' ? [JSON.stringify(catalog.default)] : [];
    const candidates = [previous, ...preferredCodex, JSON.stringify({provider: 'openai', model: 'gpt-6-sol'}), JSON.stringify(catalog.default), ...available.map(item => JSON.stringify({provider: item.provider, model: item.model})), ''];
    select.value = candidates.find(value => [...select.options].some(option => option.value === value && (!option.disabled || (value && JSON.parse(value).provider === 'codex')))) ?? '';
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


function showBrief(brief) {
  // The brief that starts the run: the chosen, adjusted version without its choices.
  const {options: _options, clarification_options: _answers, ...chosen} = brief;
  questionBrief = chosen;
  document.getElementById('brief-question').textContent = brief.interpreted_question;
  document.getElementById('brief-objective').textContent = brief.objective;
  document.getElementById('brief-method').textContent = brief.provider
    ? `Interpreted with ${modelLabel(brief)} — check the scope and assumptions before approving.`
    : 'Automatic research brief — AI interpretation is unavailable; check the scope before approving.';
  const details = document.getElementById('brief-details');
  details.replaceChildren();
  if (brief.data_research?.adapter === 'effis_reported_fires_v1') {
    document.getElementById('brief-method').textContent = 'Suggested approach: analyse official data. Calculations use a verified source adapter, not model-generated numbers.';
    const scope = brief.data_research;
    const controls = document.createElement('div'); controls.className = 'data-plan-controls';
    for (const [key, label, choices] of [
      ['route', 'Research approach', [['data', 'Data analysis — EFFIS pilot'], ['literature', 'Literature review']]],
      ['geography', 'Country scope', [['europe', 'Broader Europe — listed country set, including Türkiye and Cyprus'], ['eu27', 'EU-27 — fixed membership']]],
    ]) {
      const field = document.createElement('label'); field.textContent = label;
      const select = document.createElement('select'); select.setAttribute('aria-label', label);
      for (const [value, text] of choices) select.append(new Option(text, value));
      select.value = scope[key]; select.onchange = () => { scope[key] = select.value; };
      field.append(select); controls.append(field);
    }
    for (const [key, label] of [['start_year', 'First year'], ['end_year', 'Last year']]) {
      const field = document.createElement('label'); field.textContent = label;
      const input = document.createElement('input'); input.type = 'number'; input.min = '1980'; input.max = String(new Date().getFullYear()); input.required = true; input.value = scope[key]; input.setAttribute('aria-label', label);
      input.oninput = () => { scope[key] = Number(input.value); document.getElementById('approve-question').disabled = ![...controls.querySelectorAll('input')].every(i => i.checkValidity()) || scope.start_year > scope.end_year; };
      field.append(input); controls.append(field);
    }
    const note = document.createElement('p'); note.textContent = 'Measures: nationally reported forest-fire counts and burned area in km². This source edition ends in 2024. Missing years and country coverage will be shown; no causal explanation is inferred.';
    controls.append(note); details.append(controls);
  }
  const plan = brief.research_plan;
  const relationship = plan?.intent === 'relationship';
  const unresolvedRoles = relationship && (!plan.subject_terms?.length || !plan.driver_terms?.length);
  const needsClarification = brief.ambiguity === 'material' || unresolvedRoles;
  const outcomes = plan?.outcome_measure_terms?.length
    ? [`${plan.subject_terms.join(', ')} (${plan.outcome_measure_terms.join(', ')})`]
    : plan?.subject_terms;
  const specified = values => values == null ? ['Not resolved automatically — check your question']
    : values.length ? values : ['Not specified — no restriction'];
  if (!brief.data_research || brief.data_research.route === 'literature') for (const [label, values] of [
    ['Factor being studied', relationship ? (plan.driver_terms?.length ? plan.driver_terms : ['Not identified — clarify the question']) : []],
    [relationship ? 'Outcome being studied' : plan?.intent === 'comparison' ? 'What is being compared' : 'Topic being studied', outcomes],
    ['Relationship to investigate', relationship ? [plan.relationship_type === 'association'
      ? 'Whether the factor and outcome are associated. An association alone does not establish cause and effect.'
      : 'How the proposed factors relate to the outcome; their effects are not assumed.'] : []],
    ['People or study subjects', specified(plan?.population_terms)],
    ['Location', specified(plan?.geography_terms)],
    ['Time period', specified(plan?.time_terms)],
    ['Automatic evidence filters', brief.research_plan?.evidence_preferences?.map(value => value.replaceAll('_', ' '))],
    ['Excluded terms used in screening', brief.research_plan?.exclusion_terms],
    ['Evidence to look for', brief.evidence_scope], ['Assumptions to check', brief.assumptions],
    ['Exclusions', brief.exclusions], ['Clarification', brief.clarification_question ? [brief.clarification_question] : []],
  ]) {
    if (!values?.length) continue;
    const heading = document.createElement('h3'); heading.textContent = label;
    const list = document.createElement('ul');
    for (const value of values) { const item = document.createElement('li'); item.textContent = value; list.append(item); }
    details.append(heading, list);
  }
  document.getElementById('approve-question').disabled = needsClarification;
  approvalStatus(needsClarification
    ? (brief.clarification_question || 'Identify both the factor and the outcome in your question, then review it again.')
    : 'Ready to start. Approve this interpretation to begin the research.', needsClarification ? 'error' : 'info');
  document.getElementById('question-brief').hidden = false;
  setStatus(needsClarification
    ? 'Clarify the question above and review it again before starting.'
    : 'Review the interpretation below. Research starts only when you approve.');
}

// Asks for an interpretation; `extra` carries a steer or a clarification answer.
async function interpretQuestion(extra = {}) {
  const project = currentProject();
  if (!project) throw new Error('Create or select a project first');
  clearBrief();
  const version = interpretationVersion;
  setStatus(extra.steer ? 'Proposing other versions of your question…' : extra.clarification ? 'Using your answer…' : 'Interpreting your question…');
  const interpretation = await request(`/api/v1/projects/${project.id}/runs/interpret`, {
    method: 'POST', body: {question: document.getElementById('research-question').value.trim(), analysis_selection: selectedModel(), ...extra},
  });
  if (version !== interpretationVersion || currentProject()?.id !== project.id) return;
  const choices = document.getElementById('brief-choices');
  if (interpretation.data_research?.adapter === 'effis_reported_fires_v1') { choices.replaceChildren(); showBrief(interpretation); return; }
  renderChoices(interpretation, {
    container: choices,
    projectId: project.id,
    onBrief: brief => { if (version === interpretationVersion) showBrief(brief); },
    onInterpret: next => interpretQuestion(next).catch(error => setStatus(error.message, 'error')),
  });
}

export function currentRun() { return activeRun; }

export function clearRun() {
  clearBrief();
  clearTimeout(pollTimer);
  clearInterval(activityTimer);
  activeRun = null;
  document.getElementById('research').hidden = false;
  document.getElementById('run-connection').textContent = '';
  document.getElementById('run-panel').hidden = true;
  document.getElementById('research-question').value = '';
  loadEvidence(null); loadValidation(null); loadExports(null);
}

export function configureRunPermissions(project) {
  const allowed = !document.getElementById('workspace-preview-notice') &&
    Boolean(project && ['owner', 'editor'].includes(project.role));
  const model = document.getElementById('analysis-model');
  const unavailable = Boolean(model.selectedOptions[0]?.disabled);
  document.querySelector('#question-form button[type="submit"]').disabled = !allowed || !modelsLoaded || unavailable;
  if (modelsLoaded && unavailable && selectedModel()?.provider === 'codex') {
    document.getElementById('analysis-model-help').textContent = 'Codex is unavailable. Sign in with ChatGPT using codex login, then refresh, or explicitly choose another provider.';
  }
  document.getElementById('analysis-model').disabled = !allowed || !modelsLoaded;
  document.getElementById('research-question').disabled = !allowed;
  document.getElementById('review-depth').disabled = !allowed;
}

function renderRun(run, loadDashboard = true) {
  const previousStatus = activeRun?.status;
  const previousId = activeRun?.id;
  activeRun = run;
  document.getElementById('research').hidden = true;
  if (run.status !== 'completed') {
    document.body.classList.remove('dashboard-open', 'compose-open');
    document.getElementById('dashboard-panel').hidden = true;
  }
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
  document.getElementById('run-status').textContent = run.status === 'completed' ? 'Processing complete' : run.status.replaceAll('_', ' ');
  document.getElementById('run-progress').textContent = (run.status === 'running' && run.progress?.message) || {
    queued: 'The review is queued for analysis.',
    running: 'Sci-Search is discovering, acquiring, and analyzing evidence.',
    completed: 'Processing is complete. Check the evidence assessment to see whether the findings answer your question.',
    failed: 'The review stopped after an error. You can retry it safely.',
    cancel_requested: 'Cancellation requested. The worker will stop at the next safe checkpoint.',
    cancelled: 'The review was cancelled.',
  }[run.status] || `Review status: ${run.status}`;
  renderActivity(run);
  document.getElementById('cancel-run').hidden = !['queued', 'running'].includes(run.status);
  document.getElementById('retry-run').hidden = run.status !== 'failed';
}

async function pollRun(delay = 1500) {
  if (!activeRun || !['queued', 'running', 'cancel_requested'].includes(activeRun.status)) return;
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    const project = currentProject();
    const runId = activeRun?.id;
    if (!project || !runId) return;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const run = await request(`/api/v1/projects/${project.id}/runs/${runId}`, {signal: controller.signal});
      if (currentProject()?.id !== project.id || activeRun?.id !== runId) return;
      renderRun(run);
      document.getElementById('run-connection').textContent = 'Status connection active.';
      pollRun(2500);
    } catch (error) {
      if (currentProject()?.id !== project.id || activeRun?.id !== runId) return;
      document.getElementById('run-connection').textContent = 'The latest status could not be retrieved. Retrying automatically; the research may still be running.';
      pollRun(5000);
    } finally { clearTimeout(timeout); }
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
  const run = await request(`/api/v1/projects/${project.id}/runs`, {
    method: 'POST',
    body: {question, question_brief: brief, review_depth: reviewDepth, analysis_selection: selectedModel(), idempotency_key: crypto.randomUUID()},
  });
  if (currentProject()?.id !== project.id) return;
  clearDashboard();
  renderRun(run);
  document.getElementById('run-panel').scrollIntoView({block: 'start', behavior: 'smooth'});
  document.getElementById('run-panel').focus({preventScroll: true});
  refreshHistory();
  setStatus(document.getElementById('local-research-notice')
    ? 'Review started. Your search is saved; real research can take several minutes.'
    : 'Review started. Keep this tab open to follow progress.');
  pollRun();
}

export function initializeRuns() {
  const newSearch = () => {
    const project = currentProject();
    if (!project) return;
    beginNewSearch(project.id);
    document.getElementById('research').scrollIntoView({block: 'start'});
    document.getElementById('research-question').focus();
  };
  document.getElementById('new-search').onclick = newSearch;
  document.getElementById('run-new-search').onclick = newSearch;
  window.addEventListener('workspace-logout', clearRun);
  onProjectChange((project) => {
    clearBrief();
    loadModels(project);
    clearTimeout(pollTimer);
    clearInterval(activityTimer);
    activeRun = null;
    document.getElementById('research').hidden = false;
    document.getElementById('run-panel').hidden = true;
  });
  document.getElementById('research-question').addEventListener('input', clearBrief);
  document.getElementById('analysis-model').addEventListener('change', () => {
    clearBrief();
    document.getElementById('analysis-model-help').textContent = 'Used for question interpretation and research analysis. Your choice is saved with this review.';
    configureRunPermissions(currentProject());
  });
  document.getElementById('question-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await interpretQuestion(); } catch (error) { setStatus(error.message, 'error'); }
  });
  document.getElementById('approve-question').addEventListener('click', async () => {
    if (!questionBrief) {
      approvalStatus('The interpretation has expired. Click Review question again before starting.', 'error');
      return;
    }
    const button = document.getElementById('approve-question');
    button.disabled = true;
    button.textContent = 'Starting research…';
    approvalStatus('Submitting your research. Waiting for the server to confirm the start…');
    const brief = questionBrief;
    try {
      await startRun(brief.original_question, document.getElementById('review-depth').value, brief);
      if (questionBrief === brief) clearBrief();
    } catch (error) { approvalStatus(error.message, 'error'); setStatus(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = 'Approve and start review'; }
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
