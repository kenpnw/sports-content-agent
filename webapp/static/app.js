const state = {
  activeJobId: null,
  pollHandle: null,
};

const sampleInput = document.body.dataset.sampleInput;

const statusBanner = document.getElementById("job-status-banner");
const stepsEl = document.getElementById("steps");
const logsEl = document.getElementById("logs");
const jobListEl = document.getElementById("job-list");
const overviewEl = document.getElementById("overview");
const hupuPreviewEl = document.getElementById("hupu-preview");
const douyinPreviewEl = document.getElementById("douyin-preview");
const hupuPublishEl = document.getElementById("hupu-publish");
const douyinPublishEl = document.getElementById("douyin-publish");
const posterWrapEl = document.getElementById("poster-wrap");

function setBanner(status, text) {
  statusBanner.className = `status-banner ${status}`;
  statusBanner.textContent = text;
}

function renderJobs(jobs) {
  jobListEl.innerHTML = "";
  if (!jobs.length) {
    jobListEl.innerHTML = `<div class="empty-state">还没有任务，先跑一次。</div>`;
    return;
  }
  for (const job of jobs) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `job-item ${job.id === state.activeJobId ? "active" : ""}`;
    item.innerHTML = `
      <strong>${job.source === "fetch_today" ? "Live Fetch" : "Local Input"} · ${job.status}</strong>
      <small>${job.created_at}${job.team ? ` · ${job.team}` : ""}</small>
    `;
    item.addEventListener("click", () => {
      state.activeJobId = job.id;
      fetchJob(job.id);
      startPolling();
      renderJobs(jobs);
    });
    jobListEl.appendChild(item);
  }
}

function renderSteps(steps) {
  stepsEl.innerHTML = "";
  if (!steps.length) {
    stepsEl.innerHTML = `<div class="empty-state">任务开始后，这里会实时显示后端步骤。</div>`;
    return;
  }
  for (const step of steps) {
    const card = document.createElement("article");
    card.className = "step-card";
    card.innerHTML = `
      <header>
        <strong>${step.stage}</strong>
        <span class="badge ${step.status}">${step.status}</span>
      </header>
      <div>${step.message}</div>
    `;
    stepsEl.appendChild(card);
  }
}

function renderLogs(logs) {
  logsEl.innerHTML = "";
  if (!logs.length) {
    logsEl.innerHTML = `<div class="empty-state">任务日志会在这里滚动出现。</div>`;
    return;
  }
  for (const log of logs.slice().reverse()) {
    const line = document.createElement("article");
    line.className = "log-line";
    line.innerHTML = `<span class="log-time">${log.timestamp} · ${log.level}</span>${log.message}`;
    logsEl.appendChild(line);
  }
}

function renderPublishPlan(target, plan) {
  if (!plan) {
    target.innerHTML = `<div class="empty-state">暂无发布计划</div>`;
    return;
  }
  target.innerHTML = `
    <div class="publish-status">${plan.status}</div>
    <div class="meta-line">${plan.mode}</div>
    <div><strong>${plan.title}</strong></div>
    <div class="meta-line">${plan.payload_path || ""}</div>
    <ul>${(plan.notes || []).map((note) => `<li>${note}</li>`).join("")}</ul>
  `;
}

function renderResult(result) {
  if (!result) {
    overviewEl.innerHTML = "运行后会在这里看到比赛摘要、可视化资产和平台发布计划。";
    hupuPreviewEl.textContent = "暂无内容";
    douyinPreviewEl.textContent = "暂无内容";
    hupuPublishEl.textContent = "暂无发布计划";
    douyinPublishEl.textContent = "暂无发布计划";
    posterWrapEl.textContent = "暂无海报";
    return;
  }

  overviewEl.innerHTML = `
    <strong>${result.game.winner}</strong> · ${result.game.scoreline}<br>
    <span class="meta-line">${result.game.date} · ${result.game.venue}</span><br>
    <span class="meta-line">${result.game.headline || ""}</span><br>
    <span class="meta-line">Primary Driver: ${result.game.primary_driver || "n/a"}</span><br>
    <span class="meta-line">Output Root: ${result.output_root}</span>
  `;

  hupuPreviewEl.textContent = result.platforms.hupu.preview || "";
  douyinPreviewEl.textContent = result.platforms.douyin.preview || "";
  renderPublishPlan(hupuPublishEl, result.platforms.hupu.publish);
  renderPublishPlan(douyinPublishEl, result.platforms.douyin.publish);

  if (result.assets && result.assets.douyin_poster) {
    const posterUrl = `/api/files?path=${encodeURIComponent(result.assets.douyin_poster)}`;
    posterWrapEl.innerHTML = `<img src="${posterUrl}" alt="Douyin poster preview">`;
  } else {
    posterWrapEl.innerHTML = `<div class="empty-state">暂无海报</div>`;
  }
}

async function fetchJobs() {
  const res = await fetch("/api/jobs");
  const data = await res.json();
  renderJobs(data.jobs || []);
}

async function fetchJob(jobId) {
  const res = await fetch(`/api/jobs/${jobId}`);
  const job = await res.json();
  setBanner(job.status, job.error ? `${job.status}: ${job.error}` : `当前任务状态：${job.status}`);
  renderSteps(job.steps || []);
  renderLogs(job.logs || []);
  renderResult(job.result);
  if (job.status === "completed" || job.status === "failed") {
    stopPolling();
  }
}

function startPolling() {
  stopPolling();
  if (!state.activeJobId) return;
  state.pollHandle = setInterval(() => fetchJob(state.activeJobId), 1500);
}

function stopPolling() {
  if (state.pollHandle) {
    clearInterval(state.pollHandle);
    state.pollHandle = null;
  }
}

document.getElementById("job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const source = document.getElementById("source").value;
  const team = document.getElementById("team").value.trim();
  const inputPath = document.getElementById("input-path").value.trim();
  const payload = { source, team, input_path: inputPath };

  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const job = await res.json();
  state.activeJobId = job.id;
  setBanner("running", "任务已启动，正在拉起后台流程。");
  await fetchJobs();
  await fetchJob(job.id);
  startPolling();
});

document.getElementById("use-sample").addEventListener("click", () => {
  document.getElementById("source").value = "input";
  document.getElementById("input-path").value = sampleInput;
});

window.addEventListener("load", async () => {
  await fetchJobs();
  renderSteps([]);
  renderLogs([]);
  renderResult(null);
});
