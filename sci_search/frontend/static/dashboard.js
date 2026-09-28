import {request} from './api.js';
import {articleControls} from './article_feedback.js';
import {renderLandscape} from './landscape.js';

export function element(tag, text = '', className = '') {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}
const views = {
  overview: ['Overview', ['answer', 'findings', 'gaps']],
  literature: ['Literature review', ['literature_review', 'comparisons']],
  landscape: ['Research landscape', ['landscape']],
  studies: ['Studies & evidence', ['studies', 'evidence', 'references']],
  methods: ['Methods & exports', ['scope', 'methods', 'validation', 'downloads']],
};
function showView(view) {
  const root = document.getElementById('dashboard-blocks');
  root.dataset.view = view;
  for (const section of root.querySelectorAll('[data-dashboard-block]')) section.hidden = !views[view][1].includes(section.dataset.dashboardBlock);
  root.querySelector('.dashboard-overview').hidden = view !== 'overview';
  for (const link of document.querySelectorAll('#dashboard-navigation a')) link.setAttribute('aria-current', link.dataset.view === view ? 'page' : 'false');
}
const label = (key) => key.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());
export function safeLink(text, url) {
  const a = element('a', text);
  try {
    const parsed = new URL(url, window.location.origin);
    if (!['http:', 'https:'].includes(parsed.protocol)) return element('span', text);
    a.href = parsed.href;
    a.rel = 'noopener noreferrer';
  } catch { return element('span', text); }
  return a;
}
export function evidenceLinks(ids = []) {
  const row = element('div', '', 'citation-links');
  ids.forEach((id) => {
    const link = element('a', `Evidence ${id}`);
    link.href = `#evidence-${encodeURIComponent(id)}`;
    link.onclick = () => {
      showView('studies');
      const target = document.getElementById(`evidence-${encodeURIComponent(id)}`);
      if (target) { target.open = true; target.focus(); }
    };
    row.append(link);
  });
  return row;
}
// Structured scientific fields remain readable; source content is always text, never HTML.
export function fields(value, parent, depth = 0) {
  if (value == null || value === '') return;
  if (Array.isArray(value)) {
    const list = element('ul', '', 'scientific-list');
    for (const item of value) { const li = element('li'); fields(item, li, depth + 1); list.append(li); }
    parent.append(list);
  } else if (typeof value === 'object') {
    if (value.text || value.statement) {
      parent.append(element('p', value.text || value.statement));
      if (value.qualification) parent.append(element('p', value.qualification, 'help'));
      if (value.evidence_ids) parent.append(evidenceLinks(value.evidence_ids));
      const rest = Object.fromEntries(Object.entries(value).filter(([k]) => !['text', 'statement', 'qualification', 'evidence_ids', 'category', 'citations', 'id', 'status'].includes(k)));
      fields(rest, parent, depth + 1);
      return;
    }
    const dl = element('dl', '', 'scientific-fields');
    for (const [key, item] of Object.entries(value)) {
      if (item == null || (Array.isArray(item) && !item.length)) continue;
      if (['category', 'schema_version', 'source_artifact', 'relative_path', 'path', 'artifact', 'source_path'].includes(key) || key.endsWith('_directory') || key.endsWith('_path')) continue;
      dl.append(element('dt', label(key)));
      const dd = element('dd');
      if (key === 'evidence_ids') dd.append(evidenceLinks(item));
      else if ((key === 'source_url' || key === 'url') && typeof item === 'string') dd.append(safeLink('Open source', item));
      else fields(item, dd, depth + 1);
      dl.append(dd);
    }
    parent.append(dl);
  } else { const text = typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value); parent.append(element('span', /^[a-z][a-z_]{5,}$/.test(text) && text.includes('_') ? label(text) : text)); }
}
export function dataTable(rows, columns) {
  const wrap = element('div', '', 'table-wrap');
  const table = element('table');
  const head = element('tr');
  for (const [key, title] of columns) { const th = element('th', title); th.scope = 'col'; head.append(th); }
  const thead = element('thead'); thead.append(head); table.append(thead);
  const body = element('tbody');
  for (const row of rows) {
    const tr = element('tr');
    for (const [key] of columns) { const td = element('td'); fields(row[key], td); tr.append(td); }
    body.append(tr);
  }
  table.append(body); wrap.append(table); return wrap;
}
function expandable(title, data) {
  const details = element('details', '', 'scientific-detail');
  details.append(element('summary', title)); fields(data, details); return details;
}
const severityText = {high: 'High severity', moderate: 'Moderate severity', low: 'Low severity'};
const contradictionAnchor = (id) => `contradiction-${String(id).replace(/[^a-zA-Z0-9-]/g, '-')}`;
function contradictionGroups(groups, parent, snapshot) {
  const references = new Map(((snapshot.blocks || []).find((b) => b.id === 'references')?.data || []).map((r) => [r.publication_id, r]));
  const wrap = element('div', '', 'contradiction-groups');
  wrap.append(element('h3', 'Where studies disagree'));
  for (const group of groups) {
    // Low-severity disagreements are usually explained by context, so they start collapsed.
    const collapsed = group.severity === 'low';
    const article = element(collapsed ? 'details' : 'article', '', 'contradiction-group');
    article.id = contradictionAnchor(group.id);
    article.dataset.severity = group.severity || '';
    const header = element(collapsed ? 'summary' : 'div', '', 'contradiction-header');
    const studyCount = new Set((group.positions || []).flatMap((position) => position.publication_ids || [])).size;
    header.append(
      element('h4', group.topic || ''),
      element('span', severityText[group.severity] || label(String(group.severity || 'unknown')), `severity-badge severity-${group.severity}`),
      element('span', label(String(group.cause || 'unexplained')), 'study-chip'),
      element('span', `${studyCount} ${studyCount === 1 ? 'study' : 'studies'}`, 'contradiction-count'),
    );
    article.append(header);
    const sides = element('div', '', 'contradiction-positions');
    for (const position of group.positions || []) {
      const side = element('div', '', 'contradiction-position');
      side.append(element('p', position.stance || '', 'contradiction-stance'));
      for (const quote of position.quotes || []) side.append(element('blockquote', quote.quote || ''));
      for (const publicationId of position.publication_ids || []) {
        const reference = references.get(publicationId) || {};
        const text = `${reference.number ? `[${reference.number}] ` : ''}${reference.title || publicationId}${reference.year ? ` (${reference.year})` : ''}`;
        const url = snapshot.documents?.[publicationId]?.url || reference.source_url;
        const study = element('p', '', 'contradiction-studies');
        study.append(url ? safeLink(text, url) : document.createTextNode(text));
        side.append(study);
      }
      side.append(evidenceLinks(position.evidence_ids || []));
      sides.append(side);
    }
    article.append(sides);
    if (group.cause_explanation) {
      const why = element('div', '', 'contradiction-explanation');
      const sentence = element('p');
      sentence.append(element('strong', 'Why they may differ: '), document.createTextNode(group.cause_explanation.text || ''));
      why.append(sentence);
      for (const quote of group.cause_explanation.quotes || []) why.append(element('blockquote', quote.quote || ''));
      article.append(why);
    } else article.append(element('p', 'No grounded explanation found.', 'help'));
    article.append(expandable('How this was assessed', {
      status: 'Model-proposed, source-verified — not expert-confirmed',
      severity_basis: group.severity_basis,
      severity_rules_version: group.severity_rules_version,
      validation_notes: group.validation_notes,
    }));
    wrap.append(article);
  }
  parent.append(wrap);
}
function contestNote(contest, parent) {
  if (!contest?.contested) return;
  const note = element('div', '', 'contest-note');
  (contest.qualifications || []).forEach((text, index) => {
    const link = element('a', text);
    const anchor = contradictionAnchor(contest.group_ids?.[index] || '');
    link.href = `#${anchor}`;
    link.addEventListener('click', (event) => {
      event.preventDefault();
      showView('literature');
      document.getElementById(anchor)?.scrollIntoView({block: 'start'});
    });
    note.append(link);
  });
  parent.append(note);
}
function reviewBlock(data, parent) {
  parent.append(element('p', 'A source-linked reading of the available literature.', 'section-intro'));
  fields(data.executive_summary, parent);
  const narrative = element('div', '', 'review-narrative');
  const sections = [['thematic_findings', 'Themes across the literature'], ['findings', 'What the studies report'], ['measurements', 'Reported measurements'], ['research_implications', 'What to investigate next']];
  for (const [key, title] of sections) if (data[key] && Object.keys(data[key]).length) {
    const section = element('article'); section.append(element('h3', title)); fields(data[key], section); narrative.append(section);
  }
  parent.append(narrative);
  if (data.quality?.limitations?.length) { parent.append(element('h3', 'How to interpret this review')); fields(data.quality.limitations, parent); }
  if (data.conclusion?.text && data.conclusion.text !== data.executive_summary?.text) { parent.append(element('h3', 'Conclusion')); fields(data.conclusion, parent); }
  parent.append(expandable('Review coverage and quality notes', {review_type: data.review_type, corpus_overview: data.corpus_overview, quality: data.quality}));
  if (data.appendices) parent.append(expandable('Search queries and rejected model records', {search_queries: data.appendices.search_queries, rejected_model_records: data.appendices.rejected_model_records}));
}
function overview(snapshot, root) {
  const blocks = Object.fromEntries((snapshot.blocks || []).map(block => [block.id, block.data]));
  const paperCount = blocks.studies?.studies?.length ?? blocks.landscape?.coverage?.records ?? 0;
  const stats = element('div', '', 'dashboard-overview'); stats.setAttribute('aria-label', 'Research overview');
  for (const [value, title, note] of [[paperCount, 'Studies discovered', 'The literature in this search'], [(blocks.evidence || []).length, 'Evidence passages', 'Retained with source provenance'], [(blocks.references || []).length, 'Listed publications', 'Sources retained with this review'], [label(blocks.answer?.answer_adequacy?.status || 'Not assessed'), 'Evidence coverage', 'Adequacy for this question']]) {
    const card = element('div', '', 'dashboard-stat'); card.append(element('strong', String(value)), element('span', title), element('small', note)); stats.append(card);
  }
  root.append(stats);
}
function evidenceBlock(data, parent, snapshot, context) {
  for (const record of data || []) {
    const detail = element('details', '', 'evidence-card');
    detail.id = `evidence-${encodeURIComponent(record.id)}`;
    detail.tabIndex = -1;
    detail.append(element('summary', record.statement || record.publication_title || record.title || `Evidence ${record.id}`));
    detail.append(element('blockquote', record.passage || record.source_passage || record.quote || 'No retained passage.'));
    fields(Object.fromEntries(Object.entries(record).filter(([key]) => !['passage', 'source_passage', 'quote', 'statement'].includes(key))), detail);
    const doc = snapshot.documents?.[record.publication_id];
    if (doc?.url) detail.append(safeLink('Open original publication', doc.url));
    const review = snapshot.evidence_reviews?.[record.id];
    if (review) {
      detail.append(element('p', `Finding review: ${review.review_decision || 'pending'} · version ${review.version}`, 'help'));
      if (review.review_note) detail.append(element('p', review.review_note));
      const actions = element('div', '', 'button-row');
      const status = element('p', '', 'status'); status.setAttribute('role', 'status');
      for (const [decision, title] of [['accepted', 'Accept evidence'], ['rejected', 'Reject evidence']]) {
        const button = element('button', title, 'button button-secondary'); button.type = 'button';
        button.disabled = context.historical || !['owner', 'reviewer'].includes(snapshot.role || context.role);
        button.onclick = async () => {
          for (const action of actions.children) action.disabled = true;
          try {
            await request(`/api/v1/projects/${encodeURIComponent(context.projectId)}/evidence/${encodeURIComponent(review.id)}/review`, {method: 'PATCH', body: {decision, expected_version: review.version}});
            await context.onEvidenceReview?.(record.id);
          } catch (error) {
            status.textContent = error.status === 409 ? 'This finding changed in another session. Reopen the dashboard before reviewing again.' : error.message;
            for (const action of actions.children) action.disabled = false;
          }
        };
        actions.append(button);
      }
      detail.append(actions, status);
    }
    parent.append(detail);
  }
}
function studyBlock(data, parent, snapshot, context) {
  if (data.studies?.length) parent.append(element('p', `${data.studies.length} studies retained. Review each article’s relevance to this question, or explore its source passages.`, 'section-intro'));
  const filter = element('input'); filter.type = 'search'; filter.placeholder = 'Filter studies'; filter.setAttribute('aria-label', 'Filter studies'); parent.append(filter);
  const list = element('div'); parent.append(list);
  for (const study of data.studies || []) {
    const card = element('article', '', 'study-card');
    card.dataset.studyTitle = `${study.title || ''} ${study.publication_id || ''}`.toLowerCase();
    card.append(element('h3', study.title || study.publication_id));
    card.append(element('p', [study.year, (study.authors || []).map(a => typeof a === 'string' ? a : a.name || a.display_name).join(', ')].filter(Boolean).join(' · '), 'help'));
    const chips = element('div', '', 'study-chips');
    chips.append(element('span', label(study.screening?.decision || 'Not screened'), 'study-chip'), element('span', (Boolean(snapshot.documents?.[study.publication_id]?.url) || (study.full_text_available ?? Boolean(study.source_artifact))) ? 'Full text retained' : 'Full text unavailable', 'study-chip'));
    card.append(chips);
    if (study.screening?.reason) card.append(element('p', study.screening.reason, 'help'));
    if (study.feedback_explanation || study.memory_explanation) fields(study.feedback_explanation || study.memory_explanation, card);
    const doc = snapshot.documents?.[study.publication_id];
    if (doc?.url) card.append(safeLink('Open original publication', doc.url));
    card.append(articleControls(study, snapshot, context));
    card.append(expandable('Study details and passages', Object.fromEntries(Object.entries(study).filter(([k]) => !['title', 'authors', 'screening'].includes(k)))));
    list.append(card);
  }
  filter.oninput = () => { for (const card of list.children) card.hidden = !card.dataset.studyTitle.includes(filter.value.toLowerCase()); };
}
export function renderDashboard(snapshot, context = {}) {
  const root = document.getElementById('dashboard-blocks');
  const key = `${context.projectId}:${snapshot.question}`;
  if (root.dataset.questionKey !== key && window.matchMedia('(max-width: 800px)').matches) document.querySelector('.history-panel').open = false;
  const selectedView = root.dataset.questionKey === key ? root.dataset.view || 'overview' : 'overview';
  root.dataset.questionKey = key;
  root.replaceChildren();
  document.body.classList.add('dashboard-open');
  overview(snapshot, root);
  document.getElementById('dashboard-panel').hidden = false;
  root.dataset.dashboardRevision = snapshot.revision;
  document.getElementById('dashboard-question').textContent = snapshot.question;
  document.getElementById('dashboard-version').textContent = `Saved revision ${snapshot.revision}`;
  const analysis = snapshot.analysis || {};
  const retained = snapshot.blocks?.find(block => block.id === 'methods')?.data?.methodology?.model || {};
  const provider = analysis.provider || retained.provider;
  const model = analysis.model || retained.name;
  const actual = provider && model ? `${provider === 'openai' ? 'OpenAI' : provider === 'mistral' ? 'Mistral' : provider} · ${model}` : null;
  const method = analysis.method || retained.method;
  const usedFallback = Boolean(analysis.fallback_reason || method === 'deterministic_extractive_fallback' || (analysis.status && !['complete', 'coverage_limited'].includes(analysis.status)) || (analysis.status === 'coverage_limited' && !actual));
  const selected = analysis.selection;
  const fallback = usedFallback ? `Extractive analysis${selected ? ` · selected: ${selected.provider === 'openai' ? 'OpenAI' : 'Mistral'} · ${selected.model}` : ''}${analysis.fallback_reason ? ` — ${analysis.fallback_reason}` : ''}` : null;
  document.getElementById('dashboard-model').textContent = fallback || (actual ? `Analysis model: ${actual}` : 'Analysis model: not recorded for this saved result');
  document.getElementById('download-all')?.remove();
  const artifacts = snapshot.artifacts || snapshot.blocks?.find(block => block.id === 'downloads')?.data || [];
  const bundle = artifacts.find(item => item.url && (item.content_type === 'application/zip' || /\.zip$/i.test(item.filename || '')));
  if (bundle) {
    const download = safeLink('Download all', bundle.url);
    if (download.tagName === 'A') {
      download.id = 'download-all';
      download.className = 'button button-primary';
      download.download = bundle.filename || 'research-package.zip';
      download.title = `Download the complete research package for revision ${snapshot.revision}`;
      document.getElementById('new-search').before(download);
    }
  }

  const nav = document.getElementById('dashboard-navigation'); nav.replaceChildren();
  for (const [view, [title]] of Object.entries(views)) {
    const link = element('a', title); link.href = `#dashboard-${view}`; link.dataset.view = view;
    link.onclick = event => { event.preventDefault(); showView(view); };
    nav.append(link);
  }
  const titles = {scope: 'Question and scope', answer: 'What the evidence tells us', literature_review: 'Literature review', findings: 'Key findings', comparisons: 'Study comparisons', landscape: 'Research landscape', studies: 'Studies and article relevance', gaps: 'Gaps and limitations', methods: 'Methods and selection', evidence: 'Source evidence', validation: 'Validation', references: 'References', downloads: 'Downloads'};
  const order = ['answer', 'scope', 'gaps', 'literature_review', 'landscape', 'findings', 'comparisons', 'studies', 'evidence', 'validation', 'methods', 'references', 'downloads'];
  for (const block of [...(snapshot.blocks || [])].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))) {
    const section = element('section', '', 'panel dashboard-block');
    section.dataset.dashboardBlock = block.id;
    section.id = `dashboard-${block.id}`;
    section.append(element('h2', titles[block.id] || label(block.id)));
    if (block.explanation && !(block.id === 'downloads' && snapshot.artifacts?.length)) section.append(element('p', block.explanation, 'empty-state'));
    const data = block.data;
    if (block.id === 'downloads') {
      for (const artifact of snapshot.artifacts || data || []) if (artifact.url) section.append(safeLink(artifact.filename || artifact.id || 'Download', artifact.url));
    } else if (block.status === 'ready') {
      if (block.id === 'scope') {
        fields(data.question_brief, section);
        const scope = data.research_scope || {};
        const plan = data.plan || {};
        if (plan.intent) section.append(element('p', label(plan.intent), 'section-intro'));
        const concepts = element('div', '', 'study-chips'); for (const concept of plan.concepts || []) concepts.append(element('span', typeof concept === 'string' ? concept : concept.label || concept.name || '', 'study-chip')); section.append(concepts);
        if (scope.dimensions?.length) section.append(dataTable(scope.dimensions, [['label', 'Scope dimension'], ['kind', 'Type'], ['required', 'Required']]));
        section.append(expandable('Full question interpretation and search plan', {research_scope: scope, plan}));
      } else if (block.id === 'answer') {
        const narrative = element('div', '', 'answer-narrative'); fields(data.executive_summary, narrative); section.append(narrative);
        const adequacy = data.answer_adequacy || {};
        if (adequacy.decision) section.append(element('p', adequacy.decision, 'adequacy-decision'));
        if (adequacy.status) section.append(element('p', `Evidence coverage: ${label(adequacy.status)}`, 'status-badge'));
        contestNote(data.answer_contest, section);
        if (adequacy.missing_requirements?.length) { section.append(element('h3', 'What is still missing')); fields(adequacy.missing_requirements, section); }
        section.append(expandable('Evidence adequacy checks', Object.fromEntries(Object.entries(adequacy).filter(([key]) => !['decision', 'status', 'missing_requirements'].includes(key)))));
        if (!data.executive_summary && data.synthesis?.claims?.length) fields(data.synthesis.claims, section);
      } else if (block.id === 'literature_review') reviewBlock(data, section);
      else if (block.id === 'evidence') evidenceBlock(data, section, snapshot, context);
      else if (block.id === 'studies') studyBlock(data, section, snapshot, context);
      else if (block.id === 'landscape') renderLandscape(data, section);
      else if (block.id === 'references') {
        for (const reference of data || []) {
          const p = element('p', `${reference.number ? `[${reference.number}] ` : ''}${reference.title || reference.publication_id}`);
          const doc = snapshot.documents?.[reference.publication_id];
          if (doc?.url || reference.source_url) { p.append(document.createTextNode(' · '), safeLink('Open publication', doc?.url || reference.source_url)); }
          fields({authors: reference.authors, year: reference.year, doi: reference.doi}, p); section.append(p);
        }
      } else if (block.id === 'gaps') {
        fields(data.limitations, section);
        if (data.follow_up_questions?.length) { section.append(element('h3', 'Next questions')); fields(data.follow_up_questions, section); }
        if (data.quality_flags?.length) section.append(expandable('Evidence limitations in detail', data.quality_flags));
      } else if (block.id === 'findings') {
        fields(data.claims, section);
        if (data.measurements?.length) section.append(expandable('Measurements and their context', data.measurements));
        if (data.thematic_findings) section.append(expandable('Findings by theme', data.thematic_findings));
        if (!data.claims?.length) section.append(element('p', 'No supported findings were retained for this question.', 'section-intro'));
      } else if (block.id === 'comparisons') {
        if (data.contradiction_groups?.length) contradictionGroups(data.contradiction_groups, section, snapshot);
        if (data.comparison_groups?.length) fields(data.comparison_groups, section);
        else if (!data.contradiction_groups?.length) section.append(element('p', 'The retained evidence does not establish a cross-study comparison.', 'section-intro'));
        section.append(expandable('Comparability and measurement details', {comparability: data.comparability, measurements: data.measurements}));
      } else if (block.id === 'validation') {
        section.append(element('p', 'Source grounding and researcher review are recorded separately. Expand the checks to inspect their outcomes.', 'section-intro'));
        section.append(expandable('Validation checks and review states', data));
      } else if (block.id === 'methods') {
        section.append(element('p', 'Inspect how this search selected literature, acquired full texts, and assessed evidence.', 'section-intro'));
        section.append(expandable('Search methods and selection flow', {methodology: data.methodology, selection_flow: data.selection_flow}));
        const run = data.research_run || {};
        const compact = Object.fromEntries(Object.entries(run).filter(([key]) => !['candidates', 'full_text_screening', 'study_matrix', 'acquisitions', 'acquired', 'evidence', 'authorized_uploads'].includes(key)));
        section.append(expandable('Search and screening record', compact));
      } else fields(data, section);
    }
    root.append(section);
  }
  showView(selectedView);
}

