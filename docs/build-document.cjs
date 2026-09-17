const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');
const runtime = createRequire('/Users/teslimsulaiman/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/');
const { marked } = runtime('marked');

const root = __dirname;
const sources = [
  { id: 'product', label: 'Product specification', file: 'product-specification.md' },
  { id: 'delivery', label: 'Milestones and sprints', file: 'delivery-plan.md' },
];
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const toc = [];
const bodies = sources.map(source => {
  const md = fs.readFileSync(path.join(root, source.file), 'utf8');
  const links = [];
  let body = marked.parse(md);
  body = body.replace(/<h([123])>(.*?)<\/h\1>/g, (_, level, title) => {
    const id = source.id + '-' + slug(title.replace(/<[^>]+>/g, ''));
    if (level === '2') links.push(`<a href="#${id}">${title}</a>`);
    return `<h${level} id="${id}">${title}</h${level}>`;
  });
  body = body.replace(/<table>/g, '<div class="table-scroll" tabindex="0"><table>').replace(/<\/table>/g, '</table></div>');
  toc.push(`<details open><summary>${source.label}</summary><div class="toc-links">${links.join('')}</div></details>`);
  return `<article class="document" id="${source.id}"><div class="part-label">${source.id === 'product' ? 'Part one' : 'Part two'}<a href="${source.file}" download>Editable Markdown ↗</a></div>${body}</article>`;
});

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Stackjunior Exam Coach version 2 product specification and delivery plan for the NECO GCE Mathematics pilot.">
<title>Stackjunior Exam Coach Product and Delivery Plan</title>
<style>
:root{--ink:#172b2b;--muted:#546563;--green:#17644f;--line:#dbe3de;--paper:#fff;--wash:#f4f6f1;--sidebar:284px}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:28px}body{margin:0;background:var(--wash);color:var(--ink);font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:var(--green);text-decoration:none}a:hover{text-decoration:underline}a:focus-visible,button:focus-visible,summary:focus-visible,.table-scroll:focus-visible{outline:3px solid #d69237;outline-offset:4px}button{font:inherit}aside{position:fixed;inset:0 auto 0 0;width:var(--sidebar);background:#f9faf7;border-right:1px solid var(--line);padding:28px 22px;overflow-y:auto}.brand{display:flex;align-items:center;gap:10px;font-size:16px;font-weight:750;color:var(--ink);margin-bottom:22px}.brand-mark{display:grid;place-items:center;width:32px;height:32px;border-radius:8px;background:var(--green);color:white;font-size:13px}aside .version{color:var(--muted);font-size:12px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:28px}details{margin-bottom:18px}summary{cursor:pointer;font-weight:650;font-size:13px;padding:6px 0}.toc-links{display:grid;gap:3px;margin-top:8px}.toc-links a{padding:4px 7px;color:#53615b;font-size:12px;line-height:1.45;border-radius:4px}.toc-links a:hover{background:#e8eee6;color:#104e3d;text-decoration:none}.sidebar-bottom{margin-top:24px;border-top:1px solid var(--line);padding-top:18px;font-size:12px;color:var(--muted)}main{margin-left:var(--sidebar);max-width:1170px;padding:54px 60px 70px}.cover{margin-bottom:42px}.kicker{font-weight:650;color:var(--green);font-size:12px;text-transform:uppercase;letter-spacing:.12em}.cover h1{font-size:clamp(32px,3.5vw,48px);line-height:1.13;letter-spacing:-.04em;max-width:720px;margin:18px 0}.cover .intro{font-size:18px;line-height:1.65;max-width:730px;color:var(--muted)}.meta{display:flex;gap:8px 18px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:22px}.cover-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:24px}.button{border:1px solid var(--line);background:white;border-radius:6px;padding:9px 14px;font-size:13px;color:var(--ink);cursor:pointer;display:inline-block}.button.primary{background:var(--green);color:#fff;border-color:var(--green)}.button:hover{text-decoration:none;filter:brightness(.96)}.timeline{display:grid;grid-template-columns:repeat(5,1fr);gap:0;border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:34px 0 0;background:#fff}.timeline div{padding:17px 13px;border-right:1px solid var(--line)}.timeline div:last-child{border:0}.timeline small{display:block;font-size:10px;color:var(--green);text-transform:uppercase;letter-spacing:.06em;font-weight:700}.timeline strong{display:block;line-height:1.3;font-size:13px;margin:7px 0}.timeline span{display:block;font-size:11px;color:var(--muted)}.planning-note{font-size:12px;color:var(--muted);margin-top:10px}.document{background:var(--paper);padding:40px 44px 48px;border:1px solid var(--line);border-radius:10px;margin-bottom:40px;box-shadow:0 3px 16px #183c2404}.part-label{display:flex;justify-content:space-between;gap:12px;color:var(--green);font-size:11px;font-weight:650;letter-spacing:.09em;text-transform:uppercase;margin-bottom:20px}.part-label a{font-weight:500;letter-spacing:0;text-transform:none}.document h1{font-size:29px;line-height:1.25;letter-spacing:-.025em;color:#111;margin:0 0 14px}.document h1+p{font-size:12px;color:var(--muted);margin-bottom:32px}.document h2{font-size:23px;line-height:1.35;letter-spacing:-.015em;margin:42px 0 15px;color:#111}.document h3{font-size:17px;line-height:1.4;margin:28px 0 12px;color:#111}.document p{margin:0 0 16px}.document li{margin:0 0 11px;padding-left:3px}.document ul{padding-left:22px;margin:15px 0 22px}.document strong{font-weight:650}.table-scroll{overflow-x:auto;width:100%;margin:22px 0 26px;border-radius:5px;border:1px solid var(--line)}table{width:100%;border-collapse:collapse;font-size:13px;line-height:1.55}th{background:#e9f0ed;text-align:left;font-weight:650;color:#173e31}th,td{padding:12px 13px;vertical-align:top;border-right:1px solid var(--line);border-bottom:1px solid var(--line);overflow-wrap:break-word}tr:last-child td{border-bottom:0}th:last-child,td:last-child{border-right:0}tbody tr:nth-child(even){background:#fafbf9}td:first-child{font-weight:550}footer{color:var(--muted);font-size:12px;padding:0 5px}.mobile-nav{display:none}body.mobile-menu aside{display:block}
@media(min-width:1600px){main{margin-left:calc(var(--sidebar) + (100vw - 1500px)/3)}}
@media(max-width:1100px){:root{--sidebar:245px}main{padding:35px 28px}.document{padding:32px 28px}.timeline div{padding:14px 9px}}
@media(max-width:800px){aside{display:none;z-index:20;width:min(330px,90vw);box-shadow:12px 0 24px #0002;padding-top:65px}main{margin:0;padding:28px 18px}.mobile-nav{display:block;position:fixed;right:16px;top:12px;z-index:30;border:1px solid var(--line);border-radius:6px;padding:7px 12px;background:#fff;color:var(--ink);font-size:12px}.cover{padding-top:24px}.cover h1{font-size:34px}.cover .intro{font-size:16px}.document{padding:28px 20px;border-radius:7px}.document h1{font-size:25px}.document h2{font-size:21px}.timeline{grid-template-columns:1fr 1fr}.timeline div{border-bottom:1px solid var(--line);border-right:1px solid var(--line)}.timeline div:last-child{grid-column:1/-1;border:0}.timeline strong{font-size:14px}table{min-width:580px}.part-label{flex-wrap:wrap}.document ul{padding-left:18px}}
@media print{@page{size:A4;margin:18mm}body{background:#fff;font-size:10pt;line-height:1.5}aside,.mobile-nav,.cover-actions,.part-label a{display:none!important}main{max-width:none;margin:0;padding:0}.cover{margin:0 0 26px}.cover h1{font-size:30pt}.cover .intro{font-size:12pt}.document{border:0;box-shadow:none;padding:0;margin:0;border-radius:0}.document+#delivery{break-before:page}.document h1{font-size:23pt;margin-top:20px}.document h2{font-size:16pt;margin-top:25px}.document h3{font-size:12pt}.document h1,.document h2,.document h3{break-after:avoid}.document p,.document li{orphans:3;widows:3}.document li{break-inside:avoid}.table-scroll{overflow:visible;border-radius:0}table{min-width:0;font-size:8.5pt}thead{display:table-header-group}tr{break-inside:avoid}th,td{padding:7px}.timeline{break-inside:avoid}.part-label{margin-top:20px}a{color:inherit}.planning-note{font-size:9pt}footer{margin-top:24px}}
</style>
</head>
<body>
<button class="mobile-nav" type="button" aria-controls="navigation" aria-expanded="false">Contents</button>
<aside id="navigation" aria-label="Document contents">
<a class="brand" href="#top"><span class="brand-mark">sj</span>Stackjunior</a>
<div class="version">Product and delivery · v2.0</div>
${toc.join('')}
<div class="sidebar-bottom">NECO GCE Mathematics<br>13 September 2026<br>Goals, requirements and release evidence</div>
</aside>
<main id="top">
<header class="cover">
<div class="kicker">NECO GCE Mathematics</div>
<h1>Exam Coach<br>Product and delivery plan</h1>
<p class="intro">A focused learning pilot with flexible progression, inspectable evidence, and a delivery plan that tests learning and commercial viability.</p>
<div class="meta"><span>Version 2.0</span><span>13 September 2026</span><span>24 product requirements</span><span>10 two-week sprints</span></div>
<div class="cover-actions"><a class="button primary" href="#product">Read specification</a><a class="button" href="#delivery">Read sprint plan</a><button class="button" type="button" id="print">Print document</button></div>
<div class="timeline" aria-label="Proposed delivery sequence">
<div><small>M1 · Sprints 1–2</small><strong>Scope and content</strong><span>Weeks 1–4</span></div>
<div><small>M2 · Sprints 3–4</small><strong>Initial learner route</strong><span>Weeks 5–8</span></div>
<div><small>M3 · Sprints 5–6</small><strong>Pilot readiness</strong><span>Weeks 9–12</span></div>
<div><small>M4 · Sprints 7–9</small><strong>Six-week pilot</strong><span>Weeks 13–18</span></div>
<div><small>M5 · Sprint 10</small><strong>Evidence and decision</strong><span>Weeks 19–20</span></div>
</div>
<p class="planning-note">Planning assumption, subject to staffing, content throughput and the verified examination calendar. Expansion is separately gated.</p>
</header>
${bodies.join('\n')}
<footer>Stackjunior Exam Coach · Product specification and delivery plan · Version 2.0<br>Editable source documents accompany this self-contained reading copy.</footer>
</main>
<script>
const menu=document.querySelector('.mobile-nav');
menu.addEventListener('click',()=>{const open=document.body.classList.toggle('mobile-menu');menu.setAttribute('aria-expanded',String(open));menu.textContent=open?'Close contents':'Contents';});
document.querySelectorAll('aside a').forEach(link=>link.addEventListener('click',()=>{document.body.classList.remove('mobile-menu');menu.setAttribute('aria-expanded','false');menu.textContent='Contents';}));
document.addEventListener('keydown',event=>{if(event.key==='Escape'){document.body.classList.remove('mobile-menu');menu.setAttribute('aria-expanded','false');menu.textContent='Contents';}});
document.getElementById('print').addEventListener('click',()=>window.print());
</script>
</body>
</html>`;
const dest = path.join(root, 'Stackjunior_Exam_Coach_Product_and_Delivery_Plan.html');
fs.writeFileSync(dest, html);
console.log(dest);
