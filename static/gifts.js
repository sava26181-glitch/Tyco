/* NFT-модели: векторные рисунки подарков. gsvg(вид, модель, фон, узор) возвращает SVG-строку. */
const GIFT_BASE = {
  box:    { a: "#c8955a", b: "#e6b880", c: "#94643a", d: "#ead27a" },
  rose:   { a: "#d33a4c", b: "#f07282", c: "#3f8a4a", d: "#2c6236" },
  bike:   { a: "#3b6fd6", b: "#86abf2", c: "#26262c", d: "#cfcfd4" },
  coffee: { a: "#f1f0ec", b: "#d6d3cc", c: "#b9b5ad", d: "#6b3f22" },
  frog:   { a: "#5fbf4a", b: "#cfe9a6", c: "#2f6a2a", d: "#151515" },
  key:    { a: "#e3b54a", b: "#fbe39a", c: "#a77f2a", d: "#8a6a20" },
  rocket: { a: "#e04a3a", b: "#f1f1f1", c: "#9b9ba6", d: "#5fb8f0" },
  crown:  { a: "#e3b54a", b: "#fbe39a", c: "#a77f2a", d: "#d33a4c" },
};
const GIFT_MODELS = {
  "Хром":       { a: "#b6bcc6", b: "#f2f4f7", c: "#78808c", d: "#dfe3e8" },
  "Неон":       { a: "#1d1236", b: "#ff4fd8", c: "#2b1a52", d: "#4fe3ff", ink: "#ff4fd8", glow: "#ff4fd8" },
  "Пиксель":    { a: "#7a5cff", b: "#bba9ff", c: "#3a2a7a", d: "#ffd34f", pixel: 1 },
  "Лава":       { a: "#e8501f", b: "#ffb03a", c: "#3a1410", d: "#ffe06a", glow: "#ff6a2a" },
  "Голограмма": { a: "holo", b: "#ffffff", c: "#7a8aff", d: "#ff7ad9" },
  "Алмаз":      { a: "#9fe7ff", b: "#ffffff", c: "#4aa8d6", d: "#d6f6ff", glow: "#bff0ff" },
};
const GIFT_BACK = { "Ночь": ["#2a2d52", "#121327"], "Закат": ["#c4566e", "#3a1630"], "Океан": ["#2f86b8", "#0f2a44"], "Лес": ["#3f8a5a", "#11281c"], "Золото": ["#c79a2a", "#3a2a08"], "Космос": ["#6a3ac4", "#120a2a"] };
const GIFT_PATTERN = {
  "Звёзды": "M5 0l1.5 3.5L10 4l-2.7 2.3L8 10 5 8 2 10l.7-3.7L0 4l3.5-.5z",
  "Сердца": "M5 9C1 6 0 4 1 2.5 2 1 4 1 5 3c1-2 3-2 4-.5 1 1.5 0 3.5-4 6.5z",
  "Молнии": "M6 0L1 6h3l-1 4 5-6H5z",
  "Короны": "M0 8l1-6 2.5 3L5 1l1.5 4L9 2l1 6z",
  "Алмазы": "M2 0h6l2 3-5 7-5-7z",
};
let GIFT_UID = 0;
function giftFigure(kind, p) {
  const A = p.a === "holo" ? `url(#h${GIFT_UID})` : p.a, S = p.ink || "#16131c", W = 2.6;
  const st = `stroke="${S}" stroke-width="${W}" stroke-linejoin="round" stroke-linecap="round"`;
  switch (kind) {
    case "box": return `<path d="M50 18 82 32 50 46 18 32z" fill="${p.b}" ${st}/><path d="M18 32v36l32 15V46z" fill="${A}" ${st}/><path d="M82 32v36L50 83V46z" fill="${p.c}" ${st}/><path d="M34 25l32 14v14l-6 3V42L28 28z" fill="${p.d}" ${st}/>`;
    case "rose": return `<path d="M50 52v34" stroke="${p.c}" stroke-width="5" stroke-linecap="round"/><path d="M50 72c-10-8-20-6-24 0 8 4 16 5 24 0z" fill="${p.c}" ${st}/><path d="M51 66c8-8 17-8 22-3-7 5-14 6-22 3z" fill="${p.d}" ${st}/><path d="M30 34c0 14 9 22 20 22s20-8 20-22c-6 4-10 4-12 0-2-6-14-6-16 0-2 4-6 4-12 0z" fill="${A}" ${st}/><path d="M40 30c2-10 18-10 20 0-4 6-16 6-20 0z" fill="${p.b}" ${st}/><path d="M44 30c2 3 10 3 12 0" fill="none" ${st}/>`;
    case "bike": return `<circle cx="27" cy="64" r="15" fill="none" stroke="${p.c}" stroke-width="5"/><circle cx="73" cy="64" r="15" fill="none" stroke="${p.c}" stroke-width="5"/><circle cx="27" cy="64" r="3" fill="${p.d}"/><circle cx="73" cy="64" r="3" fill="${p.d}"/><path d="M27 64l14-24h26l6 24M41 40l12 24h20M53 64l14-24" fill="none" stroke="${A}" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/><path d="M36 34h12M64 32l6-6h7" fill="none" stroke="${S}" stroke-width="4" stroke-linecap="round"/>`;
    case "coffee": return `<path d="M30 20c-4 6 4 8 0 14M44 18c-4 6 4 8 0 14M58 20c-4 6 4 8 0 14" fill="none" stroke="${p.c}" stroke-width="3" stroke-linecap="round"/><ellipse cx="48" cy="78" rx="32" ry="7" fill="${p.c}" ${st}/><path d="M24 40h48l-5 30c-1 6-6 8-11 8H40c-5 0-10-2-11-8z" fill="${A}" ${st}/><path d="M71 46c11 0 11 16-2 16" fill="none" ${st}/><ellipse cx="48" cy="40" rx="24" ry="5" fill="${p.d}" ${st}/>`;
    case "frog": return `<ellipse cx="50" cy="60" rx="32" ry="22" fill="${A}" ${st}/><ellipse cx="50" cy="66" rx="18" ry="11" fill="${p.b}"/><circle cx="34" cy="38" r="11" fill="${A}" ${st}/><circle cx="66" cy="38" r="11" fill="${A}" ${st}/><circle cx="34" cy="38" r="6" fill="#fff"/><circle cx="66" cy="38" r="6" fill="#fff"/><circle cx="35" cy="38" r="3" fill="${p.d}"/><circle cx="67" cy="38" r="3" fill="${p.d}"/><path d="M34 56c10 7 22 7 32 0" fill="none" stroke="${p.c}" stroke-width="3.5" stroke-linecap="round"/>`;
    case "key": return `<circle cx="34" cy="38" r="17" fill="${A}" ${st}/><circle cx="34" cy="38" r="7" fill="${p.c}" ${st}/><path d="M46 50l28 28M62 66l7-7M70 74l7-7" fill="none" stroke="${S}" stroke-width="12" stroke-linecap="round"/><path d="M46 50l28 28M62 66l7-7M70 74l7-7" fill="none" stroke="${A}" stroke-width="7" stroke-linecap="round"/><path d="M24 31c3-5 8-7 12-6" fill="none" stroke="${p.b}" stroke-width="3" stroke-linecap="round"/>`;
    case "rocket": return `<path d="M42 72c-4 8-2 14 8 18 10-4 12-10 8-18z" fill="#ffb03a" ${st}/><path d="M36 60l-12 14 14-2zM64 60l12 14-14-2z" fill="${A}" ${st}/><path d="M50 12c14 12 18 30 14 56H36c-4-26 0-44 14-56z" fill="${p.b}" ${st}/><path d="M50 12c7 6 11 13 13 22H37c2-9 6-16 13-22z" fill="${A}" ${st}/><circle cx="50" cy="46" r="7" fill="${p.d}" ${st}/>`;
    case "crown": return `<path d="M18 70l-4-38 20 18 16-26 16 26 20-18-4 38z" fill="${A}" ${st}/><rect x="18" y="68" width="64" height="12" rx="3" fill="${p.c}" ${st}/><circle cx="50" cy="56" r="6" fill="${p.d}" ${st}/><circle cx="31" cy="60" r="4" fill="${p.d}" ${st}/><circle cx="69" cy="60" r="4" fill="${p.d}" ${st}/><path d="M26 40l6 6M50 30v8" stroke="${p.b}" stroke-width="3" stroke-linecap="round"/>`;
  }
  return "";
}
function gsvg(kind, model, backdrop, pattern) {
  const id = ++GIFT_UID, p = Object.assign({}, GIFT_BASE[kind] || GIFT_BASE.box, GIFT_MODELS[model] || {});
  const bg = GIFT_BACK[backdrop] || ["#232329", "#18181c"], pt = GIFT_PATTERN[pattern];
  let defs = `<radialGradient id="b${id}" cx="50%" cy="42%" r="70%"><stop offset="0" stop-color="${bg[0]}"/><stop offset="1" stop-color="${bg[1]}"/></radialGradient>`;
  if (p.a === "holo") defs += `<linearGradient id="h${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ff7ad9"/><stop offset=".35" stop-color="#7ad7ff"/><stop offset=".65" stop-color="#a6ff9a"/><stop offset="1" stop-color="#ffe27a"/></linearGradient>`;
  if (pt) defs += `<pattern id="p${id}" width="22" height="22" patternUnits="userSpaceOnUse" patternTransform="rotate(-18)"><path d="${pt}" fill="#fff" transform="translate(6 6)"/></pattern>`;
  if (p.glow) defs += `<filter id="g${id}" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="0" stdDeviation="3.2" flood-color="${p.glow}" flood-opacity=".9"/></filter>`;
  if (p.pixel) defs += `<pattern id="x${id}" width="5" height="5" patternUnits="userSpaceOnUse"><path d="M0 0H5V5" fill="none" stroke="#000" stroke-opacity=".35" stroke-width="1"/></pattern><clipPath id="c${id}">${giftFigure(kind, Object.assign({}, p, { ink: "#000" }))}</clipPath>`;
  const fig = giftFigure(kind, p);
  return `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" ${p.pixel ? 'shape-rendering="crispEdges"' : ""}><defs>${defs}</defs><rect width="100" height="100" fill="url(#b${id})"/>${pt ? `<rect width="100" height="100" fill="url(#p${id})" opacity=".13"/>` : ""}<g transform="translate(10 8) scale(.8)" ${p.glow ? `filter="url(#g${id})"` : ""}>${fig}${p.pixel ? `<rect width="100" height="100" fill="url(#x${id})" clip-path="url(#c${id})"/>` : ""}</g></svg>`;
}
