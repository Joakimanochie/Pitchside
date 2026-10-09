/* Pitchside prototype: three screens over a JSON snapshot of real stored predictions. No build step. */
(() => {
  'use strict';

  const TABS = [
    { id: 'main', label: 'Main' }, { id: 'goals', label: 'Goals' }, { id: 'halves', label: 'Halves' },
    { id: 'flow', label: 'Game flow' }, { id: 'minutes', label: 'Minutes' }, { id: 'combos', label: 'Combos' },
  ];
  const MAIN_IDS = new Set(['1x2', 'double_chance', 'draw_no_bet', 'ou_total', 'btts', 'asian_handicap', 'handicap_3way']);
  const SORT_BY_PROBABILITY = new Set(['correct_score', 'multiscores']);
  const COLLAPSED_ROWS = 6;

  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const motionOK = !reduceMotion && 'IntersectionObserver' in window;
  if (motionOK) document.documentElement.classList.add('js-motion');

  const state = { data: null, league: 'ALL', tab: 'main', query: '', lines: {}, expanded: new Set() };
  const main = document.getElementById('main');
  main.removeAttribute('aria-live');

  // ---- small helpers -------------------------------------------------------------------------------------------------
  function h(tag, attrs = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs = {}, ...kids) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    for (const kid of kids) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return el;
  }
  const ICONS = {
    info: '<circle cx="8" cy="8" r="6.5"/><path d="M8 7.2v4"/><circle cx="8" cy="4.8" r=".6" fill="currentColor"/>',
    search: '<circle cx="7" cy="7" r="4.6"/><path d="m10.6 10.6 3.2 3.2"/>',
    back: '<path d="M10 3 5 8l5 5"/>',
  };
  function icon(name, size = 16) {
    const s = svg('svg', { viewBox: '0 0 16 16', width: size, height: size, fill: 'none', stroke: 'currentColor', 'stroke-width': '1.6', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' });
    s.innerHTML = ICONS[name];
    return s;
  }

  const pct0 = (p) => `${Math.round(p * 100)}%`;
  const pct1 = (p) => (p > 0 && p < 0.0005 ? '<0.1%' : `${(p * 100).toFixed(1)}%`);
  const fair = (p) => (p <= 0 ? '—' : 1 / p >= 100 ? String(Math.round(1 / p)) : (1 / p).toFixed(2));
  const fmtNum = (n) => String(n);
  const signed = (n) => (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n);
  const kickoffDate = (iso) => new Date(iso);
  const dayKey = (iso) => kickoffDate(iso).toLocaleDateString('en-CA');
  const dayLabel = (iso) => kickoffDate(iso).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  const timeLabel = (iso) => kickoffDate(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  const tzLabel = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
  const groupBy = (xs, key) => xs.reduce((m, x) => ((m[key(x)] ||= []).push(x), m), {});

  // ---- labels: turn stored codes into words -------------------------------------------------------------------------
  function comboLine(mid) {
    const m = mid.match(/_(\d)(\d)$/) || mid.match(/^ou_(\d)(\d)_/);
    return m ? parseFloat(`${m[1]}.${m[2]}`) : null;
  }
  function tokenLabel(tok, mid, ctx) {
    const { home, away } = ctx;
    const isBtts = mid.includes('btts');
    const fixed = {
      home, away, draw: 'Draw', none: 'No goal', no_goal: 'No goal', odd: 'Odd', even: 'Even', '1st': '1st half', '2nd': '2nd half', equal: 'Equal',
      '1x': `${home} or Draw`, x2: `Draw or ${away}`, '12': `${home} or ${away}`, home_goal: `${home} scores first`, away_goal: `${away} scores first`,
      only_home: `Only ${home}`, only_away: `Only ${away}`, both: 'Both teams', other: 'Other', other_home: `Other ${home} win`, other_away: `Other ${away} win`,
      yes: isBtts ? 'Both teams score' : 'Yes', no: isBtts ? 'Not both teams' : 'No',
    };
    if (tok in fixed) return fixed[tok];
    if (tok === 'over' || tok === 'under') {
      const line = comboLine(mid);
      return (tok === 'over' ? 'Over' : 'Under') + (line != null ? ` ${fmtNum(line)}` : '');
    }
    let m = tok.match(/^(home|away)_(\d)(\+?)$/);
    if (m) return `${m[1] === 'home' ? home : away} by ${m[2]}${m[3]}`;
    m = tok.match(/^(home|away)_([\d_-]+\+?)$/);                       // multiscores: home_3-2_4-2_4-3_5-1
    if (m) return `${m[1] === 'home' ? home : away} win: ${m[2].split('_').map((s) => s.replace('-', ':')).join(', ')}`;
    return tok.replace(/_/g, ' ');
  }
  function partLabel(part, mid, ctx) {
    if (!part.includes('/')) return tokenLabel(part, mid, ctx);
    const [a, b] = part.split('/').map((t) => tokenLabel(t, mid, ctx));
    return `HT ${a} / FT ${b}`;
  }
  function selectionLabel(mid, lineKey, sel, ctx) {
    const line = lineKey === 'null' ? null : Number(lineKey);
    const { home, away } = ctx;
    if (mid.startsWith('asian_handicap')) return sel === 'home' ? `${home} ${signed(line)}` : `${away} ${signed(-line)}`;
    if (mid.startsWith('handicap_3way')) return `${tokenLabel(sel, mid, ctx)} (${line < 0 ? `0:${-line}` : `${line}:0`})`;
    if ((sel === 'over' || sel === 'under') && line != null) return `${sel === 'over' ? 'Over' : 'Under'} ${fmtNum(line)}`;
    if (mid === 'first_goal_10' || mid === 'first_goal_15') return sel === 'none' ? 'No goal' : `${sel} min`;
    if (mid === 'gg_ng_each_half') { const [a, b] = sel.split('/'); return `1st half: ${a === 'yes' ? 'Yes' : 'No'} · 2nd half: ${b === 'yes' ? 'Yes' : 'No'}`; }
    if (sel.includes('&')) return sel.split('&').map((part) => partLabel(part, mid, ctx)).join(' & ');
    if (mid === 'ht_ft') return partLabel(sel, mid, ctx);
    if (mid.includes('multigoals') && sel === 'no_goal') return 'No goal';
    return tokenLabel(sel, mid, ctx);
  }
  function lineChipLabel(mid, lineKey) {
    const n = Number(lineKey);
    if (mid.startsWith('handicap_3way')) return n < 0 ? `0:${-n}` : `${n}:0`;
    if (mid.startsWith('asian_handicap')) return signed(n);
    if (mid.startsWith('lead_by')) return `${n}+ goal${n > 1 ? 's' : ''}`;
    if (mid.startsWith('goals_in_a_row')) return `${n}+ in a row`;
    return fmtNum(n);
  }
  function marketTitle(name, ctx) {
    return name.replace(/Home Team/g, ctx.home).replace(/Away Team/g, ctx.away);
  }
  // Search: people type "first goal", the market is called "1st Goal"; "btts" is "GG/NG".
  const ALIASES = [[/gg\/ng/i, 'both teams to score btts'], [/half time\/full time|halftime\/fulltime/i, 'half time full time ht ft'],
                   [/1x2/i, 'match result win draw'], [/clean sheet/i, 'shutout']];
  const normalise = (t) => t.toLowerCase().replace(/\bfirst\b/g, '1st').replace(/\bsecond\b/g, '2nd').replace(/[^a-z0-9/& ]+/g, ' ');
  function matchesQuery(title, query) {
    const text = normalise(`${title} ${ALIASES.filter(([re]) => re.test(title)).map(([, w]) => w).join(' ')}`);
    return normalise(query).split(/\s+/).filter(Boolean).every((word) => text.includes(word));
  }
  function tabOf(mid) {
    const fam = state.data.markets[mid].family;
    if (fam === 'A') return MAIN_IDS.has(mid) ? 'main' : 'goals';
    return { B: 'halves', C: 'flow', D: 'minutes', E: 'combos' }[fam];
  }
  function defaultLine(lines) {
    const keys = Object.keys(lines);
    const halfLines = keys.filter((k) => k === 'null' || !Number.isInteger(Number(k)));
    let best = null;
    for (const lk of halfLines.length ? halfLines : keys) {
      const gap = Math.abs((lines[lk][0] ? lines[lk][0][1] : 0) - 0.5);
      if (best === null || gap < best.gap) best = { lk, gap };
    }
    return best.lk;
  }

  // ---- motion (all of it optional) -----------------------------------------------------------------------------------
  let io = null;
  function observeReveals() {
    if (!motionOK) return;
    io?.disconnect();
    io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); }
    }, { threshold: 0.08, rootMargin: '0px 0px -4% 0px' });
    main.querySelectorAll('.reveal').forEach((el) => io.observe(el));
  }
  function typeInto(el, text) {
    el.textContent = text;
    if (!motionOK || sessionStorage.getItem('typed')) return;
    sessionStorage.setItem('typed', '1');
    el.setAttribute('aria-label', text);
    el.textContent = '';
    const cursor = h('span', { class: 'cursor', 'aria-hidden': 'true' });
    const out = h('span', { 'aria-hidden': 'true' });
    el.append(out, cursor);
    let i = 0;
    const step = () => {
      out.textContent = text.slice(0, ++i);
      if (i < text.length) setTimeout(step, 26);
      else setTimeout(() => cursor.remove(), 500);
    };
    step();
  }
  function countUp(el) {
    const target = Number(el.dataset.count);
    if (!motionOK) return;
    const start = performance.now();
    const dur = 900;
    const tick = (now) => {
      const t = Math.min(1, (now - start) / dur);
      el.textContent = Math.round(target * (1 - Math.pow(1 - t, 4))).toLocaleString();
      if (t < 1) requestAnimationFrame(tick);
    };
    el.textContent = '0';
    requestAnimationFrame(tick);
  }

  // ---- screen 1: fixtures ----------------------------------------------------------------------------------------------
  function renderFixtures() {
    const d = state.data;
    const countBy = groupBy(d.fixtures, (f) => f.league);
    const title = h('h1', { class: 'display' });
    const pills = h('div', { class: 'pills', role: 'group', 'aria-label': 'League' },
      [['ALL', 'All leagues', d.fixtures.length], ...Object.entries(d.leagues).map(([id, name]) => [id, name, (countBy[id] || []).length])].map(([id, name, n]) =>
        h('button', { class: 'pill', 'aria-pressed': String(state.league === id), onclick: () => { state.league = id; render(); } }, name, ' ', h('span', { class: 'count' }, n))));
    const list = h('div', { 'data-list': '' });
    main.append(h('div', { class: 'wrap' },
      h('div', { class: 'intro reveal' },
        title,
        h('p', { class: 'lede' }, 'Every upcoming match, with a probability for every market a betting site offers. Open a match to read all of them, and the numbers behind them.'),
        pills,
        h('div', { class: 'notice' }, icon('info'), h('p', {}, h('strong', {}, 'Prototype. '),
          `A snapshot of the ${d.fixtures.length} matches predicted on ${new Date(d.generated_at).toLocaleDateString(undefined, { day: 'numeric', month: 'long' })}. `,
          'Predictions use results only: no lineups, injuries or suspensions. Confidence ratings are not calibrated yet, so none are shown. Times are in your time zone (', tzLabel(), ').'))),
      list));
    typeInto(title, "This week across Europe’s top five leagues");
    drawFixtureList(list);
  }
  function drawFixtureList(list) {
    const d = state.data;
    const shown = d.fixtures.filter((f) => state.league === 'ALL' || f.league === state.league);
    const days = groupBy(shown, (f) => dayKey(f.kickoff));
    list.replaceChildren(...Object.keys(days).sort().map((k, gi) => h('section', { class: 'reveal', style: `--i:${Math.min(gi, 3)}` },
      h('h2', { class: 'day' }, dayLabel(days[k][0].kickoff)),
      h('ol', { class: 'match-list' }, days[k].map((f) => matchCard(f))))));
    if (!shown.length) list.append(h('p', { class: 'empty' }, 'No matches in this league in the current snapshot.'));
    observeReveals();
  }
  function matchCard(f) {
    const p = f.p, leagueName = state.data.leagues[f.league];
    const seg = (cls, v) => h('i', { class: cls, style: `width:${(v * 100).toFixed(1)}%` });
    return h('li', {}, h('a', { class: 'match-card', href: `#/match/${f.id}` },
      h('div', { class: 'kick' }, h('span', { class: 'kick-time' }, timeLabel(f.kickoff)), h('span', { class: 'kick-league' }, leagueName)),
      h('div', { class: 'teams' }, h('span', {}, f.home), h('span', {}, h('span', { class: 'vs' }, 'v '), f.away)),
      h('div', { class: 'probs' },
        h('div', { class: 'bar3', 'aria-hidden': 'true' }, seg('h', p.home), seg('d', p.draw), seg('a', p.away)),
        h('div', { class: 'pnums' },
          h('span', {}, h('b', {}, pct0(p.home)), h('small', {}, 'Home win')),
          h('span', {}, h('b', {}, pct0(p.draw)), h('small', {}, 'Draw')),
          h('span', {}, h('b', {}, pct0(p.away)), h('small', {}, 'Away win'))))));
  }

  // ---- screen 2: a match, every market ------------------------------------------------------------------------------
  function renderMatch(id) {
    const d = state.data;
    const f = d.fixtures.find((x) => String(x.id) === String(id));
    if (!f) { main.append(h('div', { class: 'wrap stack' }, h('a', { class: 'back', href: '#/' }, icon('back'), 'Fixtures'), h('p', { class: 'empty' }, 'That match is not in this snapshot.'))); return; }
    const ctx = { home: f.home, away: f.away };
    const c = f.ctx || {};
    const markets = Object.entries(d.preds[f.id] || {}).sort((a, b) => d.markets[a[0]].order - d.markets[b[0]].order);
    const counts = Object.fromEntries(TABS.map((t) => [t.id, 0]));
    markets.forEach(([mid]) => { counts[tabOf(mid)] += 1; });
    if (!counts[state.tab]) state.tab = 'main';

    const grid = h('div', { class: 'markets' });
    const status = h('p', { class: 'muted small', role: 'status' });
    const tabsEl = h('div', { class: 'tabs', role: 'group', 'aria-label': 'Market groups' });
    const drawTabs = () => tabsEl.replaceChildren(...TABS.map((t) => h('button', { class: 'pill', 'aria-pressed': String(!state.query && state.tab === t.id),
      onclick: () => { state.tab = t.id; state.query = ''; search.value = ''; drawTabs(); drawMarkets(); } }, t.label, ' ', h('span', { class: 'count' }, counts[t.id]))));
    const search = h('input', { type: 'search', placeholder: 'Find a market, e.g. first goal', 'aria-label': 'Find a market',
      oninput: (e) => { state.query = e.target.value.trim().toLowerCase(); drawTabs(); drawMarkets(); } });
    const drawMarkets = () => {
      const q = state.query;
      const rows = markets.filter(([mid]) => q ? matchesQuery(marketTitle(d.markets[mid].name, ctx), q) : tabOf(mid) === state.tab);
      grid.replaceChildren(...rows.map(([mid, lines], i) => marketCard(f, mid, lines, ctx, i)));
      status.textContent = q ? `${rows.length} market${rows.length === 1 ? '' : 's'} match “${state.query}”` : '';
      if (!rows.length) grid.append(h('p', { class: 'empty' }, q ? 'No market matches that search.' : 'Nothing in this group.'));
      observeReveals();
    };
    const hp = (label, p) => h('div', { class: 'hp' }, h('span', { class: 'who' }, label), h('span', { class: 'big' }, pct0(p)), h('span', { class: 'mini', 'aria-hidden': 'true' }, h('i', { style: `width:${(p * 100).toFixed(1)}%` })));
    const dd = (k, v) => [h('dt', {}, k), h('dd', {}, v)];

    main.append(h('div', { class: 'wrap wide' },
      h('a', { class: 'back', href: '#/' }, icon('back'), 'Fixtures'),
      h('header', { class: 'match-head reveal' },
        h('h1', { class: 'display' }, `${f.home} v ${f.away}`),
        h('p', { class: 'meta' }, h('span', {}, d.leagues[f.league]),
          h('span', {}, kickoffDate(f.kickoff).toLocaleString(undefined, { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', hour12: false })),
          h('span', {}, `Time zone: ${tzLabel()}`))),
      h('section', { class: 'reveal', 'aria-label': 'Match result probabilities' },
        h('div', { class: 'headline-card' }, hp(`${f.home} win`, f.p.home), hp('Draw', f.p.draw), hp(`${f.away} win`, f.p.away)),
        h('dl', { class: 'why' },
          dd('Expected goals', `${f.home} ${Number(c.lambda_home).toFixed(2)} · ${f.away} ${Number(c.lambda_away).toFixed(2)}`),
          dd('History used', `${Number(c.matches_used).toLocaleString()} finished ${d.leagues[f.league]} matches`),
          dd('Goals before half-time', `${(c.first_half_goal_share * 100).toFixed(1)}% of all goals`),
          dd('Simulated matches', Number(c.n_sims).toLocaleString()),
          dd('Model', d.model_version),
          h('p', { class: 'span' }, 'Lineups, injuries and suspensions are not used yet. The model knows past scores, how goals split between the halves, and when in a match goals tend to happen.'))),
      h('div', { class: 'notice', style: 'margin-top:1rem' }, icon('info'), h('p', {}, h('strong', {}, '18+. '), 'These are statistical estimates, not advice or a promise of any result. Fair odds are simply 1 divided by the probability; they are not bookmaker prices.')),
      h('div', { class: 'toolbar' },
        h('div', { class: 'conf-note' }, h('span', { class: 'chip', title: 'Confidence tiers need a calibration study first. Until then no tier is shown.' }, icon('info', 14), 'Confidence: not rated yet'),
          h('span', { class: 'muted small' }, 'A “Pick” is the most likely outcome of a market where only one outcome can happen.')),
        tabsEl,
        h('div', { class: 'search' }, icon('search'), search),
        status),
      grid));
    drawTabs();
    drawMarkets();
  }
  function marketCard(f, mid, linesMap, ctx, index) {
    const d = state.data, meta = d.markets[mid];
    const key = `${f.id}:${mid}`;
    const lineKeys = Object.keys(linesMap).sort((a, b) => (a === 'null' ? -1 : b === 'null' ? 1 : Number(a) - Number(b)));
    const current = state.lines[key] && linesMap[state.lines[key]] ? state.lines[key] : defaultLine(linesMap);
    let rows = linesMap[current].slice();
    if (SORT_BY_PROBABILITY.has(mid)) rows.sort((a, b) => b[1] - a[1]);
    const total = rows.length, open = state.expanded.has(key);
    if (total > COLLAPSED_ROWS + 2 && !open) rows = rows.slice(0, COLLAPSED_ROWS);
    const card = h('article', { class: 'market reveal', style: `--i:${Math.min(index, 4)}`, 'data-market': mid },
      h('h3', {}, marketTitle(meta.name, ctx)),
      lineKeys.length > 1 && h('div', { class: 'lines', role: 'group', 'aria-label': 'Line' }, lineKeys.map((lk) =>
        h('button', { class: 'pill sm', 'aria-pressed': String(lk === current), onclick: () => { state.lines[key] = lk; card.replaceWith(marketCard(f, mid, linesMap, ctx, 0)); } }, lineChipLabel(mid, lk)))),
      current !== 'null' && Number.isInteger(Number(current)) && /^(ou_|asian_handicap)/.test(mid) &&
        h('p', { class: 'refund' }, 'On a whole-number line, the stake is returned if the result lands exactly on it. Probabilities here exclude that case.'),
      h('ul', { class: 'sels' }, rows.map(([sel, p, pick]) =>
        h('li', { class: `sel${pick ? ' is-pick' : ''}` },
          h('div', { class: 'sel-top' },
            h('span', { class: 'sel-name' }, selectionLabel(mid, current, sel, ctx), pick ? h('span', { class: 'pick-tag' }, 'Pick') : null),
            h('span', { class: 'sel-p' }, pct1(p)), h('span', { class: 'sel-fair', title: 'Fair odds: 1 divided by the probability' }, fair(p))),
          h('div', { class: 'sel-bar', 'aria-hidden': 'true' }, h('i', { style: `width:${(p * 100).toFixed(1)}%` }))))),
      total > COLLAPSED_ROWS + 2 && h('div', { class: 'more' }, h('button', { onclick: () => { open ? state.expanded.delete(key) : state.expanded.add(key); card.replaceWith(marketCard(f, mid, linesMap, ctx, 0)); } },
        open ? 'Show fewer' : `Show all ${total}${SORT_BY_PROBABILITY.has(mid) ? ' (most likely first)' : ''}`)));
    if (index === 0) card.classList.add('is-in');
    return card;
  }

  // ---- screen 3: the record (dark) --------------------------------------------------------------------------------------
  function renderRecord() {
    const d = state.data, v = d.validation;
    const stored = d.fixtures.length * 945;
    const storedEl = h('b', { 'data-count': stored }, stored.toLocaleString());
    main.append(h('div', { class: 'wrap record' },
      h('div', { class: 'reveal' },
        h('h1', { class: 'display' }, 'The record, kept honestly'),
        h('p', { class: 'lede', style: 'margin-top:1rem' }, 'Every prediction is stored before kickoff and scored after the match, and the stored predictions cannot be edited. Below: what is stored so far, then how the model did in tests on matches it had never seen.'),
        h('p', { class: 'status-line' }, storedEl, ' predictions are stored for ', String(d.fixtures.length), ' upcoming matches. ', h('b', {}, '0'),
          ' have been settled so far; the first results arrive after this weekend’s matches.')),

      h('section', { class: 'reveal' }, h('h2', { class: 'h2' }, 'When it says 70%, does it happen 70% of the time?'),
        h('p', { class: 'muted' }, 'A held-out test: 500 real matches from the 2025/26 and 2026/27 seasons, scored on about 330,000 predictions. Each point is a group of predictions with a similar probability. Points on the dashed line mean the model’s numbers match reality. This is a test, not the live record.'),
        h('div', { class: 'panel chart-wrap', style: 'margin-top:1.25rem' }, calibrationChart(v.calibration),
          h('div', { class: 'legend' }, h('span', {}, h('i', {}), 'What actually happened'), h('span', {}, h('i', { class: 'dash' }), 'Perfect match with the predictions')),
          h('details', { class: 'data' }, h('summary', {}, 'Show the numbers'), h('div', { class: 'tbl-wrap' }, calibrationTable(v.calibration))))),

      h('section', { class: 'reveal' }, h('h2', { class: 'h2' }, 'Does it add anything beyond a plain average?'),
        h('p', { class: 'muted' }, 'Compared with simply guessing how often each outcome usually happens. A higher share removed means the model carries real information. Lower log loss is better.'),
        h('div', { class: 'panel', style: 'margin-top:1.25rem' }, h('div', { class: 'tbl-wrap' }, familyTable(v.families)))),

      h('section', { class: 'reveal' }, h('h2', { class: 'h2' }, 'Against the bookmakers on the match result'),
        h('p', { class: 'muted' }, 'The model beats a league average in every league, but the bookmakers’ closing odds still predict the result better. That is expected: they use lineups and team news, and this model does not.'),
        h('div', { class: 'panel', style: 'margin-top:1.25rem' }, h('div', { class: 'tbl-wrap' }, leagueTable(v.leagues)))),

      h('section', { class: 'reveal' }, h('h2', { class: 'h2' }, 'What it does not know'),
        h('ul', { class: 'list', style: 'margin-top:1rem' },
          h('li', {}, h('strong', {}, 'Lineups, injuries and suspensions.'), ' Not used yet.'),
          h('li', {}, h('strong', {}, 'Confidence ratings.'), ' They need a calibration study of their own before any rating is shown.'),
          h('li', {}, h('strong', {}, 'A live record.'), ' None exists until matches are played and scored; the tests above are not live results.'),
          h('li', {}, h('strong', {}, 'Markets beyond goals.'), ' Corners, cards, shots and players are not built yet.')))));
    countUp(storedEl);
  }
  function calibrationChart(points) {
    const W = 560, H = 380, L = 48, R = 18, T = 14, B = 42;
    const x = (p) => L + p * (W - L - R), y = (p) => H - B - p * (H - T - B);
    const maxN = Math.max(...points.map((p) => p.n));
    const s = svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Calibration chart: predicted probability on the horizontal axis, actual frequency on the vertical axis. Points follow the diagonal closely.' });
    for (const t of [0, .25, .5, .75, 1]) {
      s.append(svg('line', { class: 'grid', x1: x(0), x2: x(1), y1: y(t), y2: y(t) }), svg('line', { class: 'grid', x1: x(t), x2: x(t), y1: y(0), y2: y(1) }),
        svg('text', { x: x(t), y: H - B + 20, 'text-anchor': 'middle' }, `${t * 100}%`), svg('text', { x: L - 10, y: y(t) + 4, 'text-anchor': 'end' }, `${t * 100}%`));
    }
    s.append(svg('text', { x: (L + W - R) / 2, y: H - 6, 'text-anchor': 'middle' }, 'Predicted probability'),
      svg('text', { x: 14, y: (T + H - B) / 2, transform: `rotate(-90 14 ${(T + H - B) / 2})`, 'text-anchor': 'middle' }, 'How often it happened'),
      svg('line', { class: 'diag', x1: x(0), y1: y(0), x2: x(1), y2: y(1) }),
      svg('polyline', { class: 'line', points: points.map((p) => `${x(p.predicted)},${y(p.actual)}`).join(' ') }));
    for (const p of points) {
      const dot = svg('circle', { class: 'dot', cx: x(p.predicted), cy: y(p.actual), r: (3.5 + 5 * Math.sqrt(p.n / maxN)).toFixed(1) });
      dot.append(svg('title', {}, `Predicted ${pct1(p.predicted)}, happened ${pct1(p.actual)} (${p.n.toLocaleString()} predictions)`));
      s.append(dot);
    }
    return h('div', { class: 'chart' }, s);
  }
  function table(head, rows) {
    return h('table', {}, h('thead', {}, h('tr', {}, head.map((t) => h('th', { scope: 'col' }, t)))), h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c) => h('td', {}, c))))));
  }
  function calibrationTable(points) {
    return table(['Predicted range', 'Average predicted', 'Actually happened', 'Predictions'],
      points.map((p) => [`${Math.round(p.from * 100)}–${Math.round(Math.min(p.to, 1) * 100)}%`, pct1(p.predicted), pct1(p.actual), p.n.toLocaleString()]));
  }
  function familyTable(fams) {
    const names = { B: 'Halves', C: 'Game flow', D: 'Minutes', E: 'Combinations' };
    return table(['Group of markets', 'Predictions tested', 'Model log loss', 'Plain-average log loss', 'Share removed'],
      fams.map((f) => [names[f.family], f.selections.toLocaleString(), f.model.toFixed(4), f.base.toFixed(4), h('strong', {}, `${f.skill >= 0 ? '+' : ''}${(f.skill * 100).toFixed(1)}%`)]));
  }
  function leagueTable(rows) {
    return table(['League', 'Matches', 'Model', 'League average', 'Bookmakers', 'Right result: model', 'Right result: bookmakers'],
      rows.map((r) => [r.name, r.matches.toLocaleString(), r.model.toFixed(3), r.base.toFixed(3), r.book.toFixed(3), `${(r.right_model * 100).toFixed(1)}%`, `${(r.right_book * 100).toFixed(1)}%`]));
  }

  // ---- routing ----------------------------------------------------------------------------------------------------------
  function render() {
    const m = (location.hash || '#/').match(/^#\/([a-z]*)\/?(.*)$/) || [];
    const path = m[1] || '', arg = m[2] || '';
    document.body.classList.toggle('on-record', path === 'record');
    document.querySelectorAll('.nav-links a').forEach((a) => {
      const on = (a.dataset.route === 'record') === (path === 'record');
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    main.replaceChildren();
    if (path === 'match') renderMatch(arg); else if (path === 'record') renderRecord(); else renderFixtures();
    observeReveals();
  }
  let lastPath = null;
  function onRoute() {
    const path = (location.hash || '#/').split('/')[1] + (location.hash.split('/')[2] || '');
    render();
    if (path !== lastPath) { window.scrollTo(0, 0); main.focus({ preventScroll: true }); }
    lastPath = path;
  }
  window.addEventListener('hashchange', onRoute);

  fetch('data/snapshot.json')
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then((data) => {
      state.data = data;
      document.getElementById('foot-meta').textContent =
        `Prototype · private · snapshot ${new Date(data.generated_at).toLocaleString(undefined, { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', hour12: false })} · model ${data.model_version}`;
      onRoute();
    })
    .catch((err) => {
      main.replaceChildren(h('div', { class: 'wrap stack' }, h('h1', { class: 'display' }, 'The snapshot did not load'),
        h('p', { class: 'lede' }, 'This prototype reads data/snapshot.json, which browsers block when the page is opened as a plain file. Serve the folder instead, for example: python -m http.server 4173 --directory web/prototype.'),
        h('p', { class: 'muted small' }, String(err.message || err))));
    });
})();
