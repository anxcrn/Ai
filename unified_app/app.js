const grid = document.getElementById("agentGrid");
const timeline = document.getElementById("timeline");
const modelSelect = document.getElementById("modelSelect");

async function safeFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${text}`);
  }
  return res.json();
}

async function loadAgents() {
  const data = await safeFetch("/api/agents");
  grid.innerHTML = "";
  data.agents.forEach((a) => {
    const card = document.createElement("article");
    card.className = "agent-card";
    card.innerHTML = `<h3>${a.name}</h3><p>${a.role}</p>`;
    grid.appendChild(card);
  });
}

async function loadModels() {
  const data = await safeFetch("/api/models");
  modelSelect.innerHTML = "";
  const saved = localStorage.getItem("pcs_model");
  data.models.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    if (saved === m) opt.selected = true;
    modelSelect.appendChild(opt);
  });
}

async function refreshTimeline() {
  const data = await safeFetch("/api/timeline");
  timeline.innerHTML = "";
  data.timeline.forEach((entry) => {
    const li = document.createElement("li");
    li.textContent = `[${entry.ts}] ${entry.event}`;
    timeline.appendChild(li);
  });
}

document.getElementById("dispatchBtn").addEventListener("click", async () => {
  const mission = document.getElementById("taskInput").value.trim();
  if (!mission) return;
  const model = modelSelect.value;
  localStorage.setItem("pcs_model", model);
  await safeFetch("/api/dispatch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mission, model }),
  });
  await refreshTimeline();
});

document.getElementById("pingMobileBtn").addEventListener("click", async () => {
  const endpoint = document.getElementById("mobileEndpoint").value.trim();
  const out = document.getElementById("mobileStatus");
  try {
    const data = await safeFetch(`/api/mobile/ping?endpoint=${encodeURIComponent(endpoint)}`);
    out.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    out.textContent = `Mobile ping failed: ${err.message}`;
  }
});

document.getElementById("healthBtn").addEventListener("click", async () => {
  const el = document.getElementById("healthStatus");
  try {
    const data = await safeFetch("/api/health");
    el.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    el.textContent = `Health check failed: ${err.message}`;
  }
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(console.error);
}

setInterval(refreshTimeline, 1500);
Promise.all([loadAgents(), loadModels()]).then(refreshTimeline).catch(console.error);
