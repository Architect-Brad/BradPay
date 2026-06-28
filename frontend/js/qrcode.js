// Minimal QR Code generator for BradPay
// Renders a QR code to a canvas element using a compact bit matrix

const QR_RS_BLOCK = [
  [1, 26, 19], [1, 44, 34], [1, 70, 55], [1, 100, 80],
  [1, 134, 108], [2, 86, 68], [2, 98, 78], [2, 121, 97],
  [2, 146, 116], [2, 86, 68], [4, 101, 81], [2, 116, 92],
  [2, 133, 107], [3, 145, 115], [5, 109, 87], [5, 121, 98],
  [5, 131, 107], [4, 151, 120], [5, 147, 117], [6, 132, 106],
  [6, 137, 111], [7, 134, 110], [8, 139, 114], [9, 144, 119],
  [9, 151, 125], [10, 141, 118], [11, 145, 123], [13, 153, 130],
  [13, 156, 133], [15, 126, 108], [17, 128, 110], [17, 131, 113],
  [17, 131, 113], [18, 129, 111], [20, 131, 113], [21, 128, 110],
  [21, 129, 111], [22, 130, 112], [24, 131, 113], [25, 128, 110],
  [25, 129, 111], [26, 129, 111], [27, 130, 112], [29, 131, 113],
  [29, 131, 113], [31, 131, 113], [31, 131, 113], [31, 131, 113],
  [31, 131, 113], [31, 131, 113], [31, 131, 113], [31, 131, 113],
];

const GF256 = {
  exp: new Array(256),
  log: new Array(256),
};

(function () {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    GF256.exp[i] = x;
    GF256.log[x] = i;
    x = (x * 2) ^ (x >= 128 ? 0x11d : 0);
  }
  GF256.exp[255] = 1;
})();

function polyMul(a, b) {
  const res = new Array(a.length + b.length - 1).fill(0);
  for (let i = 0; i < a.length; i++)
    for (let j = 0; j < b.length; j++)
      res[i + j] ^= GF256.exp[(GF256.log[a[i]] + GF256.log[b[j]]) % 255];
  return res;
}

function polyRest(numer, denom) {
  const res = [...numer];
  for (let i = 0; i < numer.length - denom.length + 1; i++) {
    if (res[i] !== 0) {
      for (let j = 1; j < denom.length; j++) {
        res[i + j] ^= GF256.exp[(GF256.log[res[i]] + GF256.log[denom[j]]) % 255];
      }
    }
  }
  return res.slice(numer.length - denom.length + 1);
}

function genECWords(data, eccCount) {
  const gen = [1];
  for (let i = 0; i < eccCount; i++) {
    gen.push(1);
    for (let j = gen.length - 2; j > 0; j--) {
      gen[j] = gen[j - 1] ^ GF256.exp[(GF256.log[gen[j]] + i) % 255];
    }
    gen[0] = GF256.exp[(GF256.log[gen[0]] + i) % 255];
  }
  const padded = [...data, ...new Array(eccCount).fill(0)];
  const rem = polyRest(padded, gen);
  return data.concat(rem);
}

function toBytes(str) {
  const bytes = [];
  for (let i = 0; i < str.length; i++) {
    const code = str.charCodeAt(i);
    if (code < 128) bytes.push(code);
    else if (code < 2048) bytes.push(192 | (code >> 6), 128 | (code & 63));
    else bytes.push(224 | (code >> 12), 128 | ((code >> 6) & 63), 128 | (code & 63));
  }
  return bytes;
}

const PATTERN_TABLE = [
  [1, 0, 3, 2], [0, 1, 3, 2], [1, 1, 3, 2], [0, 0, 3, 2],
  [1, 0, 2, 3], [0, 1, 2, 3], [1, 1, 2, 3], [0, 1, 3, 2],
];

export function generateQR(text, size = 280) {
  const bytes = toBytes(text);
  const lenBits = bytes.length;
  const ver = lenBits < 26 ? 1 : lenBits < 48 ? 2 : lenBits < 70 ? 3 : lenBits < 100 ? 4 : lenBits < 134 ? 5 : lenBits < 172 ? 6 : lenBits < 196 ? 7 : 8;
  const v = ver;
  const modCount = v * 4 + 17;
  const matrix = Array.from({ length: modCount }, () => new Array(modCount).fill(0));

  // Finder patterns
  for (const [r, c] of [[0, 0], [0, modCount - 7], [modCount - 7, 0]]) {
    for (let i = -1; i < 8; i++) {
      for (let j = -1; j < 8; j++) {
        const y = r + i, x = c + j;
        if (y < 0 || x < 0 || y >= modCount || x >= modCount) continue;
        const outer = i < 0 || i > 6 || j < 0 || j > 6;
        const inner = i >= 1 && i <= 5 && j >= 1 && j <= 5;
        const center = i === 3 && j === 3;
        const sep = (i === -1 || i === 7 || j === -1 || j === 7) && !(i === -1 && j === -1) && !(i === 7 && j === 7);
        if (sep) continue;
        if (outer || inner || center) matrix[y][x] = 1;
      }
    }
  }

  // Timing patterns
  for (let i = 8; i < modCount - 8; i++) {
    matrix[6][i] = i % 2 === 0 ? 1 : 0;
    matrix[i][6] = i % 2 === 0 ? 1 : 0;
  }

  // Format info area placeholder
  for (let i = 0; i < 9; i++) {
    if (i !== 6) { matrix[8][i] = i < 6 ? 1 : 0; matrix[i][8] = i < 6 ? 1 : 0; }
  }
  for (let i = modCount - 8; i < modCount; i++) matrix[8][i] = 1;
  for (let i = modCount - 7; i < modCount - 1; i++) matrix[i][8] = 1;
  matrix[modCount - 8][8] = 1;

  // Align pattern for v2+
  if (v >= 2) {
    const pos = v >= 7 ? 22 : v >= 2 ? 16 + v * 2 : 0;
    const positions = [];
    for (let p = pos; p < modCount - 8; p += pos + 1) positions.push(p);
    if (!positions.includes(6)) positions.unshift(6);
    for (let i = 0; i < positions.length; i++) {
      for (let j = 0; j < positions.length; j++) {
        const y = positions[i], x = positions[j];
        if ((y < 9 && x < 9) || (y < 9 && x > modCount - 9) || (y > modCount - 9 && x < 9)) continue;
        for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
          const val = Math.abs(dy) === 2 || Math.abs(dx) === 2 || (dy === 0 && dx === 0) ? 1 : 0;
          matrix[y + dy][x + dx] = val;
        }
      }
    }
  }

  // Data encoding (byte mode)
  const dataBits = [];
  const mode = 4; // byte mode
  const bitsCount = v < 10 ? 8 : 16;
  const dataBytes = [mode, ...(v < 10 ? [lenBits] : [lenBits >> 8, lenBits & 0xff]), ...bytes];

  const eccCount = (v - 1) * 4 + (v + 6) * 2;
  const totalData = modCount * modCount;
  const maxData = ver < 9 ? Math.floor(totalData / 8) - eccCount : 0;

  const dataWithEC = genECWords(dataBytes, eccCount > 20 ? eccCount : 18);
  const bits = [];
  for (const b of dataWithEC) {
    for (let i = 7; i >= 0; i--) bits.push((b >> i) & 1);
  }

  // Place bits in matrix
  let bitIdx = 0;
  for (let col = modCount - 1; col >= 1; col -= 2) {
    if (col === 6) col = 5;
    for (let row = 0; row < modCount; row++) {
      for (const c of [col, col - 1]) {
        const r = col % 4 < 2 ? row : modCount - 1 - row;
        if (matrix[r] === undefined || matrix[r][c] === undefined) continue;
        if (matrix[r][c] !== 0) continue;
        if (bitIdx < bits.length) {
          matrix[r][c] = bits[bitIdx++];
        }
      }
    }
  }

  // Apply mask pattern
  let bestScore = Infinity;
  let bestMatrix = null;
  for (let mask = 0; mask < 8; mask++) {
    const m = matrix.map(r => [...r]);
    const [r1, r2, r3, r4] = PATTERN_TABLE[mask];
    for (let y = 0; y < modCount; y++) {
      for (let x = 0; x < modCount; x++) {
        if (m[y][x] !== 0 && m[y][x] !== 1) continue;
        if ((y >= 0 && y <= 8 && x >= 0 && x <= 8) ||
            (y >= 0 && y <= 8 && x >= modCount - 8 && x < modCount) ||
            (y >= modCount - 8 && y < modCount && x >= 0 && x <= 8)) continue;
        const cond = (r1 * y + r2 * x + r3 * (y * x) + r4) % 2 === 0;
        if (cond) m[y][x] = m[y][x] === 0 ? 1 : 0;
      }
    }
    // Score
    let score = 0;
    for (let y = 0; y < modCount; y++) {
      let run = 1;
      for (let x = 1; x < modCount; x++) {
        if (m[y][x] === m[y][x - 1]) run++;
        else { if (run >= 5) score += run + 3; run = 1; }
      }
      if (run >= 5) score += run + 3;
    }
    for (let x = 0; x < modCount; x++) {
      let run = 1;
      for (let y = 1; y < modCount; y++) {
        if (m[y][x] === m[y - 1][x]) run++;
        else { if (run >= 5) score += run + 3; run = 1; }
      }
      if (run >= 5) score += run + 3;
    }
    if (score < bestScore) {
      bestScore = score;
      bestMatrix = m;
    }
  }

  matrix.length = 0;
  if (bestMatrix) matrix.push(...bestMatrix);

  // Render
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  const cell = size / modCount;
  ctx.fillStyle = "white";
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = "#0f172a";
  for (let y = 0; y < modCount; y++) {
    for (let x = 0; x < modCount; x++) {
      if (bestMatrix[y][x] === 1) {
        ctx.fillRect(x * cell, y * cell, Math.ceil(cell), Math.ceil(cell));
      }
    }
  }
  return canvas;
}
