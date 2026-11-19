import {element, dataTable, safeLink} from './dashboard.js';
const format = value => value == null ? 'Missing' : Number(value).toLocaleString('en-GB', {maximumFractionDigits: 1});
const observation = value => value == null ? 'Missing' : Number(value).toLocaleString('en-GB', {maximumSignificantDigits: 15});
function axisScale(values) {
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  const roughStep = (high - low || 1) / 6;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const step = [1, 2, 2.5, 5, 10].find(n => n * magnitude >= roughStep) * magnitude;
  const min = Math.floor(low / step) * step;
  const max = high === low ? min + step * 5 : Math.ceil(high / step) * step;
  return {min, max, step};
}
function executionDetails(analysis, parent) {
  if (!analysis.execution) return;
  const details = element('details');
  details.append(element('summary', 'Executed Python and validation'));
  details.append(element('p', 'The displayed values were checked against an executed Python script. Download all includes the original files, scripts, dependencies and offline replay.'));
  for (const check of analysis.execution.checks || []) details.append(element('p', check));
  const extraction = analysis.python_extraction;
  if (extraction) {
    details.append(element('p', `The model wrote and executed the extraction in ${extraction.attempts} attempt(s).`));
    details.append(element('p', 'Model review: ' + (extraction.review?.reason || 'Not recorded')));
    for (const assumption of extraction.assumptions || []) details.append(element('p', 'Assumption: ' + assumption));
    for (const decision of extraction.reflection || []) details.append(element('p', 'Extraction review: ' + decision.reason));
    details.append(element('p', 'Model review does not replace expert validation.'));
  }
  parent.append(details);
}
function chart(rows, metric, title, unit) {
  const section = element('section', '', 'data-chart');
  section.append(element('h3', title + ' (' + unit + ')'));
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', '0 0 720 240'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', `${title}. Fixed reporting panel. Values and source references in the annual table.`);
  const values = rows.map(r => r[metric]).filter(v => v != null);
  const {min, max, step: tickStep} = axisScale(values);
  const span = max - min;
  const add = (tag, attrs, text) => { const node = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k,v]) => node.setAttribute(k, v)); if (text) node.textContent = text; svg.append(node); return node; };
  const tickCount = Math.round(span / tickStep);
  for (let index = 0; index <= tickCount; index++) {
    const value = Number((min + index * tickStep).toPrecision(12));
    const y = 195 - (value - min) / span * 168;
    add('line', {x1:90,x2:690,y1:y,y2:y,stroke:'#dce4df'});
    add('text', {x:80,y:y+4,'text-anchor':'end','font-size':12,fill:'#42554a'}, observation(Object.is(value, -0) ? 0 : value));
  }
  let points = [];
  const flush = () => { if (points.length) add('polyline', {points:points.join(' '),fill:'none',stroke:'#28604a','stroke-width':2}); points = []; };
  rows.forEach((row,i) => {
    const x = 90 + i * 600 / Math.max(1, rows.length - 1);
    if (row[metric] == null) { flush(); return; }
    const y = 195 - (row[metric] - min) / span * 168;
    points.push(`${x},${y}`);
    const point = add('circle',{cx:x,cy:y,r:3,fill:'#28604a',tabindex:0});
    const hint = document.createElementNS(ns,'title'); hint.textContent = `${row.year}: ${observation(row[metric])} ${unit}`; point.append(hint);
    if (i === 0 || i === rows.length - 1 || i % 5 === 0) add('text',{x,y:218,'text-anchor':'middle','font-size':12},String(row.year));
  });
  flush(); section.append(svg); return section;
}
export function renderDataResearch(data, parent) {
  if (data.kind === 'discovered') { renderDiscovered(data, parent); return; }
  executionDetails(data, parent);
  meaningDetails(data.semantic_review, parent);
  const note = element('aside', '', 'landscape-shared-reason');
  note.append(element('strong', 'A reporting panel, not all Europe'));
  note.append(element('p', `${data.panel_countries.length} of ${data.requested_countries.length} requested countries have both measures for every available year. Missing requested years: ${data.missing_years.join(', ') || 'none'}. Coverage consistency does not guarantee unchanged reporting methods.`));
  parent.append(note);
  const countryNames = codes => codes.map(code => data.country_names?.[code] || code).join(', ');
  const countries = element('details'); countries.append(element('summary','Countries included and missing'));
  countries.append(element('p', `Fixed panel: ${countryNames(data.panel_countries)}`));
  countries.append(element('p', `Requested country set: ${countryNames(data.requested_countries)}`)); parent.append(countries);
  parent.append(element('p', data.source.definition));
  const charts = element('div', '', 'data-charts');
  charts.append(chart(data.annual,'panel_fires','Reported forest fires','fires'),chart(data.annual,'panel_burned_area_km2','Burned area','km²')); parent.append(charts);
  parent.append(element('h3','First five years versus last five years'));
  if (!data.comparisons.length) parent.append(element('p','Not calculated: a continuous fixed panel of at least ten years is required.'));
  for (const c of data.comparisons) parent.append(element('p',`${c.unit}: mean ${format(c.first_mean)} (${c.first_period.join('–')}) → ${format(c.last_mean)} (${c.last_period.join('–')}); ${c.change_percent == null ? 'percentage change undefined because the initial mean is zero' : format(c.change_percent) + '% change'}. Descriptive comparison only.`));
  const table = element('details'); table.append(element('summary','Annual values and coverage'));
  table.append(dataTable(data.annual.map(r => ({year:r.year, fires:observation(r.panel_fires), area:observation(r.panel_burned_area_km2), coverage:`${r.reporting_countries}/${data.requested_countries.length}`,missing:countryNames(r.missing_countries)})),[['year','Year'],['fires','Panel fires'],['area','Panel km²'],['coverage','Countries reporting'],['missing','Missing countries']])); parent.append(table);
  parent.append(element('h3','Source and reproducibility'),safeLink(data.source.title,data.source.url),element('p',data.source.attribution),element('p',`Retrieved ${data.source.retrieved_at}. Source SHA-256: ${data.source.sha256}`,'data-source-hash'),safeLink('Source licence',data.source.license_url));
  parent.append(element('p','Download all includes the original workbook, annual and country data, calculation metadata, and an offline reproduction script.'));
  const limitations = element('ul'); data.limitations.forEach(note => limitations.append(element('li',note))); parent.append(limitations);
}


function renderDerived(data, parent) {
  const completion = data.output_completion;
  // Without requested calculations, the input completeness is already in the summary.
  if (!completion || (!(data.derived_outputs?.outputs || []).length && ['not_requested', 'not_assessed'].includes(completion.calculation_status))) return;
  const section = element('section', '', 'derived-outputs');
  section.append(element('h3', 'Requested calculations'));
  const inputs = {complete: 'Requested input data complete', partial: 'Requested input data incomplete', blocked: 'Requested input data unavailable'};
  const calculations = {complete: 'Requested calculations complete', partial: 'Requested calculations partly available', blocked: 'Requested calculations unavailable', not_assessed: 'Requested calculations have not been assessed', not_requested: 'No additional calculations requested'};
  section.append(element('p', inputs[completion.data_status] || completion.data_status));
  section.append(element('p', calculations[completion.calculation_status] || completion.calculation_status));
  section.append(element('strong', completion.numerical_answer_status === 'complete' ? 'Requested numerical outputs complete' : completion.numerical_answer_status === 'not_assessed' ? 'Numerical answer completeness not assessed' : 'Requested numerical outputs incomplete'));
  section.append(element('p', completion.qualification || ''));
  const derived = data.derived_outputs || {};
  if (derived.reason) section.append(element('p', derived.reason));
  for (const output of derived.outputs || []) {
    const details = element('details'); details.open = (derived.outputs || []).length <= 6;
    details.append(element('summary', `${output.entity} — ${output.label} · ${output.status}`));
    if (output.reason) details.append(element('p', output.reason));
    if (output.formula) details.append(element('p', 'Calculation: ' + output.formula));
    if (output.annual.some(row => row.value != null)) details.append(chart(output.annual, 'value', output.entity + ' — ' + output.label, output.unit));
    // A table of only missing years says nothing the reason above does not.
    if (output.annual.some(row => row.value != null)) details.append(dataTable(output.annual.map(row => ({year: row.year, value: observation(row.value), reason: row.reason || '', inputs: (row.inputs || []).map(input => `${input.role} (${input.year}): ${input.observation?.source_reference || input.observation?.source_row || 'No source observation'}`).join('; ')})), [['year', 'Year'], ['value', output.unit || 'Value'], ['reason', 'Missing input or limitation'], ['inputs', 'Input references']]));
    for (const source of output.sources || []) {
      const original = data.analyses[source.analysis_index]?.source;
      if (original) details.append(safeLink(source.role + ': ' + original.title, original.url));
    }
    if (output.semantic_review) meaningDetails(output.semantic_review, details);
    section.append(details);
  }
  executionDetails(derived, section);
  parent.append(section);
}

// Charts and values first; how the data were found and checked follows in one folded section.
function renderDiscovered(data, parent) {
  if (!(data.analyses || []).length) parent.append(element('p', 'No dataset gave a supported numerical answer.', 'help'));
  for (const analysis of data.analyses || []) {
    if (analysis.kind === 'wildfire') { renderDataResearch(analysis, parent); continue; }
    renderSeries(analysis, parent);
  }
  renderDerived(data, parent);
  const notUsed = (data.assessments || []).filter(item => item.decision !== 'analysed').length;
  const how = element('details', '', 'result-more data-provenance');
  // Without a usable dataset, why sources failed is the whole result of the data search.
  how.open = !(data.analyses || []).length;
  how.append(element('summary', `How the data were found and checked${notUsed ? ` · ${notUsed} ${notUsed === 1 ? 'source' : 'sources'} not used` : ''}`));
  provenance(data, how);
  parent.append(how);
}

function renderSeries(analysis, parent) {
  const heading = element('h3');
  heading.append(safeLink(analysis.source.title, analysis.source.url));
  if (analysis.source.publisher) heading.append(element('span', ' · ' + analysis.source.publisher, 'help'));
  parent.append(heading);
  for (const series of analysis.series || []) {
    const labels = analysis.preparation?.selection?.code_labels || {};
    const dims = series.annual.find(row => row.source_dimensions)?.source_dimensions;
    const display = dims ? (analysis.preparation.selection.series_dimensions || []).map(d => labels[d]?.[dims[d]] || dims[d]).join(' · ') : series.entity;
    const title = !display || display === series.label ? series.label : display + ' — ' + series.label;
    const unit = labels.unit?.[series.unit] || series.unit;
    let host = parent;
    let detail;
    if ((analysis.series || []).length > 10) {
      detail = element('details'); detail.append(element('summary', display)); parent.append(detail);
      host = element('div'); detail.append(host);
    }
    const draw = () => {
      host.append(chart(series.annual, 'value', title, unit));
      const observed = series.annual.filter(row => row.value != null);
      const span = observed.length > 1 ? `${observed[0].year}–${observed[observed.length - 1].year}` : '';
      const parts = [];
      const signed = (value, text) => (value > 0 ? '+' : '') + text;
      if (series.absolute_change != null) parts.push(`${signed(series.absolute_change, format(series.absolute_change))} ${series.absolute_change_unit || unit}`);
      if (series.change_percent != null) parts.push(`${signed(series.change_percent, format(series.change_percent))}%`);
      if (parts.length) host.append(element('p', `Change ${span}: ${parts.join(' (')}${parts.length > 1 ? ')' : ''}. Descriptive only.`));
      else if (series.change_note) host.append(element('p', series.change_note));
      if ((series.missing_years || []).length) host.append(element('p', 'Missing years: ' + series.missing_years.join(', '), 'help'));
      if (series.comparability_note) host.append(element('p', series.comparability_note, 'help'));
      const table = element('details'); table.append(element('summary', 'Annual values and source rows'));
      table.append(dataTable(series.annual.map(r => ({year:r.year,value:observation(r.value),row:r.source_reference || r.source_row || 'No source observation',status:r.source_status || 'Not specified'})), [['year','Year'],['value',unit],['row','Source row'],['status','Reporting status']]));
      host.append(table);
    };
    if (detail) detail.addEventListener('toggle', () => { if (detail.open && !host.childElementCount) draw(); });
    else draw();
  }
}

function provenance(data, parent) {
  if (data.coverage) {
    const cells = data.coverage.cells || [];
    parent.append(element('p', `${cells.filter(c => c.status === 'complete').length} of ${cells.length} requested combinations covered. Coverage does not establish scientific validity.`));
    for (const [measurement, choice] of Object.entries(data.coverage.source_choices || {})) {
      const source = data.analyses[choice.source_index].source;
      parent.append(element('p', `Chosen definition for ${measurement}: ${choice.definition}. Source: ${source.title}. Alternative sources remain separate and are not combined in this comparison.`));
    }
    if ((data.coverage.gaps || []).length) {
      const gaps = element('details');
      gaps.append(element('summary', 'Missing coverage'));
      for (const gap of data.coverage.gaps) {
        gaps.append(element('p', `${gap.measurement} · ${gap.entity} · ${Object.entries(gap.dimensions || {}).map(([k,v]) => k + ': ' + v).join(', ')} — ${gap.reason}`));
        if ((gap.missing_years || []).length) gaps.append(element('p', 'Missing years: ' + gap.missing_years.join(', ')));
      }
      parent.append(gaps);
    }
  }
  const completion = data.output_completion;
  if (completion?.calculation_status && completion.calculation_status !== 'not_requested') {
    parent.append(element('p', completion.numerical_answer_status === 'complete' ? 'Requested numerical outputs complete.' : 'Requested numerical outputs incomplete.'));
  }
  if (data.run_control?.stop_reason) parent.append(element('p', 'Stopped: ' + data.run_control.stop_reason));
  if (data.literature_fallback) parent.append(element('p', data.literature_fallback));
  for (const gap of data.connector_gaps || []) parent.append(element('p', 'Needs an API connector for ' + gap.host + ' (' + gap.measurement + ')'));
  const period = data.period;
  if (period) {
    parent.append(element('p', 'Requested period: ' + period.requested));
    const coverage = element('details'); coverage.append(element('summary', 'Analysed period per series'));
    for (const row of period.analysed || []) {
      coverage.append(element('p', (row.first_year == null ? 'No numeric observations' : row.first_year + '–' + row.last_year) + ' · ' + row.source + ' · ' + row.entity + ((row.missing_years || []).length ? ' · Missing years: ' + row.missing_years.join(', ') : '')));
    }
    coverage.append(element('p', period.qualification, 'help'));
    if ((period.analysed || []).length) parent.append(coverage);
  }
  if (data.followup) parent.append(element('p', 'Additional search for earlier data and missing coverage: ' + data.followup.status + '. Series with different definitions remain separate.'));
  const strategy = data.strategy || {};
  if ((strategy.measurements || []).length) parent.append(element('p', 'Requested measurements: ' + strategy.measurements.join(', ')));
  if (strategy.rationale) parent.append(element('p', 'Why this approach: ' + strategy.rationale, 'help'));
  const process = data.research_process;
  if (process) {
    const details = element('details');
    details.append(element('summary', 'Research attempts and stopping reason'));
    for (const step of process.steps || []) {
      details.append(element('p', 'Attempt ' + step.round + ': ' + step.reason + ' · ' + step.status));
      if (step.query) details.append(element('p', 'Search: ' + step.query));
      if (step.error) details.append(element('p', step.error));
      if (step.outcome) details.append(element('p', 'Outcome: ' + step.outcome.status + ' · ' + (step.outcome.reason || '')));
    }
    details.append(element('p', 'Stopped: ' + process.stop_reason), element('p', process.qualification));
    parent.append(details);
  }
  if (data.discovery) {
    const trace = element('details'); trace.append(element('summary', 'Web searches and consulted sources'));
    trace.append(element('p', 'Source discovery: ' + data.discovery.provider + ' · ' + data.discovery.model, 'help'));
    for (const action of [...(data.discovery.search_actions || []), ...(data.followup?.discovery?.search_actions || []), ...(data.research_process?.steps || []).flatMap(s => s.discovery?.search_actions || [])]) {
      if (action?.query || action?.queries) trace.append(element('p', action.query || action.queries.join('; ')));
    }
    for (const url of new Set([...(data.discovery.observed_urls || []), ...(data.followup?.discovery?.observed_urls || []), ...(data.research_process?.steps || []).flatMap(s => s.discovery?.observed_urls || [])])) { const p = element('p'); p.append(safeLink(url, url)); trace.append(p); }
    parent.append(trace);
  }
  for (const analysis of data.analyses || []) {
    if (analysis.kind === 'wildfire') continue;
    const source = element('details'); source.append(element('summary', 'Source checks: ' + analysis.source.title));
    source.append(safeLink('Open downloaded data source', analysis.source.url));
    if (analysis.source.definition) source.append(element('p', 'Source definition: ' + analysis.source.definition));
    if (analysis.source_verification) {
      const check = analysis.source_verification;
      source.append(element('p', `${check.value_verified} values checked directly against source bytes; ${check.unverified} values without an independently checked numeric reference. Meaning remains a separate review.`));
    }
    if (analysis.preparation?.format === 'statistical_tsv_v1') source.append(element('p', 'Source status codes: b = break in time series; p = provisional; e = estimated; d = differing definition; c = confidential. Combined codes retain each qualification.'));
    executionDetails(analysis, source);
    const meaningReviews = [analysis.semantic_review, ...(analysis.components || []).map(c => c.semantic_review)].filter(Boolean);
    const displayed = new Set();
    for (const review of meaningReviews) {
      const key = JSON.stringify(review);
      if (!displayed.has(key)) meaningDetails(review, source);
      displayed.add(key);
    }
    if (analysis.source.license_note) source.append(element('p', 'Licence assessment: ' + analysis.source.license_note));
    if (analysis.source.connector) source.append(element('p', 'Queried the ' + analysis.source.publisher + ' API: dataset ' + analysis.source.connector.dataset), safeLink('Exact request', analysis.source.connector.request.url));
    for (const note of analysis.limitations || []) source.append(element('p', note));
    if (analysis.source.sha256) source.append(element('p', 'Source SHA-256: ' + analysis.source.sha256, 'data-source-hash'));
    parent.append(source);
  }
  const decisions = element('details'); decisions.open = !(data.analyses || []).length;
  decisions.append(element('summary', 'Why sources were used or could not be used'));
  for (const item of [...(data.assessments || []), ...(data.discovery?.rejected || []), ...(data.followup?.discovery?.rejected || [])]) {
    const article = element('article');
    article.append(safeLink(item.title || item.url, item.url), element('p', ({analysed:'Used for analysis',blocked:'Not analysed',rejected:'Not verified',duplicate:'Already analysed'}[item.decision] || item.decision) + ': ' + item.reason));
    for (const step of item.recovery || []) article.append(element('p', 'Automatic recovery: ' + step.class + ' → ' + step.action + ' · ' + step.outcome));
    if (item.workbook_inspected) article.append(element('p', 'Workbook sheets and accompanying metadata inspected.'));
    for (const review of item.semantic_reviews || []) meaningDetails(review, article);
    meaningDetails(item.execution_review?.semantic_review, article);
    for (const attempt of item.reassessments || []) meaningDetails(attempt.execution_review?.semantic_review, article);
    if (item.python_error) article.append(element('p', 'Python extraction: ' + item.python_error));
    const attempts = [...(item.preparation_attempts || []), ...(item.transformation_attempts || [])];
    if (item.preparation_checks && Object.keys(item.preparation_checks).length) {
      const checks = item.preparation_checks;
      if (checks.input_series != null) article.append(element('p', `Statistical table checked: ${checks.selected_series} of ${checks.input_series} series selected; ${checks.output_rows} observations, including missing values. Quality flags retained.`));
      else article.append(element('p', `Table checked: ${checks.input_rows} source rows, ${checks.output_rows} prepared rows; ${checks.removed_empty_columns || 0} entirely empty trailing columns removed.`));
    }
    if (attempts.length) {
      const details = element('details'); details.append(element('summary', 'Data preparation attempts and checks'));
      for (const attempt of attempts) {
        details.append(element('p', `${attempt.status}: ${attempt.plan?.operation || attempt.plan?.reason || 'Read table'}. ${attempt.reason || attempt.previous_error || ''}`));
        if (attempt.checks) details.append(element('pre', JSON.stringify(attempt.checks, null, 2)));
      }
      article.append(details);
    }
    if (item.statistical_selection) article.append(element('p', item.statistical_selection.reason));
    if (item.worksheet_selection) article.append(element('p', item.worksheet_selection.reason));
    if (item.availability) article.append(element('p', item.availability === 'found_but_not_read' ? 'Source found, but data could not be read. This does not mean the data does not exist.' : 'Source found, but not usable for this question with the current analysis.'));
    if (item.model_assessment?.definition_quote) article.append(element('blockquote',item.model_assessment.definition_quote));
    for (const mapping of item.mapping_assessments || []) article.append(element('p', 'Column mapping assessment: ' + mapping.reason));
    for (const gap of item.mapping_gaps || []) article.append(element('p', gap.measurement + ': ' + gap.reason));
    decisions.append(article);
  }
  parent.append(decisions);
}


function meaningDetails(review, parent) {
  if (!review || typeof review !== 'object') return;
  const records = value => Array.isArray(value) ? value.filter(item => item && typeof item === 'object') : [];
  const details = element('details');
  details.open = !review.accepted;
  details.append(element('summary', review.accepted ? 'Measurement meaning checked against source passages' : 'Measurement meaning not confirmed — excluded from results'));
  details.append(element('p', review.reason), element('p', review.qualification || 'Interpretation is a model assessment.'));
  for (const measurement of records(review.measurements)) {
    details.append(element('h4', measurement.measurement));
    for (const check of records(measurement.checks)) {
      details.append(element('p', `${check.aspect}: ${check.status} · ${check.reason}`));
      for (const citation of records(check.evidence)) {
        details.append(element('blockquote', citation.quote), element('small', 'Source passage: ' + citation.document));
      }
    }
  }
  for (const question of Array.isArray(review.followup_questions) ? review.followup_questions : []) details.append(element('p', 'Documentation needed: ' + question));
  parent.append(details);
}

// ---- The answer view: one chart per dataset, its source, nothing about how it was checked.

const COLOURS = ['#28604a', '#c0790a', '#3b6fb6', '#a23b72', '#6b7a2a', '#5b5b5b'];
const MAX_LINES = 6;
// 'geo=AL (Albania) | sex=F (Females)' -> 'Albania, Females'
export const cleanName = text => String(text || '').replace(/\b[A-Za-z_]+=[\w-]+ \(([^)]*)\)/g, '$1').replaceAll(' | ', ', ').trim();
const UNIT_WORDS = {year: 'years', day: 'days', hour: 'hours', person: 'persons'};
function unitOf(analysis, series) {
  const label = analysis.preparation?.selection?.code_labels?.unit?.[series.unit] || series.unit || '';
  return UNIT_WORDS[String(label).toLowerCase()] || label;
}
function nameOf(analysis, series) {
  // Statistical tables name a series by its codes; their labels read better than the entity key.
  const selection = analysis.preparation?.selection || {};
  const dims = (series.annual || []).find(row => row.source_dimensions)?.source_dimensions;
  if (dims && (selection.series_dimensions || []).length) return selection.series_dimensions.map(d => selection.code_labels?.[d]?.[dims[d]] || dims[d]).join(', ');
  return cleanName(series.entity) || series.label || 'Series';
}

function lineChart(lines, unit) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 720 250');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', lines.map(l => l.name).join(', ') + (unit ? ` (${unit})` : ''));
  const add = (tag, attrs, text) => { const node = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v)); if (text != null) node.textContent = text; svg.append(node); return node; };
  const points = lines.flatMap(l => l.rows.filter(r => r.value != null));
  const years = points.map(r => r.year);
  const first = Math.min(...years), last = Math.max(...years);
  const {min, max, step} = axisScale(points.map(r => r.value));
  const x = year => 70 + (last === first ? 300 : (year - first) / (last - first) * 610);
  const y = value => 205 - (value - min) / (max - min) * 185;
  for (let v = min; v <= max + step / 2; v += step) {
    const value = Number(v.toPrecision(12));
    add('line', {x1: 70, x2: 680, y1: y(value), y2: y(value), stroke: '#e3e8e4'});
    add('text', {x: 62, y: y(value) + 4, 'text-anchor': 'end', 'font-size': 12, fill: '#5b6b62'}, observation(Object.is(value, -0) ? 0 : value));
  }
  const tick = Math.max(1, Math.ceil((last - first) / 6 / 5) * 5);
  for (let year = first; year <= last; year += tick) add('text', {x: x(year), y: 228, 'text-anchor': 'middle', 'font-size': 12, fill: '#5b6b62'}, String(year));
  if ((last - first) % tick) add('text', {x: x(last), y: 228, 'text-anchor': 'middle', 'font-size': 12, fill: '#5b6b62'}, String(last));
  lines.forEach((line, index) => {
    const colour = COLOURS[index % COLOURS.length];
    let path = [];
    const flush = () => { if (path.length > 1) add('polyline', {points: path.join(' '), fill: 'none', stroke: colour, 'stroke-width': 2.5}); path = []; };
    for (const row of line.rows) {
      if (row.value == null) { flush(); continue; }
      path.push(`${x(row.year)},${y(row.value)}`);
      const dot = add('circle', {cx: x(row.year), cy: y(row.value), r: line.rows.length > 40 ? 1.5 : 2.5, fill: colour});
      const hint = document.createElementNS(ns, 'title'); hint.textContent = `${line.name}, ${row.year}: ${observation(row.value)} ${unit}`; dot.append(hint);
    }
    flush();
  });
  return svg;
}

function legend(lines) {
  const row = element('p', '', 'chart-legend');
  lines.forEach((line, index) => {
    const item = element('span', line.name);
    item.style.setProperty('--swatch', COLOURS[index % COLOURS.length]);
    row.append(item);
  });
  return row;
}

function sourceLine(source) {
  const line = element('p', '', 'chart-source');
  line.append(document.createTextNode('Source: '));
  line.append(source.url ? safeLink(source.title || source.url, source.url) : element('span', source.title || 'Dataset'));
  if (source.publisher && !(source.title || '').includes(source.publisher)) line.append(document.createTextNode(` · ${source.publisher}`));
  return line;
}

export function answerCharts(data, parent) {
  const drawn = new Set();
  for (const analysis of data.analyses || []) {
    if (analysis.kind === 'wildfire') continue;
    const series = (analysis.series || []).filter(s => (s.annual || []).some(r => r.value != null));
    if (!series.length) continue;
    // Two sources with the same numbers are one chart.
    const key = JSON.stringify(series.map(s => [s.entity, s.label, s.annual.map(r => r.value)]));
    if (drawn.has(key)) continue;
    drawn.add(key);
    const unit = unitOf(analysis, series[0]);
    const short = cleanName(series[0].label).split(' by ')[0];
    const label = short.charAt(0).toUpperCase() + short.slice(1);
    const figure = element('figure', '', 'answer-chart');
    figure.append(element('figcaption', unit && !label.toLowerCase().includes(unit.toLowerCase()) ? `${label} (${unit})` : label));
    const lines = s => s.map(item => ({name: nameOf(analysis, item), rows: item.annual}));
    if (series.length <= MAX_LINES) {
      figure.append(lineChart(lines(series), unit));
      if (series.length > 1) figure.append(legend(lines(series)));
    } else {
      const pick = element('select'); pick.setAttribute('aria-label', 'Series to show');
      series.forEach((item, index) => { const option = element('option', nameOf(analysis, item)); option.value = String(index); pick.append(option); });
      const holder = element('div');
      const draw = () => holder.replaceChildren(lineChart(lines([series[Number(pick.value)]]), unit));
      pick.onchange = draw;
      const choose = element('label', `${series.length} series · show `, 'chart-pick'); choose.append(pick);
      figure.append(choose, holder);
      draw();
    }
    figure.append(sourceLine(analysis.source || {}));
    parent.append(figure);
  }
  // A requested calculation is the answer only when no measured series is; otherwise it repeats one.
  for (const output of drawn.size ? [] : data.derived_outputs?.outputs || []) {
    if (!(output.annual || []).some(r => r.value != null)) continue;
    const figure = element('figure', '', 'answer-chart');
    figure.append(element('figcaption', `${cleanName(output.entity)} — ${output.label}${output.unit ? ` (${output.unit})` : ''}`));
    figure.append(lineChart([{name: output.label, rows: output.annual}], output.unit || ''));
    if (output.formula) figure.append(element('p', 'Calculation: ' + output.formula, 'chart-source'));
    parent.append(figure);
  }
}

// ---- The details view: annual values, calculations and every check, folded.
export function dataDetails(data, parent) {
  if (data.kind !== 'discovered') { renderDataResearch(data, parent); return; }
  for (const analysis of data.analyses || []) {
    if (analysis.kind === 'wildfire') { renderDataResearch(analysis, parent); continue; }
    const values = element('details');
    values.append(element('summary', 'Annual values: ' + (analysis.source?.title || 'dataset')));
    renderSeries(analysis, values);
    parent.append(values);
  }
  renderDerived(data, parent);
  provenance(data, parent);
}
