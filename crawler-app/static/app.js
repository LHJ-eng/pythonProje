'use strict';

const $ = (id) => document.getElementById(id);

let csrf = null;
let source = 'url';
let currentJobId = null;
let pollTimer = null;
let selectedTableIndex = null;

const noticeBox = $('notice');
const analysisBox = $('analysis');
const resultsEmptyHint = '在左侧配置并开始抓取，结果会显示在这里。';

/* ------------------------------------------------------------------ 基础 */
async function api(path, { method = 'GET', body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (csrf) headers['X-CSRF-Token'] = csrf;
  const response = await fetch(path, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('未登录');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    let detail = data.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join('；');
    throw new Error(detail || `请求失败（${response.status}）`);
  }
  return data;
}

function notice(message, type = 'info') {
  noticeBox.textContent = message;
  noticeBox.className = 'notice' + (type === 'info' ? '' : ' ' + type);
  noticeBox.hidden = !message;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function fmtTime(raw) {
  return raw ? raw.slice(5, 16) : '';
}

function statusLabel(status) {
  return {
    queued: '排队中',
    running: '抓取中',
    done: '已完成',
    error: '失败',
    idle: '等待任务',
  }[status] || status;
}

/* ------------------------------------------------------------------ 表单 */
function switchSource(next) {
  source = next;
  document.querySelectorAll('#source-tabs button').forEach((button) => {
    button.classList.toggle('active', button.dataset.source === next);
  });
  $('pane-url').hidden = next !== 'url';
  $('pane-html').hidden = next !== 'html';
  $('analyze').disabled = false;
}

function switchMode(mode) {
  $('table-options').hidden = mode !== 'table';
  $('css-options').hidden = mode !== 'css';
}

function addField(name = '', selector = '', attr = 'text') {
  const row = node('div', 'field-row');
  const nameInput = node('input');
  nameInput.type = 'text';
  nameInput.placeholder = '字段名';
  nameInput.value = name;

  const selectorInput = node('input');
  selectorInput.type = 'text';
  selectorInput.placeholder = '选择器（留空=条目自身）';
  selectorInput.value = selector;

  const attrInput = node('input');
  attrInput.type = 'text';
  attrInput.placeholder = 'text / href';
  attrInput.value = attr;

  const remove = node('button', 'del-field', '×');
  remove.type = 'button';
  remove.title = '删除字段';
  remove.addEventListener('click', () => row.remove());

  row.append(nameInput, selectorInput, attrInput, remove);
  $('fields').appendChild(row);
}

function collectFields() {
  return Array.from(document.querySelectorAll('#fields .field-row')).map((row) => {
    const inputs = row.querySelectorAll('input');
    return {
      name: inputs[0].value.trim(),
      selector: inputs[1].value.trim(),
      attr: inputs[2].value.trim() || 'text',
    };
  }).filter((field) => field.name);
}

function currentRequest({ forAnalyze = false } = {}) {
  const request = {
    source,
    url: $('url').value.trim(),
    html: $('html').value,
    base_url: $('base-url').value.trim(),
    mode: $('mode').value,
    browser: $('browser').value === '1',
    pages: Number($('pages').value) || 1,
    delay: Number($('delay').value) || 0,
    ignore_robots: $('ignore-robots').checked,
    first_row_header: $('first-row-header').checked,
    item_selector: $('item-selector').value.trim(),
    fields: collectFields(),
  };
  const tableIndex = $('table-index').value.trim();
  request.table_index = tableIndex === '' ? null : Number(tableIndex);
  if (forAnalyze && request.url) request.url = request.url.replace('{page}', '1');
  return request;
}

/* ------------------------------------------------------------------ 分析 */
function renderAnalysis(data) {
  analysisBox.hidden = false;
  $('analysis-summary').textContent =
    `${data.title || '（无标题）'} · 链接 ${data.links} 个 · HTML ${data.chars} 字符` +
    (data.url ? ` · ${data.url}` : '');

  const tablesBox = $('analysis-tables');
  tablesBox.textContent = '';
  selectedTableIndex = null;

  if (data.tables.length) {
    tablesBox.appendChild(node('h3', '', `检测到 ${data.tables.length} 个表格（点击选择）`));
    let best = data.tables[0];
    data.tables.forEach((table) => {
      if (table.rows * table.cols > best.rows * best.cols) best = table;
      const card = node('div', 'table-card');
      card.appendChild(node('b', '', `表格 #${table.index} · ${table.rows} 行 × ${table.cols} 列`));
      card.appendChild(node('div', 'preview-line', table.headers.join(' | ').slice(0, 160)));
      if (table.preview.length) {
        const first = table.preview[0].map((cell) => String(cell).slice(0, 24)).join(' | ');
        card.appendChild(node('div', 'preview-line', '首行：' + first.slice(0, 160)));
      }
      card.addEventListener('click', () => {
        document.querySelectorAll('.table-card').forEach((item) => item.classList.remove('active'));
        card.classList.add('active');
        selectedTableIndex = table.index;
        $('table-index').value = String(table.index);
        $('mode').value = 'table';
        switchMode('table');
      });
      card.dataset.index = String(table.index);
      tablesBox.appendChild(card);
    });
    const cards = tablesBox.querySelectorAll('.table-card');
    const target = Array.from(cards).find((card) => Number(card.dataset.index) === best.index);
    if (target) target.click();
  } else {
    tablesBox.appendChild(node('p', 'hint', '未检测到 HTML 表格。可改用 CSS 选择器或正文模式。'));
  }

  const articleBox = $('analysis-article');
  articleBox.textContent = '';
  if (data.article.length > 0) {
    articleBox.hidden = false;
    articleBox.appendChild(
      node('div', 'article-head', `正文约 ${data.article.length} 字符`)
    );
    articleBox.appendChild(node('div', 'article-text', data.article.preview + '…'));
    const useArticle = node('button', 'ghost small', '使用正文模式');
    useArticle.type = 'button';
    useArticle.addEventListener('click', () => {
      $('mode').value = 'article';
      switchMode('article');
      notice('已切换到正文模式，点击「开始抓取」即可。', 'ok');
    });
    articleBox.appendChild(useArticle);
  } else {
    articleBox.hidden = true;
  }
}

async function analyzePage() {
  notice('');
  const button = $('analyze');
  button.disabled = true;
  button.textContent = '分析中…';
  try {
    const data = await api('/api/analyze', { method: 'POST', body: currentRequest({ forAnalyze: true }) });
    renderAnalysis(data);
    notice('分析完成，可调整提取方式后开始抓取。', 'ok');
  } catch (error) {
    notice(error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = '分析页面结构';
  }
}

/* ------------------------------------------------------------------ 任务 */
function renderJob(job) {
  const pill = $('job-status');
  pill.textContent = statusLabel(job.status);
  pill.className = 'pill ' + job.status;

  const meta = job.meta || {};
  const metaLine = $('job-meta');
  metaLine.textContent = '';
  if (job.status === 'error') {
    metaLine.appendChild(node('span', 'warn', `错误：${job.error || '未知错误'}`));
  } else if (job.status === 'done') {
    const parts = [
      `${job.total_rows} 行 × ${job.columns.length} 列`,
      meta.via === 'browser' ? '浏览器渲染' : '静态请求',
      meta.pages_fetched ? `${meta.pages_fetched} 页` : '',
      meta.elapsed_ms ? `${(meta.elapsed_ms / 1000).toFixed(1)} 秒` : '',
      job.url || '',
    ].filter(Boolean);
    metaLine.appendChild(node('span', '', parts.join(' · ')));
    (meta.warnings || []).forEach((warning) => {
      metaLine.appendChild(node('span', 'warn', '⚠ ' + warning));
    });
  } else {
    metaLine.textContent = job.message || '处理中…';
  }

  const exportsBox = $('exports');
  exportsBox.textContent = '';
  if (job.status === 'done') {
    const formats = [
      ['csv', '导出 CSV'],
      ['xlsx', '导出 Excel'],
      ['json', '导出 JSON'],
      ['html', 'HTML 报告'],
    ];
    formats.forEach(([format, label]) => {
      const link = node('a', '', label);
      link.href = `/api/jobs/${job.id}/export?format=${format}`;
      exportsBox.appendChild(link);
    });
  }
  exportsBox.hidden = job.status !== 'done';

  const statsBox = $('stats');
  statsBox.textContent = '';
  if (job.status === 'done') {
    [
      ['总行数', job.total_rows],
      ['字段数', job.columns.length],
      ['抓取页数', meta.pages_fetched || 1],
      ['耗时', meta.elapsed_ms ? `${(meta.elapsed_ms / 1000).toFixed(1)}s` : '-'],
    ].forEach(([label, value]) => {
      const chip = node('span', 'stat-chip', `${label} `);
      chip.appendChild(node('b', '', String(value)));
      statsBox.appendChild(chip);
    });
  }

  const preview = $('preview');
  preview.textContent = '';
  if (job.status !== 'done') {
    preview.appendChild(node('div', 'empty', job.status === 'error' ? '任务失败，请查看上方错误信息。' : '正在采集数据…'));
    return;
  }
  if (!job.rows.length) {
    preview.appendChild(node('div', 'empty', '没有提取到数据行。'));
    return;
  }

  const table = node('table');
  const thead = node('thead');
  const headRow = node('tr');
  job.columns.forEach((column) => headRow.appendChild(node('th', '', column)));
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = node('tbody');
  job.rows.forEach((row) => {
    const tr = node('tr');
    job.columns.forEach((_, index) => {
      const value = row[index] === undefined ? '' : String(row[index]);
      const td = node('td', '', value.length > 500 ? value.slice(0, 500) + '…' : value);
      if (value.length > 500) td.title = '内容较长，完整内容请导出查看';
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  preview.appendChild(table);

  if (job.preview_limited) {
    preview.appendChild(
      node('div', 'empty', `预览仅显示前 ${job.rows.length} 行，完整 ${job.total_rows} 行请导出。`)
    );
  }
}

async function pollJob(jobId, startedAt = Date.now()) {
  if (currentJobId !== jobId) return;
  try {
    const job = await api(`/api/jobs/${jobId}`);
    if (currentJobId !== jobId) return;
    renderJob(job);
    if (job.status === 'done' || job.status === 'error') {
      loadHistory();
      if (job.status === 'done') notice(`抓取完成：${job.total_rows} 行数据。`, 'ok');
      return;
    }
  } catch (error) {
    notice(error.message, 'error');
  }
  if (Date.now() - startedAt > 6 * 60 * 1000) {
    notice('任务等待超时，请稍后在历史任务中查看结果。', 'error');
    return;
  }
  pollTimer = setTimeout(() => pollJob(jobId, startedAt), 1200);
}

async function startJob() {
  notice('');
  const button = $('run');
  button.disabled = true;
  button.textContent = '提交中…';
  try {
    const request = currentRequest();
    if (request.source === 'url' && !request.url) throw new Error('请填写网页 URL');
    if (request.source === 'html' && request.html.trim().length < 20) throw new Error('请粘贴或上传 HTML 内容');
    const data = await api('/api/jobs', { method: 'POST', body: request });
    currentJobId = data.id;
    if (pollTimer) clearTimeout(pollTimer);
    $('job-status').textContent = '排队中';
    $('job-status').className = 'pill running';
    $('job-meta').textContent = '任务已提交，正在等待执行…';
    $('preview').textContent = '';
    $('exports').hidden = true;
    $('stats').textContent = '';
    pollJob(data.id);
  } catch (error) {
    notice(error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = '开始抓取';
  }
}

/* ------------------------------------------------------------------ 历史 */
async function loadHistory() {
  try {
    const data = await api('/api/jobs?limit=40');
    const list = $('history-list');
    list.textContent = '';
    if (!data.jobs.length) {
      list.appendChild(node('p', 'muted small', '暂无任务'));
      return;
    }
    data.jobs.forEach((job) => {
      const item = node('div', 'history-item');
      if (job.id === currentJobId) item.classList.add('active');
      item.appendChild(node('div', 'url', job.url || '本地 HTML 数据'));
      const sub = node('div', 'sub');
      const state = node('span', '', `${statusLabel(job.status)} · ${job.total_rows} 行 · ${fmtTime(job.created_at)}`);
      const del = node('button', 'del', '删除');
      del.type = 'button';
      del.addEventListener('click', async (event) => {
        event.stopPropagation();
        if (!confirm('确认删除该任务及其数据？')) return;
        try {
          await api(`/api/jobs/${job.id}`, { method: 'DELETE' });
          if (currentJobId === job.id) resetResult();
          loadHistory();
        } catch (error) {
          notice(error.message, 'error');
        }
      });
      sub.append(state, del);
      item.appendChild(sub);
      item.addEventListener('click', async () => {
        currentJobId = job.id;
        if (pollTimer) clearTimeout(pollTimer);
        document.querySelectorAll('.history-item').forEach((node2) => node2.classList.remove('active'));
        item.classList.add('active');
        if (job.status === 'queued' || job.status === 'running') {
          pollJob(job.id);
        } else {
          const detail = await api(`/api/jobs/${job.id}`);
          renderJob(detail);
        }
      });
      list.appendChild(item);
    });
  } catch (error) {
    notice(error.message, 'error');
  }
}

function resetResult() {
  currentJobId = null;
  $('job-status').textContent = '等待任务';
  $('job-status').className = 'pill idle';
  $('job-meta').textContent = resultsEmptyHint;
  $('exports').hidden = true;
  $('stats').textContent = '';
  $('preview').textContent = '';
  loadHistory();
}

/* ------------------------------------------------------------------ 启动 */
async function boot() {
  let me;
  try {
    me = await fetch('/api/me').then((response) => response.json());
  } catch {
    document.body.textContent = '无法连接服务器';
    return;
  }
  if (!me.authenticated) {
    window.location.href = '/login';
    return;
  }
  csrf = me.csrf;

  document.querySelectorAll('#source-tabs button').forEach((button) => {
    button.addEventListener('click', () => switchSource(button.dataset.source));
  });
  $('mode').addEventListener('change', () => switchMode($('mode').value));
  $('add-field').addEventListener('click', () => addField());
  $('analyze').addEventListener('click', analyzePage);
  $('run').addEventListener('click', startJob);
  $('refresh-history').addEventListener('click', loadHistory);
  $('logout').addEventListener('click', async () => {
    try {
      await api('/api/logout', { method: 'POST' });
    } catch {
      /* 忽略，直接回登录页 */
    }
    window.location.href = '/login';
  });
  $('html-file').addEventListener('change', (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      $('html').value = String(reader.result || '');
      notice(`已载入文件：${file.name}（${$('html').value.length} 字符）`, 'ok');
    };
    reader.readAsText(file, 'utf-8');
  });

  addField('标题', 'h2', 'text');
  addField('链接', 'a', 'href');
  switchMode('table');
  loadHistory();
}

boot();
