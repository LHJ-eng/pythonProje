'use strict';

const $ = (id) => document.getElementById(id);

let csrf = null;
let source = 'url';
let currentJobId = null;
let pollTimer = null;
let selectedTableIndex = null;
let imageData = '';
let imageName = '';
let lastAutoRule = null;

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
  $('pane-image').hidden = next !== 'image';
  $('advanced').hidden = next === 'image';
  $('analyze').disabled = next === 'image';
  $('run').textContent = next === 'image' ? '开始识别' : '开始抓取';
  $('primary-hint').textContent = next === 'image'
    ? '选择一张图片后点击「开始识别」，无需配置字段；中文 OCR 在本地运行。'
    : '无需填写选择器。智能模式会自动识别表格、重复列表、正文；图片链接会自动进行文字识别。';
  if (next !== 'url') $('pages').value = '1';
  if (next === 'image') {
    $('mode').value = 'auto';
    switchMode('auto');
  }
  updateDeepVisibility();
  analysisBox.hidden = true;
  notice('');
}

function switchMode(mode) {
  $('table-options').hidden = mode !== 'table';
  $('css-options').hidden = mode !== 'css';
  updateDeepVisibility();
}

function updateDeepVisibility() {
  const enabled = source === 'url' && $('mode').value === 'auto';
  $('deep-options').hidden = !enabled;
  if (!enabled) {
    $('deep').checked = false;
    $('pages').disabled = false;
  }
  if ($('deep').checked) $('pages').disabled = true;
}

function addField(name = '', selector = '', attr = 'text', selectorType = 'css') {
  const row = node('div', 'field-row');
  const nameInput = node('input');
  nameInput.type = 'text';
  nameInput.placeholder = '字段名';
  nameInput.value = name;

  const selectorInput = node('input');
  selectorInput.type = 'text';
  selectorInput.placeholder = '选择器（留空=条目自身）';
  selectorInput.value = selector;

  const typeSelect = node('select');
  ['css', 'xpath'].forEach((value) => {
    const option = node('option', '', value.toUpperCase());
    option.value = value;
    typeSelect.appendChild(option);
  });
  typeSelect.value = selectorType === 'xpath' ? 'xpath' : 'css';

  const attrInput = node('input');
  attrInput.type = 'text';
  attrInput.placeholder = 'text / href';
  attrInput.value = attr;

  const remove = node('button', 'del-field', '×');
  remove.type = 'button';
  remove.title = '删除字段';
  remove.addEventListener('click', () => row.remove());

  row.append(nameInput, selectorInput, typeSelect, attrInput, remove);
  $('fields').appendChild(row);
}

function collectFields() {
  return Array.from(document.querySelectorAll('#fields .field-row')).map((row) => {
    const inputs = row.querySelectorAll('input');
    const select = row.querySelector('select');
    return {
      name: inputs[0].value.trim(),
      selector: inputs[1].value.trim(),
      selector_type: select ? select.value : 'css',
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
    image_data: imageData,
    image_name: imageName,
    mode: $('mode').value,
    browser: $('browser').value === '1',
    pages: Number($('pages').value) || 1,
    delay: Number($('delay').value) || 0,
    ignore_robots: $('ignore-robots').checked,
    first_row_header: $('first-row-header').checked,
    item_selector: $('item-selector').value.trim(),
    item_selector_type: $('item-selector-type').value,
    fields: collectFields(),
    wait_for: $('wait-for').value.trim(),
    scan_full_page: $('scan-full-page').checked,
    expand_clicks: $('expand-clicks').checked ? 5 : 0,
    cache_mode: $('cache-mode').value,
    deep: $('deep').checked,
    max_depth: Number($('max-depth').value) || 0,
    max_links: Number($('max-links').value) || 10,
    include_pattern: $('include-pattern').value.trim(),
    exclude_pattern: $('exclude-pattern').value.trim(),
  };
  const tableIndex = $('table-index').value.trim();
  request.table_index = tableIndex === '' ? null : Number(tableIndex);
  if (request.deep && request.pages > 1) request.pages = 1;
  if (forAnalyze && request.url) {
    request.url = request.url.replace('{page}', '1');
    request.deep = false;
  }
  return request;
}

/* ------------------------------------------------------------------ 分析 */
function renderAnalysis(data) {
  analysisBox.hidden = false;
  lastAutoRule = data.auto || null;
  const sizeText = data.image ? `图片约 ${Math.ceil(data.chars / 1000)} KB` : `HTML ${data.chars} 字符`;
  $('analysis-summary').textContent =
    `${data.title || '（无标题）'} · 链接 ${data.links} 个 · ${sizeText}` +
    (data.url ? ` · ${data.url}` : '');

  const tablesBox = $('analysis-tables');
  tablesBox.textContent = '';
  selectedTableIndex = null;

  if (lastAutoRule && lastAutoRule.mode) {
    const labels = { table: 'HTML 数据表', css: '重复列表 / 卡片', article: '正文文章', structured: '页面结构化数据', feed: 'RSS / Atom 订阅源', ocr: '图片文字识别' };
    const card = node('div', 'auto-card');
    const score = lastAutoRule.score === undefined ? '' : ` · 置信度 ${Math.round(lastAutoRule.score * 100)}%`;
    card.appendChild(node('b', '', `智能识别：${labels[lastAutoRule.mode] || lastAutoRule.mode}${score}`));
    card.appendChild(node('div', 'preview-line', lastAutoRule.reason || '已自动确定提取方式'));
    if (lastAutoRule.columns && lastAutoRule.columns.length) {
      card.appendChild(node('div', 'preview-line', `字段：${lastAutoRule.columns.join(' | ')}`));
    }
    if (['table', 'css', 'article'].includes(lastAutoRule.mode)) {
      const edit = node('button', 'ghost small', '在高级设置中查看 / 修改规则');
      edit.type = 'button';
      edit.addEventListener('click', () => {
        $('advanced').open = true;
        $('mode').value = lastAutoRule.mode;
        if (lastAutoRule.mode === 'table') {
          $('table-index').value = String(lastAutoRule.table_index ?? '');
          $('first-row-header').checked = Boolean(lastAutoRule.first_row_header);
        }
        if (lastAutoRule.mode === 'css') {
          $('item-selector').value = lastAutoRule.item_selector || '';
          $('item-selector-type').value = lastAutoRule.item_selector_type === 'xpath' ? 'xpath' : 'css';
          $('fields').textContent = '';
          (lastAutoRule.fields || []).forEach((field) => addField(
            field.name, field.selector, field.attr, field.selector_type || 'css'
          ));
        }
        switchMode(lastAutoRule.mode);
      });
      card.appendChild(edit);
    }
    tablesBox.appendChild(card);
  } else if (lastAutoRule && lastAutoRule.error) {
    tablesBox.appendChild(node('p', 'notice error', lastAutoRule.error));
  }

  if (data.tables.length) {
    tablesBox.appendChild(node('h3', '', `手动选择表格（共 ${data.tables.length} 个）`));
    data.tables.forEach((table) => {
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
        $('advanced').open = true;
        $('table-index').value = String(table.index);
        $('mode').value = 'table';
        switchMode('table');
      });
      tablesBox.appendChild(card);
    });
  } else if (!data.image) {
    tablesBox.appendChild(node('p', 'hint', '未检测到 HTML 表格；仍可直接尝试智能抓取。'));
  }

  const articleBox = $('analysis-article');
  articleBox.textContent = '';
  if (data.article.length > 0) {
    articleBox.hidden = false;
    articleBox.appendChild(node('div', 'article-head', `正文约 ${data.article.length} 字符`));
    articleBox.appendChild(node('div', 'article-text', data.article.preview + '…'));
    const useArticle = node('button', 'ghost small', '使用手动正文模式');
    useArticle.type = 'button';
    useArticle.addEventListener('click', () => {
      $('advanced').open = true;
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
    button.disabled = source === 'image';
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
    const viaLabels = {
      browser: '浏览器渲染',
      http: '静态请求',
      cache: '命中本地缓存',
      'cache-revalidated': 'ETag 校验复用',
      html: '本地 HTML',
      local_image: '本地图片 OCR',
    };
    const detection = meta.auto_detection || {};
    const ocr = meta.ocr || {};
    const averageConfidence = ocr.average_confidence ?? ocr.avg_confidence;
    const parts = [
      `${job.total_rows} 行 × ${job.columns.length} 列`,
      viaLabels[meta.via] || '本地处理',
      detection.reason || '',
      averageConfidence !== undefined ? `OCR 平均置信度 ${(Number(averageConfidence) * 100).toFixed(1)}%` : '',
      meta.auto_browser ? '已自动切换浏览器渲染' : '',
      meta.deep ? `深度抓取 ${meta.pages_fetched} 页${meta.truncated ? '（已截断）' : ''}` : '',
      meta.frame_url ? '已跟进框架页' : '',
      meta.pages_fetched && !meta.deep ? `${meta.pages_fetched} 页` : '',
      meta.elapsed_ms ? `${(meta.elapsed_ms / 1000).toFixed(1)} 秒` : '',
      job.url || meta.image_name || '',
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
      ['md', '导出 Markdown'],
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
      if (job.status === 'done') {
        const action = (job.meta || {}).resolved_mode === 'ocr' ? '识别' : '抓取';
        notice(`${action}完成：${job.total_rows} 行数据。`, 'ok');
      }
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
    if (request.source === 'image' && !request.image_data) throw new Error('请先选择需要识别的图片');
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
    button.textContent = source === 'image' ? '开始识别' : '开始抓取';
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
      const sourceLabel = job.source_type === 'image' ? '本地图片识别' : '本地 HTML 数据';
      item.appendChild(node('div', 'url', job.url || sourceLabel));
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

/* ------------------------------------------------------------------ 规则模板 */
function applyRuleToForm(rule) {
  if (!rule || !rule.mode) return false;
  const mode = String(rule.mode);
  if (mode === 'css') {
    $('advanced').open = true;
    $('mode').value = 'css';
    $('item-selector').value = rule.item_selector || '';
    $('item-selector-type').value = rule.item_selector_type === 'xpath' ? 'xpath' : 'css';
    $('fields').textContent = '';
    (rule.fields || []).forEach((field) => addField(
      field.name || '', field.selector || '', field.attr || 'text',
      field.selector_type || 'css'
    ));
    switchMode('css');
    return true;
  }
  if (mode === 'table') {
    $('advanced').open = true;
    $('mode').value = 'table';
    $('table-index').value =
      rule.table_index === null || rule.table_index === undefined
        ? '' : String(rule.table_index);
    $('first-row-header').checked = Boolean(rule.first_row_header);
    switchMode('table');
    return true;
  }
  if (mode === 'article' || mode === 'auto') {
    $('advanced').open = true;
    $('mode').value = mode;
    switchMode(mode);
    return true;
  }
  return false;
}

function currentRule() {
  const mode = $('mode').value;
  if (mode === 'css') {
    const fields = collectFields();
    if (!$('item-selector').value.trim() || !fields.length) return null;
    return {
      mode: 'css',
      item_selector: $('item-selector').value.trim(),
      item_selector_type: $('item-selector-type').value,
      fields,
    };
  }
  if (mode === 'table') {
    const raw = $('table-index').value.trim();
    return {
      mode: 'table',
      table_index: raw === '' ? null : Number(raw),
      first_row_header: $('first-row-header').checked,
    };
  }
  if (mode === 'article') return { mode: 'article' };
  if (lastAutoRule && ['table', 'css', 'article', 'structured'].includes(lastAutoRule.mode)) {
    return lastAutoRule;
  }
  return null;
}

async function loadTemplates(selectName) {
  const select = $('template-select');
  const previous = select.value;
  try {
    const data = await api('/api/templates');
    select.textContent = '';
    select.appendChild(new Option('（未选择模板）', ''));
    (data.templates || []).forEach((template) => {
      select.appendChild(new Option(`${template.name} · ${template.rule.mode}`, template.id));
    });
    if (selectName) {
      const match = (data.templates || []).find((item) => item.name === selectName);
      if (match) select.value = match.id;
    } else if (previous) {
      select.value = previous;
    }
  } catch (error) {
    notice(error.message, 'error');
  }
}

async function applySelectedTemplate() {
  const id = $('template-select').value;
  if (!id) {
    notice('请先选择一个模板。', 'error');
    return;
  }
  try {
    const data = await api('/api/templates');
    const template = (data.templates || []).find((item) => item.id === id);
    if (!template) throw new Error('模板不存在');
    if (!applyRuleToForm(template.rule)) throw new Error('模板规则不完整');
    notice(`已套用模板「${template.name}」，点击「开始抓取」即可。`, 'ok');
  } catch (error) {
    notice(error.message, 'error');
  }
}

async function deleteSelectedTemplate() {
  const id = $('template-select').value;
  if (!id) {
    notice('请先选择一个模板。', 'error');
    return;
  }
  if (!confirm('确认删除该规则模板？')) return;
  try {
    await api(`/api/templates/${id}`, { method: 'DELETE' });
    notice('模板已删除。', 'ok');
    await loadTemplates();
  } catch (error) {
    notice(error.message, 'error');
  }
}

async function saveTemplateFlow(ruleOverride) {
  const rule = ruleOverride || currentRule();
  if (!rule) {
    notice('当前没有可保存的提取规则，请选择表格 / CSS / 正文模式，或先完成页面分析。', 'error');
    return;
  }
  const host = (() => {
    try { return new URL($('url').value.trim(), location.origin).hostname; } catch { return ''; }
  })();
  const suggestion = `${rule.mode === 'css' ? '列表' : rule.mode === 'table' ? '表格' : '正文'}${host ? ' · ' + host : ''}`;
  const name = (prompt('模板名称', suggestion) || '').trim();
  if (!name) return;
  try {
    await api('/api/templates', {
      method: 'POST',
      body: {
        name,
        description: '',
        source_url: $('url').value.trim(),
        rule,
      },
    });
    notice(`模板「${name}」已保存。`, 'ok');
    await loadTemplates(name);
  } catch (error) {
    notice(error.message, 'error');
  }
}

/* ------------------------------------------------------------------ 可视化点选 */
const pickState = { data: null, rule: null, blobUrl: '', bound: false };
const SAFE_IDENT = /^-?[_a-zA-Z]+[_a-zA-Z0-9-]*$/;

function cssEscape(value) {
  if (window.CSS && CSS.escape) return CSS.escape(value);
  return String(value).replace(/([^a-zA-Z0-9_-])/g, '\\$1');
}

function pickCssPath(el) {
  const doc = el.ownerDocument;
  const parts = [];
  let current = el;
  while (current && current.nodeType === 1) {
    if (current.tagName === 'BODY') {
      parts.push('body');
      break;
    }
    const id = current.getAttribute('id') || '';
    if (SAFE_IDENT.test(id)) {
      try {
        if (doc.querySelectorAll('#' + cssEscape(id)).length === 1) {
          parts.push('#' + cssEscape(id));
          break;
        }
      } catch {
        /* 忽略非法 id */
      }
    }
    const classes = Array.from(current.classList).filter((name) => SAFE_IDENT.test(name)).slice(0, 2);
    if (classes.length) {
      parts.push(current.tagName.toLowerCase() + '.' + classes.map(cssEscape).join('.'));
    } else {
      const parent = current.parentElement;
      let index = 1;
      if (parent) {
        index = Array.from(parent.children)
          .filter((child) => child.tagName === current.tagName)
          .indexOf(current) + 1;
      }
      parts.push(`${current.tagName.toLowerCase()}:nth-of-type(${Math.max(index, 1)})`);
    }
    current = current.parentElement;
  }
  return parts.length ? parts.reverse().join(' > ') : 'body';
}

function pickRelativeSelector(root, node) {
  const classes = Array.from(node.classList).filter((name) => SAFE_IDENT.test(name));
  if (classes.length) {
    return node.tagName.toLowerCase() + '.' + classes.map(cssEscape).join('.');
  }
  const parts = [];
  let current = node;
  while (current && current !== root) {
    const parent = current.parentElement;
    let index = 1;
    if (parent) {
      index = Array.from(parent.children)
        .filter((child) => child.tagName === current.tagName)
        .indexOf(current) + 1;
    }
    parts.push(`${current.tagName.toLowerCase()}:nth-of-type(${Math.max(index, 1)})`);
    current = parent;
  }
  return parts.reverse().join(' > ');
}

function pickItemSegment(el) {
  const tag = el.tagName.toLowerCase();
  const classes = Array.from(el.classList).filter((name) => SAFE_IDENT.test(name)).slice(0, 2);
  return classes.length ? `${tag}.${classes.map(cssEscape).join('.')}` : tag;
}

function pickTarget(start) {
  if (!start || start.nodeType !== 1) return null;
  const table = start.closest('table');
  if (table) return { kind: 'table', el: table };
  let current = start;
  const body = start.ownerDocument.body;
  while (current && current.parentElement && current !== body) {
    const parent = current.parentElement;
    const classes = Array.from(current.classList).filter((name) => SAFE_IDENT.test(name));
    const siblings = Array.from(parent.children).filter((sibling) => {
      if (sibling.tagName !== current.tagName) return false;
      if (!classes.length) return true;
      return classes.some((name) => sibling.classList.contains(name));
    });
    if (siblings.length >= 3 && (current.textContent || '').trim().length >= 2) {
      return { kind: 'list', el: current, parent };
    }
    current = parent;
  }
  return null;
}

function guessFieldName(el, attr) {
  if (attr === 'href') return '链接';
  if (attr === 'src') return '图片';
  const tag = el.tagName.toLowerCase();
  const semantic = `${el.id || ''} ${typeof el.className === 'string' ? el.className : ''}`.toLowerCase();
  if (/^h[1-6]$/.test(tag) || /title|heading|name/.test(semantic)) return '标题';
  if (/price|amount|cost|money/.test(semantic)) return '价格';
  if (tag === 'time' || /date|time|publish/.test(semantic)) return '日期';
  if (/author|user|byline/.test(semantic)) return '作者';
  if (tag === 'a') return '链接文字';
  return '字段';
}

function collectPickFieldSpecs(root) {
  const specs = [];
  const walk = (parent) => {
    Array.from(parent.children).forEach((child) => {
      const tag = child.tagName;
      if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(tag)) return;
      const text = (child.textContent || '').trim();
      if (tag === 'IMG') {
        if (child.getAttribute('src')) specs.push({ el: child, attr: 'src', priority: 80 });
        return;
      }
      const hasChildText = Array.from(child.children).some((node2) => (node2.textContent || '').trim());
      if (tag === 'A' && child.getAttribute('href')) {
        if (text && !hasChildText) specs.push({ el: child, attr: 'text', priority: 60 });
        specs.push({ el: child, attr: 'href', priority: 70 });
        if (hasChildText) walk(child);
        return;
      }
      if (hasChildText) {
        walk(child);
        return;
      }
      if (!text) return;
      let priority = 50;
      if (/^H[1-6]$/.test(tag)) priority = 95;
      else if (/price|amount|cost|money/i.test(`${child.className || ''}`)) priority = 90;
      else if (tag === 'TIME') priority = 85;
      specs.push({ el: child, attr: 'text', priority });
    });
  };
  walk(root);
  return specs;
}

function buildTableCandidateFromDom(table) {
  const base = pickCssPath(table);
  const thead = table.querySelector('thead');
  const allRows = Array.from(table.querySelectorAll('tr'))
    .filter((tr) => tr.closest('table') === table);
  let headerRow = thead
    ? Array.from(thead.querySelectorAll('tr')).find((tr) => tr.closest('table') === table)
    : allRows[0];
  let bodyRows = allRows.filter((tr) => tr !== headerRow);
  if (!headerRow && bodyRows.length) headerRow = bodyRows[0];
  const headers = headerRow
    ? Array.from(headerRow.cells).flatMap((cell) => {
      const span = Math.min(Number(cell.colSpan) || 1, 50);
      return Array(span).fill((cell.textContent || '').trim());
    })
    : [];
  const width = Math.max(headers.length, ...bodyRows.map((tr) => tr.cells.length), 0);
  if (!width) return null;
  const names = [];
  for (let index = 0; index < width; index += 1) {
    names.push(headers[index] || `列${index + 1}`);
  }
  const usesTd = bodyRows[0] ? bodyRows[0].querySelector('td') !== null : true;
  const cellTag = usesTd ? 'td' : 'th';
  let itemSelector;
  if (thead && table.querySelector('tbody')) {
    itemSelector = `${base} tbody tr`;
  } else if (!thead && headerRow === allRows[0] && !headerRow.querySelector('th') && bodyRows.length >= 2) {
    itemSelector = `${base} tr + tr`;
  } else {
    itemSelector = `${base} tr`;
  }
  const fields = names.map((name, index) => ({
    name,
    selector: `${cellTag}:nth-child(${index + 1})`,
    attr: 'text',
    selector_type: 'css',
  }));
  return {
    kind: 'table',
    selector: base,
    item_selector: itemSelector,
    item_selector_type: 'css',
    headers: names,
    fields,
    rows: bodyRows.length,
    cols: width,
    hidden: false,
    nested: false,
    sample: bodyRows.slice(0, 3).map((tr) => Array.from(tr.cells).map((cell) => (cell.textContent || '').trim())),
    rule: {
      mode: 'css',
      item_selector: itemSelector,
      item_selector_type: 'css',
      fields,
    },
  };
}

function buildListCandidateFromDom(item, parent) {
  const itemSelector = `${pickCssPath(parent)} > ${pickItemSegment(item)}`;
  let items = [];
  try {
    items = Array.from(parent.children).filter((sibling) => {
      const classes = Array.from(item.classList).filter((name) => SAFE_IDENT.test(name));
      return sibling.tagName === item.tagName
        && (classes.length === 0 || classes.every((name) => sibling.classList.contains(name)));
    });
  } catch {
    items = [item];
  }
  const sample = items.slice(0, 4);
  const specs = collectPickFieldSpecs(item).sort((a, b) => b.priority - a.priority);
  const fields = [];
  const usedNames = new Set();
  const usedSelectors = new Set();
  specs.forEach((spec) => {
    const selector = pickRelativeSelector(item, spec.el);
    const key = `${selector}|${spec.attr}`;
    if (usedSelectors.has(key)) return;
    const coverage = sample.length
      ? sample.filter((node2) => {
        try {
          return Boolean(node2.querySelector(selector));
        } catch {
          return false;
        }
      }).length / sample.length
      : 1;
    if (coverage < 0.6) return;
    let name = guessFieldName(spec.el, spec.attr);
    if (usedNames.has(name)) {
      let suffix = 2;
      while (usedNames.has(`${name}_${suffix}`)) suffix += 1;
      name = `${name}_${suffix}`;
    }
    usedNames.add(name);
    usedSelectors.add(key);
    fields.push({
      name,
      selector,
      attr: spec.attr,
      selector_type: 'css',
    });
  });
  if (!fields.length) return null;
  return {
    kind: 'list',
    selector: itemSelector,
    item_selector: itemSelector,
    item_selector_type: 'css',
    headers: fields.map((field) => field.name),
    fields,
    count: items.length,
    sample: sample.slice(0, 3).map((node2) => fields.map((field) => {
      const el = node2.querySelector(field.selector);
      if (!el) return '';
      return field.attr === 'href' ? (el.getAttribute('href') || '') : field.attr === 'src' ? (el.getAttribute('src') || '') : (el.textContent || '').trim();
    })),
    hidden: false,
    rule: {
      mode: 'css',
      item_selector: itemSelector,
      item_selector_type: 'css',
      fields,
    },
  };
}

function pickSetEnabled(enabled) {
  ['pick-apply', 'pick-run', 'pick-save'].forEach((id) => {
    $(id).disabled = !enabled;
  });
}

function renderPickSelection(candidate) {
  const box = $('pick-selection');
  box.textContent = '';
  box.className = 'pick-selection';
  box.appendChild(node('b', '', candidate.kind === 'table' ? '表格规则' : '列表规则'));
  box.appendChild(node('div', 'pick-rule-line', `条目选择器：${candidate.item_selector}`));
  const names = (candidate.fields || []).map((field) => `${field.name}（${field.attr || 'text'}）`).join('、');
  box.appendChild(node('div', 'pick-rule-line', `字段：${names || '无'}`));
  if (candidate.hidden) {
    box.appendChild(node('div', 'warn', '该表格在页面中被隐藏，快照已自动展开。'));
  }
  pickSetEnabled(true);
}

function highlightPickSelection(candidate) {
  const frame = $('pick-frame');
  let doc;
  try {
    doc = frame.contentDocument;
  } catch {
    return;
  }
  if (!doc) return;
  doc.querySelectorAll('.__dh_selected').forEach((el) => el.classList.remove('__dh_selected'));
  let el = null;
  try {
    el = doc.querySelector(candidate.selector || candidate.item_selector);
  } catch {
    el = null;
  }
  if (el) {
    el.classList.add('__dh_selected');
    try { el.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch { /* 忽略 */ }
  }
}

function selectPickCandidate(candidate) {
  if (!candidate || !candidate.rule) return;
  pickState.rule = candidate.rule;
  renderPickSelection(candidate);
  highlightPickSelection(candidate);
}

function cantRenderPick(message) {
  $('pick-loading').hidden = false;
  $('pick-loading').textContent = message;
}

function loadPickFrame(html) {
  const frame = $('pick-frame');
  if (pickState.blobUrl) URL.revokeObjectURL(pickState.blobUrl);
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  pickState.blobUrl = URL.createObjectURL(blob);
  pickState.bound = false;
  frame.onload = () => {
    bindPickFrame();
    $('pick-loading').hidden = true;
  };
  frame.src = pickState.blobUrl;
}

function bindPickFrame() {
  const frame = $('pick-frame');
  let doc;
  try {
    doc = frame.contentDocument;
  } catch {
    cantRenderPick('浏览器不允许访问快照内容，请换用 Chrome / Edge 重试。');
    return;
  }
  if (!doc || pickState.bound) return;
  pickState.bound = true;
  const style = doc.createElement('style');
  style.textContent = `
    .__dh_hover { outline: 3px solid #38bdf8 !important; outline-offset: -3px !important; background: rgba(56,189,248,.08) !important; cursor: crosshair !important; }
    .__dh_selected { outline: 3px solid #34d399 !important; outline-offset: -3px !important; background: rgba(52,211,153,.10) !important; }
  `;
  (doc.head || doc.documentElement).appendChild(style);

  const clearHover = () => {
    doc.querySelectorAll('.__dh_hover').forEach((el) => el.classList.remove('__dh_hover'));
  };
  doc.addEventListener('mouseover', (event) => {
    const target = pickTarget(event.target);
    clearHover();
    if (target) target.el.classList.add('__dh_hover');
  }, true);
  doc.addEventListener('mouseout', clearHover, true);
  doc.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    const target = pickTarget(event.target);
    if (!target) {
      notice('没有识别到表格或重复列表，请点击更具体的条目。', 'error');
      return;
    }
    let candidate = null;
    if (target.kind === 'table') {
      const path = pickCssPath(target.el);
      candidate = ((pickState.data || {}).tables || []).find((item) => item.selector === path);
      if (!candidate) candidate = buildTableCandidateFromDom(target.el);
    } else {
      candidate = buildListCandidateFromDom(target.el, target.parent);
      const matched = candidate && ((pickState.data || {}).lists || []).find(
        (item) => item.item_selector === candidate.item_selector
      );
      if (matched) candidate = matched;
    }
    if (candidate) {
      selectPickCandidate(candidate);
      notice('已生成规则，可点击右侧「套用到表单」。', 'ok');
    } else {
      notice('该区域无法生成规则，请尝试点击其他表格或列表。', 'error');
    }
  }, true);
  doc.addEventListener('submit', (event) => event.preventDefault(), true);
  doc.addEventListener('auxclick', (event) => event.preventDefault(), true);
}

function renderPickCandidates(data) {
  const tableBox = $('pick-tables');
  const listBox = $('pick-lists');
  tableBox.textContent = '';
  listBox.textContent = '';
  const tables = data.tables || [];
  const lists = data.lists || [];
  $('pick-table-count').textContent = tables.length ? `共 ${tables.length} 个` : '';
  $('pick-list-count').textContent = lists.length ? `共 ${lists.length} 个` : '';

  if (!tables.length) {
    tableBox.appendChild(node('p', 'hint', '未检测到表格，可直接在预览中点击重复列表项。'));
  }
  tables.forEach((candidate, index) => {
    const chip = node('button', 'pick-chip');
    chip.type = 'button';
    chip.appendChild(node('span', 'pick-chip-title', `表格 #${index + 1} · ${candidate.rows} 行 × ${candidate.cols} 列`));
    if (candidate.hidden) chip.appendChild(node('span', 'pick-badge', '隐藏'));
    if (candidate.nested) chip.appendChild(node('span', 'pick-badge muted-badge', '嵌套'));
    chip.appendChild(node('span', 'pick-chip-sub', (candidate.headers || []).slice(0, 4).join(' | ') || '无表头'));
    chip.addEventListener('click', () => selectPickCandidate(candidate));
    tableBox.appendChild(chip);
  });

  if (!lists.length) {
    listBox.appendChild(node('p', 'hint', '未检测到重复列表，可直接在预览中点击卡片。'));
  }
  lists.forEach((candidate, index) => {
    const chip = node('button', 'pick-chip');
    chip.type = 'button';
    chip.appendChild(node('span', 'pick-chip-title', `列表 #${index + 1} · ${candidate.count} 个条目`));
    chip.appendChild(node('span', 'pick-chip-sub', (candidate.headers || []).slice(0, 4).join(' | ')));
    chip.addEventListener('click', () => selectPickCandidate(candidate));
    listBox.appendChild(chip);
  });
}

async function openPicker() {
  if (source === 'image') {
    notice('图片识别不需要可视化点选。', 'error');
    return;
  }
  if (source === 'url' && !$('url').value.trim()) {
    notice('请先填写网页 URL。', 'error');
    return;
  }
  if (source === 'html' && $('html').value.trim().length < 20) {
    notice('请先粘贴 HTML 内容。', 'error');
    return;
  }
  $('pick-modal').hidden = false;
  document.body.classList.add('modal-open');
  $('pick-loading').hidden = false;
  $('pick-loading').textContent = '正在生成安全快照…';
  $('pick-meta').textContent = '';
  $('pick-selection').textContent = '尚未选择';
  $('pick-selection').className = 'pick-selection muted';
  $('pick-tables').textContent = '';
  $('pick-lists').textContent = '';
  $('pick-table-count').textContent = '';
  $('pick-list-count').textContent = '';
  pickSetEnabled(false);
  pickState.data = null;
  pickState.rule = null;

  const request = currentRequest({ forAnalyze: true });
  try {
    const data = await api('/api/snapshot', {
      method: 'POST',
      body: {
        source: request.source,
        url: request.url,
        html: request.html,
        base_url: request.base_url,
        browser: request.browser,
        ignore_robots: request.ignore_robots,
        wait_for: request.wait_for,
        scan_full_page: request.scan_full_page,
        expand_clicks: request.expand_clicks,
        cache_mode: request.cache_mode,
        reveal_hidden: true,
      },
    });
    pickState.data = data;
    $('pick-meta').textContent =
      `${data.title || '（无标题）'} · ${data.final_url}` +
      (data.tables.length ? ` · 表格 ${data.tables.length}` : '') +
      (data.lists.length ? ` · 列表 ${data.lists.length}` : '');
    renderPickCandidates(data);
    loadPickFrame(data.snapshot_html);
  } catch (error) {
    cantRenderPick(error.message);
  }
}

function closePicker() {
  $('pick-modal').hidden = true;
  document.body.classList.remove('modal-open');
  const frame = $('pick-frame');
  frame.onload = null;
  try { frame.src = 'about:blank'; } catch { /* 忽略 */ }
  if (pickState.blobUrl) {
    URL.revokeObjectURL(pickState.blobUrl);
    pickState.blobUrl = '';
  }
  pickState.data = null;
  pickState.rule = null;
  pickState.bound = false;
}

function applyPick(andRun) {
  if (!pickState.rule) {
    notice('请先在快照中选择一个表格或列表。', 'error');
    return;
  }
  if (!applyRuleToForm(pickState.rule)) {
    notice('规则不完整，无法套用。', 'error');
    return;
  }
  closePicker();
  if (andRun) {
    notice('已套用可视化规则，正在开始抓取…', 'ok');
    startJob();
  } else {
    notice('已把规则套用到高级设置，确认后点击「开始抓取」。', 'ok');
  }
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
  $('deep').addEventListener('change', () => {
    const on = $('deep').checked;
    $('pages').disabled = on;
    if (on) $('pages').value = '1';
  });
  $('add-field').addEventListener('click', () => addField());
  $('analyze').addEventListener('click', analyzePage);
  $('run').addEventListener('click', startJob);
  $('visual-pick').addEventListener('click', openPicker);
  $('pick-close').addEventListener('click', closePicker);
  $('pick-apply').addEventListener('click', () => applyPick(false));
  $('pick-run').addEventListener('click', () => applyPick(true));
  $('pick-save').addEventListener('click', () => saveTemplateFlow(pickState.rule));
  $('apply-template').addEventListener('click', applySelectedTemplate);
  $('delete-template').addEventListener('click', deleteSelectedTemplate);
  $('save-template').addEventListener('click', () => saveTemplateFlow());
  $('pick-modal').addEventListener('click', (event) => {
    if (event.target === $('pick-modal')) closePicker();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !$('pick-modal').hidden) closePicker();
  });
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
  $('image-file').addEventListener('change', (event) => {
    const file = event.target.files[0];
    if (!file) return;
    imageData = '';
    imageName = file.name;
    $('image-preview').hidden = true;
    const allowedTypes = ['image/jpeg', 'image/png', 'image/webp'];
    if (file.size > 10_000_000) {
      event.target.value = '';
      notice('图片超过 10 MB，请压缩后重试。', 'error');
      return;
    }
    if (file.type && !allowedTypes.includes(file.type)) {
      event.target.value = '';
      notice('仅支持 JPG、PNG、WebP 图片。', 'error');
      return;
    }
    $('image-name').textContent = `正在读取：${file.name}`;
    const reader = new FileReader();
    reader.onerror = () => notice('图片读取失败，请重新选择。', 'error');
    reader.onload = () => {
      imageData = String(reader.result || '');
      $('image-name').textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
      $('image-preview').src = imageData;
      $('image-preview').hidden = false;
      notice('图片已载入，点击「开始识别」即可。', 'ok');
    };
    reader.readAsDataURL(file);
  });

  addField('标题', 'h2', 'text');
  addField('链接', 'a', 'href');
  switchMode('auto');
  loadHistory();
  loadTemplates();
}

boot();
