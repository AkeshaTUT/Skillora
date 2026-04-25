const queryInput = document.getElementById('query');
const sourceSelect = document.getElementById('source');
const searchBtn = document.getElementById('searchBtn');
const statusEl = document.getElementById('status');
const dbBadge = document.getElementById('db-badge');
const resultsEl = document.getElementById('results');

function esc(str) {
  return String(str || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderStars(rating) {
  if (!rating) return '<span class="stars">—</span>';
  const r = parseFloat(rating);
  const full = Math.floor(r);
  const half = r - full >= 0.3;
  let s = '';
  for (let i = 0; i < full && i < 5; i++) s += '★';
  if (half && full < 5) s += '½';
  return `<span class="stars">${r.toFixed(1)} ${s}</span>`;
}

function formatNum(n) {
  if (!n) return '0';
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(n);
}

function badgeClass(platform) {
  const p = (platform || '').toLowerCase();
  if (p === 'udemy') return 'badge badge-udemy';
  if (p === 'coursera') return 'badge badge-coursera';
  return 'badge badge-unknown';
}

function render(items) {
  resultsEl.innerHTML = '';
  if (!items.length) {
    resultsEl.innerHTML = '<div class="no-results">Ничего не найдено. Попробуйте другой запрос.</div>';
    return;
  }

  items.forEach((item, i) => {
    const card = document.createElement('article');
    card.className = 'card';
    card.style.animationDelay = `${Math.min(i * 0.04, 0.6)}s`;

    const imgUrl = item.image_url || item.image || '';
    const imgHtml = imgUrl
      ? `<img class="card-img" src="${esc(imgUrl)}" alt="${esc(item.title)}" loading="lazy" onerror="this.style.display='none'" />`
      : '';

    const level = item.level ? `<span class="badge-level">${esc(item.level)}</span>` : '';
    const instructor = item.instructor ? `<div class="card-instructor">👤 ${esc(item.instructor)}</div>` : '';
    const url = item.course_url || item.url || '#';

    card.innerHTML = `
      ${imgHtml}
      <div class="card-body">
        <div class="card-top">
          <span class="${badgeClass(item.platform)}">${esc(item.platform || 'unknown')}</span>
          ${level}
        </div>
        <h3>${esc(item.title || 'Untitled')}</h3>
        <p class="card-desc">${esc(item.description || item.headline || '')}</p>
        ${instructor}
        <div class="card-stats">
          <span class="stat">${renderStars(item.rating)}</span>
          <span class="stat">📝 ${formatNum(item.reviews_count || item.num_reviews)} отзывов</span>
          ${item.subscribers_count || item.num_subscribers ? `<span class="stat">👥 ${formatNum(item.subscribers_count || item.num_subscribers)}</span>` : ''}
          ${item.content_length ? `<span class="stat">⏱ ${esc(item.content_length)}</span>` : ''}
        </div>
      </div>
      <div class="card-footer">
        <a href="${esc(url)}" target="_blank" rel="noreferrer">
          Открыть курс →
        </a>
      </div>
    `;
    resultsEl.appendChild(card);
  });
}

async function runSearch() {
  const query = queryInput.value.trim();
  const source = sourceSelect.value;

  if (query.length < 2) {
    statusEl.textContent = 'Введите минимум 2 символа';
    return;
  }

  statusEl.textContent = 'Ищем...';
  dbBadge.classList.add('hidden');
  searchBtn.disabled = true;
  searchBtn.classList.add('loading');

  // Show skeleton while loading
  showSkeleton();

  // Show 'live search' warning after 5 sec
  const slowTimer = setTimeout(() => {
    statusEl.textContent = '🌐 Ищем в интернете — подождите несколько секунд...';
  }, 5000);

  try {
    const params = new URLSearchParams({ query, source, limit: '30' });
    const resp = await fetch(`/api/external/search?${params.toString()}`);
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }

    const payload = await resp.json();
    render(payload.items || []);

    const fromCache = payload.cached === true;
    const fromDb = (payload.items || []).some(i => i.source === 'db');
    const count = payload.count || 0;

    if (count === 0) {
      statusEl.textContent = 'Ничего не найдено. Попробуйте другой запрос.';
    } else {
      statusEl.textContent = `Найдено: ${count} курсов${fromCache ? ' (из кеша)' : fromDb ? ' (из базы)' : ' (live)'}`;
    }

    if (fromDb || fromCache) {
      dbBadge.classList.remove('hidden');
    }
  } catch (err) {
    statusEl.textContent = `Ошибка: ${err.message}`;
    resultsEl.innerHTML = '';
  } finally {
    clearTimeout(slowTimer);
    searchBtn.disabled = false;
    searchBtn.classList.remove('loading');
  }
}

searchBtn.addEventListener('click', runSearch);
queryInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') runSearch();
});

// Focus search on load
queryInput.focus();

// ---- Loading skeleton ----
function showSkeleton() {
  resultsEl.innerHTML = Array.from({ length: 6 }, () => `
    <article class="card skeleton">
      <div class="sk-img"></div>
      <div class="card-body">
        <div class="sk-line" style="width:40%"></div>
        <div class="sk-line" style="width:80%;height:18px;margin:8px 0"></div>
        <div class="sk-line" style="width:65%"></div>
        <div class="sk-line" style="width:50%;margin-top:12px"></div>
      </div>
    </article>
  `).join('');
}
