import {request, setStatus} from './api.js';

let activeWorkspace = null;
let activeProject = null;
const listeners = new Set();

export function onProjectChange(listener) { listeners.add(listener); }
export function currentProject() { return activeProject; }

function notify() { listeners.forEach((listener) => listener(activeProject)); }

function renderProjects(items, preferredId = null) {
  const select = document.getElementById('project-select');
  select.replaceChildren();
  for (const project of items) {
    const option = document.createElement('option');
    option.value = project.id;
    option.textContent = project.name;
    select.append(option);
  }
  if (preferredId && items.some((project) => project.id === preferredId)) select.value = preferredId;
  activeProject = items.find((project) => project.id === select.value) || items[0] || null;
  select.disabled = items.length === 0;
  notify();
}

export async function loadProjects(preferredId = null) {
  const data = await request('/api/v1/projects');
  renderProjects(data.items, preferredId);
  if (!data.items.length) setStatus('Create a project to begin a research review.');
}

export async function createProject(name, isPrivate) {
  if (!activeWorkspace) throw new Error('No workspace is available');
  const project = await request('/api/v1/projects', {
    method: 'POST',
    body: {workspace_id: activeWorkspace.id, name, is_private: isPrivate},
  });
  await loadProjects(project.id);
  setStatus(`Project “${project.name}” created.`);
  return project;
}

export async function initializeProjects() {
  const workspaces = await request('/api/v1/workspaces');
  activeWorkspace = workspaces.items[0] || null;
  document.getElementById('workspace-name').textContent = activeWorkspace?.name || 'No workspace';
  await loadProjects(new URL(window.location.href).searchParams.get('project'));
  document.getElementById('project-select').addEventListener('change', async (event) => {
    try {
      const projects = await request('/api/v1/projects');
      activeProject = projects.items.find((project) => project.id === event.target.value) || null;
      notify();
    } catch (error) { if (error.name !== 'AbortError') setStatus(error.message, 'error'); }
  });
  document.getElementById('new-project-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = document.getElementById('new-project-name').value.trim();
    try {
      await createProject(name, document.getElementById('new-project-private').checked);
      event.target.reset();
      event.target.closest('details').open = false;
    } catch (error) {
      setStatus(error.message, 'error');
    }
  });
  document.querySelector('#new-project-form button[type="submit"]').disabled = !activeWorkspace;
}
