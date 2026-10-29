'use strict';

const CATS = {
  contact: 'Contact', summary: 'Summary', experience: 'Experience', education: 'Education',
  credentials: 'Credentials', skills: 'Skills', languages: 'Languages', availability: 'Availability', other: 'Other',
};
const SECTION_CAT = {
  top: 'contact', location: 'contact', mobile: 'contact', work_phone: 'contact', job_title: 'contact', industry: 'contact',
  summary: 'summary', experience: 'experience', education: 'education', certifications: 'credentials',
  skills: 'skills', languages: 'languages', availability: 'availability',
};
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MAX_FILE = 2_000_000;

const state = {
  text: '', sections: [], result: null, model: null, items: [], datePatterns: [], ms: 0,
  hidden: new Set(), cycle: new Map(), segsByItem: new Map(), segAt: new Map(), cardsByItem: new Map(),
};

const $ = id => document.getElementById(id);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid);
  return el;
}

// ---------- locating extracted values in the text ----------

const SEP = '[\\s\\-\\u2010-\\u2014]';
const escapeRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function needleRe(value) {
  const v = value.trim();
  const body = escapeRe(v).replace(/[\s\-\u2010-\u2014]+/g, SEP + '+').replace(/['’]/g, "['’]");
  const pre = /^[\p{L}\p{N}]/u.test(v) ? '(?<![\\p{L}\\p{N}])' : '';
  const post = /[\p{L}\p{N}]$/u.test(v) ? '(?![\\p{L}\\p{N}])' : '';
  return new RegExp(pre + body + post, 'giu');
}

function scan(re, [from, to], limit = 50) {
  const out = [];
  re.lastIndex = from;
  let m;
  while (out.length < limit && (m = re.exec(state.text)) && m.index < to) {
    if (m.index + m[0].length <= to) out.push([m.index, m.index + m[0].length]);
    if (!m[0].length) re.lastIndex++;
  }
  return out;
}

const findAll = (v, range, limit) => (v != null && String(v).trim() ? scan(needleRe(String(v)), range, limit) : []);

function findFirst(v, ...ranges) {
  for (const r of ranges) if (r) { const m = findAll(v, r, 1); if (m.length) return m; }
  return [];
}

/** A paragraph the parser joined from wrapped lines: whole if possible, else sentence by sentence. */
function findBlock(v, ...ranges) {
  for (const r of ranges) {
    if (!r) continue;
    const whole = findAll(v, r, 1);
    if (whole.length) return whole;
    const parts = v.split(/(?<=[.!?;:])\s+/).filter(p => p.trim().length > 12).flatMap(p => findAll(p, r, 1));
    if (parts.length) return parts;
  }
  return [];
}

/** Normalized labels ("onsite") written with separators in the text ("on-site"). */
function findLoose(v, range) {
  const exact = findAll(v, range, 1);
  const letters = v.replace(/[\s-]+/g, '');
  if (exact.length || letters.length > 14) return exact;
  const body = [...letters].map(escapeRe).join(SEP + '?');
  return scan(new RegExp(`(?<![\\p{L}\\p{N}])${body}(?![\\p{L}\\p{N}])`, 'giu'), range, 1);
}

function findLocation(loc, ...ranges) {
  const tries = [loc.zip && `${loc.city}, ${loc.state} ${loc.zip}`, `${loc.city}, ${loc.state}`, loc.city].filter(Boolean);
  for (const t of tries) { const m = findFirst(t, ...ranges); if (m.length) return m; }
  return [];
}

function findDates(...ranges) {
  for (const r of ranges) for (const re of state.datePatterns) { const m = scan(re, r, 1); if (m.length) return m; }
  return [];
}

// ---------- model: every extracted value, with where it sits in the text ----------

function buildModel(r) {
  const T = state.text, ALL = [0, T.length], items = [];
  const add = (cat, path, field, value, spans, extra) => {
    const it = { id: items.length, cat, path, field, value: String(value), spans, ...extra };
    items.push(it);
    return it;
  };
  const range = (...names) => {
    const ss = state.sections.filter(s => names.includes(s.name));
    return ss.length ? [Math.min(...ss.map(s => s.start)), Math.max(...ss.map(s => s.end))] : null;
  };
  const top = range('top');
  const m = {};

  m.name = r.name ? add('contact', 'Profile', 'Name', r.name, findFirst(r.name, top, ALL)) : null;
  m.credentials = r.credentials.map(c => add('contact', 'Profile', 'Post-nominal', c, findFirst(c, top, ALL)));
  m.headline = r.headline.map(l => add('contact', 'Profile', 'Headline', l, findFirst(l, top, ALL)));
  m.emails = r.emails.map(e => add('contact', 'Profile', 'Email', e, findFirst(e, top, ALL)));
  m.phones = r.phones.map(p => add('contact', 'Profile', p.type ? `Phone (${p.type.replace('_', ' ')})` : 'Phone', p.number, findFirst(p.number, ALL)));
  m.urls = r.urls.map(u => add('contact', 'Profile', 'URL', u, findFirst(u, ALL)));
  m.location = r.location ? add('contact', 'Profile', 'Location', fmtLoc(r.location), findLocation(r.location, top, range('location'), ALL)) : null;
  m.job_title = r.job_title ? add('contact', 'Profile', 'Job title', r.job_title, findFirst(r.job_title, range('job_title'), ALL)) : null;
  m.industry = r.industry ? add('contact', 'Profile', 'Industry', r.industry, findFirst(r.industry, range('industry'), ALL)) : null;

  m.summary = r.summary ? add('summary', 'Summary', 'Summary', r.summary, findBlock(r.summary, range('summary'), top, ALL), { block: true }) : null;
  if (r.claimed_years != null) {
    const re = new RegExp(`\\b${r.claimed_years}\\s*\\+?\\s*(?:years?|yrs?)\\b`, 'gi');
    const spans = [...(m.summary?.spans || []), ALL].map(rg => scan(re, rg, 1)).find(s => s.length) || [];
    m.claimed = add('summary', 'Summary', 'Claimed experience', `${r.claimed_years} years`, spans);
  }

  const exp = range('experience') || ALL;
  let cur = exp[0];
  const starts = r.experience.map(j => {
    const hits = [j.title, j.company].flatMap(v => findAll(v, [cur, exp[1]], 1));
    if (!hits.length) return cur;
    cur = Math.max(...hits.map(x => x[1]));
    return Math.min(...hits.map(x => x[0]));
  });
  m.jobs = r.experience.map((j, i) => {
    const rg = [starts[i], starts.slice(i + 1).find(s => s > starts[i]) ?? exp[1]];
    const path = `Job ${i + 1}`;
    const job = { raw: j };
    job.title = j.title ? add('experience', path, 'Title', j.title, findFirst(j.title, rg, exp)) : null;
    job.company = j.company ? add('experience', path, 'Company', j.company, findFirst(j.company, rg, exp)) : null;
    job.location = j.location ? add('experience', path, 'Location', fmtLoc(j.location), findLocation(j.location, rg)) : null;
    job.bullets = j.bullets.map((b, k) => add('experience', path, `Bullet ${k + 1}`, b, findBlock(b, rg, exp), { block: true }));
    const headEnd = job.bullets.find(b => b.spans.length)?.spans[0][0] ?? rg[1];
    job.dates = j.start ? add('experience', path, 'Dates', `${fmtYM(j.start)} – ${fmtYM(j.end)}`, findDates([rg[0], headEnd], rg)) : null;
    return job;
  });

  const edu = range('education') || ALL;
  cur = edu[0];
  m.education = r.education.map((e, i) => {
    const path = `Education ${i + 1}`, rg = [cur, edu[1]];
    const f = (field, v) => (v == null || v === '' ? null : add('education', path, field, v, findFirst(String(v), rg, edu)));
    const entry = { raw: e, degree: f('Degree', e.degree), field: f('Field', e.field), school: f('School', e.school) };
    entry.year = f('Year', e.year);
    entry.gpa = f('GPA', e.gpa);
    entry.location = e.location ? add('education', path, 'Location', fmtLoc(e.location), findLocation(e.location, rg, edu)) : null;
    const ends = [entry.degree, entry.school].flatMap(x => x?.spans || []).map(s => s[1]);
    if (ends.length) cur = Math.max(...ends);
    return entry;
  });

  const certs = range('certifications');
  m.creds = [...r.licenses.map(c => ['License', c]), ...r.certifications.map(c => ['Certification', c])].map(([kind, c]) => {
    let spans = findAll(c.name, ALL, 20);
    if (!spans.length && c.acronym) spans = findAll(c.acronym, ALL, 20);
    return {
      raw: c, kind,
      name: add('credentials', kind, 'Name', c.name, spans, { conf: c.confidence }),
      issuer: c.issuer ? add('credentials', `${kind} · ${c.name}`, 'Issuer', c.issuer, findFirst(c.issuer, certs, ALL)) : null,
    };
  });
  m.acronyms = Object.entries(r.acronyms).map(([a, long]) =>
    add('credentials', 'Acronym', a, long, findFirst(`${long} (${a})`, ALL).length ? findFirst(`${long} (${a})`, ALL) : findFirst(a, ALL), { acronym: a }));

  m.skills = r.skills.map(s => add('skills', cap(s.type), 'Skill', s.text, findAll(s.text, ALL, 30), { conf: s.confidence, raw: s }));
  m.specialties = r.specialties.map(s => add('skills', 'Specialty', 'Specialty', s.text, findAll(s.text, ALL, 30), { conf: s.confidence, raw: s }));
  m.languages = r.languages.map(l => add('languages', 'Language', l.language, l.language, findAll(l.language, ALL, 30), { raw: l }));

  m.availability = Object.entries(r.availability).map(([field, vals]) =>
    [field, vals.map(v => add('availability', cap(field), cap(field), v, findLoose(v, ALL)))]);
  if (r.seniority) {
    const where = [...(m.jobs[0]?.title?.spans || []), ...m.headline.flatMap(x => x.spans)];
    const spans = where.map(rg => findLoose(r.seniority, rg)).find(s => s.length) || [];
    m.seniority = add('contact', 'Profile', 'Seniority', r.seniority, spans);
  }
  m.other = Object.entries(r.other_sections).map(([name, lines]) =>
    [name, lines.map(l => add('other', cap(name), 'Line', l, findBlock(l, range(name), ALL), { block: true }))]);

  state.items = items;
  return m;
}

// ---------- formatting ----------

const cap = s => (s ? s.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()) : s);
const fmtLoc = l => [l.city, l.state].filter(Boolean).join(', ') + (l.zip ? ` ${l.zip}` : '');

function fmtYM(ym) {
  const m = /^(\d{4})-(\d{2})$/.exec(ym || '');
  return m ? `${MONTHS[+m[2] - 1]} ${m[1]}` : cap(ym || '');
}

function fmtDur(months) {
  if (months == null) return '';
  const y = Math.floor(months / 12), mo = months % 12;
  return [y && `${y} yr`, mo && `${mo} mo`].filter(Boolean).join(' ') || '0 mo';
}

function monthIndex(ym) {
  const today = $('today').value || new Date().toLocaleDateString('en-CA');
  const m = /^(\d{4})-(\d{2})/.exec(ym === 'present' ? today : ym || '');
  return m ? +m[1] * 12 + (+m[2] - 1) : null;
}

// ---------- annotated text ----------

function renderDoc() {
  const T = state.text, doc = $('doc');
  const spans = [];
  for (const it of state.items) if (!state.hidden.has(it.cat)) for (const [s, e] of it.spans) spans.push({ s, e, it });
  const cuts = new Set([0, T.length]);
  for (const sp of spans) { cuts.add(sp.s); cuts.add(sp.e); }
  for (const sec of state.sections) { cuts.add(sec.start); if (sec.header) sec.header.forEach(x => cuts.add(x)); }
  const pts = [...cuts].sort((a, b) => a - b);

  state.segsByItem = new Map();
  state.segAt = new Map();
  doc.replaceChildren();
  let k = 0;
  for (const sec of state.sections) {
    const body = h('div', { class: 'sec-body' });
    for (; k < pts.length - 1 && pts[k] < sec.end; k++) {
      const a = pts[k], b = pts[k + 1];
      const cover = spans.filter(sp => sp.s <= a && sp.e >= b);
      const isHeader = sec.header && a >= sec.header[0] && b <= sec.header[1];
      if (!cover.length && !isHeader) { body.append(T.slice(a, b)); continue; }
      body.append(segment(a, b, cover, isHeader));
    }
    const cat = SECTION_CAT[sec.name] || 'other';
    const lines = T.slice(sec.start, sec.end).split('\n').filter(l => l.trim()).length;
    doc.append(h('div', { class: 'sec' },
      h('div', { class: `sec-label e-${cat}` }, sec.name === 'top' ? 'Header' : cap(sec.name), h('small', {}, `${lines} line${lines === 1 ? '' : 's'}`)),
      body));
  }
  doc.classList.toggle('dim', $('dim').checked);
  requestAnimationFrame(renderRail);
}

function segment(a, b, cover, isHeader) {
  const ents = cover.filter(sp => !sp.it.block).sort((x, y) => (x.e - x.s) - (y.e - y.s));
  const blk = cover.find(sp => sp.it.block);
  const cls = ['seg'];
  if (cover.length) cls.push('m');
  if (blk) cls.push('blk', `b-${blk.it.cat}`);
  if (ents.length) cls.push('ent', `e-${ents[0].it.cat}`);
  if (isHeader) cls.push('hdr');
  const el = h('span', { class: cls.join(' ') }, state.text.slice(a, b));
  el._items = [...new Set([...ents, ...(blk ? [blk] : []), ...cover].map(sp => sp.it))];
  el._start = a;
  for (const it of el._items) {
    if (!state.segsByItem.has(it.id)) state.segsByItem.set(it.id, []);
    state.segsByItem.get(it.id).push(el);
  }
  state.segAt.set(a, el);
  return el;
}

function renderRail() {
  const doc = $('doc'), rail = $('rail'), H = doc.scrollHeight || 1;
  rail.querySelectorAll('i').forEach(x => x.remove());
  for (const it of state.items) {
    if (state.hidden.has(it.cat) || it.block) continue;
    for (const [s] of it.spans) {
      const el = state.segAt.get(s);
      if (!el) continue;
      rail.append(h('i', { class: `e-${it.cat}`, style: `top:${(el.offsetTop / H) * 100}%`, 'data-item': it.id, 'data-span': s }));
    }
  }
  syncRailViewport();
}

function syncRailViewport() {
  const doc = $('doc'), vp = $('rail-vp'), H = doc.scrollHeight || 1;
  vp.style.top = `${(doc.scrollTop / H) * 100}%`;
  vp.style.height = `${Math.min(1, doc.clientHeight / H) * 100}%`;
}

// ---------- result cards ----------

function bind(el, item, cls = 'val') {
  if (!item) return el;
  el.classList.add(...cls.split(' '), `e-${item.cat}`);
  el.dataset.item = item.id;
  el.tabIndex = 0;
  if (!item.spans.length) {
    el.classList.add('missing');
    el.title = 'Extracted, but not found verbatim in the text (the parser normalized or combined it)';
  } else if (item.spans.length > 1) {
    el.title = `${item.spans.length} places in the text — click to step through them`;
  }
  if (!state.cardsByItem.has(item.id)) state.cardsByItem.set(item.id, []);
  state.cardsByItem.get(item.id).push(el);
  return el;
}

const V = (item, text) => (item ? bind(h('span', {}, text ?? item.value), item) : null);
const derived = () => h('span', { class: 'derived', title: 'Inferred by the parser, not written in the text' }, 'derived');
const join = (els, sep = ' · ') => els.filter(Boolean).flatMap((e, i) => (i ? [sep, e] : [e]));

function card(cat, title, count, ...body) {
  return h('section', { class: `card e-${cat}` },
    h('div', { class: 'card-head' }, title, count != null && h('span', { class: 'count' }, count)),
    h('div', { class: 'card-body' }, ...body));
}

function rows(pairs) {
  const kept = pairs.filter(([, v]) => v != null && !(Array.isArray(v) && !v.filter(Boolean).length));
  return kept.length ? h('dl', { class: 'rows' }, kept.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])) : null;
}

function chip(item, sub) {
  const c = h('button', { class: 'chip', type: 'button' }, item.value,
    sub && h('span', { class: 'sub' }, sub),
    item.spans.length > 1 && h('span', { class: 'sub' }, `×${item.spans.length}`),
    item.conf != null && h('span', { class: 'conf', style: `--p:${item.conf}`, title: `confidence ${item.conf}` }, h('i')));
  return bind(c, item, 'chip');
}

function renderCards() {
  const m = state.model, r = state.result, out = $('out');
  state.cardsByItem = new Map();
  const cards = [profileCard(m, r), summaryCard(m), experienceCard(m, r), educationCard(m), credentialsCard(m),
    skillsCard(m), languagesCard(m), availabilityCard(m), otherCard(m)].filter(Boolean);
  out.replaceChildren(h('div', { class: 'cards' }, cards));
}

function profileCard(m, r) {
  const occ = r.occupation_group;
  return card('contact', 'Profile', null,
    h('div', { class: 'big' }, m.name ? V(m.name) : h('span', { class: 'muted' }, 'No name found'),
      m.credentials.length ? h('span', { class: 'muted' }, ', ', join(m.credentials.map(c => V(c)), ', ')) : null),
    m.headline.length ? h('div', { class: 'muted', style: 'margin:2px 0 10px' }, join(m.headline.map(x => V(x)))) : h('div', { style: 'height:10px' }),
    rows([
      ['Email', join(m.emails.map(x => V(x)), ', ')],
      ['Phone', join(m.phones.map(x => V(x, x.field === 'Phone' ? x.value : `${x.value} (${x.field.slice(7, -1)})`)), ', ')],
      ['Location', V(m.location)],
      ['Links', join(m.urls.map(x => V(x)), ', ')],
      ['Job title', V(m.job_title)],
      ['Industry', V(m.industry)],
      ['Seniority', V(m.seniority)],
      ['Occupation group', occ && h('span', {}, `${occ.title} `, h('span', { class: 'muted small' }, occ.code), derived())],
      ['Likely roles', r.occupations.length ? h('span', {}, r.occupations.join(' · '), derived()) : null],
      ['Experience', r.total_experience_months != null
        ? h('span', {}, fmtDur(r.total_experience_months), derived(), m.claimed && h('span', { class: 'muted' }, ' · claims ', V(m.claimed)))
        : m.claimed && V(m.claimed)],
    ]));
}

function summaryCard(m) {
  if (!m.summary) return null;
  const p = h('p', { class: 'clamp', style: 'margin:0' }, V(m.summary));
  const more = h('button', { class: 'link', type: 'button', onclick: () => { p.classList.toggle('open'); more.textContent = p.classList.contains('open') ? 'Show less' : 'Show more'; } }, 'Show more');
  return card('summary', 'Summary', null, p, more);
}

function experienceCard(m, r) {
  if (!m.jobs.length) return null;
  return card('experience', 'Experience', `${m.jobs.length} role${m.jobs.length === 1 ? '' : 's'}`,
    timeline(m.jobs),
    m.jobs.map(j => h('div', { class: 'job' },
      h('div', { class: 'job-title' }, j.title ? V(j.title) : h('span', { class: 'muted' }, 'Untitled role')),
      h('div', { class: 'job-meta' }, V(j.company), V(j.location),
        j.dates && h('span', {}, V(j.dates), j.raw.months != null ? ` · ${fmtDur(j.raw.months)}` : '')),
      j.bullets.length ? h('details', {},
        h('summary', {}, `${j.bullets.length} bullet${j.bullets.length === 1 ? '' : 's'}`),
        h('ul', { class: 'bullets' }, j.bullets.map(b => h('li', {}, V(b))))) : null)),
    r.total_experience_months != null && h('div', { class: 'muted small', style: 'margin-top:6px' },
      `Total, overlaps merged: ${fmtDur(r.total_experience_months)}`));
}

function timeline(jobs) {
  const dated = jobs.map((j, i) => ({ j, i, a: monthIndex(j.raw.start), b: monthIndex(j.raw.end) })).filter(x => x.a != null && x.b != null);
  if (!dated.length) return null;
  const lo = Math.min(...dated.map(x => x.a)), hi = Math.max(...dated.map(x => x.b)) + 1, span = Math.max(hi - lo, 1);
  const pct = v => `${((v - lo) / span) * 100}%`;
  const y0 = Math.floor(lo / 12), y1 = Math.ceil(hi / 12), step = Math.max(1, Math.ceil((y1 - y0) / 6));
  const ticks = [];
  for (let y = y0; y <= y1; y += step) if (y * 12 >= lo && y * 12 <= hi) ticks.push(h('span', { style: `left:${pct(y * 12)}` }, y));
  return h('div', { class: 'timeline' },
    dated.map(x => h('div', { class: 'tl-row' }, h('span', {}, x.i + 1),
      h('div', { class: 'tl-track' }, bind(h('div', {
        class: 'tl-bar', style: `left:${pct(x.a)};width:${Math.max(((x.b + 1 - x.a) / span) * 100, 1.5)}%`,
        title: `${x.j.raw.title || ''} — ${fmtYM(x.j.raw.start)} – ${fmtYM(x.j.raw.end)}`,
      }), x.j.title || x.j.company, 'tl-bar')))),
    h('div', { class: 'tl-axis' }, ticks));
}

function educationCard(m) {
  if (!m.education.length) return null;
  return card('education', 'Education', m.education.length,
    m.education.map(e => h('div', { class: 'job' },
      h('div', { class: 'job-title' }, e.degree ? V(e.degree) : h('span', { class: 'muted' }, 'Degree not found'),
        e.field && h('span', { class: 'muted' }, ' · ', V(e.field))),
      h('div', { class: 'job-meta' }, V(e.school), V(e.location), V(e.year), e.gpa && h('span', {}, 'GPA ', V(e.gpa))))));
}

function credentialsCard(m) {
  if (!m.creds.length && !m.acronyms.length) return null;
  return card('credentials', 'Licenses & certifications', m.creds.length || null,
    m.creds.map(c => {
      const raw = c.raw;
      const facts = [c.kind, raw.acronym, raw.state, raw.year, ...(raw.status || [])].filter(Boolean);
      return h('div', { class: 'job' },
        h('div', { class: 'job-title' }, V(c.name),
          raw.confidence != null && h('span', { class: 'conf e-credentials', style: `--p:${raw.confidence};display:inline-block;margin-left:8px`, title: `confidence ${raw.confidence}` }, h('i'))),
        h('div', { class: 'job-meta' }, h('span', {}, facts.join(' · ')), V(c.issuer),
          raw.label && raw.label !== raw.name && h('span', {}, `→ ${raw.label}`)));
    }),
    m.acronyms.length ? h('div', {},
      h('div', { class: 'group-label', style: 'margin-top:12px' }, 'Acronyms defined in the text'),
      rows(m.acronyms.map(a => [a.acronym, V(a)]))) : null);
}

function skillsCard(m) {
  if (!m.skills.length && !m.specialties.length) return null;
  const groups = new Map();
  for (const s of [...m.skills, ...m.specialties]) {
    if (!groups.has(s.path)) groups.set(s.path, []);
    groups.get(s.path).push(s);
  }
  const label = s => (s.raw.label && s.raw.label.toLowerCase() !== s.value.toLowerCase() ? `→ ${s.raw.label}` : null);
  return card('skills', 'Skills & specialties', m.skills.length + m.specialties.length,
    [...groups].map(([g, list]) => [
      h('div', { class: 'group-label' }, `${g} · ${list.length}`),
      h('div', { class: 'chips' }, list.sort((a, b) => (b.conf ?? 0) - (a.conf ?? 0)).map(s => chip(s, label(s)))),
    ]));
}

function languagesCard(m) {
  if (!m.languages.length) return null;
  return card('languages', 'Languages', m.languages.length,
    h('div', { class: 'chips' }, m.languages.map(l => chip(l, l.raw.proficiency))));
}

function availabilityCard(m) {
  const filled = m.availability.filter(([, v]) => v.length);
  if (!filled.length) return null;
  return card('availability', 'Availability', null,
    rows(filled.map(([f, vals]) => [cap(f), h('div', { class: 'chips' }, vals.map(v => chip(v)))])));
}

function otherCard(m) {
  if (!m.other.length) return null;
  return card('other', 'Other sections', m.other.length,
    m.other.map(([name, lines]) => [
      h('div', { class: 'group-label' }, cap(name)),
      h('ul', { class: 'bullets' }, lines.map(l => h('li', {}, V(l)))),
    ]));
}

function jsonHtml(obj) {
  const esc = s => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
  return esc(JSON.stringify(obj, null, 2)).replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|(-?\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b)|\b(true|false|null)\b/g,
    (_, str, colon, num, lit) => (str ? `<span class="${colon ? 'k' : 's'}">${str}</span>${colon || ''}` : num ? `<span class="n">${num}</span>` : `<span class="l">${lit}</span>`));
}

// ---------- stats & legend ----------

function renderStats() {
  const T = state.text, mask = new Uint8Array(T.length);
  for (const it of state.items) for (const [s, e] of it.spans) mask.fill(1, s, e);
  let ink = 0, mapped = 0;
  for (let i = 0; i < T.length; i++) if (!/\s/.test(T[i])) { ink++; mapped += mask[i]; }
  const pct = ink ? Math.round((mapped / ink) * 100) : 0;
  const located = state.items.filter(i => i.spans.length).length;
  const metric = (value, label, bar) => h('div', { class: 'metric' }, h('b', {}, value), h('span', {}, label),
    bar != null && h('div', { class: 'bar' }, h('i', { style: `width:${bar}%` })));
  $('metrics').replaceChildren(
    metric(`${Math.round(state.ms)} ms`, 'parse'),
    metric(T.length.toLocaleString(), 'chars'),
    metric(state.sections.length, 'sections'),
    metric(`${pct}%`, 'text mapped', pct),
    metric(`${located}/${state.items.length}`, 'values located', state.items.length ? (located / state.items.length) * 100 : 0));

  const counts = {};
  for (const it of state.items) counts[it.cat] = (counts[it.cat] || 0) + 1;
  $('legend').replaceChildren(...Object.keys(CATS).filter(c => counts[c]).map(c =>
    h('button', {
      type: 'button', class: `lg e-${c}${state.hidden.has(c) ? ' off' : ''}`, 'aria-pressed': String(!state.hidden.has(c)),
      title: 'Show / hide in the text',
      onclick: () => { state.hidden.has(c) ? state.hidden.delete(c) : state.hidden.add(c); renderStats(); renderDoc(); },
    }, CATS[c], h('b', {}, counts[c]))));
  $('stats').hidden = false;
}

// ---------- linking both sides ----------

const itemById = id => state.items[+id];

function setHot(item, on) {
  if (!item) return;
  for (const el of state.segsByItem.get(item.id) || []) el.classList.toggle('hot', on);
  for (const el of state.cardsByItem.get(item.id) || []) el.classList.toggle('hot', on);
}

function flash(el) {
  el.classList.remove('flash');
  void el.offsetWidth;  // restart the animation
  el.classList.add('flash');
}

function focusItem(item, at) {
  if (!item.spans.length) return toast(`“${trim(item.value, 60)}” was extracted but isn't written verbatim in the text`, true);
  if (state.hidden.has(item.cat)) { state.hidden.delete(item.cat); renderStats(); renderDoc(); }
  setView('annotated');
  let i = at != null ? item.spans.findIndex(s => s[0] === at) : (state.cycle.get(item.id) ?? 0) % item.spans.length;
  if (i < 0) i = 0;
  state.cycle.set(item.id, i + 1);
  const [s, e] = item.spans[i];
  const segs = (state.segsByItem.get(item.id) || []).filter(el => el._start >= s && el._start < e);
  segs[0]?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  segs.forEach(flash);
  $('source-hint').textContent = `${CATS[item.cat]} › ${item.path} › ${item.field}` + (item.spans.length > 1 ? ` — ${i + 1} of ${item.spans.length}` : '');
}

function revealCard(item) {
  if (state.out !== 'fields') setOut('fields');
  const el = (state.cardsByItem.get(item.id) || [])[0];
  if (!el) return;
  const d = el.closest('details');
  if (d) d.open = true;
  el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  flash(el);
}

const trim = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

function showTip(seg, x, y) {
  const tip = $('tip');
  tip.replaceChildren(...seg._items.slice(0, 4).map(it => h('div', { class: `t-row e-${it.cat}` },
    h('span', { class: 't-dot' }),
    h('div', {}, h('div', { class: 't-path' }, `${CATS[it.cat]} › ${it.path} › ${it.field}`), h('div', { class: 't-val' }, trim(it.value, 140))))));
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = `${Math.min(x + 14, innerWidth - r.width - 8)}px`;
  tip.style.top = `${y + 18 + r.height > innerHeight ? y - r.height - 12 : y + 18}px`;
}

function wireLinks() {
  const doc = $('doc'), out = $('out'), rail = $('rail');
  let hotSeg = null;
  doc.addEventListener('mousemove', ev => {
    const seg = ev.target.closest('.seg.m');
    if (seg !== hotSeg) {
      if (hotSeg) setHot(hotSeg._items[0], false);
      hotSeg = seg;
      if (seg) setHot(seg._items[0], true);
    }
    if (seg) showTip(seg, ev.clientX, ev.clientY); else $('tip').hidden = true;
  });
  doc.addEventListener('mouseleave', () => { if (hotSeg) setHot(hotSeg._items[0], false); hotSeg = null; $('tip').hidden = true; });
  doc.addEventListener('click', ev => { const seg = ev.target.closest('.seg.m'); if (seg) revealCard(seg._items[0]); });
  doc.addEventListener('scroll', syncRailViewport, { passive: true });

  out.addEventListener('mouseover', ev => { const el = ev.target.closest('[data-item]'); if (el) setHot(itemById(el.dataset.item), true); });
  out.addEventListener('mouseout', ev => { const el = ev.target.closest('[data-item]'); if (el) setHot(itemById(el.dataset.item), false); });
  out.addEventListener('click', ev => { const el = ev.target.closest('[data-item]'); if (el) focusItem(itemById(el.dataset.item)); });
  out.addEventListener('keydown', ev => {
    const el = ev.target.closest('[data-item]');
    if (el && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); focusItem(itemById(el.dataset.item)); }
  });
  rail.addEventListener('click', ev => { const t = ev.target.closest('i'); if (t) focusItem(itemById(t.dataset.item), +t.dataset.span); });
}

// ---------- views, input, parsing ----------

function setView(view) {
  const annotated = view === 'annotated';
  $('input').hidden = annotated;
  $('doc-wrap').hidden = !annotated;
  $('tab-annotated').classList.toggle('active', annotated);
  $('tab-edit').classList.toggle('active', !annotated);
  if (annotated) requestAnimationFrame(renderRail);
  else $('source-hint').textContent = 'Paste text or drop a .txt file';
}

function setOut(view) {
  state.out = view;
  document.querySelectorAll('[data-out]').forEach(t => t.classList.toggle('active', t.dataset.out === view));
  $('copy').hidden = view !== 'json';
  if (view === 'json') $('out').replaceChildren(Object.assign(h('pre', { class: 'json' }), { innerHTML: jsonHtml(state.result) }));
  else renderCards();
}

async function extract() {
  const text = $('input').value, btn = $('parse');
  if (!text.trim()) return toast('Paste some text first', true);
  btn.disabled = true;
  try {
    const res = await fetch('/api/parse', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, today: $('today').value || null }),
    });
    const body = res.headers.get('Content-Type')?.includes('json') ? await res.json() : { error: `server replied HTTP ${res.status}` };
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    Object.assign(state, {
      text: body.text, sections: body.sections, result: body.result, ms: body.ms,
      datePatterns: body.date_patterns.map(p => new RegExp(p, 'gi')), cycle: new Map(),
    });
    state.model = buildModel(body.result);
    $('tab-annotated').disabled = false;
    renderStats();
    renderDoc();
    setView('annotated');
    setOut(state.out || 'fields');
    $('source-hint').textContent = 'Hover a highlight to see what was extracted · click to jump to it';
  } catch (e) {
    toast(e instanceof TypeError ? 'Cannot reach the server — is ui/server.py running?' : e.message, true);
  } finally {
    btn.disabled = false;
  }
}

let toastTimer;
function toast(msg, isError) {
  const t = $('toast');
  t.textContent = msg;
  t.className = `toast${isError ? '' : ' ok'}`;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
}

async function loadFile(file) {
  if (!file) return;
  if (file.size > MAX_FILE) return toast('That file is over 2 MB — paste the text instead', true);
  if (file.type && !file.type.startsWith('text/')) return toast('Only plain-text files — convert PDF/DOCX to text first', true);
  $('input').value = await file.text();
  setView('edit');
  await extract();
}

function wireInput() {
  $('today').value = new Date().toLocaleDateString('en-CA');
  $('parse').addEventListener('click', extract);
  $('file').addEventListener('change', ev => { loadFile(ev.target.files[0]).catch(e => toast(e.message, true)); ev.target.value = ''; });
  $('tab-edit').addEventListener('click', () => setView('edit'));
  $('tab-annotated').addEventListener('click', () => setView('annotated'));
  document.querySelectorAll('[data-out]').forEach(t => t.addEventListener('click', () => state.result && setOut(t.dataset.out)));
  $('copy').addEventListener('click', () => navigator.clipboard.writeText(JSON.stringify(state.result, null, 2))
    .then(() => toast('JSON copied'), e => toast(`Copy failed: ${e.message}`, true)));
  $('dim').addEventListener('change', ev => $('doc').classList.toggle('dim', ev.target.checked));
  $('input').addEventListener('input', () => { if (state.result) $('source-hint').textContent = 'Edited — press Extract to refresh'; });
  document.addEventListener('keydown', ev => { if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') { ev.preventDefault(); extract(); } });
  addEventListener('resize', () => { if (!$('doc-wrap').hidden) renderRail(); });

  const source = $('source'), drop = $('drop');
  let depth = 0;
  source.addEventListener('dragenter', ev => { ev.preventDefault(); depth++; drop.hidden = false; });
  source.addEventListener('dragover', ev => ev.preventDefault());
  source.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; drop.hidden = true; } });
  source.addEventListener('drop', ev => {
    ev.preventDefault();
    depth = 0;
    drop.hidden = true;
    loadFile(ev.dataTransfer.files[0]).catch(e => toast(e.message, true));
  });
}

state.out = 'fields';
wireInput();
wireLinks();
