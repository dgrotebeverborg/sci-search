let loadVersion = 0;
import {request, setStatus} from './api.js';

export async function loadExports(project) {
  const version = ++loadVersion;
  const target = document.getElementById('export-actions');
  target.replaceChildren();
  if (!project) {
    target.textContent = 'Downloads become available after this review.';
    return;
  }
  let exports = [];
  try {
    exports = (await request(`/api/v1/projects/${project.id}/exports`)).items;
  } catch (error) {
    setStatus(error.message, 'error');
  }
  if (version !== loadVersion) return;
  if (!exports.length) {
    const note = document.createElement('span');
    note.className = 'help';
    note.textContent = 'Downloads become available after a review.';
    target.append(note);
    return;
  }
  for (const item of exports) {
    const link = document.createElement('a');
    link.className = 'button button-primary';
    link.href = `/api/v1/projects/${project.id}/exports/${item.id}`;
    link.textContent = item.content_type === 'application/zip' ? 'Download research package' : item.filename;
    target.append(link);
  }
}
