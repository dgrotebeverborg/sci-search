import {request, setStatus, currentUserId} from './api.js';
import {currentProject, onProjectChange, loadProjects} from './projects.js';
import {renderDashboard, element} from './dashboard.js';
import {selectRun, clearRun} from './runs.js';

let generation = 0, historyGeneration = 0, controller = null, timer = null;
let selectedRun = null, selectedRevision = null, cursor = null;
let historyProject = null;
export function selectedDashboard() { return {runId: selectedRun, revision: selectedRevision}; }
function path(projectId, runId) { return `/api/v1/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}`; }
function updateUrl(projectId, runId, revision, replace = false) {
  const url = new URL('/app', window.location.origin);
  url.searchParams.set('project', projectId);
  if (runId) url.searchParams.set('run', runId);
  if (revision != null) url.searchParams.set('revision', revision);
  if (url.href !== window.location.href) window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
}
export function clearDashboard() {
  clearRun();
  document.body.classList.remove('dashboard-open', 'compose-open');
  generation++; controller?.abort(); clearTimeout(timer); selectedRun = null; selectedRevision = null;
  document.getElementById('dashboard-panel').hidden = true;
  document.getElementById('dashboard-blocks').replaceChildren();
  for (const id of ['evidence', 'validation', 'exports']) document.getElementById(id).hidden = true;
}
export function beginNewSearch(projectId) {
  clearDashboard();
  updateUrl(projectId, null, null);
}
function statusMessage(snapshot, historical) {
  const status = snapshot.rebuild_status;
  if (historical) return `Viewing historical revision ${snapshot.revision}.`;
  if (['queued', 'running'].includes(status)) return `Updating dashboard… Showing completed revision ${snapshot.revision} while your saved decisions are applied.`;
  if (status === 'failed') return `Dashboard update failed. Revision ${snapshot.revision} remains available. Retry the update below.`;
  return ''; 
}
export async function openDashboard(projectId, runId, revision = null, {navigate = true, preserve = false} = {}) {
  const token = ++generation; controller?.abort(); controller = new AbortController(); clearTimeout(timer);
  selectedRun = runId; selectedRevision = revision;
  if (navigate) updateUrl(projectId, runId, revision);
  if (!preserve) { document.getElementById('dashboard-panel').hidden = true; document.getElementById('dashboard-blocks').replaceChildren(); }
  try {
    const snapshot = await request(`${path(projectId, runId)}/dashboard${revision != null ? `?revision=${revision}` : ''}`, {signal: controller.signal});
    if (token !== generation || currentProject()?.id !== projectId) return;
    selectRun({id: runId, project_id: projectId, question: snapshot.question, status: 'completed'});
    for (const id of ['evidence', 'validation', 'exports']) document.getElementById(id).hidden = true;
    const historical = revision != null && snapshot.current_revision !== revision;
    renderDashboard(snapshot, {projectId, role: currentProject()?.role, historical, onEvidenceReview: async evidenceId => {
      if (token !== generation) return;
      await openDashboard(projectId, runId, revision, {navigate: false, preserve: true});
      if (selectedRun === runId) { const detail = document.getElementById(`evidence-${encodeURIComponent(evidenceId)}`); if (detail) detail.open = true; }
    }, onFeedback: async () => {
      if (token !== generation) return;
      document.getElementById('dashboard-status').textContent = `Updating dashboard… Your decision is saved. Showing revision ${snapshot.revision}.`;
      document.querySelectorAll('.article-feedback button').forEach(button => { button.disabled = true; });
      timer = setTimeout(() => openDashboard(projectId, runId, null, {navigate: false, preserve: true}), 1000);
    }});
    document.getElementById('dashboard-status').textContent = statusMessage(snapshot, historical);
    const retry = document.getElementById('retry-dashboard'); retry.hidden = snapshot.rebuild_status !== 'failed' || historical;
    retry.disabled = !['owner', 'reviewer'].includes(snapshot.role || currentProject()?.role);
    retry.onclick = async () => {
      try { await request(`${path(projectId, runId)}/rebuild/retry`, {method: 'POST'}); if (token === generation) openDashboard(projectId, runId, null, {navigate: false, preserve: true}); }
      catch (error) { if (token === generation) setStatus(error.message, 'error'); }
    };
    const current = document.getElementById('current-dashboard'); current.hidden = !historical;
    current.onclick = () => openDashboard(projectId, runId);
    const revisions = document.getElementById('dashboard-revisions'); revisions.replaceChildren();
    const initial = element('option', `Revision ${snapshot.revision}`); initial.value = snapshot.revision; revisions.append(initial);
    request(`${path(projectId, runId)}/revisions`, {signal: controller.signal}).then(data => {
      if (token !== generation) return;
      revisions.replaceChildren();
      for (const item of data.items || []) { const option = element('option', `Revision ${item.revision}${item.created_at ? ' · ' + new Date(item.created_at).toLocaleString() : ''}`); option.value = item.revision; revisions.append(option); }
      revisions.value = String(snapshot.revision);
    }).catch(error => { if (error.name !== 'AbortError' && token === generation) setStatus(error.message, 'error'); });
    revisions.onchange = () => openDashboard(projectId, runId, Number(revisions.value));
    if (['queued', 'running'].includes(snapshot.rebuild_status) && revision == null) timer = setTimeout(() => openDashboard(projectId, runId, null, {navigate: false, preserve: true}), 1500);
    for (const link of document.querySelectorAll('#research-history a')) link.setAttribute('aria-current', link.dataset.runId === runId ? 'page' : 'false');
  } catch (error) {
    if (error.name === 'AbortError' || token !== generation) return;
    if (error.status === 404) {
      setStatus('This run has no saved dashboard yet. Its research status remains in the history.');
      try {
        const run = await request(path(projectId, runId), {signal: controller.signal});
        if (token === generation && run.id && run.status) selectRun(run);
      } catch (runError) { if (token === generation && runError.name !== 'AbortError') setStatus(runError.message, 'error'); }
    } else setStatus(error.message, 'error');
  }
}
function hiddenHistoryKey(projectId) {
  return `sci-search:hidden-history:${JSON.stringify([currentUserId(), projectId])}`;
}
function hiddenRuns(projectId) {
  try {
    const value = JSON.parse(localStorage.getItem(hiddenHistoryKey(projectId)) || '[]');
    return new Set(Array.isArray(value) ? value.filter(id => typeof id === 'string') : []);
  } catch { return new Set(); }
}
export async function loadHistory(projectId, {query = '', cursor: next = null} = {}) {
  const token = ++historyGeneration;
  historyProject = projectId;
  const list = document.getElementById('research-history');
  if (!next) list.replaceChildren();
  const params = new URLSearchParams({query, limit: '30'}); if (next) params.set('cursor', next);
  try {
    const data = await request(`/api/v1/projects/${encodeURIComponent(projectId)}/runs?${params}`);
    if (token !== historyGeneration || currentProject()?.id !== projectId) return;
    const hidden = hiddenRuns(projectId);
    const showHidden = document.getElementById('history-show-hidden').checked;
    for (const run of data.items || []) {
      if (hidden.has(run.id) && !showHidden) continue;
      const item = element('li');
      const link = element('a', run.question); link.dataset.runId = run.id;
      link.href = `/app?${new URLSearchParams({project: projectId, run: run.id})}`;
      link.onclick = event => { if (event.ctrlKey || event.metaKey || event.shiftKey) return; event.preventDefault(); selectRun(run); openDashboard(projectId, run.id); };
      const hide = element('button', hidden.has(run.id) ? 'Restore' : 'Hide', 'history-hide button button-quiet');
      hide.type = 'button';
      hide.setAttribute('aria-label', `${hidden.has(run.id) ? 'Restore' : 'Hide'} search: ${run.question}`);
      hide.title = 'Changes history visibility in this browser. Research data and project memory are kept.';
      hide.onclick = () => {
        const updated = hiddenRuns(projectId);
        const wasHidden = updated.has(run.id);
        if (wasHidden) updated.delete(run.id); else updated.add(run.id);
        try { localStorage.setItem(hiddenHistoryKey(projectId), JSON.stringify([...updated])); }
        catch { setStatus('This browser could not save your history preference.', 'error'); return; }
        if (!wasHidden && selectedRun === run.id) beginNewSearch(projectId);
        setStatus(wasHidden ? 'Search restored to history.' : 'Search hidden in this browser. Use Show hidden searches to restore it. Research data is kept.');
        refreshHistory();
      };
      item.append(link, element('span', `${(run.status || 'saved').replaceAll('_', ' ')}${hidden.has(run.id) ? ' · hidden' : ''}`, 'history-status'), hide); list.append(item);
    }
    cursor = data.next_cursor; document.getElementById('history-more').hidden = !cursor;
    document.getElementById('history-empty').hidden = Boolean(list.children.length);
    document.getElementById('history-empty').textContent = hidden.size ? 'No visible searches on this page. Show hidden searches or load more.' : 'Saved research will appear here.';
  } catch (error) {
    if (token !== historyGeneration) return;
    document.getElementById('history-empty').textContent = error.status === 404 ? 'Saved research will appear here.' : `History unavailable: ${error.message}`;
  }
}
export function refreshHistory() { if (currentProject()) loadHistory(currentProject().id, {query: document.getElementById('history-search').value}); }
export function initializeHistory() {
  window.addEventListener('workspace-logout', () => { clearDashboard(); historyGeneration++; });
  onProjectChange(project => {
    clearDashboard(); historyGeneration++;
    document.getElementById('research-history').replaceChildren(); document.getElementById('history-search').value = '';
    document.getElementById('history-more').hidden = true;
    if (!project) return;
    const url = new URL(window.location.href);
    loadHistory(project.id);
    if (url.searchParams.get('project') === project.id && url.searchParams.get('run')) {
      const runId = url.searchParams.get('run');
      openDashboard(project.id, runId, url.searchParams.has('revision') ? Number(url.searchParams.get('revision')) : null, {navigate: false});
    } else if (historyProject && url.searchParams.has('project')) updateUrl(project.id, null, null);
  });
  document.getElementById('history-show-hidden').onchange = () => refreshHistory();
  let searchTimer;
  document.getElementById('history-search').oninput = event => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { if (currentProject()) loadHistory(currentProject().id, {query: event.target.value}); }, 200); };
  document.getElementById('history-more').onclick = () => loadHistory(currentProject().id, {query: document.getElementById('history-search').value, cursor});
  window.addEventListener('popstate', async () => {
    const url = new URL(window.location.href); const projectId = url.searchParams.get('project');
    if (projectId && currentProject()?.id !== projectId) await loadProjects(projectId);
    else if (projectId && url.searchParams.get('run')) openDashboard(projectId, url.searchParams.get('run'), url.searchParams.has('revision') ? Number(url.searchParams.get('revision')) : null, {navigate: false});
    else clearDashboard();
  });
}
