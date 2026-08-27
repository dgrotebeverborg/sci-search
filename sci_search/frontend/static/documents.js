import {request, setStatus} from './api.js';
import {currentProject} from './projects.js';
import {currentRun} from './runs.js';

function encodeBase64(bytes) {
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 32768) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  }
  return btoa(binary);
}

export function configureUploadPermissions(project) {
  document.getElementById('upload-controls').hidden = !project || !['owner', 'editor'].includes(project.role);
}

export function initializeDocumentUpload() {
  const input = document.getElementById('authorized-document');
  document.getElementById('upload-document-button').addEventListener('click', () => input.click());
  input.addEventListener('change', async () => {
    const project = currentProject();
    const run = currentRun();
    const file = input.files[0];
    const candidateId = document.getElementById('upload-candidate-id').value.trim();
    if (!project || !run || !file || !candidateId) {
      setStatus('Start a review and provide a candidate identifier before uploading.', 'error');
      input.value = '';
      return;
    }
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      await request(`/api/v1/projects/${project.id}/documents/upload`, {
        method: 'POST',
        body: {
          run_id: run.id,
          candidate_id: candidateId,
          filename: file.name,
          content_base64: encodeBase64(bytes),
          authorization_confirmed: true,
        },
      });
      setStatus('Authorized full text added to this project.');
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      input.value = '';
    }
  });
}
