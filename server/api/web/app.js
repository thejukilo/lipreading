/* Lipreading PWA — auth, push-to-talk speak, voices, and teach/train.
   Vanilla JS (no build step); talks to the FastAPI backend on the same origin. */

const FPS = 25;
const $ = (id) => document.getElementById(id);
const store = {
  get token() { try { return localStorage.getItem("lip_token") || ""; } catch { return ""; } },
  set token(v) { try { v ? localStorage.setItem("lip_token", v) : localStorage.removeItem("lip_token"); } catch {} },
};

// ---- API helper ------------------------------------------------------------
async function api(path, { method = "GET", json, form, auth = true } = {}) {
  const headers = {};
  if (auth && store.token) headers["Authorization"] = "Bearer " + store.token;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  else if (form !== undefined) body = form;
  const res = await fetch(path, { method, headers, body });
  const text = await res.text();
  let data = null; try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) throw new Error((data && (data.detail || data.message)) || `HTTP ${res.status}`);
  return data;
}
const detail = (e) => (e && e.message) ? e.message : String(e);

// ============================================================================
// AUTH
// ============================================================================
let authMode = "login";
function renderAuthMode() {
  const login = authMode === "login";
  $("authSub").textContent = login ? "Speak with your eyes. Sign in to continue."
                                    : "Create an account to get started.";
  $("authBtn").textContent = login ? "Sign in" : "Create account";
  $("nameField").classList.toggle("hidden", login);
  $("password").autocomplete = login ? "current-password" : "new-password";
  $("authToggle").innerHTML = login
    ? `New here? <a href="#">Create an account</a>`
    : `Have an account? <a href="#">Sign in</a>`;
  $("authToggle").querySelector("a").onclick = (e) => { e.preventDefault(); authMode = login ? "register" : "login"; $("authErr").textContent = ""; renderAuthMode(); };
}
async function submitAuth() {
  const email = $("email").value.trim();
  const password = $("password").value;
  $("authErr").textContent = "";
  if (!email || !password) { $("authErr").textContent = "Email and password are required."; return; }
  $("authBtn").disabled = true;
  try {
    const path = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
    const json = authMode === "login"
      ? { email, password }
      : { email, password, display_name: $("displayName").value.trim() };
    const out = await api(path, { method: "POST", json, auth: false });
    store.token = out.access_token;
    await enterApp();
  } catch (e) {
    $("authErr").textContent = detail(e);
  } finally {
    $("authBtn").disabled = false;
  }
}

// ============================================================================
// SHARED CAMERA
// ============================================================================
let stream = null;
const capCanvas = document.createElement("canvas");
const capCtx = capCanvas.getContext("2d");

async function ensureCamera() {
  if (stream) return true;
  if (!navigator.mediaDevices?.getUserMedia) {
    setStatus("speakStatus", "This browser can't use the camera (needs HTTPS).", true); return false;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
    for (const v of [$("cam"), $("teachCam")]) { v.srcObject = stream; v.play().catch(() => {}); }
    return true;
  } catch (e) {
    setStatus("speakStatus", "Camera permission denied (" + detail(e) + ").", true); return false;
  }
}

function grabFrom(video, into) {
  const w = video.videoWidth, h = video.videoHeight;
  if (!w || !h) return;
  const scale = Math.min(1, 480 / Math.max(w, h));
  capCanvas.width = Math.round(w * scale);
  capCanvas.height = Math.round(h * scale);
  capCtx.drawImage(video, 0, 0, capCanvas.width, capCanvas.height);
  capCanvas.toBlob((b) => { if (b) into.push(b); }, "image/jpeg", 0.6);
}

// A reusable push-to-talk recorder bound to a <video> + a button.
function pushToTalk(video, button, onDone, { minFrames = 8 } = {}) {
  let recording = false, frames = [], timer = null;
  const start = () => {
    if (recording || button.disabled) return;
    recording = true; frames = [];
    button.classList.add("rec");
    grabFrom(video, frames);
    timer = setInterval(() => grabFrom(video, frames), 1000 / FPS);
  };
  const stop = async () => {
    if (!recording) return;
    recording = false; clearInterval(timer); timer = null;
    button.classList.remove("rec");
    await new Promise((r) => setTimeout(r, 130)); // let last toBlob() resolve
    if (frames.length < minFrames) { onDone(null, "too short — hold a bit longer"); return; }
    onDone(frames.slice(), null);
  };
  button.addEventListener("pointerdown", (e) => { e.preventDefault(); start(); });
  button.addEventListener("pointerup", (e) => { e.preventDefault(); stop(); });
  button.addEventListener("pointercancel", stop);
  button.addEventListener("pointerleave", () => { if (recording) stop(); });
}

function setStatus(id, msg, isErr) {
  const el = $(id); if (!el) return;
  el.textContent = msg || ""; el.classList.toggle("err", !!isErr);
}

// ---- audio playback --------------------------------------------------------
let audioCtx = null, lastUrl = null;
function bytesFromB64(b64) {
  const bin = atob(b64), a = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
  return a;
}
async function playB64(b64, mime = "audio/wav") {
  if (!b64) return;
  const bytes = bytesFromB64(b64);
  // Preferred: Web Audio decode + play from sample 0. Plain <audio>.play() on a
  // just-created blob URL can clip the first word while it buffers.
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    audioCtx = audioCtx || new AC();
    if (audioCtx.state === "suspended") await audioCtx.resume();
    const buf = await audioCtx.decodeAudioData(bytes.buffer.slice(0));
    const src = audioCtx.createBufferSource();
    src.buffer = buf; src.connect(audioCtx.destination); src.start(0);
    return;
  } catch { /* fall back to <audio> below */ }
  if (lastUrl) URL.revokeObjectURL(lastUrl);
  lastUrl = URL.createObjectURL(new Blob([bytes], { type: mime }));
  const p = $("player");
  p.src = lastUrl;
  p.addEventListener("canplaythrough", function once() {
    p.removeEventListener("canplaythrough", once); p.currentTime = 0; p.play().catch(() => {});
  }, { once: true });
  p.load();
}

// ============================================================================
// SPEAK
// ============================================================================
let lastSpeakFrames = null;

function initSpeak() {
  pushToTalk($("cam"), $("talk"), async (frames, err) => {
    if (err) { setStatus("speakStatus", err, true); return; }
    $("talk").disabled = true;
    $("addTrainBtn").hidden = true;
    $("addTrainHint").hidden = true;
    setStatus("speakStatus", `thinking… (${frames.length} frames)`);
    const fd = new FormData();
    frames.forEach((b, i) => fd.append("frames", b, `f${i}.jpg`));
    fd.append("fps", String(FPS));
    fd.append("speak", $("speak").checked ? "true" : "false");
    fd.append("cleanup", $("cleanup").checked ? "true" : "false");
    try {
      const data = await api("/api/utter", { method: "POST", form: fd });
      $("transcript").value = data.text || "";
      setStatus("speakStatus", data.message || "done — you can edit the text, then add it to training");
      if (data.text) {
        lastSpeakFrames = frames;
        $("addTrainBtn").hidden = false;
        $("addTrainHint").hidden = false;
        $("addTrainHint").textContent = $("cleanup").checked
          ? "⚠ Clean up was on — the text may have been auto-corrected. Make sure it's exactly what you said before adding."
          : "Check the words match exactly what you said before adding.";
      }
      if (data.audio) playB64(data.audio, data.audio_mime);
    } catch (e) {
      setStatus("speakStatus", detail(e), true);
    } finally {
      $("talk").disabled = false;
    }
  });

  // Correct the transcript, keep this clip as rep #1, and queue the sentence
  // to practice (one clip rarely fixes a misread — record a few more on Teach).
  $("addTrainBtn").onclick = async () => {
    const phrase = $("transcript").value.trim();
    if (!phrase || !lastSpeakFrames) { setStatus("speakStatus", "Nothing to add yet.", true); return; }
    $("addTrainBtn").disabled = true;
    setStatus("speakStatus", "adding to training…");
    const fd = new FormData();
    lastSpeakFrames.forEach((b, i) => fd.append("frames", b, `f${i}.jpg`));
    fd.append("phrase", phrase); fd.append("fps", String(FPS));
    try {
      await api("/api/teach/samples", { method: "POST", form: fd });      // rep #1
      await api("/api/teach/practice", { method: "POST", json: { text: phrase } }); // queue it
      setStatus("speakStatus", "added ✓ — open Teach and record it a few more times, then train.");
      $("addTrainBtn").hidden = true; $("addTrainHint").hidden = true; lastSpeakFrames = null;
    } catch (e) {
      setStatus("speakStatus", detail(e), true);
    } finally {
      $("addTrainBtn").disabled = false;
    }
  };
}

// ============================================================================
// VOICES
// ============================================================================
let pendingVoiceWav = null;

async function loadVoices() {
  const el = $("voiceList");
  try {
    const voices = await api("/api/voices");
    if (!voices.length) { el.innerHTML = `<p class="muted" style="margin:0">No voices yet. Add one below.</p>`; return; }
    el.innerHTML = "";
    for (const v of voices) {
      const row = document.createElement("div");
      row.className = "voice"; row.style.padding = "6px 0";
      row.innerHTML = `<span class="name"></span>${v.is_default ? '<span class="badge">default</span>' : ""}
        <span class="spacer"></span>
        ${v.is_default ? "" : `<button data-act="default">Set default</button>`}
        <button data-act="play">▶</button>
        <button data-act="del">Delete</button>`;
      row.querySelector(".name").textContent = v.name;
      row.querySelector('[data-act="play"]').onclick = async () => {
        const r = await fetch(`/api/voices/${v.id}/reference`, { headers: { Authorization: "Bearer " + store.token } });
        if (r.ok) { const url = URL.createObjectURL(await r.blob()); const a = $("player"); a.src = url; a.play().catch(() => {}); }
      };
      const setD = row.querySelector('[data-act="default"]');
      if (setD) setD.onclick = async () => { await api(`/api/voices/${v.id}/default`, { method: "POST" }); loadVoices(); };
      row.querySelector('[data-act="del"]').onclick = async () => {
        if (!confirm(`Delete voice “${v.name}”?`)) return;
        await api(`/api/voices/${v.id}`, { method: "DELETE" }); loadVoices();
      };
      el.appendChild(row);
    }
  } catch (e) { el.innerHTML = `<p class="err" style="margin:0">${detail(e)}</p>`; }
}

function initVoices() {
  $("voicePickBtn").onclick = () => $("voiceFile").click();
  $("voiceFile").onchange = () => {
    const f = $("voiceFile").files[0]; if (!f) return;
    pendingVoiceWav = f; $("voiceSaveBtn").disabled = false;
    setStatus("voiceStatus", `Selected ${f.name}`);
    if (!$("voiceName").value.trim()) $("voiceName").value = f.name.replace(/\.[^.]+$/, "");
  };
  $("voiceRecBtn").onclick = () => recordVoice();
  $("voiceSaveBtn").onclick = async () => {
    const name = $("voiceName").value.trim();
    if (!name) { setStatus("voiceStatus", "Give the voice a name.", true); return; }
    if (!pendingVoiceWav) { setStatus("voiceStatus", "Record or pick a WAV first.", true); return; }
    $("voiceSaveBtn").disabled = true; setStatus("voiceStatus", "Saving…");
    const fd = new FormData();
    fd.append("name", name); fd.append("engine", "voxcpm");
    fd.append("audio", pendingVoiceWav, "reference.wav");
    try {
      await api("/api/voices", { method: "POST", form: fd });
      pendingVoiceWav = null; $("voiceName").value = ""; $("voiceFile").value = "";
      setStatus("voiceStatus", "Saved ✓"); loadVoices();
    } catch (e) { setStatus("voiceStatus", detail(e), true); $("voiceSaveBtn").disabled = false; }
  };
}

// Record ~8s of mic audio and encode a real WAV client-side (server needs WAV).
async function recordVoice() {
  let mic;
  try { mic = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { setStatus("voiceStatus", "Mic denied (" + detail(e) + ").", true); return; }
  const AC = window.AudioContext || window.webkitAudioContext;
  const ac = new AC();
  const src = ac.createMediaStreamSource(mic);
  const node = ac.createScriptProcessor(4096, 1, 1);
  const chunks = []; const sr = ac.sampleRate;
  node.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  src.connect(node); node.connect(ac.destination);
  $("voiceRecBtn").disabled = true;
  let left = 8;
  setStatus("voiceStatus", `Recording… ${left}s (speak naturally)`);
  const tick = setInterval(() => { left -= 1; if (left > 0) setStatus("voiceStatus", `Recording… ${left}s`); }, 1000);
  await new Promise((r) => setTimeout(r, 8000));
  clearInterval(tick);
  node.disconnect(); src.disconnect(); mic.getTracks().forEach((t) => t.stop()); ac.close();
  $("voiceRecBtn").disabled = false;
  pendingVoiceWav = encodeWav(chunks, sr);
  $("voiceSaveBtn").disabled = false;
  setStatus("voiceStatus", "Recorded ✓ — name it and Save.");
}

function encodeWav(chunks, sampleRate) {
  let len = 0; for (const c of chunks) len += c.length;
  const pcm = new Float32Array(len); let o = 0;
  for (const c of chunks) { pcm.set(c, o); o += c.length; }
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const dv = new DataView(buf);
  const wr = (off, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(off + i, s.charCodeAt(i)); };
  wr(0, "RIFF"); dv.setUint32(4, 36 + pcm.length * 2, true); wr(8, "WAVE");
  wr(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, sampleRate, true); dv.setUint32(28, sampleRate * 2, true);
  dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
  wr(36, "data"); dv.setUint32(40, pcm.length * 2, true);
  let p = 44; for (let i = 0; i < pcm.length; i++) { const s = Math.max(-1, Math.min(1, pcm[i])); dv.setInt16(p, s < 0 ? s * 0x8000 : s * 0x7fff, true); p += 2; }
  return new Blob([buf], { type: "audio/wav" });
}

// ============================================================================
// TEACH
// ============================================================================
let teachQueue = [], teachTotalPrompts = 0, teachDone = 0, statusTimer = null, customCount = 0;

function initTeach() {
  pushToTalk($("teachCam"), $("teachRecBtn"), onTeachClip);
  pushToTalk($("teachCam"), $("customRecBtn"), onCustomClip);
  $("teachStartBtn").onclick = startTeach;
  $("trainNowBtn").onclick = async () => {
    try { const j = await api("/api/teach/train", { method: "POST" }); setStatus("teachStatus", `Training ${j.status}…`); $("statusBox").open = true; refreshTeachStatus(); }
    catch (e) { setStatus("teachStatus", detail(e), true); }
  };
  // Segmented record-mode switch.
  for (const b of document.querySelectorAll("#recMode button")) {
    b.onclick = () => {
      for (const x of document.querySelectorAll("#recMode button")) x.classList.toggle("on", x === b);
      const phrase = b.dataset.mode === "phrase";
      $("modePhrase").classList.toggle("hidden", !phrase);
      $("modePrompts").classList.toggle("hidden", phrase);
    };
  }
}

async function loadSamples() {
  const el = $("sampleList");
  try {
    const rows = await api("/api/teach/samples");
    $("recCountLbl").textContent = rows.length ? `(${rows.length})` : "";
    if (!rows.length) { el.innerHTML = `<p class="muted" style="margin:0">No recordings yet.</p>`; return; }
    el.innerHTML = "";
    for (const r of rows) {
      const row = document.createElement("div");
      row.className = "voice"; row.style.padding = "6px 0";
      row.innerHTML = `<span class="name"></span><span class="muted" style="margin-left:8px">${r.n_frames}f${r.consumed ? " · trained" : ""}</span>
        <span class="spacer"></span><button data-act="del">✕</button>`;
      row.querySelector(".name").textContent = r.phrase;
      row.querySelector('[data-act="del"]').onclick = async () => {
        try { await api(`/api/teach/samples/${r.id}`, { method: "DELETE" }); loadSamples(); refreshTeachStatus(); }
        catch (e) { setStatus("teachStatus", detail(e), true); }
      };
      el.appendChild(row);
    }
  } catch (e) { el.innerHTML = `<p class="err" style="margin:0">${detail(e)}</p>`; }
}

// Record one repetition of a user-typed phrase (e.g. their name).
async function onCustomClip(frames, err) {
  const phrase = $("customPhrase").value.trim();
  if (!phrase) { setStatus("teachStatus", "Type a phrase first.", true); return; }
  if (err) { setStatus("teachStatus", err, true); return; }
  $("customRecBtn").disabled = true;
  const fd = new FormData();
  frames.forEach((b, i) => fd.append("frames", b, `f${i}.jpg`));
  fd.append("phrase", phrase); fd.append("fps", String(FPS));
  try {
    const out = await api("/api/teach/samples", { method: "POST", form: fd });
    customCount += 1;
    $("customCount").textContent = `${customCount} recorded this session · ${out.samples_total} total clips`;
    if (out.training_triggered) setStatus("teachStatus", "Enough new clips — training started! ✨");
    else setStatus("teachStatus", `Saved “${phrase}”. Record a few more, then Train now.`);
    refreshTeachStatus();
    loadSamples();
    loadPractice();
  } catch (e) {
    setStatus("teachStatus", detail(e), true);
  } finally {
    $("customRecBtn").disabled = false;
  }
}
async function startTeach() {
  try {
    const out = await api("/api/teach/sentences?n=10");
    teachQueue = out.sentences.slice(); teachTotalPrompts = teachQueue.length; teachDone = 0;
    $("teachStartBtn").textContent = "Restart";
    nextPrompt();
  } catch (e) { setStatus("teachStatus", detail(e), true); }
}
function nextPrompt() {
  updateBar();
  if (!teachQueue.length) {
    $("teachPrompt").textContent = "All done — nice work! 🎉";
    $("teachRecBtn").disabled = true;
    setStatus("teachStatus", "Tap Start for another round.");
    return;
  }
  $("teachPrompt").textContent = teachQueue[0];
  $("teachRecBtn").disabled = false;
  setStatus("teachStatus", "Hold the button and read it aloud.");
}
function updateBar() {
  const pct = teachTotalPrompts ? Math.round((teachDone / teachTotalPrompts) * 100) : 0;
  $("teachBar").style.width = pct + "%";
  $("teachCount").textContent = `${teachDone} / ${teachTotalPrompts} this round`;
}
async function onTeachClip(frames, err) {
  if (err) { setStatus("teachStatus", err, true); return; }
  const phrase = teachQueue[0];
  $("teachRecBtn").disabled = true;
  setStatus("teachStatus", `saving… (${frames.length} frames)`);
  const fd = new FormData();
  frames.forEach((b, i) => fd.append("frames", b, `f${i}.jpg`));
  fd.append("phrase", phrase); fd.append("fps", String(FPS));
  try {
    const out = await api("/api/teach/samples", { method: "POST", form: fd });
    teachQueue.shift(); teachDone += 1;
    if (out.training_triggered) setStatus("teachStatus", "Enough new clips — training started! ✨");
    refreshTeachStatus();
    nextPrompt();
  } catch (e) {
    setStatus("teachStatus", detail(e), true);
    $("teachRecBtn").disabled = false;
  }
}
async function loadPractice() {
  const card = $("practiceCard"), el = $("practiceList");
  try {
    const rows = await api("/api/teach/practice");
    card.classList.toggle("hidden", rows.length === 0);
    el.innerHTML = "";
    for (const p of rows) {
      const enough = p.reps >= 5;
      const row = document.createElement("div");
      row.className = "voice"; row.style.cssText = "padding:8px 0; align-items:flex-start";
      row.innerHTML = `<div style="flex:1; min-width:0">
          <div class="name" style="white-space:normal"></div>
          <div class="muted" style="font-size:12px">${p.reps} clip${p.reps === 1 ? "" : "s"}${enough ? " · ready ✓" : " · record a few more"}</div>
        </div>
        <button data-act="rec">Record</button>
        <button data-act="del">✕</button>`;
      row.querySelector(".name").textContent = p.text;
      row.querySelector('[data-act="rec"]').onclick = () => {
        // Switch to "specific phrase" mode, prefilled with this sentence.
        document.querySelector('#recMode button[data-mode="phrase"]').click();
        $("customPhrase").value = p.text;
        $("customRecBtn").scrollIntoView({ behavior: "smooth", block: "center" });
        setStatus("teachStatus", `Hold to record: “${p.text}”`);
      };
      row.querySelector('[data-act="del"]').onclick = async () => {
        try { await api(`/api/teach/practice/${p.id}`, { method: "DELETE" }); loadPractice(); }
        catch (e) { setStatus("teachStatus", detail(e), true); }
      };
      el.appendChild(row);
    }
  } catch { card.classList.add("hidden"); }
}

async function refreshTeachStatus() {
  try {
    const s = await api("/api/teach/status");
    const j = s.latest_job;
    const state = j ? j.status : "idle";
    $("trainState").textContent = state;
    let d = `${s.samples_total} clips recorded · ${s.new_since_train}/${s.retrain_threshold} new toward next auto-train.`;
    if (s.active_model_id) d += " Your private model is active. ✅";
    if (j && j.status === "failed" && j.error) d += ` Last run failed: ${j.error}`;
    $("trainDetail").textContent = d;
    // Step-2 hint + train button state.
    const enough = s.samples_total >= 4;
    $("trainHint").textContent = enough
      ? `${s.samples_total} clips ready — train your private model.`
      : `Record at least 4 clips to train (you have ${s.samples_total}).`;
    $("trainNowBtn").disabled = !enough || state === "running" || state === "queued";
    // Live training log — proof it ran.
    const log = $("trainLog");
    if (j && j.log) { log.textContent = j.log.trim().split("\n").slice(-12).join("\n"); log.scrollTop = log.scrollHeight; }
    else log.textContent = "";
  } catch { /* ignore transient */ }
}

// ============================================================================
// NAV / LIFECYCLE
// ============================================================================
function switchTab(tab) {
  for (const b of document.querySelectorAll("nav.tabs button")) b.classList.toggle("active", b.dataset.tab === tab);
  for (const v of ["speak", "voices", "teach"]) $("view-" + v).classList.toggle("hidden", v !== tab);
  if (tab === "voices") loadVoices();
  if (tab === "teach") { refreshTeachStatus(); loadSamples(); loadPractice(); }
}
function initNav() {
  for (const b of document.querySelectorAll("nav.tabs button")) b.onclick = () => switchTab(b.dataset.tab);
}

let wired = false;
async function enterApp() {
  let me;
  try { me = await api("/api/auth/me"); }
  catch { store.token = ""; showAuth(); return; }
  $("auth").classList.add("hidden");
  $("app").classList.remove("hidden");
  $("who").textContent = me.display_name || me.email;
  if (!wired) {
    initSpeak(); initVoices(); initTeach(); initNav();
    $("logout").onclick = () => { store.token = ""; location.reload(); };
    wired = true;
  }
  switchTab("speak");
  await ensureCamera();
  $("talk").disabled = !stream;   // enable Hold-to-talk once the camera is live
  setStatus("speakStatus", stream ? "ready — hold the button and mouth a sentence" : "camera unavailable");
  refreshTeachStatus();
  if (statusTimer) clearInterval(statusTimer);
  statusTimer = setInterval(refreshTeachStatus, 6000);
}
function showAuth() {
  $("app").classList.add("hidden");
  $("auth").classList.remove("hidden");
  renderAuthMode();
}

// boot
$("authBtn").onclick = submitAuth;
$("password").addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth(); });
if (store.token) enterApp(); else showAuth();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
