// =====================================================================
// AI Interview Question Generator — frontend logic
// =====================================================================

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  questions: [],
  params: null,
  practice: null,
  filter: "All",
};

const HISTORY_KEY = "iqg-history";
const MAX_AVOID = 40;              // already-seen questions sent so the AI writes new ones
const REQUEST_TIMEOUT_MS = 150000; // the server tries backup models, so allow time for that
const HISTORY_MAX = 10;
const USER_KEY = "intervue-user";
const DEMO_USER = { name: "Sid Rawat", email: "sid.rawat@intervue.demo", initials: "SR" };

// ---------------------------------------------------------------- init
document.addEventListener("DOMContentLoaded", () => {
  initialiseAuth();
  loadProvider();
  renderHistory();

  $("#count").addEventListener("input", (e) => ($("#countOut").textContent = e.target.value));
  initialiseCustomSelect();
  $$("#roleChips .chip").forEach((chip) =>
    chip.addEventListener("click", () => {
      $("#role").value = chip.textContent;
      $("#role").focus();
    })
  );

  $("#genForm").addEventListener("submit", onGenerate);
  $("#newSet").addEventListener("click", () => $("#genForm").requestSubmit());
  $("#copyAll").addEventListener("click", () => copyText(asPlainText(), $("#copyAll")));
  $("#downloadTxt").addEventListener("click", downloadTxt);
  $("#printBtn").addEventListener("click", () => window.print());
  $("#shuffleProblems").addEventListener("click", shuffleProblems);
  $("#clearHistory").addEventListener("click", () => {
    storage.set(HISTORY_KEY, []);
    renderHistory();
  });
  $("#accountButton").addEventListener("click", signOut);
});

function initialiseCustomSelect() {
  const select = $("#problemSelect");
  const trigger = $(".select-trigger", select);
  const options = $(".select-options", select);
  trigger.addEventListener("click", () => {
    const open = options.hidden;
    options.hidden = !open;
    trigger.setAttribute("aria-expanded", String(open));
  });
  $$('button[role="option"]', select).forEach((option) => option.addEventListener("click", () => {
    $("#problemCount").value = option.dataset.value;
    trigger.replaceChildren(document.createTextNode(option.textContent), el("span", "⌄"));
    $$('button[role="option"]', select).forEach((item) => item.setAttribute("aria-selected", "false"));
    option.setAttribute("aria-selected", "true");
    options.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  }));
  document.addEventListener("click", (event) => {
    if (!select.contains(event.target)) {
      options.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }
  });
}

// --------------------------------------------------------------- sign-in
function initialiseAuth() {
  let savedUser = storage.get(USER_KEY, null);
  if (savedUser?.email === "alex@intervue.demo") {
    savedUser = DEMO_USER; // old demo account name saved in this browser
    storage.set(USER_KEY, savedUser);
  }
  if (savedUser?.name) finishLogin(savedUser, false);

  $("#demoLogin").addEventListener("click", () =>
    finishLogin(DEMO_USER)
  );

  if (!window.APP_CONFIG?.googleClientId) return;
  const attachGoogle = () => {
    if (!window.google?.accounts?.id) return setTimeout(attachGoogle, 100);
    google.accounts.id.initialize({
      client_id: window.APP_CONFIG.googleClientId,
      callback: handleGoogleCredential,
      auto_select: false,
      cancel_on_tap_outside: true,
    });
    google.accounts.id.renderButton($("#googleSignIn"), {
      type: "standard", theme: "outline", size: "large", text: "continue_with", width: 360,
    });
  };
  attachGoogle();
}

function handleGoogleCredential(response) {
  try {
    const payload = JSON.parse(atob(response.credential.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    finishLogin({
      name: payload.name || payload.email || "Google user",
      email: payload.email || "",
      initials: initials(payload.name || payload.email || "Google user"),
    });
  } catch {
    const error = $("#loginError");
    error.textContent = "Google sign-in could not be completed. Please try again.";
    error.hidden = false;
  }
}

function finishLogin(user, save = true) {
  if (save) storage.set(USER_KEY, user);
  $("#loginScreen").hidden = true;
  $("#accountButton").textContent = user.initials || initials(user.name);
  $("#accountButton").title = `Signed in as ${user.name}. Click to sign out.`;
}

function signOut() {
  localStorage.removeItem(USER_KEY);
  $("#loginScreen").hidden = false;
  if (window.google?.accounts?.id) google.accounts.id.disableAutoSelect();
}

function initials(name) {
  return String(name).split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

async function loadProvider() {
  const badge = $("#providerBadge");
  try {
    const info = await (await fetch("/api/status")).json();
    if (info.online) {
      badge.textContent = `AI: ${info.provider} · ${info.model}`;
      badge.className = "provider-badge online";
    } else {
      badge.textContent = info.reason ? "AI setup required" : "Offline demo mode";
      badge.title = info.reason || "No AI provider is configured.";
      badge.className = "provider-badge offline";
    }
  } catch {
    badge.textContent = "Server not reachable";
    badge.className = "provider-badge offline";
  }
}

// ------------------------------------------------------------ generate
async function onGenerate(event) {
  event.preventDefault();
  const errorBox = $("#formError");
  errorBox.hidden = true;

  const payload = {
    role: $("#role").value.trim(),
    level: $("#level").value,
    difficulty: $("#difficulty").value,
    types: $$('input[name="types"]:checked').map((c) => c.value),
    skills: $("#skills").value,
    company: $("#company").value.trim(),
    count: Number($("#count").value),
    problem_count: Number($("#problemCount").value),
    job_description: $("#jd").value,
  };

  if (!payload.role) return showFormError("Please enter a job role.");
  if (payload.types.length === 0) return showFormError("Select at least one question type.");
  payload.avoid = seenQuestions(payload.role);

  setLoading(true);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    showResults(data);
    saveToHistory(data);
  } catch (err) {
    setLoading(false, true);
    showFormError(
      err.name === "AbortError"
        ? "The server took too long to answer. Check that app.py is still running and try again."
        : err.message || "Could not generate questions."
    );
  } finally {
    clearTimeout(timeout);
  }
}

/** Questions already shown for this role (newest first), so the AI can avoid them. */
function seenQuestions(role) {
  const key = role.trim().toLowerCase();
  const seen = [];
  for (const set of storage.get(HISTORY_KEY, [])) {
    if (set.params?.role?.trim().toLowerCase() !== key) continue;
    for (const q of set.questions || []) {
      if (!seen.includes(q.question)) seen.push(q.question);
    }
  }
  return seen.slice(0, MAX_AVOID);
}

function showFormError(msg) {
  const box = $("#formError");
  box.textContent = msg;
  box.hidden = false;
}

function setLoading(on, restoreEmpty = false) {
  const btn = $("#generateBtn");
  btn.disabled = on;
  $(".btn-label", btn).textContent = on ? "Generating…" : "Generate questions";
  $("#newSet").disabled = on;
  $("#loading").hidden = !on;
  clearInterval(state.timer);
  if (on) {
    const started = Date.now();
    $("#loadingTimer").textContent = "";
    state.timer = setInterval(() => {
      $("#loadingTimer").textContent = `${Math.round((Date.now() - started) / 1000)} s`;
    }, 1000);
  }
  if (on) {
    $("#emptyState").hidden = true;
    $("#results").hidden = true;
  } else if (restoreEmpty && state.questions.length === 0) {
    $("#emptyState").hidden = false;
  } else if (restoreEmpty) {
    $("#results").hidden = false;
  }
}

// ------------------------------------------------------------- results
function showResults(data) {
  state.questions = data.questions;
  state.params = data.params;
  state.filter = "All";
  setLoading(false);

  const p = data.params;
  $("#resultsTitle").textContent = `${p.role} — ${data.questions.length} questions`;
  $("#resultsMeta").textContent =
    `${p.level} · ${p.difficulty} difficulty · ` +
    (data.source === "ai" ? `AI-generated (${data.model || "AI"})` : "Offline question bank");

  const notice = $("#notice");
  notice.hidden = !data.notice;
  notice.textContent = data.notice || "";

  renderFilters();
  renderQuestions();

  renderPractice(data.practice);

  const tips = data.tips || [];
  $("#tipsBox").hidden = tips.length === 0;
  $("#tipsList").replaceChildren(...tips.map((t) => el("li", t)));

  $("#emptyState").hidden = true;
  $("#results").hidden = false;
  $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderFilters() {
  const types = ["All", ...new Set(state.questions.map((q) => q.type))];
  const box = $("#filters");
  box.replaceChildren(
    ...types.map((t) => {
      const b = el("button", t);
      b.type = "button";
      if (t === state.filter) b.classList.add("active");
      b.addEventListener("click", () => {
        state.filter = t;
        renderFilters();
        renderQuestions();
      });
      return b;
    })
  );
  box.hidden = types.length <= 2;
}

function renderQuestions() {
  const list = $("#questionList");
  const tpl = $("#questionTpl");
  list.replaceChildren();

  state.questions.forEach((q, i) => {
    if (state.filter !== "All" && q.type !== state.filter) return;
    const node = tpl.content.cloneNode(true);
    const card = $(".qcard", node);

    $(".qnum", card).textContent = `Q${i + 1}`;
    $(".qtext", card).textContent = q.question;
    $(".why", card).textContent = q.why_asked;
    $(".why", card).hidden = !q.why_asked;

    const badges = $(".badges", card);
    badges.append(badge(q.type), badge(q.difficulty, q.difficulty));
    if (q.topic) badges.append(badge(q.topic));

    $(".points ul", card).replaceChildren(...q.key_points.map((k) => el("li", k)));
    $(".follow span", card).textContent = q.follow_up;
    $(".follow", card).hidden = !q.follow_up;

    // toggles
    const pointsBox = $(".points", card);
    const toggleBtn = $(".toggle-points", card);
    toggleBtn.addEventListener("click", () => {
      pointsBox.hidden = !pointsBox.hidden;
      toggleBtn.textContent = pointsBox.hidden ? "Show answer guide" : "Hide answer guide";
    });

    const practiceBox = $(".practice", card);
    const textarea = $("textarea", practiceBox);
    $(".practice-btn", card).addEventListener("click", () => {
      practiceBox.hidden = !practiceBox.hidden;
      if (!practiceBox.hidden) textarea.focus();
    });
    textarea.addEventListener("input", () => {
      const n = textarea.value.trim() ? textarea.value.trim().split(/\s+/).length : 0;
      $(".wc", practiceBox).textContent = `${n} word${n === 1 ? "" : "s"}`;
    });
    $(".eval-btn", card).addEventListener("click", (e) => evaluateAnswer(q, textarea, practiceBox, e.target));
    $(".copy-one", card).addEventListener("click", (e) => copyText(q.question, e.target));

    list.append(node);
  });
}

// ----------------------------------------------------- practice problems
const SOURCE_NAMES = { leetcode: "LeetCode", codeforces: "Codeforces" };

function renderPractice(practice) {
  state.practice = practice || null;
  const box = $("#practiceBox");
  const problems = practice?.problems || [];
  const hasAnything = practice && (problems.length || practice.note || practice.resources?.length);
  box.hidden = !hasAnything;
  if (!hasAnything) return;

  // which sources were live vs offline
  const src = practice.sources || {};
  $("#sourcesLine").textContent = Object.entries(src)
    .map(([k, v]) => `${SOURCE_NAMES[k] || k}: ${v}`)
    .join(" · ");

  const note = $("#practiceNote");
  note.hidden = !practice.note;
  note.textContent = practice.note || "";
  $("#shuffleProblems").hidden = problems.length === 0;

  const tpl = $("#problemTpl");
  $("#problemList").replaceChildren(
    ...problems.map((p) => {
      const node = tpl.content.cloneNode(true);
      const card = $(".pcard", node);
      const srcEl = $(".src", card);
      srcEl.textContent = p.source + (p.code ? ` ${p.code}` : "");
      srcEl.classList.add(p.source);
      const diff = $(".pdiff", card);
      diff.textContent = p.difficulty;
      if (["Easy", "Medium", "Hard"].includes(p.difficulty)) diff.classList.add(p.difficulty);
      $(".classic", card).hidden = !p.classic;
      $(".acc", card).textContent = p.acceptance ? `${p.acceptance}% accepted` : "";
      const link = $(".ptitle", card);
      link.textContent = p.title;
      link.href = p.url;
      $(".ptags", card).replaceChildren(...(p.tags || []).map((t) => el("span", t)));
      $(".pwhy", card).textContent = p.why || "";
      $(".phint p", card).textContent = p.hint || "";
      $(".phint", card).hidden = !p.hint;
      return node;
    })
  );

  const topics = practice.topics || [];
  $("#topicBox").hidden = topics.length === 0 || problems.length === 0;
  $("#topicLinks").replaceChildren(
    ...topics.map((t) => {
      const a = el("a", `${t.label} ↗`);
      a.href = t.gfg_url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      return a;
    })
  );

  const res = practice.resources || [];
  $("#resourceBox").hidden = res.length === 0;
  $("#resourceList").replaceChildren(
    ...res.map((r) => {
      const li = el("li");
      const a = el("a", r.name);
      a.href = r.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      li.append(a, document.createTextNode(` — ${r.desc}`));
      return li;
    })
  );
}

async function shuffleProblems() {
  if (!state.params) return;
  const btn = $("#shuffleProblems");
  btn.disabled = true;
  btn.textContent = "Shuffling…";
  try {
    const res = await fetch("/api/problems", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...state.params,
        skills: state.params.skills.join(", "),
        exclude: (state.practice?.problems || []).map((p) => p.url),
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load problems.");
    renderPractice(data);
  } catch (err) {
    const note = $("#practiceNote");
    note.hidden = false;
    note.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Shuffle problems";
  }
}

// ------------------------------------------------------------ practice
async function evaluateAnswer(q, textarea, box, btn) {
  const answer = textarea.value.trim();
  const fb = $(".feedback", box);
  if (answer.split(/\s+/).length < 5) {
    fb.hidden = false;
    fb.replaceChildren(el("p", "Write at least a few sentences before asking for feedback."));
    return;
  }

  btn.disabled = true;
  btn.textContent = "Evaluating…";
  try {
    const res = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: q.question,
        answer,
        role: state.params?.role,
        level: state.params?.level,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Evaluation failed.");
    renderFeedback(fb, data);
  } catch (err) {
    fb.hidden = false;
    fb.replaceChildren(el("p", err.message));
  } finally {
    btn.disabled = false;
    btn.textContent = "Get feedback";
  }
}

function renderFeedback(fb, d) {
  const level = d.score >= 7 ? "high" : d.score >= 4 ? "mid" : "low";
  const scoreEl = el("div", `${d.score}/10`);
  scoreEl.className = `score ${level}`;

  const row = el("div");
  row.className = "score-row";
  row.append(scoreEl, el("p", d.verdict));

  const parts = [row];
  if (d.strengths?.length) parts.push(el("h5", "Strengths"), listOf(d.strengths));
  if (d.improvements?.length) parts.push(el("h5", "Improve"), listOf(d.improvements));
  if (d.model_answer) {
    const m = el("p", d.model_answer);
    m.className = "model";
    parts.push(el("h5", "Example answer"), m);
  }
  fb.replaceChildren(...parts);
  fb.hidden = false;
}

// ------------------------------------------------------- export helpers
function asPlainText() {
  const p = state.params;
  const lines = [`Interview questions — ${p.role} (${p.level}, ${p.difficulty})`, ""];
  state.questions.forEach((q, i) => {
    lines.push(`${i + 1}. [${q.type} · ${q.difficulty}] ${q.question}`);
    if (q.key_points.length) lines.push("   Answer should cover: " + q.key_points.join("; "));
    if (q.follow_up) lines.push("   Follow-up: " + q.follow_up);
    lines.push("");
  });
  const problems = state.practice?.problems || [];
  if (problems.length) {
    lines.push("Practice problems", "");
    problems.forEach((p, i) => {
      lines.push(`${i + 1}. [${p.source} · ${p.difficulty}] ${p.title} — ${p.url}`);
      if (p.hint) lines.push("   Hint: " + p.hint);
    });
    lines.push("");
  }
  return lines.join("\n");
}

function downloadTxt() {
  const blob = new Blob([asPlainText()], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `interview-questions-${state.params.role.replace(/\W+/g, "-").toLowerCase()}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    flash(btn, "Copied!");
  } catch {
    flash(btn, "Copy failed");
  }
}

function flash(btn, msg) {
  const old = btn.textContent;
  btn.textContent = msg;
  setTimeout(() => (btn.textContent = old), 1200);
}

// ------------------------------------------------------------- history
const storage = {
  get(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key)) ?? fallback;
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable — history is optional */
    }
  },
};

function saveToHistory(data) {
  const history = storage.get(HISTORY_KEY, []);
  history.unshift({ ...data, savedAt: Date.now() });
  storage.set(HISTORY_KEY, history.slice(0, HISTORY_MAX));
  renderHistory();
}

function renderHistory() {
  const history = storage.get(HISTORY_KEY, []);
  const list = $("#historyList");
  if (!history.length) {
    list.replaceChildren(Object.assign(el("li", "Nothing yet."), { className: "muted" }));
    return;
  }
  list.replaceChildren(
    ...history.map((h) => {
      const btn = el("button");
      btn.type = "button";
      const time = el("time", new Date(h.savedAt).toLocaleString([], { dateStyle: "short", timeStyle: "short" }));
      btn.append(el("span", `${h.params.role} · ${h.questions.length}Q`), time);
      btn.addEventListener("click", () => showResults(h));
      const li = el("li");
      li.append(btn);
      return li;
    })
  );
}

// ---------------------------------------------------------- DOM helpers
function el(tag, text) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  return node;
}
function badge(text, extraClass) {
  const b = el("span", text);
  b.className = "badge" + (extraClass ? ` ${extraClass}` : "");
  return b;
}
function listOf(items) {
  const ul = el("ul");
  ul.append(...items.map((i) => el("li", i)));
  return ul;
}
