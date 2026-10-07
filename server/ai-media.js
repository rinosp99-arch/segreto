// Media intake for the AI interface: download from a public URL (or base64) into the same uploads folder the admin
// upload uses. Guards: only http(s), no private/loopback/link-local/metadata addresses (checked on the address the
// socket really connects to, also after every redirect), size limit, file type decided by the first bytes.
const fs = require('fs');
const net = require('net');
const dns = require('dns');
const path = require('path');
const http = require('http');
const https = require('https');
const R = require('./rules');

const blocked = new net.BlockList();
for (const [addr, bits] of [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8], ['169.254.0.0', 16], ['172.16.0.0', 12],
  ['192.0.0.0', 24], ['192.0.2.0', 24], ['192.168.0.0', 16], ['198.18.0.0', 15], ['198.51.100.0', 24], ['203.0.113.0', 24],
  ['224.0.0.0', 4], ['240.0.0.0', 4],
]) blocked.addSubnet(addr, bits, 'ipv4');
for (const [addr, bits] of [
  ['::', 127], ['64:ff9b::', 96], ['100::', 64], ['2001:db8::', 32], ['fc00::', 7], ['fe80::', 10], ['ff00::', 8],
]) blocked.addSubnet(addr, bits, 'ipv6');
// IPv4-mapped IPv6 (::ffff:a.b.c.d) lives in its own list: inside `blocked` it would match every IPv4 address
const mapped = new net.BlockList();
mapped.addSubnet('::ffff:0:0', 96, 'ipv6');

const isBlockedAddress = (address) => {
  const family = net.isIP(address);
  if (family === 4) return blocked.check(address, 'ipv4');
  return family !== 6 || mapped.check(address, 'ipv6') || blocked.check(address, 'ipv6');
};

class MediaError extends Error {}
const bad = (message) => new MediaError(message);

// Syntax + literal checks only (used by the dry run too): no network access.
function checkUrl(raw) {
  let u;
  try { u = new URL(String(raw)); } catch { throw bad('URL non valido'); }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') throw bad('Sono consentiti solo URL http(s)');
  if (u.username || u.password) throw bad('URL con credenziali non consentito');
  const host = u.hostname.replace(/^\[|\]$/g, '');
  if (!host || host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || host.endsWith('.internal')) throw bad('Host non consentito');
  if (net.isIP(host) && isBlockedAddress(host)) throw bad('Indirizzo privato o riservato non consentito');
  return u;
}

// DNS lookup that refuses private targets: the socket connects to exactly the address that was checked here.
function safeLookup(hostname, options, cb) {
  dns.lookup(hostname, { ...options, all: true }, (err, addresses) => {
    if (err) return cb(err);
    const list = Array.isArray(addresses) ? addresses : [{ address: addresses, family: net.isIP(addresses) }];
    if (!list.length || list.some((a) => isBlockedAddress(a.address))) return cb(Object.assign(new Error('Indirizzo privato o riservato non consentito'), { code: 'EBLOCKED' }));
    return options.all ? cb(null, list) : cb(null, list[0].address, list[0].family);
  });
}

function request(u, timeoutMs) {
  return new Promise((resolve, reject) => {
    const lib = u.protocol === 'https:' ? https : http;
    const req = lib.get(u, { lookup: safeLookup, timeout: timeoutMs, headers: { 'User-Agent': 'LatoSegreto-Media/1.0', Accept: 'image/*,video/*' } }, resolve);
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

// ---------------- file type by magic bytes ----------------
function sniff(buf) {
  const ascii = (a, b) => buf.subarray(a, b).toString('latin1');
  if (buf.length < 12) return null;
  if (buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'image/jpeg';
  if (buf.readUInt32BE(0) === 0x89504e47 && buf.readUInt32BE(4) === 0x0d0a1a0a) return 'image/png';
  if (ascii(0, 4) === 'GIF8') return 'image/gif';
  if (ascii(0, 4) === 'RIFF' && ascii(8, 12) === 'WEBP') return 'image/webp';
  if (buf.readUInt32BE(0) === 0x1a45dfa3) return 'video/webm';
  if (ascii(4, 8) === 'ftyp') {
    const brand = ascii(8, 12);
    if (brand === 'avif' || brand === 'avis') return 'image/avif';
    if (brand === 'qt  ') return 'video/quicktime';
    if (/^(isom|iso[2-9]|mp4[12]|avc1|M4V |MSNV|dash|mmp4|3gp[4-6])$/.test(brand)) return 'video/mp4';
  }
  return null;
}

const tipoOf = (mime) => (mime.startsWith('video/') ? 'video' : 'image');

// Moves a checked temp file to its final random name (same naming as the admin upload).
function finish(tmp, head, size) {
  const mime = sniff(head);
  if (!mime || !R.EXT[mime]) {
    fs.rmSync(tmp, { force: true });
    throw bad(`Tipo file non consentito: sono ammessi ${Object.keys(R.EXT).join(', ')}`);
  }
  const filename = R.uploadName(mime);
  fs.renameSync(tmp, path.join(R.UPLOAD_DIR, filename));
  return { url: R.uploadUrl(filename), filename, tipo: tipoOf(mime), mime, size };
}

const tmpPath = () => path.join(R.UPLOAD_DIR, `.ai-${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2)}.part`);

async function fromUrl(raw) {
  fs.mkdirSync(R.UPLOAD_DIR, { recursive: true });
  let u = checkUrl(raw);
  let res;
  for (let hop = 0; ; hop++) {
    try {
      res = await request(u, 20000);
    } catch (e) {
      throw bad(e.code === 'EBLOCKED' ? e.message : 'Download non riuscito: host non raggiungibile');
    }
    if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
      res.resume();
      if (hop >= 3) throw bad('Troppi reindirizzamenti');
      u = checkUrl(new URL(res.headers.location, u).toString()); // every hop is checked again
      continue;
    }
    break;
  }
  if (res.statusCode !== 200) {
    res.resume();
    throw bad(`Download non riuscito: HTTP ${res.statusCode}`);
  }
  if (Number(res.headers['content-length']) > R.MAX_UPLOAD_BYTES) {
    res.destroy();
    throw bad('File troppo grande (max 200MB)');
  }
  const tmp = tmpPath();
  const out = fs.createWriteStream(tmp);
  let size = 0;
  let head = Buffer.alloc(0);
  try {
    await new Promise((resolve, reject) => {
      res.on('data', (chunk) => {
        size += chunk.length;
        if (head.length < 32) head = Buffer.concat([head, chunk]).subarray(0, 32);
        if (size > R.MAX_UPLOAD_BYTES) res.destroy(bad('File troppo grande (max 200MB)'));
      });
      res.on('error', reject);
      out.on('error', reject);
      out.on('finish', resolve);
      res.pipe(out);
    });
  } catch (e) {
    out.destroy();
    fs.rmSync(tmp, { force: true });
    throw e instanceof MediaError ? e : bad('Download interrotto');
  }
  return finish(tmp, head, size);
}

function fromBase64(raw) {
  fs.mkdirSync(R.UPLOAD_DIR, { recursive: true });
  const text = String(raw).replace(/^data:[^,]*,/, '').replace(/\s+/g, '');
  if (!text || !/^[A-Za-z0-9+/_-]+=*$/.test(text)) throw bad('base64_data non è base64 valido');
  const buf = Buffer.from(text, 'base64');
  if (buf.length > R.MAX_UPLOAD_BYTES) throw bad('File troppo grande (max 200MB)');
  const tmp = tmpPath();
  fs.writeFileSync(tmp, buf);
  return finish(tmp, buf.subarray(0, 32), buf.length);
}

module.exports = { MediaError, checkUrl, fromUrl, fromBase64, sniff, isBlockedAddress, safeLookup };
