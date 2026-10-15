// Clickable versions of a research question and choices per detail, before a search starts.
// Every change is applied by the server (POST …/interpret/adjust), which keeps the literature
// plan and the data strategy consistent; this module only renders and sends clicks.
import {request} from './api.js';

const ROUTES = {literature: 'Literature review', data: 'Find and analyse datasets', both: 'Datasets and literature'};
const STEERS = [['narrower', 'Narrower'], ['broader', 'Broader'], ['more_data', 'More data'], ['more_literature', 'More literature']];

function node(tag, text = '', className = '') {
  const item = document.createElement(tag);
  if (text) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function chip(text, onClick, {selected = false} = {}) {
  const button = node('button', text, 'choice-chip'); button.type = 'button';
  button.setAttribute('aria-pressed', String(selected));
  button.onclick = onClick;
  return button;
}
function period(strategy, plan) {
  if (strategy?.start_year || strategy?.end_year) return `${strategy.start_year || 'earliest'}–${strategy.end_year || 'latest'}`;
  return plan?.time_terms?.join(', ') || 'Not restricted';
}
function geography(strategy, plan) {
  return plan?.geography_terms?.join(', ') || strategy?.geography || 'Not restricted';
}

// Renders cards, detail rows, steering and clarification into `container`.
// onBrief(brief) receives every chosen or adjusted brief; onInterpret(extra) asks for new options.
export function renderChoices(interpretation, {container, projectId, onBrief, onInterpret}) {
  const options = interpretation.options?.length
    ? interpretation.options
    : [{title: 'Your question', summary: interpretation.objective || '', closest: true, brief: interpretation, alternatives: {}}];
  let chosen = 0;
  let brief = options[0].brief;
  container.replaceChildren();

  if (interpretation.ambiguity === 'material' && interpretation.clarification_question) {
    const ask = node('div', '', 'choice-clarify');
    ask.append(node('h3', interpretation.clarification_question));
    const answers = node('div', '', 'choice-chips');
    for (const answer of interpretation.clarification_options || []) answers.append(chip(answer, () => onInterpret({clarification: answer})));
    answers.append(chip('Something else…', () => {
      const form = node('form', '', 'choice-edit');
      const input = node('input'); input.setAttribute('aria-label', 'Your answer'); input.maxLength = 300;
      const send = node('button', 'Use this answer', 'button button-secondary'); send.type = 'submit';
      form.append(input, send);
      form.onsubmit = event => { event.preventDefault(); if (input.value.trim()) onInterpret({clarification: input.value.trim()}); };
      answers.after(form); input.focus();
    }));
    ask.append(answers); container.append(ask);
  }

  const cards = node('div', '', 'choice-cards'); cards.setAttribute('aria-label', 'Versions of your question');
  const rows = node('div', '', 'choice-rows');
  options.forEach((option, index) => {
    const card = node('button', '', 'choice-card'); card.type = 'button';
    card.setAttribute('aria-pressed', String(index === chosen));
    if (option.closest) card.append(node('span', 'Closest to your question', 'choice-badge'));
    card.append(node('strong', option.title), node('span', option.summary, 'choice-summary'));
    const route = option.brief?.data_research?.route;
    if (route) card.append(node('span', ROUTES[route] || route, 'choice-route'));
    card.onclick = () => {
      chosen = index; brief = option.brief;
      for (const other of cards.children) other.setAttribute('aria-pressed', String(other === card));
      drawRows(); onBrief(brief);
    };
    cards.append(card);
  });
  if (options.length > 1 || interpretation.options?.length) container.append(node('h3', 'Versions of your question'), cards);
  container.append(rows);

  async function apply(detail, value, row) {
    row.querySelector('.choice-error')?.remove();
    try {
      brief = await request(`/api/v1/projects/${encodeURIComponent(projectId)}/runs/interpret/adjust`, {method: 'POST', body: {brief, change: {detail, value}}});
      drawRows(); onBrief(brief);
    } catch (error) {
      row.append(node('p', error.message, 'choice-error'));
    }
  }
  function editForm(row, fields, toValue) {
    row.querySelector('.choice-edit')?.remove();
    const form = node('form', '', 'choice-edit');
    const inputs = fields.map(([label, type, value]) => {
      const input = node('input'); input.type = type; input.value = value ?? ''; input.setAttribute('aria-label', label);
      if (type === 'number') { input.min = '1800'; input.max = '2100'; }
      form.append(input); return input;
    });
    const save = node('button', 'Apply', 'button button-secondary'); save.type = 'submit'; form.append(save);
    form.onsubmit = event => {
      event.preventDefault();
      const change = toValue(inputs.map(input => input.value.trim()));
      apply(change.detail, change.value, row);
    };
    row.append(form); inputs[0].focus();
    return form;
  }
  function row(label, current, choices, edit) {
    const item = node('div', '', 'choice-row'); item.dataset.detail = label.toLowerCase();
    item.append(node('span', label, 'choice-label'), node('span', current, 'choice-current'));
    const chips = node('div', '', 'choice-chips');
    for (const [text, onClick, selected] of choices) chips.append(chip(text, () => onClick(item), {selected}));
    if (edit) chips.append(chip('Edit…', () => edit(item)));
    item.append(chips);
    return item;
  }
  function drawRows() {
    rows.replaceChildren();
    const strategy = brief.data_research;
    const plan = brief.research_plan;
    if (strategy && strategy.adapter && strategy.adapter !== 'discovered_data_v1') return;
    const alternatives = options[chosen].alternatives || {};
    const route = strategy?.route || 'literature';
    rows.append(row('Approach', ROUTES[route], Object.entries(ROUTES).map(([value, text]) => [text, item => apply('route', value, item), value === route]), null));
    const measurements = strategy?.measurements || [];
    const measurementRow = row('Measurements', measurements.join(', ') || (route === 'literature' ? 'None — not needed for a literature review' : 'Required for data research'),
      (alternatives.measurements || []).map(names => [names.join(', '), item => apply('measurements', names, item), names.join() === measurements.join()]),
      item => editForm(item, [['Measurements, separated by commas', 'text', measurements.join(', ')]], ([text]) => ({detail: 'measurements', value: text.split(',').map(v => v.trim()).filter(Boolean)})));
    if (route !== 'literature' && !measurements.length) measurementRow.classList.add('choice-required');
    rows.append(measurementRow);
    rows.append(row('Geography', geography(strategy, plan),
      (alternatives.geography || []).map(place => [place.label, item => apply('geography', place, item), false]),
      item => editForm(item, [['Geography', 'text', geography(strategy, plan)]], ([text]) => ({detail: 'geography', value: {label: text, geography_terms: text ? [text] : [], countries: []}}))));
    rows.append(row('Period', period(strategy, plan),
      (alternatives.period || []).map(value => [value.label || `${value.start_year || ''}–${value.end_year || ''}`, item => apply('period', value, item), false]),
      item => editForm(item, [['First year', 'number', strategy?.start_year], ['Last year', 'number', strategy?.end_year]], ([start, end]) => ({detail: 'period', value: {label: '', start_year: start ? Number(start) : null, end_year: end ? Number(end) : null}}))));
    const steer = node('div', '', 'choice-steer');
    steer.append(node('span', 'Other versions:', 'choice-label'));
    for (const [direction, text] of STEERS) steer.append(chip(text, () => onInterpret({steer: {direction, option: {title: options[chosen].title, interpreted_question: brief.interpreted_question, research_plan: brief.research_plan, research_strategy: brief.data_research}}})));
    rows.append(steer);
  }
  drawRows();
  onBrief(brief);
}
