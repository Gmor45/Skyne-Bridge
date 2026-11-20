#!/usr/bin/env node
// web_check.mjs -- the automatic half of the Web Standard (step 1 of grading).
//
// The Web Standard is .claude/skills/web-standard/SKILL.md in this repo
// (RULED 2026-11-20). This script opens each page of a site in a real
// browser, at phone width (390px) and at 2560px, in light and in dark, and
// counts problems:
//
//   axe:<rule>       axe-core, WCAG 2.2 AA tags, with target-size switched on
//                    (it ships OFF by default)              -> the R rules
//   tap-44           a clickable thing under 44x44px        -> P1
//   input-16         a form field with text under 16px      -> P2
//   h-scroll         the page scrolls sideways on a phone   -> R6
//   touch-none       a big area with touch-action: none     -> P5
//   radius           a corner that is not 0/8/14/22/pill    -> L3
//   one-column       a long page using under half of 2560px -> L4
//   no-light-dark    the page looks the same in light and dark -> L7
//   no-theme-toggle  no element marked data-theme-toggle   -> L7
//   load-error       the page did not load (never a pass)
//
// A site keeps its known problems in a baseline file. The check FAILS when a
// count goes up (or a new problem appears), and says which. A count that goes
// down is reported so the baseline can be lowered in the same pull request.
// This lets a site turn the check on today without fixing every old problem
// first, while nothing new gets in.
//
// What it cannot see, said plainly: about half of accessibility problems need
// a person (Deque's study: axe found 57% by count). Every rule marked
// "review" in the standard is a judgment no script makes. `one-column` is a
// heuristic (content narrower than 1280px on a page taller than 1.5 screens).
//
// Usage:
//   node web_check.mjs --base http://127.0.0.1:8791 --pages /,/app
//   node web_check.mjs --serve site --pages /index.html
//   options: --header "Name: value" (repeat)  --baseline FILE
//            --update-baseline  --baseline-from FINDINGS.json  --json FILE  --self-test
// Exit: 0 no regressions, 1 a count went up, 2 the tool itself failed.

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { AxeBuilder } from '@axe-core/playwright';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const VIEWS = {
  phone: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
  wide: { viewport: { width: 2560, height: 1440 } },
};
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

function parseArgs(argv) {
  const a = { pages: [], headers: {}, baseline: null, update: false, json: null, base: null, serve: null, selfTest: false };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const v = () => argv[++i];
    if (k === '--base') a.base = v();
    else if (k === '--serve') a.serve = v();
    else if (k === '--pages') a.pages.push(...v().split(/[\s,]+/).filter(Boolean));
    else if (k === '--header') { const h = v(); const j = h.indexOf(':'); a.headers[h.slice(0, j).trim()] = h.slice(j + 1).trim(); }
    else if (k === '--baseline') a.baseline = v();
    else if (k === '--update-baseline') a.update = true;
    else if (k === '--json') a.json = v();
    else if (k === '--self-test') a.selfTest = true;
    else if (k === '--baseline-from') a.baselineFrom = v();
    else throw new Error(`unknown option ${k}`);
  }
  return a;
}

const TYPES = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.webp': 'image/webp' };

function serveDir(dir) {
  const root = path.resolve(dir);
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    let f = path.join(root, p);
    if (!f.startsWith(root)) { res.writeHead(403); return res.end(); }
    if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
    if (!fs.existsSync(f) && fs.existsSync(f + '.html')) f += '.html';
    if (!fs.existsSync(f)) { res.writeHead(404); return res.end('not found'); }
    res.writeHead(200, { 'content-type': TYPES[path.extname(f)] || 'application/octet-stream' });
    fs.createReadStream(f).pipe(res);
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok({ server, base: `http://127.0.0.1:${server.address().port}` })));
}

// Runs inside the page. Returns { check: {count, samples[]} }.
function measure(view) {
  const out = {};
  const add = (k, s) => { (out[k] ||= { count: 0, samples: [] }).count++; if (out[k].samples.length < 5) out[k].samples.push(s); };
  const W = window.innerWidth, H = window.innerHeight;
  const name = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    else if (el.classList.length) s += '.' + [...el.classList].slice(0, 2).join('.');
    const t = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30);
    return t ? `${s} "${t}"` : s;
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0;
  };
  // A spam trap (S2's hidden field) or anything parked off-screen is not
  // something a person sees or taps; counting it would punish S2 itself.
  const forPeople = (el) => {
    if (!visible(el)) return false;
    if (el.closest('[aria-hidden="true"],[hidden],[inert]')) return false;
    if (el.tagName === 'INPUT' && el.getAttribute('tabindex') === '-1') return false;
    const r = el.getBoundingClientRect();
    if (r.right + window.scrollX <= 0 || r.bottom + window.scrollY <= 0) return false;
    return true;
  };

  // P1: 44px targets. A link inside a sentence is exempt (it cannot be 44px tall).
  const CLICK = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=tab],[role=checkbox],[role=switch],[tabindex]:not([tabindex="-1"])';
  for (const el of document.querySelectorAll(CLICK)) {
    if (!forPeople(el)) continue;
    const cs = getComputedStyle(el);
    if (el.tagName === 'A' && cs.display === 'inline' && el.parentElement) {
      const own = (el.textContent || '').trim().length;
      const around = (el.parentElement.textContent || '').trim().length;
      if (around > own + 10) continue;
    }
    let target = el;
    if (el.tagName === 'INPUT' && el.closest('label')) target = el.closest('label');
    const r = target.getBoundingClientRect();
    if (r.width < 43.5 || r.height < 43.5) add('tap-44', `${name(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
  }

  if (view === 'phone') {
    // P2: inputs 16px or larger.
    for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=button]),select,textarea')) {
      if (!forPeople(el)) continue;
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (fs < 16) add('input-16', `${name(el)} ${fs}px`);
    }
    // R6: nothing scrolls sideways at phone width.
    // A phone browser zooms out to fit a too-wide page, which grows innerWidth
    // with it; the screen's own width does not move.
    const PW = Math.min(W, screen.width || W);
    const sw = document.documentElement.scrollWidth;
    if (sw > PW + 1) add('h-scroll', `page is ${sw}px wide on a ${PW}px phone`);
  }

  // P5 and L3 walk every element once.
  const ALLOWED = [0, 2, 3, 4, 6, 8, 14, 22];
  let n = 0;
  for (const el of document.body ? document.body.querySelectorAll('*') : []) {
    if (++n > 6000) break;
    if (!visible(el)) continue;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (cs.touchAction === 'none' && r.width * r.height > 40000) add('touch-none', name(el));
    const painted = (cs.backgroundColor && !/rgba\(0, 0, 0, 0\)|transparent/.test(cs.backgroundColor))
      || parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderLeftWidth) > 0 || (cs.boxShadow && cs.boxShadow !== 'none')
      || el.tagName === 'IMG';
    if (!painted) continue;
    for (const c of [cs.borderTopLeftRadius, cs.borderTopRightRadius, cs.borderBottomRightRadius, cs.borderBottomLeftRadius]) {
      if (!c || c.includes('%')) continue;
      const v = parseFloat(c);
      if (!(v > 0)) continue;
      const round = v >= 999 || v >= Math.min(r.width, r.height) / 2 - 1;
      if (!round && !ALLOWED.some((x) => Math.abs(x - v) < 0.5)) { add('radius', `${name(el)} ${c}`); break; }
    }
  }

  // L4: a long page that uses under half of a 2560px screen.
  if (view === 'wide' && !document.querySelector('[data-layout="prose"]')) {
    let left = Infinity, right = -Infinity;
    for (const el of document.body ? document.body.querySelectorAll('h1,h2,h3,h4,p,li,td,th,img,svg,canvas,button,input,select,textarea,figure,pre,table') : []) {
      if (!forPeople(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width >= W * 0.95) continue;
      left = Math.min(left, r.left); right = Math.max(right, r.right);
    }
    const docH = document.documentElement.scrollHeight;
    if (right > left && right - left < W / 2 && docH > H * 1.5) add('one-column', `content is ${Math.round(right - left)}px wide on a ${W}px screen, page ${docH}px tall`);
  }
  return out;
}

function paint() {
  const b = getComputedStyle(document.body || document.documentElement);
  const h = getComputedStyle(document.documentElement);
  return [h.backgroundColor, b.backgroundColor, b.color].join('|');
}

async function checkPage(browser, base, page, headers) {
  const found = {}; // key -> {count, samples}
  const put = (check, view, data) => { found[`${page} | ${check} | ${view}`] = data; };
  const paints = {};
  let toggle = false;
  for (const [vname, vopts] of Object.entries(VIEWS)) {
    for (const scheme of ['light', 'dark']) {
      const ctx = await browser.newContext({ ...vopts, colorScheme: scheme, extraHTTPHeaders: headers, reducedMotion: 'reduce' });
      const tab = await ctx.newPage();
      const view = `${vname}-${scheme}`;
      let resp;
      try {
        resp = await tab.goto(base + page, { waitUntil: 'networkidle', timeout: 30000 });
      } catch (e) {
        put('load-error', view, { count: 1, samples: [String(e.message).split('\n')[0]] });
        await ctx.close();
        continue;
      }
      if (!resp || resp.status() >= 400) {
        put('load-error', view, { count: 1, samples: [`HTTP ${resp ? resp.status() : 'none'}`] });
        await ctx.close();
        continue;
      }
      const axe = await new AxeBuilder({ page: tab })
        .options({ runOnly: { type: 'tag', values: AXE_TAGS }, rules: { 'target-size': { enabled: true } } })
        .analyze();
      for (const v of axe.violations) {
        put(`axe:${v.id}`, view, { count: v.nodes.length, samples: v.nodes.slice(0, 3).map((n) => n.target.join(' ')) });
      }
      if (scheme === 'light') {
        const m = await tab.evaluate(measure, vname);
        for (const [k, d] of Object.entries(m)) put(k, vname, d);
      }
      paints[view] = await tab.evaluate(paint);
      toggle ||= await tab.evaluate(() => !!document.querySelector('[data-theme-toggle]'));
      await ctx.close();
    }
  }
  if (paints['phone-light'] && paints['phone-dark'] && paints['phone-light'] === paints['phone-dark']) {
    put('no-light-dark', 'any', { count: 1, samples: ['same colors with the device set to light and to dark'] });
  }
  if (Object.keys(paints).length && !toggle) put('no-theme-toggle', 'any', { count: 1, samples: ['no element marked data-theme-toggle'] });
  return found;
}

export async function run({ base, serve, pages, headers = {} }) {
  let server = null;
  if (serve) { const s = await serveDir(serve); server = s.server; base = s.base; }
  if (!base) throw new Error('give --base URL or --serve DIR');
  if (!pages.length) throw new Error('give --pages');
  // WEB_CHECK_CHANNEL=msedge uses the installed Edge instead of Playwright's own download.
  const browser = await chromium.launch({ headless: true, channel: process.env.WEB_CHECK_CHANNEL || undefined });
  const all = {};
  try {
    for (const p of pages) Object.assign(all, await checkPage(browser, base.replace(/\/$/, ''), p, headers));
  } finally {
    await browser.close();
    if (server) server.close();
  }
  return all;
}

export function compare(found, baseline) {
  const up = [], down = [], same = [];
  const keys = new Set([...Object.keys(found), ...Object.keys(baseline)]);
  for (const k of [...keys].sort()) {
    const now = found[k] ? found[k].count : 0;
    const was = baseline[k] || 0;
    if (now > was) up.push({ k, was, now, samples: found[k] ? found[k].samples : [] });
    else if (now < was) down.push({ k, was, now });
    else if (now) same.push({ k, now });
  }
  return { up, down, same };
}

function report({ up, down, same }, found) {
  const lines = [];
  const total = Object.values(found).reduce((s, d) => s + d.count, 0);
  lines.push(`Web Standard check: ${total} problem(s) found, ${up.length} new or worse, ${down.length} better.`);
  if (up.length) {
    lines.push('', 'NEW OR WORSE (this fails the check):');
    for (const u of up) lines.push(`  ${u.k}: ${u.was} -> ${u.now}   e.g. ${u.samples.slice(0, 2).join(' ; ')}`);
  }
  if (down.length) {
    lines.push('', 'BETTER (lower the baseline from this run\'s web-check-findings file: --baseline-from):');
    for (const d of down) lines.push(`  ${d.k}: ${d.was} -> ${d.now}`);
  }
  if (same.length) {
    lines.push('', `Known and unchanged (${same.length}):`);
    for (const s of same.slice(0, 40)) lines.push(`  ${s.k}: ${s.now}`);
    if (same.length > 40) lines.push(`  ... and ${same.length - 40} more`);
  }
  return lines.join('\n');
}

async function selfTest() {
  const fx = path.join(HERE, 'fixtures');
  const fails = [];
  const found = await run({ serve: fx, pages: ['/bad.html', '/good.html', '/missing.html'] });
  const has = (page, check) => Object.keys(found).some((k) => k.startsWith(`${page} | ${check} |`));
  // Planted faults: each must be caught (house-rules 6c).
  for (const c of ['tap-44', 'input-16', 'h-scroll', 'touch-none', 'radius', 'one-column', 'no-light-dark', 'no-theme-toggle', 'axe:image-alt', 'axe:color-contrast']) {
    if (!has('/bad.html', c)) fails.push(`bad.html: planted ${c} was not caught`);
  }
  // The clean page beside it must come back clean.
  const goodKeys = Object.keys(found).filter((k) => k.startsWith('/good.html |'));
  if (goodKeys.length) fails.push(`good.html must be clean, got: ${goodKeys.join(', ')}`);
  // A page that does not load is never a pass.
  if (!has('/missing.html', 'load-error')) fails.push('a 404 page must report load-error');
  // The ratchet: a higher count fails, an equal one passes, a lower one is reported.
  const k = '/bad.html | tap-44 | phone';
  const n = found[k] ? found[k].count : 0;
  if (!n) fails.push('no tap-44 count on bad.html to test the ratchet with');
  const base = Object.fromEntries(Object.entries(found).map(([key, d]) => [key, d.count]));
  if (compare(found, base).up.length) fails.push('equal counts must not fail');
  if (compare(found, { ...base, [k]: n - 1 }).up.length !== 1) fails.push('a count above the baseline must fail');
  if (compare(found, { ...base, [k]: n + 1 }).down.length !== 1) fails.push('a count below the baseline must be reported');
  if (fails.length) { for (const f of fails) console.log('SELF-TEST FAIL:', f); return 1; }
  console.log(`self-test: ${Object.keys(found).length} findings on the fixtures, all 10 planted faults caught, good page clean, 404 caught, ratchet ok`);
  return 0;
}

function writeBaseline(file, counts) {
  fs.mkdirSync(path.dirname(path.resolve(file)), { recursive: true });
  const sorted = Object.fromEntries(Object.keys(counts).sort().map((k) => [k, counts[k]]));
  const readme = 'Known Web Standard problems for this site (page | check | view: count). '
    + 'The check fails if a count goes up. After fixing a problem, lower its count from the '
    + 'pull request\'s CI run: download its web-check-findings file and run web_check.mjs '
    + '--baseline-from web-check.json --baseline .web-check/baseline.json. '
    + 'Rules: Skyne-Bridge .claude/skills/web-standard/SKILL.md';
  fs.writeFileSync(file, JSON.stringify({ _readme: readme, counts: sorted }, null, 1) + '\n');
  console.log(`baseline written: ${Object.keys(sorted).length} entries -> ${file}`);
}

async function main() {
  const a = parseArgs(process.argv.slice(2));
  if (a.selfTest) process.exit(await selfTest());
  if (a.baselineFrom) {
    // Set a baseline from a CI run's findings (the web-check-findings
    // artifact). CI runs on Linux, which draws text a pixel or two
    // differently from a Windows browser, so CI's numbers are the ones the
    // check compares against. Never set a baseline from a local run.
    if (!a.baseline) throw new Error('--baseline-from needs --baseline FILE');
    const f = JSON.parse(fs.readFileSync(a.baselineFrom, 'utf8'));
    writeBaseline(a.baseline, Object.fromEntries(Object.entries(f).map(([k, d]) => [k, d.count])));
    process.exit(0);
  }
  const found = await run(a);
  const counts = Object.fromEntries(Object.entries(found).map(([k, d]) => [k, d.count]));
  if (a.json) fs.writeFileSync(a.json, JSON.stringify(found, null, 1));
  if (a.update) {
    if (!a.baseline) throw new Error('--update-baseline needs --baseline FILE');
    writeBaseline(a.baseline, counts);
  }
  let baseline = {};
  if (a.baseline && fs.existsSync(a.baseline)) baseline = JSON.parse(fs.readFileSync(a.baseline, 'utf8')).counts || {};
  const cmp = compare(found, baseline);
  const text = report(cmp, found);
  console.log(text);
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, '```\n' + text + '\n```\n');
  process.exit(cmp.up.length ? 1 : 0);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e) => { console.error('web_check failed to run:', e.message); process.exit(2); });
}
