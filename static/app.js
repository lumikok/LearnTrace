const state = { dayRecords: [], activity: {}, milestones: [], categories: [], stats: {}, first_used_on: null, selectedDay: today(), editingId: null, searchPage: 1, searchTotal: 0, searchRequest: 0, reviewWeek: monday(today()), calendarRendered: false };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const formatDay = (day) => new Intl.DateTimeFormat('zh-CN', {year:'numeric',month:'long',day:'numeric',weekday:'long'}).format(new Date(`${day}T12:00:00`));
function today() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function offsetDay(day, amount) { const d = new Date(`${day}T12:00:00`); d.setDate(d.getDate()+amount); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function monday(day) { const weekday = new Date(`${day}T12:00:00`).getDay(); return offsetDay(day, -(weekday + 6) % 7); }

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type':'application/json'}, ...options});
  if (!response.ok) {
    let message = '操作失败，请稍后重试';
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : body.detail?.[0]?.msg || message; } catch {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}
async function refresh() {
  const data = await api('/api/overview');
  Object.assign(state, data);
  if (state.selectedDay < state.first_used_on) state.selectedDay = state.first_used_on;
  if (state.selectedDay > today()) state.selectedDay = today();
  state.dayRecords = await api(`/api/records?day=${state.selectedDay}`);
  if (offsetDay(state.reviewWeek, 6) < state.first_used_on) state.reviewWeek = monday(state.first_used_on);
  render();
  await Promise.all([runSearch(), loadReview()]);
}
function toast(message) {
  const node = $('#toast'); node.textContent = message; node.classList.add('show');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove('show'), 3000);
}
function render() {
  $('#todayLabel').textContent = formatDay(today());
  $('#selectedDay').value = state.selectedDay;
  $('#selectedDay').min = state.first_used_on;
  $('#selectedDay').max = today();
  $('#prevDay').disabled = state.selectedDay <= state.first_used_on;
  $('#nextDay').disabled = state.selectedDay >= today();
  for (const input of document.querySelectorAll('.modal input[type="date"]')) { input.min = state.first_used_on; input.max = today(); }
  $('#searchFrom').min = state.first_used_on;
  $('#searchFrom').max = today();
  $('#searchTo').min = state.first_used_on;
  $('#searchTo').max = today();
  $('#totalRecords').textContent = state.stats.total_records;
  $('#activeDays').textContent = state.stats.active_days;
  $('#totalMinutes').textContent = state.stats.total_minutes;
  $('#totalMilestones').textContent = state.milestones.length;
  renderCalendar(); renderRecords(); renderMilestones();
}
function renderCalendar() {
  const milestones = new Set(state.milestones.map((item) => item.day));
  const end = today(), start = state.first_used_on;
  $('#calendarRange').textContent = `自 ${start} 起`;
  const first = new Date(`${start}T12:00:00`);
  const gridStart = offsetDay(start, -first.getDay());
  const weeks = [];
  const monthLabels = [];
  for (let weekStart = gridStart; weekStart <= end; weekStart = offsetDay(weekStart, 7)) {
    const days = [];
    const firstOfMonth = Array.from({length: 7}, (_, n) => offsetDay(weekStart, n)).find((day) => day.slice(8) === '01' && day >= start && day <= end);
    const monthDay = firstOfMonth || (weeks.length === 0 && (Number(start.slice(8)) <= 14 || start.slice(0, 7) === end.slice(0, 7)) ? start : null);
    monthLabels.push(`<span class="month-slot">${monthDay ? `<span>${monthDay.slice(5, 7) === '01' ? `${monthDay.slice(0, 4)}年` : ''}${Number(monthDay.slice(5, 7))}月</span>` : ''}</span>`);
    for (let n = 0; n < 7; n++) {
      const day = offsetDay(weekStart, n), activity = state.activity[day] || {count: 0, level: 0};
      if (day < start || day > end) { days.push('<span class="day-cell future"></span>'); continue; }
      const label = `${day}：${activity.count} 条记录，活跃等级 ${activity.level}/4${milestones.has(day) ? '，有成长节点' : ''}`;
      days.push(`<button class="day-cell level-${activity.level}${day === state.selectedDay ? ' selected' : ''}${milestones.has(day) ? ' has-milestone' : ''}" data-day="${day}" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}"></button>`);
    }
    weeks.push(`<div class="week">${days.join('')}</div>`);
  }
  const scroller = $('#calendarScroll'), oldScroll = scroller.scrollLeft;
  $('#calendar').innerHTML = `<div class="calendar-month-row"><span></span><div class="month-track">${monthLabels.join('')}</div></div><div class="calendar-body"><div class="weekday-axis"><span></span><span>一</span><span></span><span>三</span><span></span><span>五</span><span></span></div><div class="calendar-weeks">${weeks.join('')}</div></div>`;
  scroller.scrollLeft = state.calendarRendered ? oldScroll : scroller.scrollWidth;
  state.calendarRendered = true;
}
function renderRecords() {
  const items = state.dayRecords;
  $('#daySummary').textContent = `${formatDay(state.selectedDay)} · ${items.length} 条记录 · 活跃等级 ${state.activity[state.selectedDay]?.level ?? 0}/4`;
  $('#recordList').innerHTML = items.length ? items.map((item) => `<article class="entry"><div class="entry-top"><span class="badge">${escapeHtml(item.category)}</span><div><button class="icon-button" data-edit="${item.id}">编辑</button><button class="icon-button" data-delete="${item.id}">删除</button></div></div><p class="entry-content">${escapeHtml(item.content)}</p><div class="entry-meta">${item.minutes !== null ? `<span>◷ ${item.minutes} 分钟</span>` : ''}${item.link ? `<a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer">查看成果 ↗</a>` : ''}</div></article>`).join('') : '<div class="empty">这一天还没有记录。<br>按下「添加记录」，留下今天学到的东西。</div>';
}
function renderMilestones() {
  $('#milestoneList').innerHTML = state.milestones.length ? state.milestones.map((item) => `<article class="milestone"><time>${escapeHtml(item.day)}</time><h3>${escapeHtml(item.title)}</h3>${item.detail ? `<p>${escapeHtml(item.detail)}</p>` : ''}<button class="icon-button" data-delete-milestone="${item.id}">删除节点</button></article>`).join('') : '<div class="empty">还没有成长节点。<br>完成了一件值得记住的事，就把它记在这里。</div>';
}
function searchParams() {
  return {query: $('#searchQuery').value.trim(), category: $('#searchCategory').value, from_day: $('#searchFrom').value, to_day: $('#searchTo').value};
}
async function runSearch() {
  const categorySelect = $('#searchCategory'), selectedCategory = categorySelect.value;
  const categories = state.categories;
  categorySelect.innerHTML = '<option value="">全部类别</option>' + categories.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
  categorySelect.value = categories.includes(selectedCategory) ? selectedCategory : '';
  const filters = searchParams(), request = ++state.searchRequest;
  if (!Object.values(filters).some(Boolean)) {
    state.searchTotal = 0; state.searchPage = 1;
    $('#searchCount').textContent = '';
    $('#searchResults').innerHTML = '<div class="empty">输入关键词或选择类别、日期后，才会显示记录。</div>';
    $('#searchPages').hidden = true;
    return;
  }
  try {
    const params = new URLSearchParams({...filters, page: String(state.searchPage), page_size: '20'});
    const result = await api(`/api/search?${params}`);
    if (request !== state.searchRequest) return;
    state.searchTotal = result.total;
    const pages = Math.max(1, Math.ceil(result.total / 20));
    if (state.searchPage > pages) { state.searchPage = pages; return runSearch(); }
    $('#searchCount').textContent = `找到 ${result.total} 条`;
    $('#searchResults').innerHTML = result.items.length ? result.items.map((item) => `<button type="button" class="search-result" data-search-day="${item.day}"><span><time>${item.day}</time><strong>${escapeHtml(item.category)}</strong></span><span class="search-excerpt">${escapeHtml(item.content)}</span><span aria-hidden="true">↗</span></button>`).join('') : '<div class="empty">没有找到符合条件的记录。</div>';
    $('#searchPages').hidden = pages <= 1;
    $('#searchPageLabel').textContent = `第 ${state.searchPage} / ${pages} 页`;
    $('#searchPrev').disabled = state.searchPage <= 1;
    $('#searchNext').disabled = state.searchPage >= pages;
  } catch (error) { if (request === state.searchRequest) $('#searchResults').innerHTML = `<div class="empty">查询失败：${escapeHtml(error.message)}</div>`; }
}
async function loadReview() {
  $('#reviewPrev').disabled = offsetDay(state.reviewWeek, -1) < state.first_used_on;
  $('#reviewNext').disabled = state.reviewWeek >= monday(today());
  const review = await api(`/api/review?week_start=${state.reviewWeek}`);
  $('#reviewRange').textContent = `${review.week_start} — ${review.week_end}`;
  const topics = review.categories.map((item) => `${escapeHtml(item.category)} ${item.count} 条`).join(' · ');
  $('#reviewSummary').innerHTML = `<span>${review.total_records} 条记录</span><span>${review.active_days} 天有学习</span><span>${review.total_minutes} 分钟已记录</span>${topics ? `<p>本周主题：${topics}</p>` : ''}`;
  $('#reviewHighlights').innerHTML = review.highlights.length ? `<h3>回看记录</h3>${review.highlights.map((item) => `<p><time>${item.day}</time> · ${escapeHtml(item.category)} · ${escapeHtml(item.content)}</p>`).join('')}` : '<div class="empty">这周还没有学习记录，仍可写下观察和下一步。</div>';
  $('#reviewForm').elements.learning.value = review.learning;
  $('#reviewForm').elements.next_step.value = review.next_step;
  $('#reviewStatus').textContent = '';
}
function openRecord(item = null) {
  state.editingId = item?.id ?? null;
  const form = $('#recordForm'); form.reset();
  form.elements.day.value = item?.day ?? state.selectedDay;
  form.elements.category.value = item?.category ?? '';
  form.elements.content.value = item?.content ?? '';
  form.elements.minutes.value = item?.minutes ?? '';
  form.elements.link.value = item?.link ?? '';
  $('#recordDialogTitle').textContent = item ? '编辑学习记录' : '添加学习记录';
  $('#recordError').textContent = '';
  $('#recordDialog').showModal();
}
function openMilestone() {
  const form = $('#milestoneForm'); form.reset(); form.elements.day.value = state.selectedDay;
  $('#milestoneError').textContent = '';
  $('#milestoneDialog').showModal();
}
async function selectDay(day) { state.selectedDay = day; state.dayRecords = await api(`/api/records?day=${day}`); render(); $('#journal').scrollIntoView({behavior:'smooth',block:'start'}); }

$('#quickAdd').addEventListener('click', () => openRecord());
$('#addRecord').addEventListener('click', () => openRecord());
$('#addMilestone').addEventListener('click', openMilestone);
$('#selectedDay').addEventListener('change', (event) => { if (event.target.value) selectDay(event.target.value); });
$('#prevDay').addEventListener('click', () => selectDay(offsetDay(state.selectedDay, -1)));
$('#nextDay').addEventListener('click', () => selectDay(offsetDay(state.selectedDay, 1)));
$('#jumpToday').addEventListener('click', () => selectDay(today()));
$('#calendar').addEventListener('click', (event) => { const day = event.target.closest('[data-day]')?.dataset.day; if (day) selectDay(day); });
for (const selector of ['#searchQuery','#searchCategory','#searchFrom','#searchTo']) {
  document.querySelector(selector).addEventListener(selector === '#searchQuery' ? 'input' : 'change', () => { state.searchPage = 1; runSearch(); });
}
$('#clearSearch').addEventListener('click', () => { $('#searchQuery').value = ''; $('#searchCategory').value = ''; $('#searchFrom').value = ''; $('#searchTo').value = ''; state.searchPage = 1; runSearch(); });
$('#searchPrev').addEventListener('click', () => { if (state.searchPage > 1) { state.searchPage--; runSearch(); } });
$('#searchNext').addEventListener('click', () => { if (state.searchPage * 20 < state.searchTotal) { state.searchPage++; runSearch(); } });
$('#searchResults').addEventListener('click', (event) => { const day = event.target.closest('[data-search-day]')?.dataset.searchDay; if (day) selectDay(day); });
$('#reviewPrev').addEventListener('click', () => { state.reviewWeek = offsetDay(state.reviewWeek, -7); loadReview().catch((error) => toast(error.message)); });
$('#reviewNext').addEventListener('click', () => { state.reviewWeek = offsetDay(state.reviewWeek, 7); loadReview().catch((error) => toast(error.message)); });
$('#reviewForm').addEventListener('submit', async (event) => { event.preventDefault(); const form = event.target; try { await api('/api/review', {method:'PUT',body:JSON.stringify({week_start:state.reviewWeek,learning:form.elements.learning.value,next_step:form.elements.next_step.value})}); $('#reviewStatus').textContent = '已保存'; toast('本周回顾已保存'); } catch (error) { $('#reviewStatus').textContent = error.message; } });
$('#saveBackup').addEventListener('click', async () => {
  try { const result = await api('/api/backup-local', {method:'POST'}); $('#dataStatus').textContent = `备份已保存：${result.path}`; toast('本地备份已保存'); }
  catch (error) { $('#dataStatus').textContent = error.message; }
});
$('#restoreFile').addEventListener('change', async (event) => {
  const file = event.target.files?.[0]; if (!file) return;
  if (!confirm(`确定从「${file.name}」恢复吗？当前数据会先自动备份，再由该文件替换。`)) { event.target.value = ''; return; }
  try {
    const result = await api('/api/restore', {method:'POST',headers:{'Content-Type':'application/octet-stream'},body:await file.arrayBuffer()});
    await refresh(); $('#dataStatus').textContent = `恢复完成。原数据的安全副本：${result.safety_backup}`; toast('数据已恢复');
  } catch (error) { $('#dataStatus').textContent = `恢复失败：${error.message}`; }
  event.target.value = '';
});
$('#recordList').addEventListener('click', async (event) => {
  const edit = event.target.closest('[data-edit]');
  if (edit) { openRecord(state.dayRecords.find((item) => item.id === Number(edit.dataset.edit))); return; }
  const remove = event.target.closest('[data-delete]');
  if (!remove || !confirm('确定删除这条学习记录吗？')) return;
  try { await api(`/api/records/${remove.dataset.delete}`, {method:'DELETE'}); await refresh(); toast('记录已删除'); } catch (error) { toast(error.message); }
});
$('#milestoneList').addEventListener('click', async (event) => {
  const remove = event.target.closest('[data-delete-milestone]');
  if (!remove || !confirm('确定删除这个成长节点吗？')) return;
  try { await api(`/api/milestones/${remove.dataset.deleteMilestone}`, {method:'DELETE'}); await refresh(); toast('节点已删除'); } catch (error) { toast(error.message); }
});
document.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
$('#recordForm').addEventListener('submit', async (event) => {
  event.preventDefault(); const form = event.target;
  const payload = {day:form.elements.day.value,category:form.elements.category.value.trim(),content:form.elements.content.value.trim(),minutes:form.elements.minutes.value === '' ? null : Number(form.elements.minutes.value),link:form.elements.link.value.trim() || null};
  try {
    await api(state.editingId ? `/api/records/${state.editingId}` : '/api/records', {method:state.editingId ? 'PUT' : 'POST',body:JSON.stringify(payload)});
    state.selectedDay = payload.day; form.closest('dialog').close(); await refresh(); toast('记录已保存');
  } catch (error) { $('#recordError').textContent = error.message; }
});
$('#milestoneForm').addEventListener('submit', async (event) => {
  event.preventDefault(); const form = event.target;
  const payload = {day:form.elements.day.value,title:form.elements.title.value.trim(),detail:form.elements.detail.value.trim()};
  try { await api('/api/milestones', {method:'POST',body:JSON.stringify(payload)}); form.closest('dialog').close(); await refresh(); toast('成长节点已保存'); }
  catch (error) { $('#milestoneError').textContent = error.message; }
});
refresh().catch((error) => { $('#recordList').innerHTML = `<div class="empty">加载失败：${escapeHtml(error.message)}。请刷新页面重试。</div>`; });
