// SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
// SPDX-License-Identifier: AGPL-3.0-only
// The Argus console. Every view draws itself for a moment of the shift (draw(t)), so the same page replays live and
// renders the demo's frames exactly (?capture=1: the page waits to be told the time, frame by frame).
"use strict";
const K = { BG: "#090C12", PANEL: "#111723", PANEL2: "#16203A", LINE: "#1E2738", INK: "#E9EDF4", MUTED: "#8B95A8",
  CYAN: "#3CCBFF", AMBER: "#FFB21E", RED: "#FF4D5E", GREEN: "#3DDC97", VIOLET: "#A08BFF", GREY: "#5D6678" };
const Q = new URLSearchParams(location.search);
const CAPTURE = Q.get("capture") === "1";
const S = { t: Number(Q.get("t") || 0), playing: false, speed: 4, view: Q.get("view") || "site", hall: Q.get("hall") || "A",
  cam: Q.get("cam") || "", site: null, cache: {} };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const ease = u => { u = clamp(u); return u * u * (3 - 2 * u); };
const win = (t, s, d) => d > 0 ? ease((t - s) / d) : (t >= s ? 1 : 0);
const font = (size, weight = 400, mono = false) => `${weight} ${size}px ${mono ? '"JetBrains Mono"' : '"Inter"'}`;
const stamp = t => { const s = Math.round(8 * 3600 + t); return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map(v => String(v).padStart(2, "0")).join(":"); };
async function api(path) { if (!S.cache[path]) S.cache[path] = fetch(path).then(r => { if (!r.ok) throw new Error(path + ": " + r.status); return r.json(); }); return S.cache[path]; }
function img(src) { return new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = src; }); }

// -- tracks on the floor ---------------------------------------------------------------------------------------------
function at(tr, t) {                        // position at t, interpolated; null outside the track or across a gap over 1.5 s
  const T = tr.t; if (!T.length || t < T[0] || t > T[T.length - 1]) return null;
  let lo = 0, hi = T.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (T[m] < t) lo = m + 1; else hi = m; }
  if (T[lo] === t) return [tr.x[lo], tr.y[lo], lo];
  const a = lo - 1; if (a < 0 || T[lo] - T[a] > 1.5) return null;
  const u = (t - T[a]) / (T[lo] - T[a]);
  return [tr.x[a] + (tr.x[lo] - tr.x[a]) * u, tr.y[a] + (tr.y[lo] - tr.y[a]) * u, a];
}
const isVehicle = tr => tr.kind !== "person" && tr.kind !== "humanoid";
function movingAt(tr, i) { return !tr.parked && (tr.kind === "humanoid" || (tr.m && tr.m[i] === 1)); }
function scene(hall, t) {                    // who is where at t, and who is within the danger zone of a moving machine
  const people = [], machines = [];
  for (const tr of hall.tracks) {
    const p = at(tr, t); if (!p) continue;
    if (tr.kind === "person") people.push({ tr, x: p[0], y: p[1] });
    else machines.push({ tr, x: p[0], y: p[1], moving: movingAt(tr, p[2]) });
  }
  const near = [];
  for (const m of machines) if (m.moving) for (const p of people) { const d = Math.hypot(p.x - m.x, p.y - m.y); if (d < hall.near_m) near.push({ p, m, d }); }
  return { people, machines, near };
}
function mapper(hall, mapImg, box) {          // floor metres -> canvas pixels, the hall's busy extent fitted into box
  const [s, tx, ty, H] = hall.transform;
  const toMap = (x, y) => [(x + tx) * s, H - (y + ty) * s];
  const [x0, y0, x1, y1] = hall.extent, pad = 4;
  const a = toMap(x0 - pad, y1 + pad), b = toMap(x1 + pad, y0 - pad);
  const cw = b[0] - a[0], ch = b[1] - a[1];
  const k = Math.min(box.w / cw, box.h / ch);
  const ox = box.x + (box.w - cw * k) / 2 - a[0] * k, oy = box.y + (box.h - ch * k) / 2 - a[1] * k;
  return { k: k * s, px: (x, y) => { const m = toMap(x, y); return [ox + m[0] * k, oy + m[1] * k]; },
    draw(c, alpha = 0.85) { c.save(); c.beginPath(); c.rect(ox + a[0] * k, oy + a[1] * k, cw * k, ch * k); c.clip();
      c.globalAlpha = alpha; c.drawImage(mapImg, ox, oy, mapImg.width * k, mapImg.height * k); c.restore(); },
    rect: [ox + a[0] * k, oy + a[1] * k, cw * k, ch * k] };
}
function glow(c, x, y, r, col, a = 1) {
  c.save(); c.globalAlpha = 0.3 * a; c.fillStyle = col; c.shadowColor = col; c.shadowBlur = r * 3;
  c.beginPath(); c.arc(x, y, r * 1.6, 0, 7); c.fill(); c.restore();
  c.save(); c.globalAlpha = a; c.fillStyle = col; c.beginPath(); c.arc(x, y, r, 0, 7); c.fill(); c.restore();
}
function drawFloor(c, hall, M, t, opts = {}) {
  M.draw(c, opts.mapAlpha ?? 0.8);
  c.save(); c.beginPath(); c.rect(...M.rect); c.clip();
  const sc = scene(hall, t);
  if (opts.trails) for (const p of sc.people) {             // where each person walked in the last ten seconds
    const tr = p.tr; let prev = null;
    for (let dt = 10; dt >= 0; dt -= 0.5) { const q = at(tr, t - dt); if (!q) { prev = null; continue; }
      const [x, y] = M.px(q[0], q[1]);
      if (prev && Math.hypot(x - prev[0], y - prev[1]) > 2.5 * M.k) prev = null;   // a jump between cameras, not a walk
      if (prev) { c.strokeStyle = K.CYAN; c.globalAlpha = 0.28 * (1 - dt / 10); c.lineWidth = 2.2; c.beginPath(); c.moveTo(...prev); c.lineTo(x, y); c.stroke(); }
      prev = [x, y]; }
    c.globalAlpha = 1;
  }
  for (const m of sc.machines) {
    const [x, y] = M.px(m.x, m.y);
    if (m.moving) { c.fillStyle = "rgba(255,178,30,0.12)"; c.strokeStyle = "rgba(255,178,30,0.8)"; c.lineWidth = 1.5;
      c.beginPath(); c.arc(x, y, hall.near_m * M.k, 0, 7); c.fill(); c.stroke(); }
  }
  for (const n of sc.near) { const a = M.px(n.p.x, n.p.y), b = M.px(n.m.x, n.m.y);
    c.strokeStyle = K.RED; c.lineWidth = 2; c.beginPath(); c.moveTo(...a); c.lineTo(...b); c.stroke(); }
  for (const p of sc.people) { const [x, y] = M.px(p.x, p.y); const hot = sc.near.some(n => n.p === p);
    glow(c, x, y, opts.r ?? 4.5, hot ? K.RED : K.CYAN); }
  for (const m of sc.machines) { const [x, y] = M.px(m.x, m.y);
    if (m.tr.parked) { c.fillStyle = K.GREY; c.fillRect(x - 6, y - 6, 12, 12); }
    else glow(c, x, y, m.tr.kind === "humanoid" ? 6 : 7.5, m.tr.kind === "humanoid" ? K.VIOLET : K.AMBER);
    if (opts.labels) { c.font = font(13, 700); c.fillStyle = m.tr.parked ? K.MUTED : K.AMBER;
      c.fillText(m.tr.id.replace(/^[A-D]-/, "") + (m.tr.parked ? " · parked" : m.moving ? " · moving" : " · stopped"), x + 12, y - 10); }
  }
  c.restore();
  return sc;
}
function fitCanvas(cv) {
  const r = cv.getBoundingClientRect(), d = CAPTURE ? 1 : (window.devicePixelRatio || 1);
  if (cv.width !== Math.round(r.width * d) || cv.height !== Math.round(r.height * d)) { cv.width = Math.round(r.width * d); cv.height = Math.round(r.height * d); }
  const c = cv.getContext("2d"); c.setTransform(d, 0, 0, d, 0, 0); return { c, w: r.width, h: r.height };
}

// -- views -------------------------------------------------------------------------------------------------------------
const Views = {};

Views.site = {
  async mount(el) {
    el.innerHTML = `<canvas id="cv" style="width:100%;height:100%"></canvas>`;
    this.cv = el.querySelector("#cv");
    this.halls = await Promise.all(S.site.halls.map(h => api(`/api/hall/${h.id}`)));
    this.maps = await Promise.all(this.halls.map(h => img(h.map)));
  },
  draw(t) {
    const { c, w, h } = fitCanvas(this.cv);
    c.clearRect(0, 0, w, h);
    const gw = (w - 16) / 2, gh = (h - 16) / 2;
    this.halls.forEach((hall, i) => {
      const meta = S.site.halls[i], x = (i % 2) * (gw + 16), y = Math.floor(i / 2) * (gh + 16);
      c.fillStyle = K.PANEL; c.strokeStyle = K.LINE; c.beginPath(); c.roundRect(x, y, gw, gh, 16); c.fill(); c.stroke();
      const M = mapper(hall, this.maps[i], { x: x + 12, y: y + 52, w: gw - 24, h: gh - 64 });
      const sc = drawFloor(c, hall, M, t, { mapAlpha: 0.75, r: 3.6 });
      const sofar = hall.close_calls.filter(e => e.t0 <= t).length;
      c.font = font(20, 700); c.fillStyle = K.INK; c.fillText(`Hall ${hall.hall}`, x + 18, y + 33);
      c.font = font(14, 500); c.fillStyle = K.MUTED; c.fillText(badge(meta), x + 104, y + 33);
      c.font = font(14, 600); c.fillStyle = K.INK; c.textAlign = "right";
      c.fillText(`${sc.people.length} people · ${sc.machines.filter(m => m.moving).length} moving · ${sofar} close calls`, x + gw - 18, y + 33);
      c.textAlign = "left";
    });
  },
};
function badge(meta) {
  if (meta.people === "cameras" && meta.vehicles === "cameras") return `${meta.cameras.length} cameras`;
  if (meta.people === "cameras") return `vehicle tags · ${meta.cameras.length} cameras for people`;
  return "badges on 70% of people · no cameras";
}

Views.floor = {
  async mount(el) {
    el.innerHTML = `<div class="row"><div class="col" style="flex:1">
      <div class="toolbar">${S.site.halls.map(h => `<button class="act" data-h="${h.id}">Hall ${h.id}</button>`).join("")}
        <span class="muted" id="fsrc"></span></div>
      <canvas id="cv" style="flex:1;width:100%;min-height:0"></canvas></div>
      <div class="col" style="width:360px"><div class="panel" id="stats"></div><div class="panel scroll" style="flex:1" id="calls"></div></div></div>`;
    el.querySelectorAll("[data-h]").forEach(b => b.onclick = () => { S.hall = b.dataset.h; route(); });
    el.querySelectorAll("[data-h]").forEach(b => b.style.borderColor = b.dataset.h === S.hall ? K.CYAN : "");
    this.cv = el.querySelector("#cv");
    this.hall = await api(`/api/hall/${S.hall}`);
    this.map = await img(this.hall.map);
    const meta = S.site.halls.find(h => h.id === S.hall);
    el.querySelector("#fsrc").textContent = `${badge(meta)} · ${meta.sources.people_tracked_vs_present || ""}`;
  },
  draw(t) {
    const { c, w, h } = fitCanvas(this.cv);
    c.clearRect(0, 0, w, h);
    const M = mapper(this.hall, this.map, { x: 0, y: 0, w, h });
    const sc = drawFloor(c, this.hall, M, t, { trails: true, labels: true });
    const calls = this.hall.close_calls.filter(e => e.t0 <= t);
    const moving = sc.machines.filter(m => m.moving).length, parked = sc.machines.filter(m => m.tr.parked).length;
    document.getElementById("stats").innerHTML = `<h3>Hall ${this.hall.hall} · now</h3>
      <div class="stat"><span>People on the floor</span><b style="color:${K.CYAN}">${sc.people.length}</b></div>
      <div class="stat"><span>Machines moving</span><b style="color:${K.AMBER}">${moving}</b></div>
      <div class="stat"><span>Parked</span><b style="color:${K.MUTED}">${parked}</b></div>
      <div class="stat"><span>Close calls so far</span><b style="color:${K.RED}">${calls.length}</b></div>
      <div class="stat"><span>Inside a danger zone now</span><b style="color:${sc.near.length ? K.RED : K.MUTED}">${sc.near.length}</b></div>`;
    document.getElementById("calls").innerHTML = `<h3>Latest close calls</h3>` + calls.slice(-14).reverse().map(e =>
      `<div class="stat"><span>${esc(e.zone)} · ${esc(e.vehicle.replace(/^[A-D]-/, ""))}</span><span class="mono muted">${stamp(e.t0)}</span></div>`).join("");
  },
};

Views.cameras = {
  async mount(el) {
    const halls = S.site.halls.filter(h => h.cameras.length);
    if (!halls.some(h => h.id === S.hall)) S.hall = halls[0].id;
    const meta = halls.find(h => h.id === S.hall);
    if (!meta.cameras.includes(S.cam)) S.cam = meta.cameras.includes("Camera_03") ? "Camera_03" : meta.cameras[0];
    el.innerHTML = `<div class="row"><div class="col" style="flex:1">
      <div class="toolbar">${halls.map(h => `<button class="act" data-h="${h.id}">Hall ${h.id}</button>`).join("")}
        <select id="cam">${meta.cameras.map(c => `<option ${c === S.cam ? "selected" : ""}>${c}</option>`).join("")}</select>
        <span class="muted" id="csrc"></span></div>
      <div id="stage" style="position:relative;flex:1;min-height:0;background:#000;border-radius:14px;overflow:hidden">
        <video id="vid" muted playsinline preload="auto" style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain"></video>
        <canvas id="ov" style="position:absolute;inset:0;width:100%;height:100%"></canvas></div></div>
      <div class="col" style="width:380px"><div class="panel" id="cstats"></div><div class="panel scroll" style="flex:1" id="csup"></div></div></div>`;
    el.querySelectorAll("[data-h]").forEach(b => { b.style.borderColor = b.dataset.h === S.hall ? K.CYAN : ""; b.onclick = () => { S.hall = b.dataset.h; S.cam = ""; route(); }; });
    el.querySelector("#cam").onchange = e => { S.cam = e.target.value; route(); };
    this.vid = el.querySelector("#vid"); this.ov = el.querySelector("#ov");
    [this.data, this.hall, this.sup] = await Promise.all([api(`/api/hall/${S.hall}/camera/${S.cam}`), api(`/api/hall/${S.hall}`), api("/api/supervision")]);
    this.vid.src = this.data.video;
    await new Promise(ok => { this.vid.onloadeddata = ok; this.vid.onerror = ok; });
    this.index = {};
    for (const [concept, rows] of Object.entries(this.data.boxes)) {
      const by = {}; for (const r of rows) (by[r[1]] = by[r[1]] || []).push(r);
      this.index[concept] = Object.values(by);
    }
    const H = this.data.homography;
    this.H = H; this.Hi = inv3(H);
    el.querySelector("#csrc").textContent = (this.data.people_in_tiles ? "SAM 3.1 · people followed in tiles at full resolution" : "SAM 3.1 · whole view") +
      (Object.keys(this.data.kinds || {}).length ? " · machines named by Muse Spark" : "");
    const issues = (this.sup.issues || []).filter(i => i.subject === S.cam);
    document.getElementById("csup").innerHTML = `<h3>Camera supervisor</h3>` + (issues.length ? issues.map(i =>
      `<div class="finding" style="margin:8px 0">${esc(i.verdict.finding || "")}</div><div class="remedy" style="color:${K.GREEN};font-weight:600">${esc(remedyText(i))}</div>`).join("")
      : `<div class="muted">No issue on this camera.</div>`);
  },
  async seek(t) { if (Math.abs(this.vid.currentTime - t) > 0.02) { this.vid.currentTime = t; await new Promise(ok => { this.vid.onseeked = ok; setTimeout(ok, 4000); }); } },
  box(rows, t) {                                  // a box at t, following its object between SAM's two frames a second
    const f = t * this.data.fps; let a = null, b = null;
    for (const r of rows) { if (r[0] <= f) a = r; if (r[0] >= f) { b = r; break; } }
    if (a && b && b[0] - a[0] <= 2) { if (b[0] === a[0]) return a.slice(2); const u = (f - a[0]) / (b[0] - a[0]); return a.slice(2).map((v, k) => v + (b[k + 2] - v) * u); }
    if (a && f - a[0] <= 0.6) return a.slice(2); if (b && b[0] - f <= 0.6) return b.slice(2);
    return null;
  },
  draw(t) {
    const live = !CAPTURE && S.playing; if (live && Math.abs(this.vid.currentTime - t) > 0.6) this.vid.currentTime = t;
    if (!CAPTURE) { if (S.playing && this.vid.paused) this.vid.play().catch(() => {}); if (!S.playing && !this.vid.paused) this.vid.pause();
      this.vid.playbackRate = S.speed; if (!S.playing && Math.abs(this.vid.currentTime - t) > 0.05) this.vid.currentTime = t; }
    const { c, w, h } = fitCanvas(this.ov); c.clearRect(0, 0, w, h);
    const k = Math.min(w / 1920, h / 1080), ox = (w - 1920 * k) / 2, oy = (h - 1080 * k) / 2;
    const P = (u, v) => [ox + u * k, oy + v * k];
    const sc = scene(this.hall, t);
    // the danger zone of each moving machine, drawn on the floor as this camera sees it
    for (const m of sc.machines) { if (!m.moving) continue;
      const pts = []; for (let a = 0; a < 48; a++) { const q = project(this.H, m.x + this.hall.near_m * Math.cos(a / 48 * 6.283), m.y + this.hall.near_m * Math.sin(a / 48 * 6.283)); if (!q) { pts.length = 0; break; } pts.push(P(...q)); }
      if (pts.length) { c.fillStyle = "rgba(255,178,30,0.18)"; c.strokeStyle = K.AMBER; c.lineWidth = 2.5; c.beginPath(); pts.forEach((p, i) => i ? c.lineTo(...p) : c.moveTo(...p)); c.closePath(); c.fill(); c.stroke(); } }
    let nPeople = 0, nHot = 0;
    for (const rows of this.index.person || []) { const b = this.box(rows, t); if (!b) continue;
      const foot = unproject(this.Hi, (b[0] + b[2]) / 2, b[3]);
      const hot = foot && sc.machines.some(m => m.moving && Math.hypot(foot[0] - m.x, foot[1] - m.y) < this.hall.near_m);
      nPeople++; if (hot) nHot++;
      const [x1, y1] = P(b[0], b[1]), [x2, y2] = P(b[2], b[3]);
      c.fillStyle = hot ? "rgba(255,77,94,0.18)" : "rgba(60,203,255,0.10)"; c.strokeStyle = hot ? K.RED : K.CYAN; c.lineWidth = hot ? 3 : 1.6;
      c.beginPath(); c.roundRect(x1, y1, x2 - x1, y2 - y1, 4); c.fill(); c.stroke(); }
    for (const rows of this.index.vehicle || []) { const b = this.box(rows, t); if (!b) continue;
      const foot = unproject(this.Hi, (b[0] + b[2]) / 2, b[3]);
      let best = null; if (foot) for (const m of sc.machines) { const d = Math.hypot(foot[0] - m.x, foot[1] - m.y); if (d < 3.5 && (!best || d < best.d)) best = { m, d }; }
      const parked = best && best.m.tr.parked, moving = best && best.m.moving;
      const [x1, y1] = P(b[0], b[1]), [x2, y2] = P(b[2], b[3]);
      c.setLineDash(parked ? [8, 6] : []); c.strokeStyle = parked ? K.MUTED : K.AMBER; c.lineWidth = 2.6;
      c.beginPath(); c.roundRect(x1, y1, x2 - x1, y2 - y1, 5); c.stroke(); c.setLineDash([]);
      const named = (this.data.kinds || {})[rows[0][1]];          // what the tagger named this machine
      const label = best ? `${best.m.tr.id.replace(/^[A-D]-/, "")} · ${parked ? "parked" : moving ? "moving" : "stopped"}` : (named || "vehicle");
      c.font = font(13, 700); const tw = c.measureText(label).width + 12;
      c.fillStyle = parked ? K.GREY : K.AMBER; c.beginPath(); c.roundRect(x1, y1 - 22, tw, 20, 4); c.fill();
      c.fillStyle = K.BG; c.fillText(label, x1 + 6, y1 - 7); }
    document.getElementById("cstats").innerHTML = `<h3>${esc(S.cam.replace("_", " "))} · ${stamp(t)}</h3>
      <div class="stat"><span>People followed</span><b style="color:${K.CYAN}">${nPeople}</b></div>
      <div class="stat"><span>Machines moving in the hall</span><b style="color:${K.AMBER}">${sc.machines.filter(m => m.moving).length}</b></div>
      <div class="stat"><span>Inside a danger zone (1.5 m)</span><b style="color:${nHot ? K.RED : K.MUTED}">${nHot}</b></div>`;
  },
};
function inv3(m) {
  const [a, b, c] = m[0], [d, e, f] = m[1], [g, h, i] = m[2];
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g, det = a * A + b * B + c * C;
  return [[A / det, -(b * i - c * h) / det, (b * f - c * e) / det], [B / det, (a * i - c * g) / det, -(a * f - c * d) / det], [C / det, -(a * h - b * g) / det, (a * e - b * d) / det]];
}
function project(H, x, y) { const w = H[2][0] * x + H[2][1] * y + H[2][2]; if (w <= 0) return null; return [(H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w]; }
function unproject(Hi, u, v) { const w = Hi[2][0] * u + Hi[2][1] * v + Hi[2][2]; if (Math.abs(w) < 1e-9) return null; const x = (Hi[0][0] * u + Hi[0][1] * v + Hi[0][2]) / w, y = (Hi[1][0] * u + Hi[1][1] * v + Hi[1][2]) / w; return Math.abs(x) > 200 || Math.abs(y) > 200 ? null : [x, y]; }
function remedyText(i) {
  const r = i.result || {}, v = i.verdict || {};
  if (i.remedy === "split") return r.pending ? "Look again in tiles: waiting for the model" : `Looked again in ${r.tiles} tiles: ${r.people_per_frame_before} → ${r.people_per_frame_after} people a frame`;
  if ((i.remedy === "correct" || i.remedy === "rederive") && r.told) return `Told the hive: these readings are not measurements` + ((r.warnings_inside || []).length ? `; the watcher's warning at ${r.warnings_inside.join(", ")} stood on them` : "");
  if (i.remedy === "correct" || i.remedy === "rederive") return `Corrected the memory: ${r.this_vehicle_now || ""} ${r.this_vehicle_parked ? "is parked" : ""}; ${(r.moving || []).length} machines moving, ${(r.parked || []).length} parked`;
  return v.remedy || i.remedy;
}

// -- ask: a question to a manager, every call to the memory shown ----------------------------------------------------
Views.ask = {
  async mount(el) {
    this.saved = await api("/api/answers");
    el.innerHTML = `<div class="row"><div class="col" style="width:420px">
      <div class="panel"><h3>Ask the site</h3><select id="who" style="margin-bottom:8px">
        <option value="director">plant director</option><option value="floor">floor operations</option>
        <option value="safety">safety manager</option><option value="logistics">logistics manager</option></select>
        <textarea id="text" placeholder="What single change would remove the most close calls?"></textarea>
        <button class="act" id="go" style="margin-top:8px">Ask</button></div>
      <div class="panel scroll saved" style="flex:1"><h3>Asked this shift</h3>${this.saved.map((q, i) =>
        `<button data-i="${i}"><span class="who">${esc(q.role)}</span>${esc(q.transcript || q.text)}</button>`).join("")}</div></div>
      <div class="col" style="flex:1" id="card"></div></div>`;
    el.querySelectorAll("[data-i]").forEach(b => b.onclick = () => { this.q = this.saved[+b.dataset.i]; this.t0 = S.t; this.render(1e9); });
    el.querySelector("#go").onclick = () => this.ask(el.querySelector("#who").value, el.querySelector("#text").value);
    const want = Q.get("q"); this.q = this.saved.find(q => q.id === want) || this.saved[0]; this.t0 = 0;
    this.render(CAPTURE ? 0 : 1e9);
  },
  async ask(who, text) {
    if (!text.trim()) return;
    this.q = { role: who, text, model: "", now: "", trace: [], answer: null, live: true }; this.render(1e9);
    const r = await fetch("/api/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ who, text }) });
    const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) { const { value, done } = await rd.read(); if (done) break; buf += dec.decode(value, { stream: true });
      let k; while ((k = buf.indexOf("\n\n")) >= 0) { const chunk = buf.slice(0, k); buf = buf.slice(k + 2);
        const ev = /event: (\w+)/.exec(chunk)?.[1], data = JSON.parse(/data: (.*)/.exec(chunk)?.[1] || "{}");
        if (ev === "start") Object.assign(this.q, data); else if (ev === "step") this.q.trace.push(data);
        else if (ev === "answer") this.q.answer = data.answer; else if (ev === "error") this.q.error = data.error;
        this.render(1e9); } }
  },
  draw(t) { if (CAPTURE) this.render(t); },
  render(t) {                                       // t: seconds since the question was asked (capture types it out)
    const q = this.q; if (!q) return;
    const card = document.getElementById("card"); const ans = q.answer || {};
    const question = q.transcript || q.text, tq = 0.6 + question.length / 34;
    const steps = (q.trace || []), shown = steps.filter((_, i) => t >= tq + 0.4 + 0.75 * i);
    const tAns = tq + 0.4 + 0.75 * steps.length + 0.6, body = String(ans.body || "");
    const typed = Math.max(0, (t - tAns - 1) * Math.max(75, body.length / 18));
    const level = { act_now: ["ACT NOW", K.RED], watch: ["WATCH", K.AMBER], info: ["INFO", K.CYAN] }[ans.level] || ["", K.CYAN];
    card.innerHTML = `<div class="row" style="gap:18px;height:100%"><div class="col" style="flex:1">
      <div class="qbox"><div class="label">${q.voice ? "Asked by voice · transcribed by Muse Voice Transcribe" : "Question"} · ${esc(q.role)}</div>
        <div class="q">${esc(question.slice(0, Math.floor(Math.max(0, t - 0.6) * 34)))}</div></div>
      <div class="panel scroll" style="flex:1"><h3>Working from the memory</h3>${shown.map(chip).join("")}${whatif(steps, t >= tAns - 0.6)}</div></div>
      <div class="panel col answer scroll" style="flex:1.1">${q.error ? `<div style="color:${K.RED}">${esc(q.error)}</div>` : ""}
      ${t >= tAns && q.answer ? `<div><span class="tag" style="color:${level[1]}">${level[0]}</span></div>
        <div class="head">${esc(ans.headline || "")}</div>
        <div class="body">${md(body.slice(0, Math.floor(typed)))}</div>
        ${typed >= body.length ? (ans.actions || []).map(a => `<div class="act">● ${esc(a.action)}${a.who ? " — " + esc(a.who) : ""}</div>`).join("") +
          `<div class="muted" style="margin-top:10px">Confidence: ${esc(ans.confidence || "")} · ${esc((ans.citations || []).slice(0, 3).join(", "))}</div>` : ""}`
        : `<div class="muted">${q.live ? "Working…" : ""}</div>`}</div></div>`;
    if (CAPTURE || q.live) card.querySelectorAll(".scroll").forEach(el => { el.scrollTop = el.scrollHeight; });
  },
};
function chip(st) {
  const raw = String(st.result || ""), refused = raw.slice(0, 200).includes('"error"');
  let title = st.tool, detail = "";
  const p = typeof st.args?.plan === "string" ? safeJSON(st.args.plan) : st.args?.plan;
  if (st.tool === "table_query" && p) { title = `table query · ${p.op || "query"} · ${String(p.table || "").replace("factory/", "")}` + (p.group_by ? ` · by ${p.group_by.join(", ")}` : "");
    const m = /computed over (\d+) matching rows/.exec(raw); detail = m ? `exact answer, computed over ${(+m[1]).toLocaleString()} rows` : "an exact answer from the memory"; }
  else if (st.tool === "whatif") { title = `what-if · ${st.args?.vehicle || ""}`; const r = safeJSON(raw); const av = r?.avoid;
    detail = av ? `kept out of ${av.zones.join(", ")}: up to ${av.inside_zones} of its ${av.close_calls} close calls avoided` : "replayed against the people as they moved"; }
  else if (st.tool === "search") { title = `search · “${String(st.args?.query || "").slice(0, 48)}”`; detail = "the memory's notes and reports"; }
  else if (st.tool === "tables") detail = "what the memory holds, and its columns";
  else if (st.tool === "memory_facts") { title = "shared facts"; detail = "what other agents and people wrote"; }
  if (refused) { const m = /"error":\s*"((?:[^"\\]|\\.)*)/.exec(raw);
    detail = "refused: " + (m ? m[1] : "").replace(/^\d{3}:\s*/, "").replace(/^\{'error':\s*/, "").replace(/\\"/g, '"').replace(/^["']+|["'}]+$/g, "").split(";")[0]; }
  return `<div class="chip ${refused ? "refused" : ""}"><span class="dot"></span><span class="t">${esc(title)}</span><span class="d">${esc(detail)}</span></div>`;
}
function whatif(steps, show) {
  if (!show) return "";
  for (const st of steps) { if (st.tool !== "whatif") continue; const r = safeJSON(String(st.result || "")); if (!r?.by_shift) continue;
    const mx = Math.max(...r.by_shift.map(x => x.close_calls)), best = r.by_shift.reduce((a, b) => b.close_calls < a.close_calls ? b : a);
    return `<h3 style="margin-top:18px">What-if · ${esc(r.vehicle)}: its close calls if it ran earlier or later</h3><div class="bars">${r.by_shift.map(x =>
      `<div style="height:${100 * x.close_calls / mx}%;background:${x === best ? K.GREEN : x.shift_s === 0 ? K.RED : K.MUTED}"><span>${x.close_calls}</span><i>${x.shift_s === 0 ? "as run" : (x.shift_s > 0 ? "+" : "") + x.shift_s + " s"}</i></div>`).join("")}</div><div style="height:24px"></div>`; }
  return "";
}
function safeJSON(s) { try { return JSON.parse(s); } catch { return null; } }
function md(s) { return esc(s).split("\n").filter(Boolean).map(l => l.replace(/^#+\s*/, "").replace(/\*\*/g, "")).map(l => /^[-*]\s/.test(l) ? `<p>• ${l.slice(2)}</p>` : `<p>${l}</p>`).join(""); }

// -- hive: the agents' coordination, and the decisions waiting for people ---------------------------------------------
Views.hive = {
  async mount(el) {
    this.data = await api(`/api/hive${Q.get("run") ? "?run=" + Q.get("run") : ""}`);
    el.innerHTML = `<div class="row"><div class="col" style="flex:1"><div class="toolbar"><select id="run">${(this.data.runs || []).map(r =>
      `<option ${r === this.data.run ? "selected" : ""}>${r}</option>`).join("")}</select><span class="muted">a run of the factory's hive</span></div>
      <div class="scroll feed" id="feed" style="flex:1"></div></div>
      <div class="col" style="width:400px"><div class="panel scroll" style="flex:1" id="live"><h3>Waiting for people</h3><div class="muted">reading the hive…</div></div></div></div>`;
    el.querySelector("#run").onchange = e => { S.cache[`/api/hive?run=${e.target.value}`] = null; Q.set("run", e.target.value); route(); };
    this.items = feedItems(this.data);
    if (!CAPTURE) this.live(); else this.copies(0);
  },
  copies(t) {                                       // who held a copy of what, and when it went stale (the run's own log)
    const rows = (this.data.log || []).filter(e => e.call === "claim" && (e.write || (e.made_stale || []).length) && e.at <= this.items.length * 4.5);
    const shown = CAPTURE ? rows.filter((e, k) => t >= 1.5 + 4.5 * Math.min(k, this.items.length)) : rows;
    document.getElementById("live").innerHTML = `<h3>Copies and who was told</h3>` + shown.map(e =>
      `<div class="stat" style="display:block"><div><b>${esc(e.agent.replace("factory/", ""))}</b> takes ${esc((e.resources || []).join(", "))}</div>
       <div style="color:${K.RED};font-size:13px">${(e.made_stale || []).length ? "stale for " + esc(e.made_stale.join(", ").replace(/factory\//g, "")) : ""} <span class="muted">+${e.at.toFixed(1)} s</span></div></div>`).join("");
  },
  async live() {
    try { const s = await (await fetch("/api/state")).json(); if (s.error) throw new Error(s.error);
      const open = (s.cards || []).filter(c => c.resolution === "open");
      document.getElementById("live").innerHTML = `<h3>Waiting for people</h3>` + (open.length ? open.map(c => `<div class="issue"><b>${esc(c.title)}</b>
        <div class="muted">${esc(c.detail).slice(0, 400)}</div>${(c.options || []).map(o => `<button class="act" data-c="${esc(c.id)}" data-o="${esc(o.id)}">${esc(o.label)}</button>`).join(" ")}</div>`).join("")
        : `<div class="muted">Nothing: the agents settled everything between themselves.</div>`) +
        `<h3 style="margin-top:18px">Shared memory, newest</h3>` + (s.facts || []).slice(0, 12).map(f => `<div class="stat" style="display:block"><div>${esc(f.text)}</div><div class="muted" style="font-size:12px">${esc(f.author)} · ${esc(f.kind)}${f.corrects ? " · corrects an earlier fact" : ""}</div></div>`).join("");
      document.querySelectorAll("[data-c]").forEach(b => b.onclick = async () => { await fetch(`/api/cards/${encodeURIComponent(b.dataset.c)}/resolve`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ resolution: b.dataset.o }) }); this.live(); });
    } catch (e) { document.getElementById("live").innerHTML = `<h3>Waiting for people</h3><div class="muted">The live hive is not reachable from here (${esc(e.message)}).</div>`; }
  },
  draw(t) {
    if (CAPTURE) this.copies(t);
    const shown = this.items.filter(it => CAPTURE ? t >= it.show : true);
    document.getElementById("feed").innerHTML = shown.map(it => `<div class="item" style="border-left-color:${it.col}"><span class="who" style="color:${it.col}">${esc(it.who)}</span><span class="head">${esc(it.head)}</span>
      <div class="body">${esc(it.body)}</div>${it.stamp ? `<div class="stamp ${it.alert ? "alert" : ""}">${esc(it.stamp)}</div>` : ""}</div>`).join("");
    if (CAPTURE) { const f = document.getElementById("feed"); f.scrollTop = f.scrollHeight; }
  },
};
function feedItems(d) {
  const dec = d.decision || {}, log = d.log || [], items = [];
  const at = (call, f) => { const e = log.find(e => e.call === call && Object.entries(f).every(([k, v]) => e[k] === v)); return e ? `+${e.at.toFixed(1)} s` : ""; };
  let show = 1.5; const add = (who, col, head, body, stamp = "", alert = false) => { items.push({ who, col, head, body, stamp, alert, show }); show += 4.5; };
  if (dec.finding) {
    add("CAMERA SUPERVISOR", K.GREEN, "corrected the hall's memory", dec.finding.verdict?.finding || "", `${at("claim", { agent: "factory/perception-a", write: true })} · safety's copy of Hall A's memory: stale`, true);
    if (dec.safety_review) add("SAFETY MANAGER", K.VIOLET, dec.safety_review.stands === false ? "withdraws its 08:05 decision" : "keeps its decision", dec.safety_review.why || "",
      `${at("claim", { agent: "factory/safety", write: true })} · copies held by logistics and floor operations: stale`, true);
    if (dec.logistics_after) add("LOGISTICS", K.AMBER, "re-read, and changes", dec.logistics_after.change || "");
    if (dec.floor_after) add("FLOOR OPERATIONS", K.CYAN, "re-read, and changes", dec.floor_after.change || "");
    const a = dec.answer?.answer; if (a) add("SAFETY MANAGER", K.VIOLET, "asks the corrected memory again", a.headline || "");
  }
  const n = dec.new || dec;
  if (n.ask) {
    add("SAFETY  →  LOGISTICS", K.VIOLET, "request", n.ask.split("] ").slice(1).join("] "), (n.collided_with || []).length ? "collides with logistics, which is using the route" : "", true);
    if (n.logistics) add("LOGISTICS  →  SAFETY", K.GREEN, String(n.logistics.answer || "").toUpperCase(), n.logistics.reply || "");
    if (n.agreed) add("SAFETY MANAGER", K.VIOLET, "takes the route", `Agreed: ${n.agreed}`, `copies held by ${(n.made_stale || []).join(", ").replace(/factory\//g, "")}: stale`, true);
    if (n.floor) add("FLOOR OPERATIONS", K.CYAN, "re-read its stale copy, then re-planned", n.floor.change || "", n.floor.why || "");
    if (n.card) add("PEOPLE", K.RED, "a decision is waiting", n.card);
  }
  return items;
}

// -- supervisors: what they found, what they looked at, what they changed ---------------------------------------------
Views.supervisors = {
  async mount(el) {
    const d = await api("/api/supervision");
    const label = { limit: ["AT ITS LIMIT", K.AMBER], disagrees: ["DISAGREES", K.AMBER], implausible: ["IMPLAUSIBLE", K.RED], missing: ["MISSING", K.RED] };
    let last = "";
    el.innerHTML = `<div class="scroll" style="height:100%"><div class="toolbar"><span class="muted">Every supervisor's newest run: the issues its checks raised, what it looked at, what it found and what it changed.</span></div>` +
      (d.issues || []).map(i => { const [l, col] = label[i.check] || [i.check, K.MUTED]; const r = i.result || {};
        const head = i.supervisor !== last ? `<h3 style="margin:18px 0 10px">Supervising ${esc(i.supervisor)}</h3>` : ""; last = i.supervisor;
        return head + `<div class="issue"><span class="tag" style="color:${col}">${l}</span> <b style="margin-left:8px">${esc(i.subject)}</b> <span class="muted mono" style="font-size:12px">run ${esc(i.run)}</span>
        <span class="muted" style="margin-left:8px">${esc(evidence(i))}</span>
        ${i.images.length ? `<div class="imgs">${i.images.map((s, k) => `<figure><img src="${s}"><figcaption>${i.check === "limit" ? "what SAM 3.1 boxed, one look at the whole view" : `the vehicle, ${["first", "a minute later", "two minutes later"][k] || ""}`}</figcaption></figure>`).join("")}${(i.after_images || []).map(s => `<figure><img src="${s}"><figcaption>after the remedy: the view looked at in tiles</figcaption></figure>`).join("")}</div>` : ""}
        <div class="finding">${esc(i.verdict?.finding || "")}</div>
        <div class="remedy">${esc(remedyText(i))}</div>${i.verdict?.lesson ? `<div class="muted" style="margin-top:6px">Lesson for every agent: ${esc(i.verdict.lesson)}</div>` : ""}</div>`; }).join("") + `</div>`;
    this.box = el.querySelector(".scroll");
  },
  draw(t) { if (CAPTURE && this.box) this.box.scrollTop = Math.max(0, (t - 3) * 60); },
};
function evidence(i) {
  const e = i.evidence || {};
  if (i.check === "limit" && e.units === 1) return `followed ${e.followed_in_the_request} people in one request: SAM's cap (most in a frame: ${e.most_in_a_frame})`;
  if (i.check === "limit") return `${e.units_at_limit} of ${e.units} frames at SAM's limit (most in a frame: ${e.most_in_a_frame})`;
  if (i.check === "implausible") return e.why || "";
  return Object.entries(e).slice(0, 4).map(([k, v]) => `${k}: ${v}`).join(" · ");
}

// -- the clock, the tabs, the capture hook ---------------------------------------------------------------------------
let current = null;
async function route() {
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.view === S.view));
  const el = document.getElementById("view"); el.innerHTML = `<div class="muted">loading…</div>`;
  current = Views[S.view]; await current.mount(el); current.draw(S.t); tick();
}
function tick() {                                  // the shift's clock; answers and the hive's runs happened at 08:05
  document.getElementById("clock").textContent = ["ask", "hive", "supervisors"].includes(S.view) ? "08:05:00" : stamp(S.t);
  document.getElementById("scrub-fill").style.width = `${100 * S.t / 300}%`;
}
let last = 0;
function loop(now) {
  if (S.playing && current) { const dt = last ? (now - last) / 1000 : 0; S.t = (S.t + dt * S.speed) % 300;
    if (current === Views.cameras && current.vid && !current.vid.paused) S.t = current.vid.currentTime;
    current.draw(S.t); tick(); }
  last = now; requestAnimationFrame(loop);
}
async function boot() {
  if (CAPTURE) document.body.classList.add("capture");
  await document.fonts.load('600 16px "Inter"'); await document.fonts.load('600 16px "JetBrains Mono"');
  S.site = await api("/api/site");
  document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => { S.view = b.dataset.view; route(); });
  document.getElementById("play").onclick = () => { S.playing = !S.playing; document.getElementById("play").textContent = S.playing ? "❚❚" : "▶"; };
  document.getElementById("speed").onchange = e => { S.speed = +e.target.value; };
  document.getElementById("scrub").onclick = e => { S.t = 300 * e.offsetX / e.currentTarget.clientWidth; current?.draw(S.t); tick(); };
  await route();
  if (!CAPTURE) requestAnimationFrame(loop);
  window.argus = { ready: true, async seek(t) { S.t = t; if (current.seek) await current.seek(t); current.draw(t); tick(); return true; } };
}
boot();
