const C = { r: '\x1b[0m', dim: '\x1b[2m', b: '\x1b[1m', g: '\x1b[32m', y: '\x1b[33m', red: '\x1b[31m', c: '\x1b[36m' };

export const log = {
  step: (n, msg) => console.log(`\n${C.b}${C.c}[${n}]${C.r} ${C.b}${msg}${C.r}`),
  info: (msg) => console.log(`    ${msg}`),
  dim: (msg) => console.log(`    ${C.dim}${msg}${C.r}`),
  ok: (msg) => console.log(`    ${C.g}✓${C.r} ${msg}`),
  warn: (msg) => console.log(`    ${C.y}!${C.r} ${msg}`),
  err: (msg) => console.log(`    ${C.red}✗${C.r} ${msg}`),
  skip: (msg) => console.log(`    ${C.dim}- skip: ${msg}${C.r}`),
};
