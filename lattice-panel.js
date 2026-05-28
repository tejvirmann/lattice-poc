/* Lattice-poc sidebar panel — injected via /static/loader.js */
(function () {
  const MANAGER = 'http://localhost:5000';
  const POLL_MS  = 20000;

  let session    = null;
  let activeTab  = 'context';
  let expanded   = true;

  // ── Theme ─────────────────────────────────────────────────────────────────
  // Load custom.css (fonts, scrollbars, hover states, prose — the parts that
  // don't need to beat CSS layers).  v0.6.10 removed the auto-<link> for it.
  function loadThemeCSS() {
    if (document.getElementById('lattice-theme')) return;
    const link = document.createElement('link');
    link.id   = 'lattice-theme';
    link.rel  = 'stylesheet';
    link.href = '/static/custom.css';
    document.head.appendChild(link);
  }

  // Set teal accent variables as INLINE styles on <html>.
  // Inline styles beat every CSS layer, including Tailwind v4's @layer theme,
  // so this is the only reliable way to remap --color-blue-* in v0.6.10.
  function applyRootVars() {
    const r = document.documentElement;
    const vars = {
      '--color-blue-50':  '#f3f8f7', '--color-blue-100': '#e6f1ef',
      '--color-blue-200': '#c8dedd', '--color-blue-300': '#9dd0cc',
      '--color-blue-400': '#62b3ae', '--color-blue-500': '#369996',
      '--color-blue-600': '#2a7e7b', '--color-blue-700': '#15716a',
      '--color-blue-800': '#0f5753', '--color-blue-900': '#0a3e3b',
      '--color-blue-950': '#062927',
    };
    for (const [k, v] of Object.entries(vars)) r.style.setProperty(k, v);
  }

  // Paint the sidebar element directly — inline styles win over all CSS.
  // Called every watch tick so Svelte re-renders can't wipe it.
  function applySidebarStyle() {
    const sb = document.getElementById('sidebar');
    if (!sb) return;
    sb.style.setProperty('background-color', '#369996');
    sb.style.setProperty('color', 'rgba(255,255,255,0.92)');
    sb.style.setProperty('border-right', '1px solid rgba(255,255,255,0.10)');
    const gray = {
      '--color-gray-950': '#2a7e7b', '--color-gray-900': '#2d8480',
      '--color-gray-850': '#329490', '--color-gray-800': '#369996',
      '--color-gray-700': '#42a8a4', '--color-gray-100': 'rgba(255,255,255,0.95)',
      '--color-gray-200': 'rgba(255,255,255,0.85)', '--color-gray-300': 'rgba(255,255,255,0.75)',
      '--color-gray-400': 'rgba(255,255,255,0.60)', '--color-gray-500': 'rgba(255,255,255,0.45)',
      '--color-gray-600': 'rgba(255,255,255,0.35)',
    };
    for (const [k, v] of Object.entries(gray)) sb.style.setProperty(k, v);
  }

  // ── Styles ────────────────────────────────────────────────────────────────
  function injectStyles() {
    const s = document.createElement('style');
    s.textContent = `
      #lattice-panel {
        flex-shrink: 0;
        background: rgba(0,0,0,0.15);
        border-bottom: 1px solid rgba(255,255,255,0.10);
        font-family: 'Inter', sans-serif;
      }
      #lp-head {
        display: flex; align-items: center; justify-content: space-between;
        padding: 7px 12px 5px;
      }
      #lp-tabs { display: flex; gap: 3px; }
      .lp-tab {
        font-family: 'JetBrains Mono', monospace;
        font-size: 9px; font-weight: 500;
        letter-spacing: .1em; text-transform: uppercase;
        padding: 3px 9px; border-radius: 4px; border: none;
        background: rgba(255,255,255,.10); color: rgba(255,255,255,.55);
        cursor: pointer; transition: all .15s;
        font-feature-settings: "ss01";
      }
      .lp-tab:hover { background: rgba(255,255,255,.18); color: rgba(255,255,255,.9); }
      .lp-tab.active { background: rgba(255,255,255,.22); color: #fff; }
      #lp-chevron {
        background: none; border: none;
        color: rgba(255,255,255,.45); font-size: 11px;
        cursor: pointer; padding: 2px 4px; border-radius: 3px; line-height: 1;
        transition: color .15s;
      }
      #lp-chevron:hover { color: #fff; }
      #lp-body {
        padding: 0 12px 10px;
        max-height: 180px; overflow-y: auto;
      }
      .lp-empty {
        font-size: 11px; color: rgba(255,255,255,.45);
        padding: 2px 0; line-height: 1.5;
      }
      .lp-empty a { color: rgba(255,255,255,.65); text-decoration: underline; }
      .lp-repo {
        font-family: 'JetBrains Mono', monospace;
        font-size: 8.5px; font-weight: 500; letter-spacing: .12em;
        text-transform: uppercase; color: rgba(255,255,255,.50);
        margin: 8px 0 3px; padding-top: 4px;
        border-top: 1px solid rgba(255,255,255,.08);
      }
      .lp-repo:first-child { margin-top: 2px; border-top: none; }
      .lp-mod {
        display: flex; align-items: center; justify-content: space-between;
        padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,.05);
      }
      .lp-mod:last-child { border-bottom: none; }
      .lp-mod-name { font-size: 11.5px; color: rgba(255,255,255,.88); }
      .lp-mod-tok {
        font-family: 'JetBrains Mono', monospace;
        font-size: 9px; color: rgba(255,255,255,.38); letter-spacing: .03em;
      }
      .lp-mcp {
        display: flex; align-items: flex-start; gap: 8px;
        padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,.06);
      }
      .lp-mcp:last-child { border-bottom: none; }
      .lp-mcp-dot {
        width: 6px; height: 6px; border-radius: 50%;
        background: rgba(255,255,255,.75); flex-shrink: 0; margin-top: 4px;
      }
      .lp-mcp-name { font-size: 12px; font-weight: 600; color: rgba(255,255,255,.92); }
      .lp-mcp-sys {
        font-family: 'JetBrains Mono', monospace;
        font-size: 9px; color: rgba(255,255,255,.45); letter-spacing: .04em;
      }
    `;
    document.head.appendChild(s);
  }

  // ── Render ────────────────────────────────────────────────────────────────
  function renderBody() {
    const body = document.getElementById('lp-body');
    if (!body) return;

    if (!session || !session.active) {
      body.innerHTML = `<p class="lp-empty">No session active.<br>
        <a href="${MANAGER}" target="_blank" rel="noreferrer">Open Lattice Manager →</a></p>`;
      return;
    }

    if (activeTab === 'context') {
      const modules = session.modules || [];
      if (!modules.length) {
        body.innerHTML = `<p class="lp-empty">No context modules loaded.</p>`;
        return;
      }
      const groups = {};
      for (const m of modules) {
        const r = m.repo || 'Context';
        (groups[r] = groups[r] || []).push(m);
      }
      body.innerHTML = Object.entries(groups).map(([repo, mods]) => `
        <div class="lp-repo">${repo}</div>
        ${mods.map(m => `
          <div class="lp-mod">
            <span class="lp-mod-name">${m.name}</span>
            ${m.tokens ? `<span class="lp-mod-tok">${(m.tokens/1000).toFixed(1)}k</span>` : ''}
          </div>`).join('')}
      `).join('');
    } else {
      const mcps = session.mcps || [];
      if (!mcps.length) {
        body.innerHTML = `<p class="lp-empty">No MCP tools loaded.</p>`;
        return;
      }
      body.innerHTML = mcps.map(id => `
        <div class="lp-mcp">
          <div class="lp-mcp-dot"></div>
          <div>
            <div class="lp-mcp-name">${id}</div>
          </div>
        </div>`).join('');
    }
  }

  // ── Panel DOM ─────────────────────────────────────────────────────────────
  function buildPanel() {
    const el = document.createElement('div');
    el.id = 'lattice-panel';
    el.innerHTML = `
      <div id="lp-head">
        <div id="lp-tabs">
          <button class="lp-tab active" data-lp="context">Context</button>
          <button class="lp-tab"        data-lp="mcps">MCP Tools</button>
        </div>
        <button id="lp-chevron" title="Toggle">▾</button>
      </div>
      <div id="lp-body"></div>
    `;

    el.querySelectorAll('.lp-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        activeTab = btn.dataset.lp;
        el.querySelectorAll('.lp-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderBody();
      });
    });

    el.querySelector('#lp-chevron').addEventListener('click', () => {
      expanded = !expanded;
      const body = document.getElementById('lp-body');
      const chev = document.getElementById('lp-chevron');
      if (body) body.style.display = expanded ? '' : 'none';
      if (chev) chev.textContent = expanded ? '▾' : '▸';
    });

    return el;
  }

  // ── Inject & watch ────────────────────────────────────────────────────────
  function inject() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar || document.getElementById('lattice-panel')) return;

    const panel = buildPanel();
    // Place after the first element (top nav/new-chat area)
    const first = sidebar.firstElementChild;
    if (first && first.nextSibling) {
      sidebar.insertBefore(panel, first.nextSibling);
    } else if (first) {
      first.after(panel);
    } else {
      sidebar.prepend(panel);
    }
    renderBody();
  }

  // Re-inject if sidebar is replaced by Svelte navigation
  let watchTimer = null;
  function watchSidebar() {
    clearInterval(watchTimer);
    watchTimer = setInterval(() => {
      applySidebarStyle();
      if (document.getElementById('sidebar') && !document.getElementById('lattice-panel')) {
        inject();
      }
    }, 800);
  }

  // ── Fetch session ─────────────────────────────────────────────────────────
  async function fetchSession() {
    try {
      const r = await fetch(`${MANAGER}/api/session`, { mode: 'cors' });
      if (r.ok) { session = await r.json(); renderBody(); }
    } catch (_) { /* manager offline */ }
  }

  // ── Boot ──────────────────────────────────────────────────────────────────
  function boot() {
    loadThemeCSS();
    applyRootVars();
    injectStyles();
    // Wait for sidebar to appear
    const obs = new MutationObserver(() => {
      if (document.getElementById('sidebar')) { obs.disconnect(); inject(); watchSidebar(); }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
    // Also try immediately (already rendered)
    inject();
    watchSidebar();

    fetchSession();
    setInterval(fetchSession, POLL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
