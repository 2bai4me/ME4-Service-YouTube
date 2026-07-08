// ME4-YouTube Framie — Job-Detail-View mit Live-Log + Auto-Close
const $ = (id) => document.getElementById(id);

let logEntries = [];
let currentJobId = null;
let currentWorkerId = null;
let sseSource = null;
let logIndex = 0;
let closeCountdownTimer = null;
let closeCountdownValue = 0;

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso * 1000);
  return d.toLocaleTimeString("de-DE", { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, '0');
}

function fmtDur(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms/1000).toFixed(1)}s`;
  return `${(ms/60000).toFixed(1)}m`;
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

// ============================================================
// LOG-SYSTEM
// ============================================================

const log = (level, category, message, data) => {
  const ts = new Date();
  const entry = {
    id: ++logIndex,
    ts,
    level,
    category,
    message,
    data: data || null,
  };
  logEntries.push(entry);
  renderLogEntry(entry);
  $("logStats").textContent = `${logEntries.length} Eintrag${logEntries.length !== 1 ? 'e' : ''}`;
  const logEl = $("log");
  logEl.scrollTop = logEl.scrollHeight;
};

function renderLogEntry(e) {
  const el = document.createElement("div");
  el.className = `log-entry log-${e.level}`;
  el.id = `log-${e.id}`;
  const time = e.ts.toLocaleTimeString("de-DE", { hour12: false }) + "." + String(e.ts.getMilliseconds()).padStart(3, '0');
  const icon = {
    info: "ℹ", success: "✓", warn: "⚠", error: "✗", http: "⇄", worker: "⚙", db: "💾", sse: "📡"
  }[e.level] || "·";
  let html = `<span class="ts">${time}</span> <span class="icon">${icon}</span> `;
  if (e.category) html += `<span class="cat">[${escapeHtml(e.category)}]</span> `;
  html += `<span class="msg">${escapeHtml(e.message)}</span>`;
  if (e.data) {
    const json = typeof e.data === 'object' ? JSON.stringify(e.data, null, 0) : String(e.data);
    html += ` <span class="data">${escapeHtml(json.length > 200 ? json.slice(0, 200) + '…' : json)}</span>`;
  }
  el.innerHTML = html;
  $("log").appendChild(el);
};

function clearLog() {
  if (!confirm("Log wirklich leeren?")) return;
  logEntries = [];
  $("log").innerHTML = "";
  $("logStats").textContent = "0 Eintraege";
  log("info", "ui", "Log vom User geleert");
}

function exportLog() {
  const blob = new Blob([JSON.stringify(logEntries, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `youtube-job-log-${currentJobId || 'no-job'}.json`;
  a.click();
  URL.revokeObjectURL(url);
  log("info", "ui", `Log exportiert: ${logEntries.length} Eintraege`);
}

// ============================================================
// JOB-VERARBEITUNG
// ============================================================

let workers = [];

async function loadWorkers() {
  try {
    const r = await fetch("/api/health");
    const d = await r.json();
    if (d.loadbalancer && d.loadbalancer.workers) {
      workers = d.loadbalancer.workers;
      $("workerStats").textContent = `${workers.filter(w => w.status === "up").length}/${workers.length} online`;
    }
    return workers;
  } catch (e) {
    return [];
  }
}

function renderWorkers() {
  const list = $("worker-list");
  if (!workers.length) {
    list.innerHTML = `<li class="empty">Keine Worker verfuegbar</li>`;
    return;
  }
  list.innerHTML = workers
    .map(w => `
    <li class="${currentWorkerId === w.worker_id ? 'active-worker' : ''}">
      <span><strong>${w.worker_id}</strong> · :${w.port}</span>
      <span>
        <span class="pill ${w.status === "up" ? (w.current_load > 0 ? "busy" : "idle") : "down"}">
          ${w.status === "up" ? (w.current_load > 0 ? `busy (${w.current_load})` : "idle") : "down"}
        </span>
        <small style="color:var(--fg-muted); margin-left:0.5rem">${w.total_processed} jobs</small>
      </span>
    </li>`).join("");
}

// ============================================================
// AUTO-CLOSE nach erfolgreichem Process
// ============================================================

function startCloseCountdown(seconds = 3) {
  closeCountdownValue = seconds;
  $("closeHint").style.display = "flex";
  $("closeCountdown").textContent = String(seconds);

  // Expand "Ergebnis" automatisch (fuer sichtbare Bestaetigung)
  $("resultDetails").open = true;

  if (closeCountdownTimer) clearInterval(closeCountdownTimer);
  closeCountdownTimer = setInterval(() => {
    closeCountdownValue--;
    $("closeCountdown").textContent = String(closeCountdownValue);
    if (closeCountdownValue <= 0) {
      clearInterval(closeCountdownTimer);
      closeCountdownTimer = null;
      doClose();
    }
  }, 1000);
}

function cancelCloseCountdown() {
  if (closeCountdownTimer) {
    clearInterval(closeCountdownTimer);
    closeCountdownTimer = null;
  }
  $("closeHint").style.display = "none";
}

function doClose() {
  // Wenn wir in einem iframe sind, Parent informieren
  if (window.parent !== window) {
    log("sse", "sse", "Sende 'close'-Signal an SMproducer-Parent");
    window.parent.postMessage({
      type: "youtube-iframe-close",
      jobId: currentJobId
    }, "*");
  } else {
    // Standalone-Modus: einfach schliessen
    log("info", "ui", "Schliesse Fenster (standalone)");
    window.close();
    // Falls window.close() nicht erlaubt ist, zumindest Status anzeigen
    setTimeout(() => {
      document.body.innerHTML = "<div style='padding:40px;text-align:center;color:#22c55e;font-size:1.5rem'>✓ Job abgeschlossen — Fenster kann geschlossen werden</div>";
    }, 100);
  }
}

// ============================================================
// JOB-VERARBEITUNG
// ============================================================

async function processUrl(url) {
  log("info", "init", `Neuer Process-Auftrag fuer URL`, { url });
  cancelCloseCountdown();

  // 1) Worker-Pool
  log("info", "load-balancer", "Worker-Pool wird abgefragt");
  await loadWorkers();
  log("success", "load-balancer", `Worker-Pool geladen: ${workers.length} Worker verfuegbar`,
      workers.map(w => `${w.worker_id}(${w.status})`).join(", "));
  renderWorkers();

  // 2) Job-ID
  currentJobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
  $("jobId").textContent = currentJobId;
  $("jobUrl").textContent = url;
  $("jobTitle").textContent = "Verarbeitung laeuft…";
  $("jobState").textContent = "running";
  $("jobState").className = "badge running";
  log("info", "init", `Job-ID generiert: ${currentJobId}`);

  // 3) HTTP-Request
  const t0 = performance.now();
  log("http", "http", `POST /api/process gestartet`,
      { endpoint: "/api/process", method: "POST", body: { url, options: { transcript: true, metadata: true, comments: true } } });

  let data;
  try {
    const resp = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": "ob-youtube-key-2026" },
      body: JSON.stringify({
        url,
        options: { transcript: true, metadata: true, comments: true }
      })
    });
    const t1 = performance.now();
    const httpMs = Math.round(t1 - t0);
    log("http", "http", `HTTP ${resp.status} ${resp.statusText} empfangen (${fmtDur(httpMs)})`,
        { status: resp.status, statusText: resp.statusText, duration_ms: httpMs });

    if (!resp.ok) {
      const errText = await resp.text();
      log("error", "http", `Server-Fehler: ${errText.slice(0, 200)}`, { error: errText });
      $("jobState").textContent = "error";
      $("jobState").className = "badge error";
      $("jobTitle").textContent = "Fehler";
      return;
    }
    data = await resp.json();
    log("success", "http", `Response JSON deserialisiert (${Object.keys(data).length} Top-Level-Keys)`,
        { keys: Object.keys(data) });
  } catch (e) {
    log("error", "http", `Exception: ${e.message}`, { error: e.message });
    $("jobState").textContent = "error";
    $("jobState").className = "badge error";
    $("jobTitle").textContent = "Fehler";
    return;
  }

  // 4) Worker-Info
  if (data.worker_id) {
    currentWorkerId = data.worker_id;
    $("jobWorker").textContent = `${data.worker_id}`;
    log("worker", "worker", `Worker hat den Job verarbeitet: ${data.worker_id}`, { worker_id: data.worker_id });
  }

  // 5) Dauer
  if (data.duration_sec) {
    $("jobDuration").textContent = `${data.duration_sec.toFixed(2)}s`;
    log("info", "timing", `Worker-Processing-Dauer: ${data.duration_sec.toFixed(2)}s`);
  }

  // 6) Metadaten
  const m = data.metadata || {};
  if (m.title) {
    $("jobTitle").textContent = m.title;
    log("success", "metadata", `Video-Metadaten extrahiert: "${m.title}"`,
        { title: m.title, channel: m.channel, duration: m.duration_sec, views: m.view_count, likes: m.like_count });
  }

  // 7) Transkript
  const t = data.transcript || {};
  if (t.snippet_count) {
    log("success", "transcript", `Transkript extrahiert: ${t.snippet_count} Snippets (Sprache: ${t.language || "?"})`,
        { snippet_count: t.snippet_count, language: t.language });
  } else {
    log("warn", "transcript", "Kein Transkript verfuegbar (Video hat evtl. keine Untertitel)");
  }

  // 8) Comments
  if (Array.isArray(data.comments)) {
    log("success", "comments", `${data.comments.length} Comments extrahiert`);
  }

  // 9) Chapters
  if (Array.isArray(m.chapters)) {
    log("success", "chapters", `${m.chapters.length} Chapter-Marker extrahiert`);
  }

  // 10) Persistenz
  const pers = data._persistence || {};
  if (pers.id) {
    log("db", "persistence", `Ergebnis in DB gespeichert (Row-ID: ${pers.id})`,
        { id: pers.id, json_path: pers.json_path });
  }

  // 11) Render Ergebnis + Persistenz
  renderResult(data);
  renderWorkers();

  // 12) Job-Status done
  $("jobState").textContent = "done";
  $("jobState").className = "badge done";
  log("success", "init", `Job ${currentJobId} erfolgreich abgeschlossen`);

  // 13) postMessage an SMproducer-Parent mit ALLEN Daten
  if (window.parent !== window) {
    log("sse", "sse", "Sende 'youtube-job-complete' an Parent-Frame (alle Daten)");
    window.parent.postMessage({
      type: "youtube-job-complete",
      jobId: currentJobId,
      // Vollstaendige Daten fuer SMproducer zum Speichern
      url,
      result: {
        video_id: m.video_id,
        title: m.title,
        channel: m.channel,
        channel_id: m.channel_id,
        duration_sec: m.duration_sec,
        view_count: m.view_count,
        like_count: m.like_count,
        upload_date: m.upload_date,
        language: m.language,
        thumbnail: m.thumbnail,
        description: m.description,
        tags: m.tags,
        categories: m.categories,
        chapters: m.chapters,
        transcript: t,
        comments: data.comments,
        worker_id: data.worker_id,
        job_duration_sec: data.duration_sec,
        // Framie-Resultate
        framie: {
          json_path: pers.json_path,
          db_row_id: pers.id,
          db_path: pers.db_path,
          persistence_status: pers.status,
        }
      }
    }, "*");
    log("success", "sse", "Daten an SMproducer gesendet. Starte Auto-Close-Countdown (3s)");

    // 14) Auto-Close Countdown starten
    startCloseCountdown(3);
  } else {
    log("info", "sse", "Standalone-Modus (kein Parent-Frame). Kein Auto-Close.");
  }
}

function renderResult(data) {
  const card = $("resultDetails");
  const box = $("resultContent");
  card.open = true;
  card.style.display = "block";

  const m = data.metadata || {};
  const t = data.transcript || {};
  const c = data.comments || [];
  const tags = (m.tags || []).slice(0, 8).join(", ");
  const chapters = m.chapters || [];

  const rows = [
    ["Title", m.title],
    ["Channel", m.channel],
    ["Video-ID", m.video_id],
    ["Dauer", `${m.duration_sec || 0}s`],
    ["Views / Likes", `${(m.view_count||0).toLocaleString()} / ${(m.like_count||0).toLocaleString()}`],
    ["Upload", m.upload_date],
    ["Language", m.language],
    ["Tags", tags],
    ["Transkript", `${t.snippet_count || 0} Snippets`],
    ["Comments", `${c.length}`],
    ["Chapters", `${chapters.length}`],
    ["Worker", data.worker_id],
  ];
  box.innerHTML = `<div class="meta-grid">${
    rows.map(([k, v]) => `<div class="label">${escapeHtml(k)}</div><div class="value">${escapeHtml(v || '—')}</div>`).join("")
  }</div>`;
  $("resultStats").textContent = `${rows.length} Felder`;

  const persCard = $("persistenceDetails");
  const persBox = $("persistenceContent");
  const pers = data._persistence || {};
  if (pers.id) {
    persCard.style.display = "block";
    const persRows = [
      ["DB-Row-ID", pers.id],
      ["Job-ID", pers.job_id],
      ["JSON-Pfad", pers.json_path],
      ["DB-Pfad", pers.db_path],
      ["Status", pers.status],
    ];
    persBox.innerHTML = `<div class="meta-grid">${
      persRows.map(([k, v]) => `<div class="label">${escapeHtml(k)}</div><div class="value">${escapeHtml(v || '—')}</div>`).join("")
    }</div>`;
    $("persistenceStats").textContent = `Row #${pers.id}`;
  }
}

// ============================================================
// SSE
// ============================================================

function connectSSE() {
  if (sseSource) sseSource.close();
  sseSource = new EventSource("/api/framie/stream");
  sseSource.addEventListener("open", () => {
    $("conn-status").classList.remove("disconnected");
    $("conn-status").querySelector("span:last-child").textContent = "live";
    log("sse", "sse", "SSE-Stream verbunden: /api/framie/stream");
  });
  sseSource.addEventListener("snapshot", (e) => {
    try {
      const snap = JSON.parse(e.data);
      log("sse", "sse", `Snapshot empfangen: ${snap.active?.length || 0} active, ${snap.recent?.length || 0} recent`);
    } catch (_) {}
  });
  sseSource.addEventListener("job.created", (e) => {
    try {
      const j = JSON.parse(e.data);
      log("sse", "status", `SSE-Event: job.created (${j.job_id})`);
    } catch (_) {}
  });
  sseSource.addEventListener("job.updated", (e) => {
    try {
      const j = JSON.parse(e.data);
      log("sse", "status", `SSE-Event: job.updated (${j.step} ${(j.progress*100).toFixed(0)}%)`);
    } catch (_) {}
  });
  sseSource.addEventListener("job.finished", (e) => {
    try {
      const j = JSON.parse(e.data);
      log("sse", "status", `SSE-Event: job.finished (${j.state})`);
    } catch (_) {}
  });
  sseSource.addEventListener("error", () => {
    $("conn-status").classList.add("disconnected");
    $("conn-status").querySelector("span:last-child").textContent = "getrennt";
    log("warn", "sse", "SSE-Stream getrennt, reconnect in 3s");
    setTimeout(connectSSE, 3000);
  });
}

// User kann Auto-Close abbrechen durch Klick auf den Log oder andere Sections
document.addEventListener("click", (e) => {
  if (closeCountdownTimer && (e.target.closest(".collapsible") || e.target.closest("#closeHint"))) {
    cancelCloseCountdown();
    log("info", "ui", "Auto-Close abgebrochen durch User-Interaktion");
  }
});

// ============================================================
// INIT
// ============================================================

(async function init() {
  try {
    const r = await fetch("/api/manifest");
    const d = await r.json();
    if (d.version) $("version").textContent = "v" + d.version;
  } catch (_) {}

  connectSSE();
  await loadWorkers();
  renderWorkers();
  log("info", "init", "Framie-UI initialisiert. Bereit fuer Job-Verarbeitung.");

  const params = new URLSearchParams(window.location.search);
  const inputUrl = params.get("url");
  if (inputUrl) {
    log("info", "init", `URL-Parameter erkannt: ${inputUrl}`);
    setTimeout(() => processUrl(inputUrl), 500);
  } else {
    log("info", "init", "Kein URL-Parameter - warte auf Aufruf (mit ?url=...)");
    $("jobTitle").textContent = "Bereit. Job wird ueber URL-Parameter ?url=... gestartet";
  }

  setInterval(async () => { await loadWorkers(); renderWorkers(); }, 10000);
})();
