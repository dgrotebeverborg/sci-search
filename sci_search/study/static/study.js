// Study plans page. All source and model text is set with textContent, never as HTML.
const HEADINGS = {
  question: 'Question as understood', critique: 'Questions about the question', definitions: 'Definitions', subquestions: 'Sub-questions',
  scope: 'Scope and assumptions', out_of_reach: 'Out of reach', existing_work: 'Existing studies and models',
  data: 'Data', chapters: 'Chapters', limits: 'Limits of this plan',
};
const METHODS = ['literature', 'data', 'model', 'synthesis'];
const $ = id => document.getElementById(id);
let current = null;      // detail of the open study
let viewing = null;      // version number being viewed, null = current
let changed = [];        // sections changed by the last revision
let pollTimer = null;

function el(tag, text = '', className = '') {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function link(text, url) {
  if (!url || !/^https?:\/\//i.test(url)) return el('span', text);
  const a = el('a', text); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || 'GET',
    headers: options.body ? {'Content-Type': 'application/json'} : {},
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}
function status(target, message, error = false) {
  target.textContent = message; target.classList.toggle('error', error);
}

async function loadStudies() {
  const list = $('studies'); list.replaceChildren();
  for (const study of await api('/api/studies')) {
    const item = el('li');
    const a = link(study.question, '#'); a.href = `#${study.id}`;
    a.setAttribute('aria-current', String(current?.study.id === study.id));
    a.onclick = event => { event.preventDefault(); changed = []; openStudy(study.id); };
    const date = new Date(study.created_at).toLocaleDateString(undefined, {day: 'numeric', month: 'short'});
    item.append(a, el('span', `${date} · ${study.status}${study.version ? ` · v${study.version}` : ''}`, 'meta'));
    list.append(item);
  }
}

function showStart() {
  clearTimeout(pollTimer); current = null; viewing = null; changed = [];
  $('start').hidden = false; $('study').hidden = true;
  history.replaceState(null, '', '/');
  loadStudies();
}

async function openStudy(id, {keepView = false} = {}) {
  clearTimeout(pollTimer);
  try {
    current = await api(`/api/studies/${id}`);
  } catch (error) { status($('start-status'), error.message, true); showStart(); return; }
  if (!keepView) viewing = null;
  history.replaceState(null, '', `#${id}`);
  $('start').hidden = true; $('study').hidden = false;
  render();
  loadStudies();
  if (current.study.status === 'scanning' || current.study.working) {
    pollTimer = setTimeout(() => openStudy(id, {keepView: true}), 2000);
  }
}

async function render() {
  const {study} = current;
  $('study-question').textContent = study.question;
  const busy = study.status === 'scanning' || study.working;
  const approved = study.status === 'approved';
  const progress = $('progress'); progress.replaceChildren();
  if (busy) for (const item of study.progress.slice(-8)) progress.append(el('li', item.message));
  status($('study-status'),
    study.status === 'failed' ? `The plan could not be made: ${study.error}` :
    study.error ? study.error :
    study.notice && !busy ? study.notice :
    busy ? 'Working… this can take a few minutes. You can leave this page and come back.' :
    approved ? `Approved (version ${study.approved_version}).` : '',
    study.status === 'failed' || Boolean(study.error));
  $('approve').hidden = approved || !study.version; $('approve').disabled = busy;
  $('reopen').hidden = !approved;
  $('download').hidden = !study.version;
  $('download').href = `/api/studies/${study.id}/plan.md`;
  await renderVersions();
  let plan = current.plan;
  if (viewing && viewing !== study.version) plan = (await api(`/api/studies/${study.id}/versions/${viewing}`)).plan;
  const readOnly = approved || busy || (viewing && viewing !== study.version);
  $('restore').hidden = !(viewing && viewing !== study.version) || approved;
  renderPlan(plan, readOnly);
}

async function renderVersions() {
  const select = $('versions'); select.replaceChildren();
  if (!current.study.version) { select.disabled = true; return; }
  select.disabled = false;
  for (const v of await api(`/api/studies/${current.study.id}/versions`)) {
    const option = el('option', `v${v.version} · ${v.origin}`.slice(0, 80)); option.value = v.version;
    select.append(option);
  }
  select.value = String(viewing || current.study.version);
}

function sourceIndex() {
  const index = {};
  for (const item of [...current.scan_items.publications, ...current.scan_items.datasets]) index[item.id] = item;
  return index;
}

function renderValue(section, value, box) {
  const sources = sourceIndex();
  const list = (items, draw) => {
    if (!items?.length) { box.append(el('p', 'None.', 'muted')); return; }
    const ul = el('ul'); for (const item of items) { const li = el('li'); draw(li, item); ul.append(li); } box.append(ul);
  };
  if (section === 'question') box.append(el('p', value));
  else if (section === 'critique') {
    if (!value.length) { box.append(el('p', 'None.', 'muted')); return; }
    const intro = el('p', 'Points a critical reviewer raises about the question itself. Adopt one to reshape the plan, or dismiss it.', 'muted');
    box.append(intro);
    value.forEach((point, index) => {
      const card = el('div', '', `point point-${point.status}`);
      card.append(el('strong', point.issue), el('div', point.why), el('div', 'Alternative: ' + point.alternative));
      if (point.status !== 'open') card.append(el('span', point.status === 'adopted' ? 'Adopted' : 'Dismissed', 'point-status'));
      else if (!box.readOnly) {
        const row = el('div', '', 'tools');
        const message = el('p', '', 'status');
        const adopt = el('button', 'Adopt', 'button'); adopt.type = 'button';
        const dismiss = el('button', 'Dismiss', 'button'); dismiss.type = 'button';
        const send = async (verb, button, wait) => {
          button.disabled = true; if (wait) status(message, 'Reshaping the plan… this takes a minute.');
          try {
            const result = await api(`/api/studies/${current.study.id}/critique/${index}/${verb}`, {method: 'POST'});
            changed = result.changed || ['critique']; await openStudy(current.study.id);
          } catch (error) { status(message, error.message, true); button.disabled = false; }
        };
        adopt.onclick = () => send('adopt', adopt, true);
        dismiss.onclick = () => send('dismiss', dismiss, false);
        row.append(adopt, dismiss); card.append(row, message);
      }
      box.append(card);
    });
  }
  else if (section === 'definitions') list(value, (li, d) => li.append(el('strong', d.term + ': '), document.createTextNode(d.definition)));
  else if (section === 'subquestions') list(value, (li, q) => li.append(el('strong', q.id + ' '), document.createTextNode(q.text)));
  else if (section === 'out_of_reach') list(value, (li, o) => li.append(el('strong', o.item), document.createTextNode(' — ' + o.reason)));
  else if (section === 'existing_work' || section === 'data') list(value, (li, w) => {
    const source = sources[w.scan_id] || {title: w.scan_id};
    li.append(link(source.title || w.scan_id, source.url));
    const extra = [source.year, source.publisher, source.kind === 'model' ? 'model or scenario study' : ''].filter(Boolean).join(' · ');
    if (extra) li.append(el('span', extra, 'source-kind'));
    li.append(el('div', w.why || w.provides));
  });
  else if (section === 'chapters') {
    if (!value.length) box.append(el('p', 'None.', 'muted'));
    value.forEach((c, i) => {
      const card = el('div', '', 'chapter');
      const title = el('strong', `${i + 1}. ${c.title}`); card.append(title, el('span', c.method, 'method'));
      card.append(el('div', 'Goal: ' + c.goal), el('div', 'Answers: ' + c.answers.join(', ')), el('div', 'Output: ' + c.output));
      box.append(card);
    });
  } else list(value, (li, text) => li.append(document.createTextNode(text)));
}

// Plain-text editing formats per section; chapters use a small form instead.
const LINES = {
  definitions: [d => `${d.term}: ${d.definition}`, line => { const [term, ...rest] = line.split(':'); return {term: term.trim(), definition: rest.join(':').trim()}; }],
  subquestions: [q => `${q.id}: ${q.text}`, line => { const [id, ...rest] = line.split(':'); return {id: id.trim(), text: rest.join(':').trim()}; }],
  out_of_reach: [o => `${o.item} — ${o.reason}`, line => { const [item, ...rest] = line.split(' — '); return {item: item.trim(), reason: rest.join(' — ').trim()}; }],
  existing_work: [w => `${w.scan_id}: ${w.why}`, line => { const [id, ...rest] = line.split(':'); return {scan_id: id.trim(), why: rest.join(':').trim()}; }],
  data: [d => `${d.scan_id}: ${d.provides}`, line => { const [id, ...rest] = line.split(':'); return {scan_id: id.trim(), provides: rest.join(':').trim()}; }],
  critique: [c => `${c.issue} — ${c.why} — ${c.alternative}`, line => { const [issue, why, ...rest] = line.split(' — '); return {issue: (issue || '').trim(), why: (why || '').trim(), alternative: rest.join(' — ').trim(), status: 'open'}; }],
  scope: [s => s, s => s.trim()],
  limits: [s => s, s => s.trim()],
};
const HINTS = {
  critique: 'One per line: issue — why it matters — alternative', definitions: 'One per line: term: definition', subquestions: 'One per line: Q1: question',
  out_of_reach: 'One per line: item — reason', existing_work: 'One per line: P1: why it matters',
  data: 'One per line: D1: what it provides', scope: 'One assumption per line', limits: 'One per line',
};

function chapterForm(chapter = {title: '', goal: '', method: 'literature', answers: [], output: ''}) {
  const form = el('div', '', 'chapter-form');
  const field = (label, value) => { const input = el('input'); input.type = 'text'; input.value = value; input.setAttribute('aria-label', label); input.placeholder = label; return input; };
  const title = field('Title', chapter.title), goal = field('Goal', chapter.goal);
  const method = el('select'); method.setAttribute('aria-label', 'Method');
  for (const m of METHODS) method.append(new Option(m, m)); method.value = chapter.method;
  const answers = field('Answers (e.g. Q1, Q2)', chapter.answers.join(', ')), output = field('Output', chapter.output);
  const remove = el('button', 'Remove chapter', 'button'); remove.type = 'button'; remove.onclick = () => form.remove();
  form.append(title, goal, method, answers, output, remove);
  form.read = () => ({title: title.value.trim(), goal: goal.value.trim(), method: method.value,
    answers: answers.value.split(',').map(a => a.trim()).filter(Boolean), output: output.value.trim()});
  return form;
}

function editor(section, value, box, done) {
  box.replaceChildren();
  let read;
  if (section === 'chapters') {
    const forms = el('div'); value.forEach(c => forms.append(chapterForm(c)));
    const add = el('button', '+ Add chapter', 'button'); add.type = 'button'; add.onclick = () => forms.append(chapterForm());
    box.append(forms, add);
    read = () => [...forms.children].map(f => f.read());
  } else {
    const area = el('textarea'); area.rows = section === 'question' ? 4 : Math.max(4, value.length + 1);
    area.setAttribute('aria-label', HEADINGS[section]);
    if (HINTS[section]) area.placeholder = HINTS[section];
    area.value = section === 'question' ? value : value.map(LINES[section][0]).join('\n');
    box.append(area);
    read = () => section === 'question' ? area.value.trim()
      : area.value.split('\n').map(l => l.trim()).filter(Boolean).map(LINES[section][1]);
  }
  const message = el('p', '', 'status');
  const save = el('button', 'Save', 'button primary'); save.type = 'button';
  const cancel = el('button', 'Cancel', 'button'); cancel.type = 'button'; cancel.onclick = done;
  save.onclick = async () => {
    save.disabled = true;
    try {
      await api(`/api/studies/${current.study.id}/edit`, {method: 'POST', body: {section, value: read()}});
      changed = [section]; await openStudy(current.study.id);
    } catch (error) { status(message, error.message, true); save.disabled = false; }
  };
  const row = el('div', '', 'tools'); row.append(save, cancel); box.append(row, message);
}

function renderPlan(plan, readOnly) {
  const root = $('plan'); root.replaceChildren();
  if (!plan) return;
  if (current.study.status === 'approved') root.append(el('p', 'This plan is approved. Reopen it to make changes.', 'approved-note'));
  for (const section of current.sections) {
    const node = el('section', '', 'section');
    const heading = el('h2', HEADINGS[section]);
    if (changed.includes(section) && !viewing) heading.append(el('span', 'Changed', 'changed'));
    const box = el('div'); box.readOnly = readOnly;
    node.append(heading, box);
    renderValue(section, plan[section] ?? (section === 'question' ? '' : []), box);
    if (!readOnly) {
      const tools = el('div', '', 'tools');
      const instruction = el('input'); instruction.type = 'text';
      instruction.placeholder = 'What should change?'; instruction.setAttribute('aria-label', `What should change in ${HEADINGS[section]}?`);
      const apply = el('button', 'Apply', 'button'); apply.type = 'button';
      const edit = el('button', 'Edit', 'button'); edit.type = 'button';
      const message = el('p', '', 'status');
      apply.onclick = async () => {
        if (!instruction.value.trim()) return;
        apply.disabled = true; status(message, 'Revising… this takes a minute.');
        try {
          const result = await api(`/api/studies/${current.study.id}/revise`, {method: 'POST', body: {section, instruction: instruction.value}});
          changed = result.changed; await openStudy(current.study.id);
          if (!result.changed.length) status($('study-status'), 'The model made no change.');
        } catch (error) { status(message, error.message, true); apply.disabled = false; }
      };
      instruction.onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); apply.click(); } };
      const value = plan[section] ?? (section === 'question' ? '' : []);
      edit.onclick = () => editor(section, value, box, () => { box.replaceChildren(); renderValue(section, value, box); });
      tools.append(instruction, apply, edit);
      node.append(tools);
      if (section === 'existing_work') {
        const more = el('div', '', 'tools');
        const terms = el('input'); terms.type = 'text'; terms.placeholder = 'Search more, e.g. hydrogen storage, seasonal storage';
        terms.setAttribute('aria-label', 'Search more terms');
        const go = el('button', 'Search more', 'button'); go.type = 'button';
        go.onclick = async () => {
          const list = terms.value.split(',').map(t => t.trim()).filter(Boolean);
          if (!list.length) return;
          go.disabled = true;
          try { await api(`/api/studies/${current.study.id}/search`, {method: 'POST', body: {terms: list}}); await openStudy(current.study.id); }
          catch (error) { status(message, error.message, true); go.disabled = false; }
        };
        more.append(terms, go); node.append(more);
      }
      node.append(message);
    }
    root.append(node);
  }
}

async function action(path, body) {
  try { await api(`/api/studies/${current.study.id}/${path}`, {method: 'POST', body}); changed = []; await openStudy(current.study.id); }
  catch (error) { status($('study-status'), error.message, true); }
}

async function init() {
  const info = await api('/api/status');
  $('model').textContent = info.model ? `AI model: ${info.model}` : 'No AI model is configured.';
  if (!info.model) { $('question').disabled = true; status($('start-status'), 'No AI model is configured. Set one up in .env.local and restart.', true); }
  $('start-form').onsubmit = async event => {
    event.preventDefault();
    const button = event.submitter; button.disabled = true;
    try { const {id} = await api('/api/studies', {method: 'POST', body: {question: $('question').value}}); $('question').value = ''; changed = []; await openStudy(id); }
    catch (error) { status($('start-status'), error.message, true); }
    finally { button.disabled = false; }
  };
  $('new-study').onclick = showStart;
  $('approve').onclick = () => action('approve');
  $('reopen').onclick = () => action('reopen');
  $('versions').onchange = () => { const n = Number($('versions').value); viewing = n === current.study.version ? null : n; changed = []; render(); };
  $('restore').onclick = () => { const n = viewing; viewing = null; action('restore', {version: n}); };
  const id = location.hash.slice(1);
  if (/^[0-9a-f]{12}$/.test(id)) openStudy(id); else showStart();
}
init();
