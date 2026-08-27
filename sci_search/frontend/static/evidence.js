import {request, setStatus} from './api.js';

function evidenceCard(record) {
  const article = document.createElement('article');
  article.className = 'evidence-card';
  const heading = document.createElement('strong');
  heading.textContent = record.statement;
  const quote = document.createElement('blockquote');
  quote.textContent = record.source_passage;
  const meta = document.createElement('p');
  meta.className = 'record-meta';
  meta.textContent = [record.section, record.page ? `page ${record.page}` : null, `version ${record.version}`].filter(Boolean).join(' · ');
  article.append(heading, quote, meta);
  return article;
}

export async function loadEvidence(project) {
  const container = document.getElementById('evidence-list');
  container.replaceChildren();
  if (!project) return;
  try {
    const data = await request(`/api/v1/projects/${project.id}/evidence?offset=0&limit=25`);
    document.getElementById('evidence-empty').hidden = data.items.length > 0;
    data.items.forEach((record) => container.append(evidenceCard(record)));
  } catch (error) { setStatus(error.message, 'error'); }
}
