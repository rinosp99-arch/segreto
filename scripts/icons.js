// Builds the site icons (browser tab, Google result, home screen) into frontend/public.
// Run once after changing the drawing below:  node scripts/icons.js   (needs "npm install" in server/)
const fs = require('fs');
const path = require('path');
const sharp = require('../server/node_modules/sharp');

const OUT = path.join(__dirname, '..', 'frontend', 'public');

// "LS" like the wordmark: LATO light, SEGRETO gold, on the dark page colour. radius 0 = full square (home screen icons).
const svg = (radius) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="${radius}" fill="#0e0e11"/>
  <g font-family="Georgia, 'Times New Roman', serif" font-size="300" text-anchor="middle">
    <text x="164" y="356" fill="#e9e3d8">L</text>
    <text x="346" y="356" fill="#d7b56d">S</text>
  </g>
  <rect x="116" y="404" width="280" height="6" fill="#d7b56d" opacity="0.7"/>
</svg>`;

const png = (size, radius) => sharp(Buffer.from(svg(radius)), { density: 300 }).resize(size, size).png().toBuffer();

// .ico = small header + PNG pictures (all current browsers read PNG inside .ico)
function ico(images) {
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach(({ size, data }, i) => {
    const at = 6 + 16 * i;
    header.writeUInt8(size, at);
    header.writeUInt8(size, at + 1);
    header.writeUInt16LE(1, at + 4);
    header.writeUInt16LE(32, at + 6);
    header.writeUInt32LE(data.length, at + 8);
    header.writeUInt32LE(offset, at + 12);
    offset += data.length;
  });
  return Buffer.concat([header, ...images.map((i) => i.data)]);
}

(async () => {
  fs.writeFileSync(path.join(OUT, 'icon-192.png'), await png(192, 96));
  fs.writeFileSync(path.join(OUT, 'icon-512.png'), await png(512, 96));
  fs.writeFileSync(path.join(OUT, 'apple-touch-icon.png'), await png(180, 0));
  const sizes = [16, 32, 48];
  const data = await Promise.all(sizes.map((s) => png(s, 96)));
  fs.writeFileSync(path.join(OUT, 'favicon.ico'), ico(sizes.map((size, i) => ({ size, data: data[i] }))));
  console.log('Icons geschrieben nach', OUT);
})();
