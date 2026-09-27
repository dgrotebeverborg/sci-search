import {element, fields, dataTable, safeLink} from './dashboard.js';

const humanize = value => String(value || 'Not assessed').replaceAll('_', ' ');
function card(title, note = '') {
  const node = element('section', '', 'landscape-card');
  node.append(element('h3', title));
  if (note) node.append(element('p', note, 'landscape-note'));
  return node;
}
function ranking(title, rows, name = 'name') {
  const node = card(title, 'Publication counts within this saved search');
  if (!rows?.length) { node.append(element('p', 'No metadata available for this search.', 'landscape-note')); return node; }
  const max = Math.max(1, ...rows.map(row => Number(row.publications) || 0));
  for (const row of rows.slice(0, 6)) {
    const item = element('div', '', 'landscape-rank');
    item.append(element('span', humanize(row[name])), element('strong', String(row.publications || 0)));
    const track = element('div', '', 'landscape-rank-track');
    const fill = element('span'); fill.style.width = `${100 * (Number(row.publications) || 0) / max}%`;
    track.append(fill); item.append(track); node.append(item);
  }
  if (rows.length > 6) {
    const more = element('details'); more.append(element('summary', `View all ${rows.length}`));
    more.append(dataTable(rows, [[name, 'Name'], ['publications', 'Publications']])); node.append(more);
  }
  return node;
}

export function renderLandscape(data, parent) {
  parent.append(element('p', 'Explore when research was published, who contributed, and which topics appear in this search. Discovery counts describe this search, not the entire field.', 'section-intro'));
  const papers = data.papers || [];
  const included = papers.filter(p => ['include', 'included'].includes(p.screening?.decision));
  const years = (data.publication_timeline || []).map(row => Number(row.year)).filter(Number.isFinite);
  const stats = element('div', '', 'landscape-metrics');
  for (const [value, name] of [[data.coverage?.records ?? papers.length, 'Discovered studies'], [included.length, 'Included evidence studies'], [years.length ? `${Math.min(...years)}–${Math.max(...years)}` : 'Not available', 'Publication years']]) {
    const stat = element('div'); stat.append(element('strong', String(value)), element('span', name)); stats.append(stat);
  }
  parent.append(stats);
  const timeline = card('Research activity over time', 'Select a year to explore its studies. Bar height shows publication counts; only years with records are shown.');
  const population = element('select'); population.setAttribute('aria-label', 'Landscape population');
  for (const [value, title] of [['discovered', 'All discovered studies'], ['included', 'Included evidence studies']]) { const option = element('option', title); option.value = value; population.append(option); }
  const toolbar = element('div', '', 'landscape-toolbar');
  const clear = element('button', 'Show all years', 'button button-quiet'); clear.type = 'button';
  toolbar.append(population, clear); timeline.append(toolbar);
  const chart = element('div', '', 'landscape-timeline'); chart.setAttribute('aria-label', 'Publication timeline');
  timeline.append(chart); parent.append(timeline);

  const grid = element('div', '', 'landscape-grid');
  grid.append(ranking('Leading authors', data.top_authors), ranking('Contributing institutions', data.top_organizations));
  parent.append(grid);
  if (data.title_term_signals?.length) {
    const method = data.trend_method || {};
    const topics = card('Topics in the literature', `Title terms from all discovered studies${method.recent_from ? ` · ${method.baseline_from}–${method.baseline_to} compared with ${method.recent_from}–${method.recent_to}` : ''}. These signals describe titles, not scientific conclusions.`);
    const tiles = element('div', '', 'landscape-topics');
    for (const term of data.title_term_signals.slice(0, 8)) {
      const tile = element('div', '', 'landscape-topic');
      tile.append(element('span', humanize(term.classification), 'landscape-topic-label'), element('strong', term.term), element('span', `${term.baseline_publications ?? 0} → ${term.recent_publications ?? 0} publications`, 'landscape-note'));
      tiles.append(tile);
    }
    topics.append(tiles); parent.append(topics);
  }
  const browser = card('Explore the studies');
  const search = element('input'); search.type = 'search'; search.placeholder = 'Find a title or author'; search.setAttribute('aria-label', 'Search landscape studies');
  const resultCount = element('p', '', 'landscape-note'); resultCount.setAttribute('role', 'status');
  const paperList = element('div');
  const more = element('button', 'Show more studies', 'button button-secondary'); more.type = 'button';
  browser.append(search, resultCount, paperList, more); parent.append(browser);
  let selectedYear = null, limit = 12;
  function drawPapers() {
    const query = search.value.toLowerCase();
    const pool = population.value === 'included' ? included : papers;
    const filtered = pool.filter(p => (selectedYear == null || String(p.year) === String(selectedYear)) && `${p.title || ''} ${JSON.stringify(p.authors || [])}`.toLowerCase().includes(query));
    resultCount.textContent = `${filtered.length} studies${selectedYear ? ` from ${selectedYear}` : ''} · ${population.value === 'included' ? 'Included evidence' : 'All discovered'}${filtered.length > limit ? ` · Showing ${limit}` : ''}`;
    paperList.replaceChildren();
    if (filtered.length) paperList.append(dataTable(filtered.slice(0, limit).map(p => ({title: p.title || 'Untitled study', year: p.year || 'Unknown', decision: humanize(p.screening?.decision)})), [['title', 'Study'], ['year', 'Year'], ['decision', 'Evidence status']]));
    else paperList.append(element('p', 'No studies match these filters.', 'empty-state'));
    more.hidden = filtered.length <= limit;
  }
  function draw() {
    chart.replaceChildren();
    const pool = population.value === 'included' ? included : papers;
    const counts = {};
    pool.forEach(p => { if (p.year) counts[p.year] = (counts[p.year] || 0) + 1; });
    const rows = (population.value === 'discovered' && data.publication_timeline?.length ? data.publication_timeline : Object.entries(counts).map(([year, publications]) => ({year, publications}))).slice().sort((a, b) => Number(a.year) - Number(b.year));
    const max = Math.max(1, ...rows.map(r => Number(r.publications) || 0));
    if (!rows.length) chart.append(element('p', 'No dated publications in this selection.', 'empty-state'));
    chart.classList.toggle('dense', rows.length > 16);
    const stride = Math.max(1, Math.ceil(rows.length / 9));
    for (const [index, row] of rows.entries()) {
      const bar = element('button', '', 'landscape-year'); bar.type = 'button';
      bar.setAttribute('aria-label', `${row.year}: ${row.publications} publications`);
      bar.title = `${row.year}: ${row.publications} publications`;
      bar.setAttribute('aria-pressed', String(String(selectedYear) === String(row.year)));
      const column = element('span', '', 'landscape-column'); column.style.height = `${Math.max(3, 100 * Number(row.publications) / max)}%`;
      column.append(element('span', String(row.publications), 'landscape-bar-count'));
      const track = element('span', '', 'landscape-column-track'); track.append(column);
      bar.append(track, element('span', index % stride === 0 || index === rows.length - 1 ? String(row.year) : '', 'landscape-year-label'));
      bar.onclick = () => { selectedYear = String(selectedYear) === String(row.year) ? null : row.year; limit = 12; draw(); };
      chart.append(bar);
    }
    clear.disabled = selectedYear === null;
    drawPapers();
  }
  population.onchange = () => { selectedYear = null; limit = 12; draw(); };
  clear.onclick = () => { selectedYear = null; limit = 12; draw(); };
  search.oninput = () => { limit = 12; drawPapers(); };
  more.onclick = () => { limit += 12; drawPapers(); };
  draw();
  const extras = element('details', '', 'scientific-detail'); extras.append(element('summary', 'Publication types, citation leaders & data coverage'));
  const extrasGrid = element('div', '', 'landscape-grid'); extrasGrid.append(ranking('Publication types', data.publication_types, 'type'), ranking('Discovery sources', data.discovery_providers, 'provider')); extras.append(extrasGrid);
  if (data.most_cited_in_discovered_set?.length) {
    const cited = card('Most cited in this search', 'Citation counts are provider snapshots, not a measure of evidence quality.');
    for (const paper of data.most_cited_in_discovered_set) {
      const row = element('p'); row.append(paper.source_url ? safeLink(paper.title, paper.source_url) : element('span', paper.title), element('span', ` · ${paper.cited_by_count} citations`, 'landscape-note')); cited.append(row);
    }
    extras.append(cited);
  }
  fields({coverage: data.coverage, trend_method: data.trend_method, limitations: data.limitations}, extras); parent.append(extras);
}
