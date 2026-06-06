#!/usr/bin/env node
// Generates app icons as PNGs using only Node's built-in zlib (no deps).
// Produces a dark rounded-square icon with a glowing "spark" mark.

const zlib = require('zlib');
const fs = require('fs');
const path = require('path');

// --- minimal PNG encoder ---------------------------------------------------
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, 'ascii');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([len, typeBuf, data, crc]);
}

function encodePNG(width, height, rgba) {
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;   // bit depth
  ihdr[9] = 6;   // color type RGBA
  ihdr[10] = 0;  // compression
  ihdr[11] = 0;  // filter
  ihdr[12] = 0;  // interlace

  // add a filter byte (0) at the start of every scanline
  const stride = width * 4;
  const raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (stride + 1)] = 0;
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, y * stride + stride);
  }
  const idat = zlib.deflateSync(raw, { level: 9 });

  return Buffer.concat([
    sig,
    chunk('IHDR', ihdr),
    chunk('IDAT', idat),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// --- drawing ---------------------------------------------------------------
function lerp(a, b, t) { return a + (b - a) * t; }

function drawIcon(size) {
  const rgba = Buffer.alloc(size * size * 4);
  const r = size * 0.22; // corner radius
  const cx = size / 2, cy = size / 2;

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4;

      // rounded-square mask
      const dx = Math.max(r - x, x - (size - r), 0);
      const dy = Math.max(r - y, y - (size - r), 0);
      const inside = Math.hypot(dx, dy) <= r;

      // diagonal gradient background (indigo -> violet)
      const t = (x + y) / (2 * size);
      let R = lerp(34, 99, t);
      let G = lerp(33, 63, t);
      let B = lerp(70, 235, t);

      // soft central radial glow
      const d = Math.hypot(x - cx, y - cy) / (size * 0.5);
      const glow = Math.max(0, 1 - d * 1.6);
      R = lerp(R, 150, glow * 0.28);
      G = lerp(G, 160, glow * 0.28);
      B = lerp(B, 255, glow * 0.28);

      // four-point "spark" mark in the center
      const px = (x - cx) / (size * 0.34);
      const py = (y - cy) / (size * 0.34);
      const ax = Math.abs(px), ay = Math.abs(py);
      const star = Math.min(ax * 0.16 + ay, ax + ay * 0.16);
      if (star < 1.0) {
        const s = Math.pow(1 - star, 1.4);
        R = lerp(R, 255, s);
        G = lerp(G, 255, s);
        B = lerp(B, 255, s);
      }

      rgba[i] = Math.round(R);
      rgba[i + 1] = Math.round(G);
      rgba[i + 2] = Math.round(B);
      rgba[i + 3] = inside ? 255 : 0;
    }
  }
  return encodePNG(size, size, rgba);
}

const outDir = path.join(__dirname, '..', 'icons');
fs.mkdirSync(outDir, { recursive: true });

const targets = [
  ['icon-192.png', 192],
  ['icon-512.png', 512],
  ['apple-touch-icon.png', 180],
  ['favicon-32.png', 32],
];

for (const [name, size] of targets) {
  fs.writeFileSync(path.join(outDir, name), drawIcon(size));
  console.log('wrote', name, size + 'x' + size);
}
