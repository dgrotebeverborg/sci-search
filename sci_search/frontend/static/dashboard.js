import {providerLabel} from './api.js';
import {renderDataResearch} from './data_research.js';
import {request} from './api.js';
import {articleControls} from './article_feedback.js';
import {renderLandscape, renderCoverageNotice} from './landscape.js';

export function element(tag, text = '', className = '') {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
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
    link.onclick = (event) => {
      const target = document.getElementById(`evidence-${encodeURIComponent(id)}`);
      if (!target) return;
      event.preventDefault();
      target.open = true;
      reveal(target);
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
      reveal(document.getElementById(anchor));
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
// Open every collapsed section around a target, so links into "More details" work.
function reveal(target) {
  for (let node = target; node; node = node.parentElement) if (node.tagName === 'DETAILS') node.open = true;
  target?.scrollIntoView({block: 'start'});
  target?.focus?.();
}
// A renderer that fails on an older or partial saved result affects only its own section.
function safely(parent, draw) {
  try { draw(); } catch (error) {
    console.error(error);
    parent.append(element('p', 'This part could not be shown for this saved result.', 'help'));
  }
}
function resultSection(id, title, {collapsed = false, line = ''} = {}) {
  const node = element(collapsed ? 'details' : 'section', '', collapsed ? 'result-section result-collapsed' : 'result-section');
  node.id = `dashboard-${id}`;
  node.dataset.resultSection = id;
  const heading = element('h2', title);
  if (collapsed) {
    const summary = element('summary'); summary.append(heading);
    if (line) summary.append(element('span', line, 'result-line'));
    node.append(summary);
  } else node.append(heading);
  return node;
}
function sourceItem(item, note = '') {
  const li = element('li');
  const text = `${item.title}${item.year ? ` (${item.year})` : ''}`;
  li.append(item.url ? safeLink(text, item.url) : element('span', text));
  const extra = [item.publisher, note].filter(Boolean).join(' · ');
  if (extra) li.append(element('span', ` · ${extra}`, 'help'));
  return li;
}
function list(items, render) { const ul = element('ul', '', 'result-list'); for (const item of items) ul.append(render(item)); return ul; }
// Partial findings the review could support, with their quotes, even without an overall answer.
function investigationReview(review, parent) {
  const details = element('details', '', 'result-more'); details.open = Boolean(review.partial_findings?.length);
  details.append(element('summary', review.partial_findings?.length ? `Partial evidence (${review.partial_findings.length})` : 'Investigation review'));
  if (review.qualification) details.append(element('p', review.qualification));
  for (const finding of review.partial_findings || []) {
    details.append(element('h3', finding.subject || ''), element('p', finding.title || ''), element('blockquote', finding.quote || ''));
    if (finding.qualification) details.append(element('p', finding.qualification, 'help'));
    if (finding.doi) details.append(safeLink('Source publication', 'https://doi.org/' + finding.doi));
  }
  for (const step of review.steps || []) details.append(element('p', `${step.decision?.reason || 'Review attempt'} · ${step.outcome?.status || 'stopped'}`, 'help'));
  if (review.stop_reason) details.append(element('p', review.stop_reason, 'help'));
  parent.append(details);
}
function answerSection(summary, answer, snapshot) {
  const node = resultSection('answer', 'Answer');
  const text = summary.answer?.text || answer.executive_summary?.text;
  if (text) node.append(element('p', text, 'result-answer'));
  const ids = summary.answer?.evidence_ids || answer.executive_summary?.evidence_ids || [];
  if (ids.length) node.append(evidenceLinks(ids));
  const certainty = summary.certainty || {level: 'not_assessed', label: 'Not assessed', sentence: ''};
  const line = element('p', '', 'certainty');
  line.append(element('span', certainty.label, `certainty-pill certainty-${certainty.level}`));
  if (certainty.sentence) line.append(document.createTextNode(` ${certainty.sentence}`));
  node.append(line);
  if (snapshot.result_quality?.validation_note) node.append(element('p', snapshot.result_quality.validation_note, 'help'));
  if (answer.investigation_review) safely(node, () => investigationReview(answer.investigation_review, node));
  contestNote(answer.answer_contest, node);
  if (summary.key_sources?.length) node.append(element('h3', 'Key sources'), list(summary.key_sources, item => sourceItem(item)));
  return node;
}
function dataSection(summary, analysis) {
  const node = resultSection('data', 'What the data show');
  const datasets = summary.data.datasets || [];
  if (datasets.length) node.append(list(datasets, d => sourceItem(d, [d.entities?.join(', '), d.first_year ? `${d.first_year}–${d.last_year}` : '', d.unit].filter(Boolean).join(' · '))));
  else node.append(element('p', 'No dataset gave a supported numerical answer.', 'help'));
  // Open by default: the chart is part of what the data show.
  const more = element('details', '', 'result-more'); more.open = true;
  more.append(element('summary', `Charts, values and sources${summary.data.not_used ? ` · ${summary.data.not_used} sources not used` : ''}`));
  safely(more, () => renderDataResearch(analysis, more));
  node.append(more);
  return node;
}
function literatureSection(summary, blocks, snapshot) {
  const node = resultSection('literature', 'What the literature says');
  const l = summary.literature;
  if (l) node.append(element('p', `${l.found} studies found · ${l.full_texts} full texts read · ${l.included} counted as evidence`, 'help'));
  if (blocks.findings?.claims?.length) fields(blocks.findings.claims, node);
  if (blocks.comparisons?.contradiction_groups?.length) safely(node, () => contradictionGroups(blocks.comparisons.contradiction_groups, node, snapshot));
  if (blocks.literature_review && Object.keys(blocks.literature_review).length) {
    const review = element('details', '', 'result-more'); review.id = 'dashboard-literature_review';
    review.append(element('summary', 'Read the full review')); safely(review, () => reviewBlock(blocks.literature_review, review)); node.append(review);
  }
  return node;
}
function studyItem(study, withDecision) {
  const li = sourceItem(study, withDecision ? study.decision : '');
  if (study.reason) li.append(element('p', study.reason, 'help'));
  return li;
}
function whySection(summary) {
  if (!summary.missing?.length && !summary.included?.length && !summary.left_out?.length) return null;
  const node = resultSection('why', 'Why this certainty');
  if (summary.missing?.length) node.append(element('h3', 'What is missing'), list(summary.missing, text => element('li', text)));
  if (summary.included?.length) node.append(element('h3', `Counted as evidence (${summary.included.length})`), list(summary.included, s => studyItem(s, false)));
  if (summary.left_out?.length) node.append(element('h3', 'Read but not counted'), list(summary.left_out, s => studyItem(s, true)));
  return node;
}
function landscapeSection(summary, landscape) {
  const node = resultSection('landscape', 'Research landscape', {collapsed: true, line: summary.landscape_line || ''});
  // Drawn on first opening: the timeline and study browser are large and usually not needed.
  node.addEventListener('toggle', () => { if (node.open && !node.dataset.drawn) { node.dataset.drawn = 'yes'; safely(node, () => renderLandscape(landscape, node)); } });
  return node;
}
function detailPart(parent, id, title, draw) {
  const part = element('details', '', 'result-part'); part.id = `dashboard-${id}`;
  part.append(element('summary', title)); safely(part, () => draw(part)); parent.append(part);
}
function detailsSection(blocks, snapshot, context) {
  const node = resultSection('details', 'More details', {collapsed: true, line: 'Question interpretation, methods, all studies and passages, validation, references and downloads'});
  if (blocks.scope) detailPart(node, 'scope', 'Question and scope', part => {
    fields(blocks.scope.question_brief, part);
    const scope = blocks.scope.research_scope || {};
    if (scope.dimensions?.length) part.append(dataTable(scope.dimensions, [['label', 'Part of the question'], ['kind', 'Type'], ['required', 'Required']]));
    part.append(expandable('Full question interpretation and search plan', {research_scope: scope, plan: blocks.scope.plan}));
  });
  if (blocks.methods) detailPart(node, 'methods', 'Search and methods', part => {
    part.append(expandable('Search methods and selection flow', {methodology: blocks.methods.methodology, selection_flow: blocks.methods.selection_flow}));
    const run = blocks.methods.research_run || {};
    part.append(expandable('Search and screening record', Object.fromEntries(Object.entries(run).filter(([key]) => !['candidates', 'full_text_screening', 'study_matrix', 'acquisitions', 'acquired', 'evidence', 'authorized_uploads'].includes(key)))));
  });
  if (blocks.studies?.studies?.length) detailPart(node, 'studies', 'All studies and article decisions', part => studyBlock(blocks.studies, part, snapshot, context));
  if (blocks.evidence?.length) detailPart(node, 'evidence', `Evidence passages (${blocks.evidence.length})`, part => evidenceBlock(blocks.evidence, part, snapshot, context));
  if (blocks.validation) detailPart(node, 'validation', 'Validation', part => part.append(expandable('Validation checks and review states', blocks.validation)));
  if (blocks.references?.length) detailPart(node, 'references', 'References', part => {
    for (const reference of blocks.references) {
      const p = element('p', `${reference.number ? `[${reference.number}] ` : ''}${reference.title || reference.publication_id}`);
      const doc = snapshot.documents?.[reference.publication_id];
      if (doc?.url || reference.source_url) p.append(document.createTextNode(' · '), safeLink('Open publication', doc?.url || reference.source_url));
      part.append(p);
    }
  });
  const artifacts = snapshot.artifacts || blocks.downloads || [];
  if (artifacts.length) detailPart(node, 'downloads', 'Downloads', part => { for (const a of artifacts) if (a.url) part.append(safeLink(a.filename || a.id || 'Download', a.url)); });
  return node;
}
export function renderDashboard(snapshot, context = {}) {
  const root = document.getElementById('dashboard-blocks');
  const key = `${context.projectId}:${snapshot.question}`;
  if (root.dataset.questionKey !== key && window.matchMedia('(max-width: 800px)').matches) document.querySelector('.history-panel').open = false;
  root.dataset.questionKey = key;
  root.replaceChildren();
  document.body.classList.add('dashboard-open');
  document.getElementById('dashboard-panel').hidden = false;
  root.dataset.dashboardRevision = snapshot.revision;
  document.getElementById('dashboard-question').textContent = snapshot.question;
  document.getElementById('dashboard-version').textContent = `Saved revision ${snapshot.revision}`;
  const analysis = snapshot.analysis || {};
  const retained = snapshot.blocks?.find(block => block.id === 'methods')?.data?.methodology?.model || {};
  const provider = analysis.provider || retained.provider;
  const model = analysis.model || retained.name;
  const actual = provider && model ? `${providerLabel(provider)} · ${model}` : null;
  const method = analysis.method || retained.method;
  const usedFallback = Boolean(analysis.fallback_reason || method === 'deterministic_extractive_fallback' || (analysis.status && !['complete', 'coverage_limited'].includes(analysis.status)));
  const selected = analysis.selection;
  const fallback = usedFallback ? `Extractive analysis${selected ? ` · selected: ${providerLabel(selected.provider)} · ${selected.model}` : ''}${analysis.fallback_reason ? ` — ${analysis.fallback_reason}` : ''}` : null;
  document.getElementById('dashboard-model').textContent = fallback || (actual ? `Analysis model: ${actual}` : ['complete', 'coverage_limited'].includes(analysis.status) ? 'AI was used · model not recorded' : 'Analysis model: not recorded for this saved result');
  const dataset = snapshot.blocks?.find(b => b.data?.data_analysis)?.data.data_analysis;
  const combined = dataset?.strategy?.route === 'both' || dataset?.literature_status === 'complete';
  if (dataset) {
    const discovery = dataset.discovery;
    document.getElementById('dashboard-model').textContent = discovery
      ? `Source discovery and assessment: ${discovery.provider} · ${discovery.model} · Calculations from downloaded data${combined && actual ? ' · Literature: ' + actual : ''}`
      : dataset.kind === 'discovered' ? 'Dataset discovery unavailable — see the recorded reason'
      : 'Reproducible data calculations · no AI-generated numerical values';
  }
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

  const blocks = Object.fromEntries((snapshot.blocks || []).filter(b => b.status === 'ready').map(b => [b.id, b.data]));
  const summary = snapshot.summary || {};
  root.append(answerSection(summary, blocks.answer || {}, snapshot));
  if (summary.data && blocks.answer?.data_analysis) root.append(dataSection(summary, blocks.answer.data_analysis));
  // Literature content can exist without screening counts, for example in older saved results.
  const literature = summary.literature || blocks.findings?.claims?.length || blocks.comparisons?.contradiction_groups?.length || (blocks.literature_review && Object.keys(blocks.literature_review).length);
  if (literature) root.append(literatureSection(summary, blocks, snapshot));
  const why = whySection(summary); if (why) root.append(why);
  if (blocks.landscape) root.append(landscapeSection(summary, blocks.landscape));
  root.append(detailsSection(blocks, snapshot, context));
}

