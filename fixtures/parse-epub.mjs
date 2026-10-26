import fs from 'fs';
import path from 'path';
import { fileURLToPath, pathToFileURL } from 'url';
import { createRequire } from 'module';
import vm from 'vm';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, '..');
const epubPath = process.argv[2] || path.join(__dirname, '1984.epub');

// Load UMD jszip.min.js into a sandbox
const code = fs.readFileSync(path.join(root, 'vendor/jszip.min.js'), 'utf8');
const sandbox = {
  window: {},
  self: {},
  global: {},
  module: { exports: {} },
  exports: {},
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  setImmediate,
  clearImmediate,
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.global = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const JSZip = sandbox.JSZip || sandbox.module.exports || sandbox.exports;
if (!JSZip) throw new Error('JSZip failed to load from vendor');

function decodeXmlEntities(s) {
  return String(s)
    .replace(/&nbsp;/gi, ' ')
    .replace(/&#160;/g, ' ')
    .replace(/&#xa0;/gi, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)));
}

function htmlToText(html) {
  let s = String(html);
  s = s.replace(/<script[\s\S]*?<\/script>/gi, ' ');
  s = s.replace(/<style[\s\S]*?<\/style>/gi, ' ');
  s = s.replace(/<(br|BR)\s*\/?>/g, '\n');
  s = s.replace(/<\/(p|div|h[1-6]|li|tr|blockquote|section|article|header|footer)>/gi, '\n');
  s = s.replace(/<[^>]+>/g, ' ');
  s = decodeXmlEntities(s);
  s = s.replace(/\u00a0/g, ' ');
  s = s.replace(/[ \t\f\v]+/g, ' ');
  s = s.replace(/\n[ \t]+/g, '\n');
  s = s.replace(/[ \t]+\n/g, '\n');
  s = s.replace(/\n{3,}/g, '\n\n');
  return s.trim();
}

function resolvePath(baseDir, href) {
  const clean = href.split('#')[0].split('?')[0];
  const parts = (baseDir ? baseDir + '/' : '').split('/').filter(Boolean);
  for (const seg of clean.split('/')) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') parts.pop();
    else parts.push(seg);
  }
  return parts.join('/');
}

async function parseEpub(buf) {
  const zip = await JSZip.loadAsync(buf);
  if (zip.file('META-INF/encryption.xml')) {
    throw new Error('DRM: ce livre EPUB est chiffré (DRM). Impossible de l’ouvrir ici.');
  }
  const container = await zip.file('META-INF/container.xml')?.async('string');
  if (!container) throw new Error('EPUB invalide : META-INF/container.xml manquant.');
  const m = container.match(/full-path\s*=\s*"([^"]+)"/i);
  if (!m) throw new Error('EPUB invalide : chemin OPF introuvable.');
  const opfPath = m[1];
  const opfDir = opfPath.includes('/') ? opfPath.replace(/\/[^/]+$/, '') : '';
  const opf = await zip.file(opfPath)?.async('string');
  if (!opf) throw new Error('EPUB invalide : fichier OPF manquant.');

  const titleMatch = opf.match(/<dc:title[^>]*>([^<]+)<\/dc:title>/i);
  const creatorMatch = opf.match(/<dc:creator[^>]*>([^<]+)<\/dc:creator>/i);
  const title = titleMatch ? decodeXmlEntities(titleMatch[1]).trim() : '';
  const creator = creatorMatch ? decodeXmlEntities(creatorMatch[1]).trim() : '';

  const manifest = new Map();
  const itemRe = /<item\b([^>]*)\/?>/gi;
  let im;
  while ((im = itemRe.exec(opf))) {
    const attrs = im[1];
    const id = (attrs.match(/\bid\s*=\s*"([^"]+)"/i) || [])[1];
    const href = (attrs.match(/\bhref\s*=\s*"([^"]+)"/i) || [])[1];
    const media = (attrs.match(/\bmedia-type\s*=\s*"([^"]+)"/i) || [])[1] || '';
    if (id && href) manifest.set(id, { href, media });
  }

  const spineIds = [];
  const spineRe = /<itemref\b([^>]*)\/?>/gi;
  let sm;
  while ((sm = spineRe.exec(opf))) {
    const idref = (sm[1].match(/\bidref\s*=\s*"([^"]+)"/i) || [])[1];
    if (idref) spineIds.push(idref);
  }
  if (!spineIds.length) throw new Error('EPUB invalide : spine vide.');

  const chunks = [];
  for (const id of spineIds) {
    const item = manifest.get(id);
    if (!item) continue;
    if (!/html|xml|xhtml/i.test(item.media) && !/\.x?html?$/i.test(item.href)) continue;
    const full = resolvePath(opfDir, item.href);
    const file = zip.file(full) || zip.file(decodeURIComponent(full));
    if (!file) continue;
    const html = await file.async('string');
    if (/encryption:EncryptedData|adept:encrypted/i.test(html) && /CipherValue/i.test(html)) {
      throw new Error('DRM: contenu chiffré détecté dans le livre.');
    }
    const text = htmlToText(html);
    if (text) chunks.push(text);
  }
  const fullText = chunks.join('\n\n').replace(/\n{3,}/g, '\n\n').trim();
  if (!fullText) throw new Error('Aucun texte extractible dans cet EPUB.');
  return { title, creator, fullText, chapters: chunks.length, words: fullText.split(/\s+/).filter(Boolean).length };
}

const buf = fs.readFileSync(epubPath);
const result = await parseEpub(buf);
const novel = (result.fullText.match(/C.?était une belle et froide journée d.?avril[^.]{0,60}/) || [null])[0];
const out = {
  title: result.title,
  creator: result.creator,
  chapters: result.chapters,
  words: result.words,
  drm: false,
  novelSnippet: novel,
  ok: !!(result.title === '1984' && novel),
};
console.log(JSON.stringify(out, null, 2));
if (!out.ok) process.exit(1);
