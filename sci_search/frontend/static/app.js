import {setStatus} from './api.js';
import {initializeAuth} from './auth.js';
import {loadEvidence} from './evidence.js';
import {showExports} from './exports.js';
import {initializeProjects, onProjectChange} from './projects.js';
import {initializeRuns} from './runs.js';
import {loadValidation} from './validation.js';

async function start() {
  try {
    await initializeAuth();
    onProjectChange((project) => {
      loadEvidence(project);
      loadValidation(project);
      showExports(project);
    });
    await initializeProjects();
    initializeRuns();
  } catch (error) {
    setStatus(error.message || 'The workspace could not be loaded.', 'error');
  }
}

start();
