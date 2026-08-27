import {setStatus} from './api.js';
import {initializeAuth} from './auth.js';
import {configureUploadPermissions, initializeDocumentUpload} from './documents.js';
import {loadEvidence} from './evidence.js';
import {loadExports} from './exports.js';
import {initializeProjects, onProjectChange} from './projects.js';
import {configureRunPermissions, initializeRuns} from './runs.js';
import {loadValidation} from './validation.js';

async function start() {
  try {
    await initializeAuth();
    onProjectChange((project) => {
      loadEvidence(project);
      loadValidation(project);
      loadExports(project);
      configureRunPermissions(project);
      configureUploadPermissions(project);
    });
    await initializeProjects();
    initializeRuns();
    initializeDocumentUpload();
  } catch (error) {
    setStatus(error.message || 'The workspace could not be loaded.', 'error');
  }
}

start();
