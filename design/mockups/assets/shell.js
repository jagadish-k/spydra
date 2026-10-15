/* ==========================================================================
   Spydra — mockup shell
   Deliberately a classic script, not an ES module: these pages are opened
   straight off disk with file://, where module imports are blocked by CORS.
   The React app has no such constraint; this is a mockup-harness decision.
   The sidebar and topbar are defined once here and injected into every
   screen. Ten hand-copied shells drift within a day; one definition does
   not. In the React app this file corresponds to <AppShell>.
   ========================================================================== */

const ICONS = {
  domains:  'M3 3h10v10H3z M3 6h10 M6 3v10',
  seeds:    'M8 2v12 M2.5 8h11 M8 2 5 5 M8 2l3 3',
  templates:'M2.5 4h11v8h-11z M2.5 7h11 M6 7v5',
  runs:     'M4 2.5l9 5.5-9 5.5z',
  unknown:  'M8 10.5v.01 M8 8.5c0-1.5 1.8-1.6 1.8-3A1.8 1.8 0 006.3 5 M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13z',
  products: 'M8 1.8l5.5 3v6.4L8 14.2 2.5 11.2V4.8z M2.5 4.8L8 7.8l5.5-3 M8 7.8v6.4',
  reports:  'M3 13V7 M8 13V3 M13 13v-4',
  search:   'M7 2.5a4.5 4.5 0 100 9 4.5 4.5 0 000-9z M10.5 10.5l3 3',
  sun:      'M8 5.2a2.8 2.8 0 100 5.6 2.8 2.8 0 000-5.6z M8 1.4v1.6 M8 13v1.6 M2.4 8H1 M15 8h-1.4 M4 4l1.1 1.1 M10.9 10.9L12 12 M12 4l-1.1 1.1 M5.1 10.9L4 12',
  moon:     'M13.2 9.6A5.6 5.6 0 016.4 2.8 5.8 5.8 0 108.9 14a5.8 5.8 0 004.3-4.4z',
  collapse: 'M6 3.5v9 M2.5 2.5h11v11h-11z',
  play:     'M4 2.5l9 5.5-9 5.5z',
  chat:     'M2.5 3h11v8h-6l-3 2.5V11h-2z M5 6h6 M5 8h4',
  playground: 'M3 2.5l4.2 11 1.9-4.4 4.4-1.9z',
};

const NAV = [
  { section: 'Operate' },
  { id: 'domains',       label: 'Domains',       href: 'domains.html' },
  { id: 'seeds',         label: 'Seeds',         href: 'seeds.html' },
  { id: 'runs',          label: 'Runs',          href: 'run-monitor.html',
    count: { text: '412', kind: 'live' } },
  { section: 'Author' },
  { id: 'chat',          label: 'Authoring Chat', href: 'authoring-chat.html' },
  { id: 'playground',    label: 'Playground',    href: 'playground.html' },
  { section: 'Review' },
  { id: 'templates',     label: 'Templates',     href: 'template-review.html',
    count: { text: '7', kind: 'attention' } },
  { id: 'unknown',       label: 'Unknown Pages', href: 'unknown-pages.html',
    count: { text: '38', kind: 'attention' } },
  { section: 'Data' },
  { id: 'products',      label: 'Products',      href: 'products.html' },
  { id: 'reports',       label: 'Reports',       href: 'reports.html' },
];

const icon = (name, cls = '') =>
  `<svg class="${cls}" viewBox="0 0 16 16" fill="none" stroke="currentColor"
     stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"
     aria-hidden="true"><path d="${ICONS[name]}"/></svg>`;

/* The mark, inlined so the sidebar needs no network request and follows
   currentColor through a theme change. Geometry matches
   design/logo/build_logo.py exactly. */
const MARK = `
<svg viewBox="0 0 64 64" fill="none" aria-hidden="true">
  <g opacity="0.38" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round">
    <path d="M32,28 L32,6"/><path d="M35.46,30 L54.52,19"/><path d="M35.46,34 L54.52,45"/>
    <path d="M32,36 L32,58"/><path d="M28.54,34 L9.48,45"/><path d="M28.54,30 L9.48,19"/>
    <polygon points="32,20 42.39,26 42.39,38 32,44 21.61,38 21.61,26"/>
    <polygon points="32,12 49.32,22 49.32,42 32,52 14.68,42 14.68,22"/>
  </g>
  <g opacity="0.38" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round">
    <rect x="28.8" y="2.8" width="6.4" height="6.4" rx="1.6"/>
    <rect x="51.32" y="15.8" width="6.4" height="6.4" rx="1.6"/>
    <rect x="51.32" y="41.8" width="6.4" height="6.4" rx="1.6"/>
    <rect x="28.8" y="54.8" width="6.4" height="6.4" rx="1.6"/>
    <rect x="6.28" y="41.8" width="6.4" height="6.4" rx="1.6"/>
    <rect x="6.28" y="15.8" width="6.4" height="6.4" rx="1.6"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round">
    <path d="M31.03,28.19 L28.56,22.07 L23.29,20.05"/><path d="M32.97,28.19 L35.44,22.07 L40.71,20.05"/>
    <path d="M29.77,29.26 L24.0,27.21 L18.78,29.46"/><path d="M34.23,29.26 L40.0,27.21 L45.22,29.46"/>
    <path d="M29.43,31.01 L23.48,31.98 L19.11,35.58"/><path d="M34.57,31.01 L40.52,31.98 L44.89,35.58"/>
    <path d="M29.84,32.44 L25.33,35.27 L22.87,40.52"/><path d="M34.16,32.44 L38.67,35.27 L41.13,40.52"/>
  </g>
  <circle cx="32" cy="36.4" r="4.6" fill="currentColor"/>
  <circle cx="32" cy="29" r="2.4" fill="currentColor"/>
</svg>`;

function navMarkup(active) {
  return NAV.map((item) => {
    if (item.section) return `<div class="nav-section">${item.section}</div>`;
    const cur = item.id === active ? ' aria-current="page"' : '';
    const badge = item.count
      ? `<span class="count ${item.count.kind}">${
          item.count.kind === 'live' ? '<i class="pulse"></i>' : ''
        }${item.count.text}</span>`
      : '';
    return `<a class="nav-item" href="${item.href}"${cur}>${icon(item.id)}<span>${item.label}</span>${badge}</a>`;
  }).join('\n');
}

function crumbMarkup(crumbs) {
  return crumbs
    .map((c, i) =>
      i === crumbs.length - 1
        ? `<span class="current">${c}</span>`
        : `<span class="muted">${c}</span><span class="sep">/</span>`
    )
    .join(' ');
}

/* ---- Theme -------------------------------------------------------------
   Light is the default. We respect prefers-color-scheme on a first visit
   only; once the user has chosen, their choice wins on every later load. */
const THEME_KEY = 'spydra.theme';

function resolveTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch (e) { /* private window, blocked storage — fall through */ }
  try {
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
  } catch (e) { /* no matchMedia */ }
  return 'light';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.innerHTML = icon(theme === 'dark' ? 'sun' : 'moon');
    btn.setAttribute('aria-label',
      theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
  }
}

function toggleTheme() {
  const next =
    document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* non-fatal */ }
  applyTheme(next);
}

/* ---- Mount -------------------------------------------------------------- */
function mountShell({ active, crumbs, runnable = true }) {
  const body = document.body;
  const host = document.getElementById('page');
  const page = host ? host.innerHTML : '';
  if (host) host.remove();

  body.insertAdjacentHTML('afterbegin', `
<div class="app">
  <aside class="sidebar">
    <div class="sidebar-brand">
      ${MARK}<span class="wordmark">Spydra</span>
    </div>
    <nav class="nav">${navMarkup(active)}</nav>
    <div class="sidebar-footer">
      <div class="health"><i class="dot ok"></i> llama-server <span class="val">30B · ready</span></div>
      <div class="health"><i class="dot ok"></i> postgres <span class="val">17.2</span></div>
      <div class="health"><i class="dot warn"></i> disk /data <span class="val">61.4 GB free</span></div>
    </div>
  </aside>
  <div class="main">
    <header class="topbar">
      <div class="breadcrumb">${crumbMarkup(crumbs)}</div>
      <div class="search">
        ${icon('search')}
        <input type="search" placeholder="Find a domain or product URL" aria-label="Search" />
      </div>
      <button class="icon-btn" id="theme-toggle" type="button"></button>
      ${runnable ? `<button class="btn btn-primary">${icon('play')} Start run</button>` : ''}
    </header>
    <div id="page">${page}</div>
  </div>
</div>`);

  applyTheme(resolveTheme());
  document.getElementById('theme-toggle').addEventListener('click', toggleTheme);
}

window.mountShell = mountShell;
window.spydraTheme = { resolve: resolveTheme, apply: applyTheme, toggle: toggleTheme };
