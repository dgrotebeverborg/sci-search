import {setStatus} from './api.js';
import {initializeAuth} from './auth.js';
import {configureUploadPermissions, initializeDocumentUpload} from './documents.js';
import {initializeHistory} from './history.js';
import {loadEvidence} from './evidence.js';
import {loadExports} from './exports.js';
import {initializeProjects, onProjectChange} from './projects.js';
import {configureRunPermissions, currentRun, initializeRuns} from './runs.js';
import {loadValidation} from './validation.js';

async function start() {
  try {
    initializeRuns();
    initializeHistory();
    initializeDocumentUpload();
    await initializeAuth();
    onProjectChange((project) => {
      const run = currentRun();
      const resultsProject = run && run.status !== 'completed' ? null : project;
      loadEvidence(resultsProject);
      loadValidation(resultsProject);
      loadExports(resultsProject);
      configureRunPermissions(project);
      configureUploadPermissions(project);
    });
    await initializeProjects();
  } catch (error) {
    setStatus(error.message || 'The workspace could not be loaded.', 'error');
  }
}

start();
