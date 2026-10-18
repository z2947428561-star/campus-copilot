import { requestJSON, setUnauthorizedHandler } from './api.js';
import { clearSession, getToken, getUser } from './session.js';

const el = id => document.getElementById('db-' + id);
const node = (tag, text, className) => {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = String(text);
  if (className) result.className = className;
  return result;
};
let catalog, data, controller, generation = 0, view = 'records';
let selection = { source: 'campus', table: 'courses', page: 1, size: 25, query: '', sort: '', direction: 'asc' };

function clearDetail() {
  el('detail').close();
  el('detail-fields').replaceChildren();
}

function gate(message = '') {
  generation++;
  controller?.abort();
  catalog = data = null;
  clearDetail();
  el('sources').replaceChildren();
  el('table').querySelector('tbody').replaceChildren();
  el('schema-rows').replaceChildren();
  el('relation-list').replaceChildren();
  el('user').textContent = '';
  el('app').hidden = true;
  el('gate').hidden = false;
  if (message) el('gate-message').textContent = message;
}

setUnauthorizedHandler(message => { clearSession(); gate(message); });

function sourceSpec() { return catalog?.sources.find(s => s.id === selection.source); }
function tableSpec() { return sourceSpec()?.tables.find(t => t.id === selection.table); }
function labelFor(key) {
  const [source, table] = key.split('.');
  return catalog.sources.find(s => s.id === source)?.tables.find(t => t.id === table)?.label || table;
}

function renderDirectory() {
  el('sources').replaceChildren();
  for (const source of catalog.sources) {
    const section = node('section', undefined, 'db-source');
    const heading = node('div', undefined, 'db-source-head');
    heading.append(node('h2', source.label), node('span', source.backend));
    section.append(heading);
    for (const table of source.tables) {
      const button = node('button', undefined, 'db-table-button');
      button.type = 'button';
      button.dataset.source = source.id;
      button.dataset.table = table.id;
      button.setAttribute('aria-current', String(source.id === selection.source && table.id === selection.table));
      button.append(node('span', table.label), node('small', table.count ?? (table.state === 'unavailable' ? '未就绪' : '连接查看')));
      button.addEventListener('click', () => openTable(source.id, table.id));
      section.append(button);
    }
    el('sources').append(section);
  }
}

function showView(name) {
  view = name;
  for (const button of document.querySelectorAll('[data-view]')) {
    button.setAttribute('aria-pressed', String(button.dataset.view === name));
  }
  for (const key of ['records', 'schema', 'relations']) el(key).hidden = key !== name || !data;
}

function openTable(source, table) {
  selection = { ...selection, source, table, query: '', page: 1, sort: '', direction: 'asc' };
  el('query').value = '';
  renderDirectory();
  if (window.matchMedia('(max-width: 760px)').matches) el('directory').open = false;
  loadTable();
}

function valueText(value) {
  if (value === null || value === undefined) return '空值';
  if (value === '') return '空字符串';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

function detail(row, index) {
  el('detail-title').textContent = data.label + ' / 第 ' + ((data.page - 1) * data.page_size + index + 1) + ' 条';
  el('detail-fields').replaceChildren();
  for (const column of data.columns) {
    el('detail-fields').append(node('dt', column.label + ' · ' + column.name));
    const value = row[column.name];
    const dd = node('dd');
    let url;
    if (column.name === 'source' && typeof value === 'string') {
      try { const parsed = new URL(value); if (['http:', 'https:'].includes(parsed.protocol)) url = parsed.href; } catch { /* Show invalid links as text. */ }
    }
    if (url) {
      const link = node('a', value);
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      dd.append(link);
    } else dd.textContent = valueText(value);
    if (row._truncated?.includes(column.name)) dd.append(node('p', '内容较长，仅展示前 20000 个字符。'));
    el('detail-fields').append(dd);
  }
  el('detail').showModal();
}

function renderRecords() {
  const head = node('tr');
  for (const column of data.columns) {
    const th = node('th');
    th.scope = 'col';
    if (data.sortable) {
      const selected = selection.sort === column.name;
      th.setAttribute('aria-sort', selected ? (selection.direction === 'asc' ? 'ascending' : 'descending') : 'none');
      const button = node('button', column.label + (selected ? (selection.direction === 'asc' ? ' ↑' : ' ↓') : ''));
      button.type = 'button';
      button.setAttribute('aria-label', '按' + column.label + '排序');
      button.addEventListener('click', () => {
        selection.direction = selected && selection.direction === 'asc' ? 'desc' : 'asc';
        selection.sort = column.name;
        selection.page = 1;
        loadTable();
      });
      th.append(button);
    } else th.append(node('span', column.label));
    th.append(node('small', column.name, 'db-code'));
    head.append(th);
  }
  const actionHeader = node('th', '详情');
  actionHeader.scope = 'col';
  head.append(actionHeader);
  el('table').querySelector('thead').replaceChildren(head);
  el('table').closest('.db-table-wrap').scrollLeft = 0;
  el('table').querySelector('caption').textContent = data.label;
  const body = el('table').querySelector('tbody');
  body.replaceChildren();
  data.rows.forEach((row, index) => {
    const tr = node('tr');
    for (const column of data.columns) {
      const value = row[column.name];
      const text = valueText(value);
      const td = node('td');
      const span = node('span', text.slice(0, 250), 'db-cell' + (value === null || value === undefined ? ' db-null' : ''));
      td.append(span);
      tr.append(td);
    }
    const td = node('td');
    const button = node('button', '查看', 'db-row-detail');
    button.type = 'button';
    button.setAttribute('aria-label', '查看记录 ' + ((data.page - 1) * data.page_size + index + 1));
    button.addEventListener('click', () => detail(row, index));
    td.append(button);
    tr.append(td);
    body.append(tr);
  });
  el('empty').hidden = data.rows.length > 0;
  el('empty-message').textContent = selection.query ? '没有匹配的记录，试试其他关键词或清空搜索。'
    : selection.source === 'personal' ? '可以返回对话，在“我的数据”中录入课程和成绩，或新建会话。'
    : selection.source === 'index' ? '当前集合没有分块；政策快照可以在左侧单独查看。' : '当前表为空，刷新后重试。';
  const first = data.rows.length ? (data.page - 1) * data.page_size + 1 : 0;
  const last = data.rows.length ? first + data.rows.length - 1 : 0;
  el('range').textContent = `${first}–${last} 条` + (data.total === null ? ' · 搜索结果总数未统计' : `，共 ${data.total} 条`);
  el('page').textContent = '第 ' + data.page + ' 页';
  el('prev').disabled = data.page === 1;
  el('next').disabled = !data.has_more || (data.page + 1) * data.page_size > 10000;
}

function renderSchema() {
  el('schema-rows').replaceChildren();
  for (const column of data.columns) {
    const row = node('tr');
    row.append(node('td', column.name, 'db-code'), node('td', column.label), node('td', column.type, 'db-code'), node('td', column.primary ? '记录标识' : '—'));
    el('schema-rows').append(row);
  }
}

function renderRelations() {
  el('relation-list').replaceChildren();
  const key = selection.source + '.' + selection.table;
  const relations = catalog.relations.filter(r => r.from === key || r.to === key);
  for (const relation of relations) {
    const article = node('article', undefined, 'db-relation');
    for (const [index, target] of [relation.from, relation.to].entries()) {
      if (index) article.append(node('span', relation.kind + '\n→'));
      const button = node('button', labelFor(target));
      button.type = 'button';
      button.append(node('code', target + '.' + (index ? relation.target : relation.field)));
      button.addEventListener('click', () => openTable(...target.split('.')));
      article.append(button);
    }
    el('relation-list').append(article);
  }
  if (!relations.length) el('relation-list').append(node('p', '此表没有已登记的关联。', 'db-section-note'));
}

async function loadTable() {
  const version = ++generation;
  controller?.abort();
  controller = new AbortController();
  clearDetail();
  data = null;
  showView(view);
  el('error').hidden = true;
  el('index-note').hidden = true;
  el('title').textContent = tableSpec()?.label || selection.table;
  el('description').textContent = tableSpec()?.description || '';
  el('context').textContent = sourceSpec()?.label + ' / ' + sourceSpec()?.backend;
  el('count').textContent = '';
  el('status').textContent = selection.source === 'index' ? '正在连接本机向量索引…' : '正在读取数据…';
  el('refresh').disabled = true;
  try {
    const params = new URLSearchParams({ q: selection.query, page: selection.page, page_size: selection.size, sort: selection.sort, direction: selection.direction });
    const result = await requestJSON(`/api/database/${selection.source}/${selection.table}?${params}`, { signal: controller.signal });
    if (version !== generation) return;
    data = result;
    if (data.total !== null && data.page > 1 && (data.page - 1) * data.page_size >= data.total) {
      selection.page = Math.max(1, Math.ceil(data.total / data.page_size));
      return loadTable();
    }
    renderRecords(); renderSchema(); renderRelations();
    el('count').textContent = `${data.columns.length} 个字段` + (data.total === null ? '' : ` / ${data.total} 条记录`);
    el('status').textContent = '已读取 · ' + new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const table = tableSpec();
    if (table && !selection.query) table.count = data.total;
    renderDirectory();
    if (selection.source === 'index') {
      const info = data.info;
      el('index-note').textContent = `${info.backend} 集合：${info.collection}` + (info.dimension ? `，实际向量维度：${info.dimension}` : '')
        + (info.generation ? (info.generation === 'legacy' ? '。旧版索引，尚无构建记录' : `。生效修订：${info.revision}，版本：${info.generation.slice(0, 8)}`) : '')
        + (info.created_at ? `，构建时间：${info.created_at}` : '')
        + '。仅浏览存储的分块；旧数据的来源类型或日期可能为空。';
      el('index-note').hidden = false;
    }
    showView(view);
  } catch (error) {
    if (version !== generation || error.name === 'AbortError') return;
    el('status').textContent = '';
    el('error').hidden = false;
    el('error-message').textContent = error.message;
  } finally {
    if (version === generation) el('refresh').disabled = false;
  }
}

async function start() {
  if (!getToken()) return gate();
  const version = ++generation;
  controller?.abort();
  controller = new AbortController();
  el('gate').hidden = true;
  el('app').hidden = false;
  clearDetail();
  data = null;
  showView(view);
  el('user').textContent = getUser();
  el('error').hidden = true;
  el('status').textContent = '正在读取数据目录…';
  el('refresh').disabled = true;
  try {
    const result = await requestJSON('/api/database', { signal: controller.signal });
    if (version !== generation) return;
    catalog = result;
    renderDirectory();
    await loadTable();
  } catch (error) {
    if (version !== generation || error.name === 'AbortError') return;
    el('status').textContent = '';
    el('error').hidden = false;
    el('error-message').textContent = error.message;
    el('refresh').disabled = false;
  }
}

document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
el('search-form').addEventListener('submit', event => { event.preventDefault(); selection.query = el('query').value.trim(); selection.page = 1; loadTable(); });
el('clear').addEventListener('click', () => { el('query').value = ''; selection.query = ''; selection.page = 1; loadTable(); });
el('page-size').addEventListener('change', () => { selection.size = Number(el('page-size').value); selection.page = 1; loadTable(); });
el('prev').addEventListener('click', () => { selection.page--; loadTable(); });
el('next').addEventListener('click', () => { selection.page++; loadTable(); });
el('refresh').addEventListener('click', start);
el('retry').addEventListener('click', () => catalog ? loadTable() : start());
el('detail-close').addEventListener('click', clearDetail);
window.addEventListener('storage', event => {
  if (['cc_token', 'cc_user', null].includes(event.key)) {
    gate();
    selection = { ...selection, source: 'campus', table: 'courses', page: 1, query: '', sort: '' };
    el('query').value = '';
    if (getToken()) start();
  }
});
const mobile = window.matchMedia('(max-width: 760px)');
if (mobile.matches) el('directory').open = false;
mobile.addEventListener('change', event => { el('directory').open = !event.matches; });
start();
