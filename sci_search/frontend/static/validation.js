let loadVersion = 0;
import {request, setStatus} from './api.js';

export async function loadValidation(project) {
  const version = ++loadVersion;
  const container = document.getElementById('validation-list');
  container.replaceChildren();
  document.getElementById('validation-empty').hidden = false;
  if (!project) return;
  try {
    const data = await request(`/api/v1/projects/${project.id}/validation`);
    if (version !== loadVersion) return;
    document.getElementById('validation-empty').hidden = data.items.length > 0;
    for (const record of data.items) {
      const row = document.createElement('div');
      row.className = 'validation-item';
      const name = document.createElement('strong');
      name.textContent = record.check_name;
      const status = document.createElement('span');
      status.textContent = record.status;
      row.append(name, status);
      container.append(row);
    }
  } catch (error) { setStatus(error.message, 'error'); }
}
