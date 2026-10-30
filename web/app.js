/* EntDoc Bulk Upload - vanilla JS, no build step.
 * Flow: POST /uploads (presigned S3 POST forms) -> upload each file straight to S3 with
 * per-file progress -> poll GET /jobs?ids=... until every job is PROCESSED or FAILED.
 * With an empty apiBaseUrl (see config.js) the whole flow is simulated ("demo mode"). */
(() => {
  "use strict";
  const API = (window.ENTDOC_CONFIG && window.ENTDOC_CONFIG.apiBaseUrl || "").replace(/\/$/, "");
  const DEMO = !API;
  const MAX_BYTES = 50 * 1024 * 1024;
  const MAX_FILES = 25;
  const PARALLEL = 3;
  const POLL_MS = DEMO ? 700 : 2000;
  const TERMINAL = new Set(["PROCESSED", "FAILED"]);

  const $ = (id) => document.getElementById(id);
  const dropzone = $("dropzone"), input = $("file-input"), list = $("file-list");
  const startBtn = $("start-btn"), clearBtn = $("clear-btn"), alertBox = $("alert");
  const items = []; // {file, id, state, progress, jobId, status, result, error, li}
  let uid = 0, polling = false;

  $("limits-hint").textContent = `PDF only · up to ${MAX_BYTES / 1048576} MB each · ${MAX_FILES} files per batch`;
  if (DEMO) $("mode-badge").hidden = false;

  const fmt = (n) => n == null ? "–" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(2)} MB`;
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const showAlert = (msg) => { alertBox.textContent = msg; alertBox.hidden = !msg; };

  /* ---------- adding files ---------- */
  function addFiles(files) {
    const problems = [];
    for (const f of files) {
      if (!/\.pdf$/i.test(f.name) || (f.type && f.type !== "application/pdf")) { problems.push(`${f.name}: not a PDF`); continue; }
      if (f.size === 0) { problems.push(`${f.name}: file is empty`); continue; }
      if (f.size > MAX_BYTES) { problems.push(`${f.name}: larger than ${MAX_BYTES / 1048576} MB`); continue; }
      if (items.filter((i) => i.state === "queued").length >= MAX_FILES) { problems.push(`${f.name}: batch is full (${MAX_FILES} files)`); continue; }
      const it = { file: f, id: ++uid, state: "queued", progress: 0 };
      it.li = renderItem(it); list.appendChild(it.li); items.push(it);
    }
    showAlert(problems.join("\n"));
    refresh();
  }

  function renderItem(it) {
    const li = el("li");
    li.append(el("div", "fname", it.file.name), el("div", "fmeta"), (() => { const b = el("div", "bar"); b.append(el("i")); return b; })());
    return li;
  }

  function paint(it) {
    const meta = it.li.querySelector(".fmeta"), bar = it.li.querySelector(".bar i");
    const label = { queued: "Ready", uploading: `Uploading ${it.progress}%`, uploaded: "Uploaded – processing…", error: "Failed" }[it.state];
    const text = it.status === "PROCESSED" ? "Processed ✓" : label;
    meta.textContent = `${fmt(it.file.size)} · ${text}`;
    bar.style.width = `${it.state === "uploaded" ? 100 : it.progress}%`;
    it.li.classList.toggle("done", it.status === "PROCESSED");
    it.li.classList.toggle("error", it.state === "error" || it.status === "FAILED");
    let err = it.li.querySelector(".err");
    if (it.error) { if (!err) { err = el("div", "err"); it.li.appendChild(err); } err.textContent = it.error; }
  }

  function refresh() {
    $("queue-panel").hidden = items.length === 0;
    const queued = items.filter((i) => i.state === "queued").length;
    $("count").textContent = `(${items.length})`;
    startBtn.disabled = queued === 0 || items.some((i) => i.state === "uploading");
    items.forEach(paint);
    renderResults();
  }

  /* ---------- upload ---------- */
  async function startUpload() {
    showAlert("");
    const batch = items.filter((i) => i.state === "queued");
    if (!batch.length) return;
    batch.forEach((i) => { i.state = "uploading"; i.progress = 0; });
    refresh();
    try {
      const forms = DEMO ? demoPresign(batch) : await presign(batch);
      const queue = [...forms];
      await Promise.all(Array.from({ length: PARALLEL }, async () => {
        while (queue.length) { const f = queue.shift(); await uploadOne(f.item, f.form); }
      }));
    } catch (e) {
      batch.filter((i) => i.state === "uploading").forEach((i) => fail(i, e.message));
      showAlert(e.message);
    }
    refresh();
    poll();
  }

  async function presign(batch) {
    const res = await fetch(`${API}/uploads`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: batch.map((i) => ({ name: i.file.name, size: i.file.size })) }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Could not start upload (HTTP ${res.status})`);
    (data.rejected || []).forEach((r) => fail(batch[r.index], r.reason));
    return data.uploads.map((u) => { const item = batch[u.index]; item.jobId = u.job_id; return { item, form: u }; });
  }

  function uploadOne(item, form) {
    return new Promise((resolve) => {
      if (DEMO) return demoUpload(item, resolve);
      const fd = new FormData();
      Object.entries(form.fields).forEach(([k, v]) => fd.append(k, v));
      fd.append("file", item.file); // must be the last field
      const xhr = new XMLHttpRequest();
      xhr.open("POST", form.url);
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) { item.progress = Math.round((e.loaded / e.total) * 100); paint(item); } };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) { item.state = "uploaded"; item.progress = 100; item.status = "PROCESSING"; }
        else fail(item, `Upload rejected (HTTP ${xhr.status})`);
        refresh(); resolve();
      };
      xhr.onerror = () => { fail(item, "Network error while uploading"); refresh(); resolve(); };
      xhr.send(fd);
    });
  }

  function fail(item, msg) { item.state = "error"; item.error = msg; item.status = "FAILED"; }

  /* ---------- polling job status ---------- */
  async function poll() {
    if (polling) return; polling = true;
    try {
      while (true) {
        const pending = items.filter((i) => i.state === "uploaded" && !TERMINAL.has(i.status));
        if (!pending.length) break;
        await new Promise((r) => setTimeout(r, POLL_MS));
        const jobs = DEMO ? demoStatus(pending) : await fetchStatus(pending);
        for (const j of jobs) {
          const it = pending.find((p) => p.jobId === j.job_id); if (!it) continue;
          it.status = j.status; it.result = j.result; if (j.error) it.error = j.error;
          if (j.status === "FAILED") it.state = "error";
        }
        refresh();
      }
    } catch (e) { showAlert(`Lost contact with the server: ${e.message}`); }
    finally { polling = false; }
  }

  async function fetchStatus(pending) {
    const res = await fetch(`${API}/jobs?ids=${pending.map((p) => p.jobId).join(",")}`);
    if (!res.ok) throw new Error(`status check failed (HTTP ${res.status})`);
    return (await res.json()).jobs;
  }

  /* ---------- results list ---------- */
  function renderResults() {
    const done = items.filter((i) => i.state === "uploaded" || i.status === "FAILED" || i.status === "PROCESSED");
    $("results-panel").hidden = done.length === 0;
    const body = $("results-body"); body.replaceChildren();
    let ok = 0, bad = 0;
    for (const it of done) {
      const status = it.status === "PROCESSED" ? "PROCESSED" : it.status === "FAILED" ? "FAILED" : "PROCESSING";
      status === "PROCESSED" ? ok++ : status === "FAILED" ? bad++ : 0;
      const tr = el("tr"), name = el("td", null, it.file.name), st = el("td"), pages = el("td", null, it.result ? it.result.pages : "–");
      const pill = el("span", `pill ${status}`, status === "PROCESSED" ? "Processed" : status === "FAILED" ? "Failed" : "Processing…"); st.append(pill);
      if (it.error && status === "FAILED") st.append(el("span", "small", it.error));
      const size = el("td", null, it.result ? `${fmt(it.result.input_bytes)} → ${fmt(it.result.output_bytes)}${it.result.reduction_pct > 0 ? ` (−${it.result.reduction_pct}%)` : ""}` : fmt(it.file.size));
      const act = el("td");
      if (it.result && it.result.download_url) { const a = el("a", null, "Download"); a.href = it.result.download_url; a.rel = "noopener"; act.append(a); }
      tr.append(name, st, pages, size, act); body.append(tr);
    }
    $("summary").textContent = `${ok} processed · ${bad} failed · ${done.length - ok - bad} in progress`;
  }

  /* ---------- demo mode (no backend) ---------- */
  function demoPresign(batch) { return batch.map((item) => { item.jobId = `demo-${item.id}`; return { item, form: {} }; }); }
  function demoUpload(item, resolve) {
    const t = setInterval(() => {
      item.progress = Math.min(100, item.progress + 8 + Math.random() * 14 | 0); paint(item);
      if (item.progress >= 100) { clearInterval(t); item.state = "uploaded"; item.status = "PROCESSING"; item.startedAt = Date.now(); refresh(); resolve(); }
    }, 120);
  }
  function demoStatus(pending) {
    return pending.filter((i) => Date.now() - i.startedAt > 1500 + (i.id % 3) * 700).map((i) => i.file.size % 7 === 0
      ? { job_id: i.jobId, status: "FAILED", error: "PDF is password-protected" }
      : { job_id: i.jobId, status: "PROCESSED", result: { pages: 1 + (i.file.size % 12), input_bytes: i.file.size, output_bytes: Math.round(i.file.size * 0.62), reduction_pct: 38, download_url: "#" } });
  }

  /* ---------- wiring ---------- */
  dropzone.addEventListener("click", () => input.click());
  dropzone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { addFiles([...input.files]); input.value = ""; });
  ["dragenter", "dragover"].forEach((t) => dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.remove("over"); }));
  dropzone.addEventListener("drop", (e) => addFiles([...e.dataTransfer.files]));
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
  startBtn.addEventListener("click", startUpload);
  clearBtn.addEventListener("click", () => {
    for (let n = items.length - 1; n >= 0; n--) if (items[n].state === "error" || items[n].status === "PROCESSED") { items[n].li.remove(); items.splice(n, 1); }
    refresh();
  });
  refresh();
})();
