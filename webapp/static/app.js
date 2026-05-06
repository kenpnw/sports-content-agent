const state = {
  activeJobId: null,
  pollHandle: null,
};

const sampleInput = document.body.dataset.sampleInput;
const sampleReplay = document.body.dataset.sampleReplay;
const sampleVideoScout = document.body.dataset.sampleVideoScout;

const statusBanner = document.getElementById("job-status-banner");
const stepsEl = document.getElementById("steps");
const logsEl = document.getElementById("logs");
const jobListEl = document.getElementById("job-list");
const overviewEl = document.getElementById("overview");
const realtimePreviewEl = document.getElementById("realtime-preview");
const videoScoutPreviewEl = document.getElementById("video-scout-preview");
const selectionPreviewEl = document.getElementById("selection-preview");
const opportunityPreviewEl = document.getElementById("opportunity-preview");
const topicPreviewEl = document.getElementById("topic-preview");
const controversyPreviewEl = document.getElementById("controversy-preview");
const knowledgePreviewEl = document.getElementById("knowledge-preview");
const dnaPreviewEl = document.getElementById("dna-preview");
const storylinePreviewEl = document.getElementById("storyline-preview");
const personaPreviewEl = document.getElementById("persona-preview");
const forecastPreviewEl = document.getElementById("forecast-preview");
const followupPreviewEl = document.getElementById("followup-preview");
const evidencePreviewEl = document.getElementById("evidence-preview");
const angleLabPreviewEl = document.getElementById("anglelab-preview");
const governancePreviewEl = document.getElementById("governance-preview");
const supervisionPreviewEl = document.getElementById("supervision-preview");
const hupuPreviewEl = document.getElementById("hupu-preview");
const douyinPreviewEl = document.getElementById("douyin-preview");
const hupuPublishEl = document.getElementById("hupu-publish");
const douyinPublishEl = document.getElementById("douyin-publish");
const posterWrapEl = document.getElementById("poster-wrap");

function setBanner(status, text) {
  statusBanner.className = `status-banner ${status}`;
  statusBanner.textContent = text;
}

function emptyHtml(text) {
  return `<div class="empty-state">${text}</div>`;
}

function renderJobs(jobs) {
  jobListEl.innerHTML = "";
  if (!jobs.length) {
    jobListEl.innerHTML = emptyHtml("还没有任务，先跑一次。");
    return;
  }
  for (const job of jobs) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `job-item ${job.id === state.activeJobId ? "active" : ""}`;
    const sourceLabel = job.source === "fetch_today"
      ? "Live Fetch"
      : job.source === "replay_demo"
        ? "Replay Demo"
        : job.source === "video_scout_demo"
          ? "Video Scout"
          : "Local Input";
    item.innerHTML = `
      <strong>${sourceLabel} / ${job.status}</strong>
      <small>${job.created_at}${job.team ? ` / ${job.team}` : ""}</small>
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
    stepsEl.innerHTML = emptyHtml("任务开始后，这里会实时显示后端步骤。");
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
    logsEl.innerHTML = emptyHtml("任务日志会在这里滚动出现。");
    return;
  }
  for (const log of logs.slice().reverse()) {
    const line = document.createElement("article");
    line.className = `log-line log-level-${log.level || "info"}`;
    line.innerHTML = `<span class="log-time">${log.timestamp} / ${log.level}</span>${log.message}`;
    logsEl.appendChild(line);
  }
}

function renderPublishPlan(target, plan) {
  if (!plan) {
    target.innerHTML = emptyHtml("暂无发布计划");
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

function renderSelection(selection) {
  if (!selection || !selection.selected_game) {
    selectionPreviewEl.innerHTML = emptyHtml("暂无选题信息");
    return;
  }
  const selectedGame = selection.selected_game;
  const candidates = selection.candidates || [];
  selectionPreviewEl.innerHTML = `
    <div><strong>${selectedGame.winner}</strong></div>
    <div class="meta-line">${selectedGame.scoreline}</div>
    <div class="meta-line">策略：${selection.strategy || "n/a"}</div>
    <div class="meta-line">总分：${selectedGame.global_topic_score}</div>
    <div class="meta-line">推荐角度：${selectedGame.recommended_angle}</div>
    <div class="meta-line">候选比赛：</div>
    <ul>${candidates
      .slice(0, 5)
      .map(
        (item, index) =>
          `<li>#${index + 1} ${item.matchup} / ${item.global_topic_score} 分 / ${item.recommended_angle}</li>`,
      )
      .join("")}</ul>
  `;
}

function renderOpportunity(editorialLab) {
  const board = editorialLab?.opportunity_board;
  if (!board) {
    opportunityPreviewEl.innerHTML = emptyHtml("暂无比赛机会榜");
    return;
  }
  opportunityPreviewEl.innerHTML = `
    <div><strong>${board.headline}</strong></div>
    <div class="meta-line">${board.summary || ""}</div>
    <div class="meta-line">${board.sequencing || ""}</div>
    <div class="rank-list">
      ${(board.entries || [])
        .map(
          (item) => `
            <article class="rank-item ${item.is_selected ? "selected" : ""}">
              <div class="rank-top">
                <strong>#${item.rank} ${item.matchup}</strong>
                <span class="score-pill">${item.heat_badge}</span>
              </div>
              <div class="meta-line">${item.scoreline}</div>
              <div class="meta-line">总分 ${item.global_topic_score} / 最佳平台 ${item.best_platform_label}</div>
              <div class="meta-line">推荐角度：${item.recommended_angle}</div>
              <div class="meta-line">发布判断：${item.publish_call}</div>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderTopic(topic) {
  if (!topic) {
    topicPreviewEl.innerHTML = emptyHtml("暂无选题评分");
    evidencePreviewEl.innerHTML = emptyHtml("暂无证据链");
    return;
  }

  topicPreviewEl.innerHTML = `
    <div><strong>${topic.recommended_angle || "暂无推荐角度"}</strong></div>
    <div class="meta-line">总分 ${topic.global_topic_score} / 虎扑 ${topic.hupu_topic_score} / 抖音 ${topic.douyin_topic_score}</div>
    <div class="meta-line">层级：${topic.selected_tier}</div>
    <ul>${(topic.why_selected || []).map((line) => `<li>${line}</li>`).join("")}</ul>
    <div class="meta-line">维度拆分：</div>
    <ul>${(topic.dimension_scores || [])
      .map((dimension) => `<li>${dimension.label} ${dimension.score} 分：${dimension.reason}</li>`)
      .join("")}</ul>
  `;

  evidencePreviewEl.innerHTML = (topic.evidence_claims || [])
    .map(
      (claim) => `
        <article class="claim-card">
          <strong>${claim.claim}</strong>
          <div class="meta-line">coverage ${claim.evidence_coverage} / signal ${claim.signal_strength} / consistency ${claim.consistency_score} / confidence ${claim.confidence_score}</div>
          <ul>${(claim.evidence || [])
            .map((item) => `<li>${item.source}.${item.field}: ${JSON.stringify(item.value)} / ${item.note}</li>`)
            .join("")}</ul>
        </article>
      `,
    )
    .join("");
  if (!evidencePreviewEl.innerHTML) {
    evidencePreviewEl.innerHTML = emptyHtml("暂无证据链");
  }
}

function renderControversy(editorialLab) {
  const controversy = editorialLab?.controversy_simulator;
  if (!controversy) {
    controversyPreviewEl.innerHTML = emptyHtml("暂无争议模拟");
    return;
  }
  controversyPreviewEl.innerHTML = `
    <div class="debate-grid">
      <article class="debate-side">
        <strong>${controversy.mainstream_side.label}</strong>
        <div>${controversy.mainstream_side.claim}</div>
        <ul>${(controversy.mainstream_side.evidence || []).map((line) => `<li>${line}</li>`).join("")}</ul>
      </article>
      <article class="debate-side">
        <strong>${controversy.counter_side.label}</strong>
        <div>${controversy.counter_side.claim}</div>
        <ul>${(controversy.counter_side.evidence || []).map((line) => `<li>${line}</li>`).join("")}</ul>
      </article>
    </div>
    <div class="meta-line">最容易引爆评论区的问题：</div>
    <div><strong>${controversy.flame_question}</strong></div>
    <div class="meta-line">${controversy.high_engagement_take || ""}</div>
  `;
}

function renderKnowledge(knowledgeContext, researchPacket) {
  if (!knowledgeContext && !researchPacket) {
    knowledgePreviewEl.innerHTML = emptyHtml("暂无研究上下文");
    return;
  }
  const home = knowledgeContext?.home_team || {};
  const away = knowledgeContext?.away_team || {};
  const h2h = knowledgeContext?.head_to_head || {};
  const players = knowledgeContext?.top_players || [];
  const hits = researchPacket?.text_rag_hits || [];

  knowledgePreviewEl.innerHTML = `
    <div><strong>Fact Store</strong></div>
    <div class="meta-line">${home.summary || "暂无主队样本"}</div>
    <div class="meta-line">${away.summary || "暂无客队样本"}</div>
    <div class="meta-line">${h2h.summary || "暂无交手样本"}</div>
    <ul>${players
      .filter((item) => item && item.player_name)
      .slice(0, 3)
      .map((item) => `<li>${item.summary}</li>`)
      .join("")}</ul>
    <div><strong>Text RAG</strong></div>
    <ul>${hits
      .slice(0, 4)
      .map((item) => `<li>${item.title} / ${item.source_type} / ${item.excerpt}</li>`)
      .join("")}</ul>
  `;
}

function renderDNA(editorialLab) {
  const dna = editorialLab?.dna_system;
  if (!dna) {
    dnaPreviewEl.innerHTML = emptyHtml("暂无 DNA 报告");
    return;
  }
  dnaPreviewEl.innerHTML = `
    <div><strong>${dna.winner_team}</strong> / ${dna.winner_tags.join(" · ")}</div>
    <div class="meta-line">${dna.winner_alignment}</div>
    <div>${dna.winner_summary}</div>
    <div class="divider"></div>
    <div><strong>${dna.loser_team}</strong> / ${dna.loser_tags.join(" · ")}</div>
    <div class="meta-line">${dna.loser_faultline}</div>
    <div>${dna.loser_summary}</div>
  `;
}

function renderStoryline(editorialLab) {
  const tree = editorialLab?.season_storyline_tree;
  if (!tree) {
    storylinePreviewEl.innerHTML = emptyHtml("暂无赛季剧情树");
    return;
  }
  storylinePreviewEl.innerHTML = `
    <div><strong>${tree.root}</strong></div>
    ${(tree.branches || [])
      .map(
        (branch) => `
          <article class="story-branch">
            <strong>${branch.label}</strong>
            <ul>${(branch.items || []).map((item) => `<li>${item}</li>`).join("")}</ul>
          </article>
        `,
      )
      .join("")}
    <details class="story-mermaid">
      <summary>查看 Mermaid 剧情图</summary>
      <pre>${tree.mermaid || ""}</pre>
    </details>
  `;
}

function renderPersona(editorialLab) {
  const persona = editorialLab?.persona_lab;
  if (!persona) {
    personaPreviewEl.innerHTML = emptyHtml("暂无人格化账号版本");
    return;
  }
  personaPreviewEl.innerHTML = `
    ${(persona.accounts || [])
      .map(
        (account) => `
          <article class="persona-card">
            <strong>${account.label}</strong>
            <div class="meta-line">${account.voice}</div>
            <div><strong>标题：</strong>${account.sample_title}</div>
            <div><strong>开头：</strong>${account.sample_opening}</div>
          </article>
        `,
      )
      .join("")}
  `;
}

function renderForecast(editorialLab) {
  const forecast = editorialLab?.comment_forecast;
  if (!forecast) {
    forecastPreviewEl.innerHTML = emptyHtml("暂无评论区预判");
    return;
  }
  forecastPreviewEl.innerHTML = `
    <div><strong>最容易引战的点</strong></div>
    <div>${forecast.flame_point}</div>
    <div class="meta-line">队蜜对线风险：${forecast.rivalry_risk}</div>
    <div><strong>最可能高赞的点</strong></div>
    <div>${forecast.high_like_point}</div>
    <div><strong>模板风险</strong></div>
    <div>${forecast.template_risk}</div>
    <ul>${(forecast.likely_comment_styles || []).map((line) => `<li>${line}</li>`).join("")}</ul>
  `;
}

function renderFollowup(editorialLab) {
  const queue = editorialLab?.follow_up_queue;
  if (!queue) {
    followupPreviewEl.innerHTML = emptyHtml("暂无后续选题");
    return;
  }
  followupPreviewEl.innerHTML = `
    <div><strong>${queue.headline || "后续选题自动续写"}</strong></div>
    <ul>${(queue.items || [])
      .map(
        (item) =>
          `<li><strong>${item.title}</strong>：${item.watch}。${item.why}</li>`,
      )
      .join("")}</ul>
    <div class="meta-line">${queue.extra_note || ""}</div>
  `;
}

function renderAngleLab(editorialLab) {
  if (!editorialLab) {
    angleLabPreviewEl.innerHTML = emptyHtml("暂无反直觉角度");
    return;
  }
  const contrarian = editorialLab.contrarian_finder || {};
  const modes = editorialLab.discussion_modes || {};
  const experiments = editorialLab.persona_lab?.experiments || [];
  angleLabPreviewEl.innerHTML = `
    <div><strong>反直觉角度</strong></div>
    <div>${contrarian.claim || ""}</div>
    <div class="meta-line">${contrarian.why_unexpected || ""}</div>
    <ul>${(contrarian.evidence || []).map((line) => `<li>${line}</li>`).join("")}</ul>
    <div><strong>可讨论结论</strong></div>
    <ul>
      <li>${modes.data_conclusion || ""}</li>
      <li>${modes.viral_conclusion || ""}</li>
      <li>${modes.controversy_conclusion || ""}</li>
    </ul>
    <div><strong>平台差异化实验室</strong></div>
    <ul>${experiments
      .map((item) => `<li>${item.platform} / ${item.angle} / 目标：${item.goal}</li>`)
      .join("")}</ul>
  `;
}

function renderGovernance(governance, promptContracts) {
  if (!governance) {
    governancePreviewEl.innerHTML = emptyHtml("暂无治理配置");
    return;
  }
  const roles = governance.agent_roles || [];
  const contracts = Object.values(promptContracts || {});
  governancePreviewEl.innerHTML = `
    <div><strong>Policy v${governance.version}</strong></div>
    <div class="meta-line">每条主张至少 ${governance.prompt_policy.claim_min_evidence_points} 个证据点，主结论置信度至少 ${governance.prompt_policy.primary_claim_min_confidence}</div>
    <div class="meta-line">RAG 来源优先级：${(governance.rag_policy.source_priority || []).join(" > ")}</div>
    <div><strong>Agent Roles</strong></div>
    <ul>${roles
      .map((role) => `<li>${role.name}: ${role.responsibility} / reviewed by ${role.reviewed_by || "n/a"}</li>`)
      .join("")}</ul>
    <div><strong>Prompt Contracts</strong></div>
    <ul>${contracts
      .slice(0, 4)
      .map((contract) => `<li>${contract.role}: must include ${contract.must_include.join(", ")}</li>`)
      .join("")}</ul>
  `;
}

function renderSupervision(supervision) {
  if (!supervision) {
    supervisionPreviewEl.innerHTML = emptyHtml("暂无审查结果");
    return;
  }
  const topic = supervision.topic_engine || {};
  const hupu = supervision.platforms?.hupu || {};
  const douyin = supervision.platforms?.douyin || {};

  const renderReviewerBlock = (label, payload) => {
    if (!payload) {
      return `<div class="meta-line">${label}: 暂无</div>`;
    }
    const factCheck = payload.fact_check || payload;
    const riskGuard = payload.risk_guard;
    const issues = [...(factCheck.findings || []), ...(factCheck.warnings || [])];
    const riskIssues = riskGuard ? [...(riskGuard.findings || []), ...(riskGuard.warnings || [])] : [];
    return `
      <div><strong>${label}</strong></div>
      <div class="meta-line">fact_check: ${factCheck.status || "n/a"}</div>
      ${riskGuard ? `<div class="meta-line">risk_guard: ${riskGuard.status || "n/a"}</div>` : ""}
      <ul>${[...issues, ...riskIssues].map((line) => `<li>${line}</li>`).join("")}</ul>
    `;
  };

  supervisionPreviewEl.innerHTML = `
    ${renderReviewerBlock("Topic Engine", topic)}
    ${renderReviewerBlock("Hupu", hupu)}
    ${renderReviewerBlock("Douyin", douyin)}
  `;
}

function resetOutput() {
  overviewEl.innerHTML = "运行后会在这里看到比赛摘要、编辑判断和发布总览。";
  realtimePreviewEl.innerHTML = "No realtime replay has been run yet.";
  videoScoutPreviewEl.innerHTML = "No video scout report has been run yet.";
  selectionPreviewEl.innerHTML = "暂无选题信息";
  opportunityPreviewEl.innerHTML = "暂无比赛机会榜";
  topicPreviewEl.innerHTML = "暂无选题评分";
  controversyPreviewEl.innerHTML = "暂无争议模拟";
  knowledgePreviewEl.innerHTML = "暂无研究上下文";
  dnaPreviewEl.innerHTML = "暂无 DNA 报告";
  storylinePreviewEl.innerHTML = "暂无赛季剧情树";
  personaPreviewEl.innerHTML = "暂无人格化账号版本";
  forecastPreviewEl.innerHTML = "暂无评论区预判";
  followupPreviewEl.innerHTML = "暂无后续选题";
  evidencePreviewEl.innerHTML = "暂无证据链";
  angleLabPreviewEl.innerHTML = "暂无反直觉角度";
  governancePreviewEl.innerHTML = "暂无治理配置";
  supervisionPreviewEl.innerHTML = "暂无审查结果";
  hupuPreviewEl.textContent = "暂无内容";
  douyinPreviewEl.textContent = "暂无内容";
  hupuPublishEl.textContent = "暂无发布计划";
  douyinPublishEl.textContent = "暂无发布计划";
  posterWrapEl.textContent = "暂无海报";
}

async function renderResult(result) {
  if (!result) {
    resetOutput();
    return;
  }

  if (result.workflow === "realtime_demo") {
    await renderRealtimeResult(result);
    return;
  }

  if (result.workflow === "video_scout") {
    await renderVideoScoutResult(result);
    return;
  }

  overviewEl.innerHTML = `
    <strong>${result.game.winner}</strong> / ${result.game.scoreline}<br>
    <span class="meta-line">${result.game.date} / ${result.game.venue}</span><br>
    <span class="meta-line">${result.game.headline || ""}</span><br>
    <span class="meta-line">Primary Driver: ${result.game.primary_driver || "n/a"}</span><br>
    <span class="meta-line">Output Root: ${result.output_root}</span>
  `;

  renderSelection(result.selection);
  renderOpportunity(result.editorial_lab);
  renderTopic(result.topic_engine);
  renderControversy(result.editorial_lab);
  renderKnowledge(result.knowledge_context, result.research_packet);
  renderDNA(result.editorial_lab);
  renderStoryline(result.editorial_lab);
  renderPersona(result.editorial_lab);
  renderForecast(result.editorial_lab);
  renderFollowup(result.editorial_lab);
  renderAngleLab(result.editorial_lab);
  renderGovernance(result.governance, result.prompt_contracts);
  renderSupervision(result.supervision);

  hupuPreviewEl.textContent = result.platforms.hupu.preview || "";
  douyinPreviewEl.textContent = result.platforms.douyin.preview || "";
  renderPublishPlan(hupuPublishEl, result.platforms.hupu.publish);
  renderPublishPlan(douyinPublishEl, result.platforms.douyin.publish);

  if (result.assets && result.assets.douyin_poster) {
    const posterUrl = `/api/files?path=${encodeURIComponent(result.assets.douyin_poster)}`;
    posterWrapEl.innerHTML = `<img src="${posterUrl}" alt="Douyin poster preview">`;
  } else {
    posterWrapEl.innerHTML = emptyHtml("暂无海报");
  }
}

async function renderRealtimeResult(result) {
  overviewEl.innerHTML = `
    <strong>Realtime Replay Demo</strong><br>
    <span class="meta-line">Replay: ${result.replay_path}</span><br>
    <span class="meta-line">Events: ${result.event_count} / Commentaries: ${result.commentary_count}</span><br>
    <span class="meta-line">Output Root: ${result.output_dir}</span>
  `;
  realtimePreviewEl.innerHTML = emptyHtml("Loading transcript...");
  const transcriptPath = `${result.output_dir}\\transcript.json`;
  try {
    const res = await fetch(`/api/files?path=${encodeURIComponent(transcriptPath)}`);
    const transcript = await res.json();
    realtimePreviewEl.innerHTML = renderRealtimeTranscript(transcript);
  } catch (error) {
    realtimePreviewEl.innerHTML = `
      <div class="error-block">
        <strong>Transcript preview failed</strong>
        <p>${error}</p>
      </div>
    `;
  }
  selectionPreviewEl.innerHTML = emptyHtml("Realtime replay jobs do not run postgame selection.");
  opportunityPreviewEl.innerHTML = emptyHtml("Realtime replay jobs focus on event-level commentary.");
  topicPreviewEl.innerHTML = emptyHtml("No postgame topic score for this workflow.");
  controversyPreviewEl.innerHTML = emptyHtml("No controversy simulator for this workflow.");
  knowledgePreviewEl.innerHTML = emptyHtml("Realtime transcript uses event-level evidence in this demo.");
  dnaPreviewEl.innerHTML = emptyHtml("No team DNA report for this workflow.");
  storylinePreviewEl.innerHTML = emptyHtml("No season storyline tree for this workflow.");
  personaPreviewEl.innerHTML = emptyHtml("Style is selected at replay generation time.");
  forecastPreviewEl.innerHTML = emptyHtml("No comment forecast for this workflow.");
  followupPreviewEl.innerHTML = emptyHtml("No follow-up queue for this workflow.");
  evidencePreviewEl.innerHTML = emptyHtml("See the realtime transcript provenance states above.");
  angleLabPreviewEl.innerHTML = emptyHtml("No angle lab for this workflow.");
  governancePreviewEl.innerHTML = emptyHtml("Realtime workflow uses live_commentary.v1.");
  supervisionPreviewEl.innerHTML = emptyHtml("Realtime provenance tags are generated per sentence.");
  hupuPreviewEl.textContent = "";
  douyinPreviewEl.textContent = "";
  hupuPublishEl.textContent = "";
  douyinPublishEl.textContent = "";
  posterWrapEl.textContent = "";
}

async function renderVideoScoutResult(result) {
  overviewEl.innerHTML = `
    <strong>Video Scout Demo</strong><br>
    <span class="meta-line">${result.title || "Tactical report"}</span><br>
    <span class="meta-line">Observations: ${result.observation_count} / Segments: ${result.segment_count}</span><br>
    <span class="meta-line">Output Root: ${result.output_dir}</span>
  `;
  realtimePreviewEl.innerHTML = emptyHtml("Video scout jobs do not generate live commentary.");
  videoScoutPreviewEl.innerHTML = emptyHtml("Loading tactical report...");
  const reportPath = `${result.output_dir}\\report.json`;
  try {
    const res = await fetch(`/api/files?path=${encodeURIComponent(reportPath)}`);
    const report = await res.json();
    videoScoutPreviewEl.innerHTML = renderVideoScoutReport(report);
  } catch (error) {
    videoScoutPreviewEl.innerHTML = `
      <div class="error-block">
        <strong>Video scout preview failed</strong>
        <p>${error}</p>
      </div>
    `;
  }
  selectionPreviewEl.innerHTML = emptyHtml("Video scout uses clip observations, not game selection.");
  opportunityPreviewEl.innerHTML = emptyHtml("No opportunity board for this workflow.");
  topicPreviewEl.innerHTML = emptyHtml("No postgame topic score for this workflow.");
  controversyPreviewEl.innerHTML = emptyHtml("No controversy simulator for this workflow.");
  knowledgePreviewEl.innerHTML = emptyHtml("This workflow grounds claims to video timestamps and observation evidence.");
  dnaPreviewEl.innerHTML = emptyHtml("No team DNA report for this workflow.");
  storylinePreviewEl.innerHTML = emptyHtml("No season storyline tree for this workflow.");
  personaPreviewEl.innerHTML = emptyHtml("Video scout report can later feed platform personas.");
  forecastPreviewEl.innerHTML = emptyHtml("No comment forecast for this workflow.");
  followupPreviewEl.innerHTML = emptyHtml("No follow-up queue for this workflow.");
  evidencePreviewEl.innerHTML = emptyHtml("See the video scout report evidence list above.");
  angleLabPreviewEl.innerHTML = emptyHtml("No angle lab for this workflow.");
  governancePreviewEl.innerHTML = emptyHtml("Video scout workflow uses video_scout.tactical_report.v1.");
  supervisionPreviewEl.innerHTML = emptyHtml("Evidence is timestamp and observation based in this MVP.");
  hupuPreviewEl.textContent = "";
  douyinPreviewEl.textContent = "";
  hupuPublishEl.textContent = "";
  douyinPublishEl.textContent = "";
  posterWrapEl.textContent = "";
}

function renderVideoScoutReport(report) {
  const segments = report.key_segments || [];
  const segmentHtml = segments
    .map(
      (segment) => `
        <article class="scout-segment">
          <div class="rank-top">
            <strong>Q${segment.period} ${segment.clock}</strong>
            <span class="score-pill">${Number(segment.confidence || 0).toFixed(2)}</span>
          </div>
          <div class="meta-line">${segment.timecode} / ${segment.tactic_type}</div>
          <div><strong>观察：</strong>${segment.observation}</div>
          <div><strong>选择：</strong>${segment.decision_analysis}</div>
          <div><strong>影响：</strong>${segment.win_loss_impact}</div>
          <ul>${(segment.evidence || []).map((item) => `<li>${item}</li>`).join("")}</ul>
        </article>
      `,
    )
    .join("");
  return `
    <div><strong>${report.title || "Video Scout Report"}</strong></div>
    <div class="meta-line">${report.executive_summary || ""}</div>
    <div class="scout-longform">${report.full_analysis || ""}</div>
    ${segmentHtml}
    <div><strong>战术主题</strong></div>
    <ul>${(report.tactical_themes || []).map((item) => `<li>${item}</li>`).join("")}</ul>
    <div><strong>比赛走势阅读</strong></div>
    <ul>${(report.quarter_flow || []).map((item) => `<li>${item}</li>`).join("")}</ul>
    <div><strong>决定比赛的结构性因素</strong></div>
    <ul>${(report.deciding_factors || []).map((item) => `<li>${item}</li>`).join("")}</ul>
    <div><strong>MVP 分析</strong></div>
    <div class="scout-longform">${report.mvp_analysis || ""}</div>
    <div><strong>球员战术发起画像</strong></div>
    ${(report.player_tactical_profiles || [])
      .map(
        (profile) => `
          <article class="scout-segment">
            <div class="rank-top">
              <strong>${profile.player || ""} / ${profile.team || ""}</strong>
              <span class="score-pill">${Number(profile.confidence || 0).toFixed(2)}</span>
            </div>
            <div class="meta-line">${profile.role || ""}</div>
            <div>${profile.tactical_read || ""}</div>
            <ul>${[...(profile.stat_evidence || []), ...(profile.video_evidence || [])].map((item) => `<li>${item}</li>`).join("")}</ul>
          </article>
        `,
      )
      .join("")}
    <div><strong>内容角度</strong></div>
    <ul>${(report.content_angles || []).map((item) => `<li>${item}</li>`).join("")}</ul>
    <div><strong>边界说明</strong></div>
    <ul>${(report.limitations || []).map((item) => `<li>${item}</li>`).join("")}</ul>
  `;
}

function renderRealtimeTranscript(transcript) {
  if (!Array.isArray(transcript) || !transcript.length) {
    return emptyHtml("Replay produced no commentaries.");
  }
  return transcript
    .map((item) => {
      const tags = (item.provenance || [])
        .map(
          (tag) => `
            <li>
              <span class="trace-state trace-${tag.state}">${tag.state}</span>
              confidence ${Number(tag.confidence || 0).toFixed(2)}
              / evidence ${tag.evidence_count}
            </li>
          `,
        )
        .join("");
      return `
        <article class="realtime-item">
          <div class="rank-top">
            <strong>Q${item.period} ${item.clock}</strong>
            <span class="score-pill">${item.salience}</span>
          </div>
          <div class="meta-line">${item.category} / ${item.score.home}-${item.score.away}</div>
          <div class="meta-line">${item.event}</div>
          <div class="realtime-comment">${item.commentary}</div>
          <ul>${tags}</ul>
        </article>
      `;
    })
    .join("");
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
  if (job.status === "failed" && job.error) {
    overviewEl.innerHTML = `
      <div class="error-block">
        <strong>任务失败</strong>
        <p>${job.error}</p>
      </div>
    `;
  } else {
    await renderResult(job.result);
  }
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

document.getElementById("use-replay-sample").addEventListener("click", () => {
  document.getElementById("source").value = "replay_demo";
  document.getElementById("input-path").value = sampleReplay;
});

document.getElementById("use-video-scout-sample").addEventListener("click", () => {
  document.getElementById("source").value = "video_scout_demo";
  document.getElementById("input-path").value = sampleVideoScout;
});

window.addEventListener("load", async () => {
  await fetchJobs();
  renderSteps([]);
  renderLogs([]);
  await renderResult(null);
});
