// Builds a single HTML page from docs/product-spec.md and docs/roadmap.md.
// Usage: node docs/_build/build.mjs [output.html]
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const docs = join(here, '..');
const out = process.argv[2] ?? join(docs, 'score-pilot-plan.html');

const read = (name) => {
  const text = readFileSync(join(docs, name), 'utf8');
  if (/<\/script/i.test(text)) throw new Error(`${name} contains "</script", which would break the page`);
  return text;
};

const html = readFileSync(join(here, 'template.html'), 'utf8')
  .replace('<!--SPEC-->', () => read('product-spec.md'))
  .replace('<!--ROADMAP-->', () => read('roadmap.md'));

writeFileSync(out, html);
console.log(`Wrote ${out}`);
