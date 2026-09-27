let loadVersion = 0;
import {ApiError, request, setStatus} from './api.js';

let activeProject = null;

async function saveReview(record, decision) {
  const reviewStatus = document.getElementById('review-status');
  try {
    await request(`/api/v1/projects/${activeProject.id}/evidence/${record.id}/review`, {
      method: 'PATCH',
      body: {decision, expected_version: record.version},
    });
    reviewStatus.textContent = decision === 'rejected'
      ? 'Evidence rejected and hidden from this list.' : 'Evidence review saved.';
    await loadEvidence(activeProject);
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      reviewStatus.textContent = 'This evidence changed in another session. The current version has been reloaded.';
      await loadEvidence(activeProject);
      return;
    }
    setStatus(error.message, 'error');
  }
}

function evidenceCard(record) {
  const article = document.createElement('article');
  article.className = 'evidence-card';
  const heading = document.createElement('strong');
  heading.textContent = record.statement;
  const quote = document.createElement('blockquote');
  quote.textContent = record.source_passage;
  const meta = document.createElement('p');
  meta.className = 'record-meta';
  meta.textContent = [record.section, record.page ? `page ${record.page}` : null, `version ${record.version}`, record.review_decision === 'accepted' ? 'Accepted' : null].filter(Boolean).join(' · ');
  article.append(heading, quote, meta);
  if (activeProject && ['owner', 'reviewer'].includes(activeProject.role)) {
    const actions = document.createElement('div');
    actions.className = 'review-actions';
    for (const [decision, label] of [['accepted', 'Accept evidence'], ['rejected', 'Reject evidence']]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'button button-secondary';
      button.textContent = label;
      button.addEventListener('click', () => saveReview(record, decision));
      actions.append(button);
    }
    article.append(actions);
  }
  return article;
}

export async function loadEvidence(project) {
  const version = ++loadVersion;
  activeProject = project;
  const container = document.getElementById('evidence-list');
  container.replaceChildren();
  document.getElementById('evidence-empty').hidden = false;
  document.getElementById('evidence-empty').textContent = 'Evidence will appear here when this review has produced source-linked findings.';
  if (!project) return;
  try {
    const data = await request(`/api/v1/projects/${project.id}/evidence?offset=0&limit=25`);
    if (version !== loadVersion) return;
    const visible = data.items.filter(record => record.review_decision !== 'rejected');
    document.getElementById('evidence-empty').hidden = visible.length > 0;
    if (!visible.length && data.items.length) {
      document.getElementById('evidence-empty').textContent = 'No evidence to show. Rejected items are hidden.';
    }
    visible.forEach((record) => container.append(evidenceCard(record)));
  } catch (error) { setStatus(error.message, 'error'); }
}
