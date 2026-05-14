const state = {
  reports: [],
  reportId: "",
  report: null,
  manifest: null,
  selectedClipIndex: -1,
  selectedSegmentIndex: -1,
};

const els = {
  reportSelect: document.getElementById("reportSelect"),
  reportMeta: document.getElementById("reportMeta"),
  clipTimeline: document.getElementById("clipTimeline"),
  reportTitle: document.getElementById("reportTitle"),
  analysisStats: document.getElementById("analysisStats"),
  fullAnalysis: document.getElementById("fullAnalysis"),
  segmentList: document.getElementById("segmentList"),
  clipPreview: document.getElementById("clipPreview"),
  evidenceList: document.getElementById("evidenceList"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function fileNameFromPath(path) {
  if (!path) {
    return "";
  }
  const normalized = String(path).replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() || "";
}

function clipUrl(path) {
  const filename = fileNameFromPath(path);
  if (!state.reportId || !filename) {
    return "";
  }
  return `/static-clips/${encodeURIComponent(state.reportId)}/${encodeURIComponent(filename)}`;
}

function clips() {
  return Array.isArray(state.manifest?.clips) ? state.manifest.clips : [];
}

function segments() {
  return Array.isArray(state.report?.key_segments) ? state.report.key_segments : [];
}

function segmentForClip(clip, clipIndex) {
  const byEvidence = segments().findIndex((segment) => {
    const evidence = Array.isArray(segment.evidence) ? segment.evidence : [];
    return evidence.some((item) => String(item) === String(clip.observation_id));
  });
  if (byEvidence >= 0) {
    return byEvidence;
  }
  return clipIndex < segments().length ? clipIndex : -1;
}

function clipForSegment(segment, segmentIndex) {
  const evidence = Array.isArray(segment?.evidence) ? segment.evidence.map(String) : [];
  const byObservation = clips().findIndex((clip) => evidence.includes(String(clip.observation_id)));
  if (byObservation >= 0) {
    return byObservation;
  }
  return segmentIndex < clips().length ? segmentIndex : -1;
}

function formatTimeWindow(clip) {
  const start = Number(clip?.start_seconds);
  const end = Number(clip?.end_seconds);
  if (!Number.isFinite(start) || !Number.isFinite(end)) {
    return "";
  }
  return `${start.toFixed(1)}s - ${end.toFixed(1)}s`;
}

function splitSentences(text) {
  const parts = String(text || "")
    .replace(/\r\n/g, "\n")
    .split(/(?<=[。！？.!?])\s+|(?<=\n)\s*/u)
    .map((part) => part.trim())
    .filter(Boolean);
  return parts.length ? parts : [String(text || "").trim()].filter(Boolean);
}

function provenanceClass(text, fallback = "narrative") {
  const value = String(text || "").toLowerCase();
  if (value.includes("可能") || value.includes("或许") || value.includes("需要") || value.includes("future") || value.includes("adjust")) {
    return "speculative";
  }
  if (/\d/.test(value) || value.includes("event:") || value.includes("命中") || value.includes("篮板") || value.includes("助攻")) {
    return "fact";
  }
  return fallback;
}

function classifyEvidence(value) {
  const text = String(value || "");
  if (/^event:\d+/i.test(text)) {
    return "PBP 行";
  }
  if (/^poss_/i.test(text)) {
    return "observation_id";
  }
  if (/\d/.test(text) && /(分|篮板|助攻|抢断|盖帽|PTS|AST|REB|3PT|DUNK|MISS)/i.test(text)) {
    return "court_report / stat";
  }
  return "evidence";
}

function setLoading(message) {
  els.fullAnalysis.className = "full-analysis empty-state";
  els.fullAnalysis.textContent = message;
  els.segmentList.innerHTML = "";
  els.clipTimeline.innerHTML = "";
  els.clipPreview.className = "clip-preview empty-state";
  els.clipPreview.textContent = "点击左侧 clip 或中间 segment 后，这里会显示 GIF 预览。";
  els.evidenceList.className = "evidence-list empty-state";
  els.evidenceList.textContent = "尚未选中 segment。";
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function loadReportList() {
  state.reports = await fetchJson("/api/tactical/list");
  els.reportSelect.innerHTML = "";
  if (!state.reports.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无已生成 report";
    els.reportSelect.appendChild(option);
    setLoading("没有找到 data/generated/video_scout/*/report.json。");
    return;
  }

  for (const report of state.reports) {
    const option = document.createElement("option");
    option.value = report.report_id;
    option.textContent = `${report.report_id} · ${report.title || "未命名报告"}`;
    els.reportSelect.appendChild(option);
  }

  const preferred = state.reports.find((report) => report.report_id === "real_okc_lal_g1_v1");
  await loadReport(preferred?.report_id || state.reports[0].report_id);
}

async function loadReport(reportId) {
  if (!reportId) {
    return;
  }
  state.reportId = reportId;
  state.selectedClipIndex = -1;
  state.selectedSegmentIndex = -1;
  els.reportSelect.value = reportId;
  setLoading("战术报告加载中...");

  const payload = await fetchJson(`/api/tactical/report/${encodeURIComponent(reportId)}`);
  state.report = payload.report || {};
  state.manifest = payload.clip_manifest || {};
  state.selectedClipIndex = clips().length ? 0 : -1;
  state.selectedSegmentIndex = segments().length ? segmentForClip(clips()[0] || {}, 0) : -1;

  renderAll();
}

function renderAll() {
  renderHeader();
  renderTimeline();
  renderAnalysis();
  renderSegments();
  renderSidePanel();
}

function renderHeader() {
  const report = state.reports.find((item) => item.report_id === state.reportId);
  els.reportTitle.textContent = state.report?.title || report?.title || state.reportId;
  els.reportMeta.innerHTML = `
    <div>${escapeHtml(report?.title || state.report?.title || state.reportId)}</div>
    <div>${clips().length} 个 clips · ${segments().length} 个 key segments</div>
  `;
  els.analysisStats.innerHTML = `
    <div>report: ${escapeHtml(state.reportId)}</div>
    <div>clips: ${clips().length} / segments: ${segments().length}</div>
  `;
}

function renderTimeline() {
  if (!clips().length) {
    els.clipTimeline.innerHTML = '<div class="empty-state">clip_manifest 中没有 clips。</div>';
    return;
  }

  els.clipTimeline.innerHTML = clips()
    .map((clip, index) => {
      const gif = clipUrl(clip.gif_path);
      const tag = Array.isArray(clip.tactic_tags) ? clip.tactic_tags[0] : "";
      const players = Array.isArray(clip.players) ? clip.players.join(", ") : "";
      const active = index === state.selectedClipIndex ? " active" : "";
      return `
        <button class="clip-row${active}" data-clip-index="${index}">
          ${gif ? `<img class="clip-thumb" src="${gif}" alt="${escapeHtml(clip.label || "clip")}">` : '<div class="clip-thumb"></div>'}
          <span>
            <span class="clip-time">Q${escapeHtml(clip.period || "?")} · ${escapeHtml(clip.clock || "")}</span>
            <span class="clip-tags">${escapeHtml(tag || clip.label || "tactic")}</span>
            <span class="clip-players">${escapeHtml(players || "players unknown")}</span>
            <span class="clip-description">${escapeHtml(clip.event_description || formatTimeWindow(clip))}</span>
          </span>
        </button>
      `;
    })
    .join("");

  els.clipTimeline.querySelectorAll(".clip-row").forEach((row) => {
    row.addEventListener("click", () => {
      const clipIndex = Number(row.dataset.clipIndex);
      state.selectedClipIndex = clipIndex;
      state.selectedSegmentIndex = segmentForClip(clips()[clipIndex], clipIndex);
      renderAll();
    });
  });
}

function renderAnalysis() {
  const text = state.report?.full_analysis || state.report?.executive_summary || "";
  if (!text) {
    els.fullAnalysis.className = "full-analysis empty-state";
    els.fullAnalysis.textContent = "report.json 中没有 full_analysis。";
    return;
  }

  els.fullAnalysis.className = "full-analysis";
  els.fullAnalysis.innerHTML = splitSentences(text)
    .map((sentence) => {
      const cls = provenanceClass(sentence, "narrative");
      return `<span class="sentence ${cls}" title="confidence: 段落级可视化，当前版本无句子级 provenance">${escapeHtml(sentence)}</span> `;
    })
    .join("");
}

function renderSegments() {
  if (!segments().length) {
    els.segmentList.innerHTML = '<div class="empty-state">report.json 中没有 key_segments。</div>';
    return;
  }

  els.segmentList.innerHTML = segments()
    .map((segment, index) => {
      const active = index === state.selectedSegmentIndex ? " active" : "";
      const confidence = Number(segment.confidence);
      const confidenceText = Number.isFinite(confidence) ? `${Math.round(confidence * 100)}%` : "n/a";
      return `
        <article class="segment-card${active}" data-segment-index="${index}">
          <header class="segment-head">
            <div>
              <h3>Q${escapeHtml(segment.period || "?")} ${escapeHtml(segment.clock || segment.timecode || "")}</h3>
              <div class="segment-meta">${escapeHtml(segment.tactic_type || "tactic")} · confidence ${confidenceText}</div>
            </div>
            <div class="segment-meta">#${index + 1}</div>
          </header>
          <div class="segment-body">
            ${renderSegmentField("observation", segment.observation, "fact", index)}
            ${renderSegmentField("decision", segment.decision_analysis || segment.decision, "speculative", index)}
            ${renderSegmentField("win_loss", segment.win_loss_impact || segment.win_loss, "narrative", index)}
          </div>
        </article>
      `;
    })
    .join("");

  els.segmentList.querySelectorAll(".segment-card, .segment-field").forEach((node) => {
    node.addEventListener("click", (event) => {
      const target = event.currentTarget;
      const segmentIndex = Number(target.dataset.segmentIndex || target.closest(".segment-card")?.dataset.segmentIndex);
      state.selectedSegmentIndex = segmentIndex;
      state.selectedClipIndex = clipForSegment(segments()[segmentIndex], segmentIndex);
      renderAll();
    });
  });
}

function renderSegmentField(label, value, cls, index) {
  if (!value) {
    return "";
  }
  return `
    <div class="segment-field ${cls}" data-segment-index="${index}" title="点击展开证据">
      <span class="field-label">${escapeHtml(label)}</span>
      ${escapeHtml(value)}
    </div>
  `;
}

function renderSidePanel() {
  const clip = clips()[state.selectedClipIndex];
  const segment = segments()[state.selectedSegmentIndex];
  renderPreview(clip);
  renderEvidence(segment, clip);
}

function renderPreview(clip) {
  if (!clip) {
    els.clipPreview.className = "clip-preview empty-state";
    els.clipPreview.textContent = "尚未选中 clip。";
    return;
  }

  const gif = clipUrl(clip.gif_path);
  const mp4 = clipUrl(clip.output_path);
  const title = `Q${clip.period || "?"} ${clip.clock || ""} · ${clip.label || ""}`;
  els.clipPreview.className = "clip-preview";
  els.clipPreview.innerHTML = `
    <div class="preview-title">
      <strong>${escapeHtml(title)}</strong>
      <div class="segment-meta">${escapeHtml(formatTimeWindow(clip))}</div>
    </div>
    ${gif ? `<img id="previewGif" class="preview-media" src="${gif}" alt="${escapeHtml(clip.label || "GIF preview")}">` : '<div class="preview-media empty-state">没有 GIF 文件</div>'}
    <div class="preview-controls">
      <button type="button" id="replayGif">重播 GIF</button>
      ${mp4 ? `<a href="${mp4}" target="_blank" rel="noreferrer">打开 MP4</a>` : ""}
    </div>
  `;

  const replay = document.getElementById("replayGif");
  const preview = document.getElementById("previewGif");
  if (replay && preview) {
    replay.addEventListener("click", () => {
      const src = gif.split("?")[0];
      preview.src = `${src}?t=${Date.now()}`;
    });
  }
}

function renderEvidence(segment, clip) {
  const items = [];
  if (clip?.observation_id) {
    items.push({ source: "clip_manifest observation_id", value: clip.observation_id });
  }
  if (clip?.event_description) {
    items.push({ source: "clip_manifest event", value: clip.event_description });
  }
  for (const item of Array.isArray(segment?.evidence) ? segment.evidence : []) {
    items.push({ source: classifyEvidence(item), value: item });
  }

  if (!items.length) {
    els.evidenceList.className = "evidence-list empty-state";
    els.evidenceList.textContent = "当前 segment 没有 evidence 字段。";
    return;
  }

  els.evidenceList.className = "evidence-list";
  els.evidenceList.innerHTML = items
    .map((item) => `
      <div class="evidence-card">
        <div class="evidence-source">${escapeHtml(item.source)}</div>
        <div class="evidence-value">${escapeHtml(item.value)}</div>
      </div>
    `)
    .join("");
}

els.reportSelect.addEventListener("change", () => {
  loadReport(els.reportSelect.value).catch((error) => {
    setLoading(`加载报告失败：${error.message}`);
    els.fullAnalysis.className = "full-analysis error-state";
  });
});

loadReportList().catch((error) => {
  setLoading(`加载战术报告列表失败：${error.message}`);
  els.fullAnalysis.className = "full-analysis error-state";
});
