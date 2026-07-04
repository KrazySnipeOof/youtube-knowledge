"use strict";

const state = {
  data: null,
  activeTopics: new Set(["all"]),
  search: "",
  sort: "score",
};

const els = {
  meta: document.getElementById("meta"),
  search: document.getElementById("search"),
  sort: document.getElementById("sort"),
  topicFilters: document.getElementById("topic-filters"),
  results: document.getElementById("results"),
  empty: document.getElementById("empty"),
  count: document.getElementById("count"),
};

init();

async function init() {
  try {
    const res = await fetch("data.json", { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    state.data = await res.json();
  } catch (err) {
    showNoData(err);
    return;
  }
  setupControls();
  buildTopicChips();
  render();
}

function showNoData(err) {
  els.empty.classList.remove("hidden");
  const fileMode = location.protocol === "file:";
  els.empty.innerHTML = fileMode
    ? `Couldn't load <code>data.json</code> because the page was opened directly from disk.<br><br>
       Start the local server instead:<br><br><code>python serve.py</code><br><br>
       then open <code>http://localhost:8000</code>.`
    : `No <code>data.json</code> found yet (${err}).<br><br>
       Run the scraper first:<br><br><code>python scraper/scrape.py</code>`;
}

function setupControls() {
  els.search.addEventListener("input", () => {
    state.search = els.search.value.trim().toLowerCase();
    render();
  });
  els.sort.addEventListener("change", () => {
    state.sort = els.sort.value;
    render();
  });
  const d = state.data;
  els.meta.textContent =
    `${d.stats.unique_links} links · ${d.stats.videos_scanned} videos · ${fmtDate(d.generated_at)}`;
}

function presentTopics() {
  // Topics that actually appear in the data, in a stable, meaningful order.
  const order = ["ai", "ml", "quant", "learning", "crypto", "uncategorized"];
  const present = new Set();
  state.data.links.forEach((l) => l.topics.forEach((t) => present.add(t)));
  const ordered = order.filter((t) => present.has(t));
  present.forEach((t) => { if (!ordered.includes(t)) ordered.push(t); });
  return ordered;
}

function labelFor(topic) {
  return (state.data.topic_labels && state.data.topic_labels[topic]) || topic;
}

function buildTopicChips() {
  const topics = ["all", ...presentTopics()];
  els.topicFilters.innerHTML = "";
  topics.forEach((topic) => {
    const chip = document.createElement("div");
    chip.className = "chip" + (state.activeTopics.has(topic) ? " active" : "");
    chip.dataset.topic = topic;
    chip.textContent = topic === "all" ? "All" : labelFor(topic);
    chip.addEventListener("click", () => toggleTopic(topic));
    els.topicFilters.appendChild(chip);
  });
}

function toggleTopic(topic) {
  if (topic === "all") {
    state.activeTopics = new Set(["all"]);
  } else {
    state.activeTopics.delete("all");
    if (state.activeTopics.has(topic)) state.activeTopics.delete(topic);
    else state.activeTopics.add(topic);
    if (state.activeTopics.size === 0) state.activeTopics = new Set(["all"]);
  }
  buildTopicChips();
  render();
}

function matches(link) {
  // Topic filter (OR across selected topics).
  if (!state.activeTopics.has("all")) {
    if (!link.topics.some((t) => state.activeTopics.has(t))) return false;
  }
  // Text search across url, domain, label, and source video/channel names.
  if (state.search) {
    const hay = [
      link.url, link.domain, link.label,
      ...link.sources.map((s) => s.video_title),
      ...link.sources.map((s) => s.channel),
    ].join(" ").toLowerCase();
    if (!hay.includes(state.search)) return false;
  }
  return true;
}

function render() {
  const links = state.data.links.filter(matches);
  const sorted = links.slice().sort(sorter);

  els.results.innerHTML = "";
  if (sorted.length === 0) {
    els.empty.classList.remove("hidden");
    els.empty.textContent = "No links match your filters.";
  } else {
    els.empty.classList.add("hidden");
    const frag = document.createDocumentFragment();
    sorted.forEach((link, i) => frag.appendChild(card(link, i + 1)));
    els.results.appendChild(frag);
  }
  els.count.textContent = `Showing ${sorted.length} of ${state.data.links.length} links`;
}

function sorter(a, b) {
  switch (state.sort) {
    case "domain": return a.domain.localeCompare(b.domain);
    case "video_count": return b.video_count - a.video_count || b.score - a.score;
    case "channel_count": return b.channel_count - a.channel_count || b.score - a.score;
    default: return b.score - a.score || b.video_count - a.video_count;
  }
}

function card(link, rank) {
  const el = document.createElement("div");
  el.className = "card";

  const badges = link.topics
    .map((t) => `<span class="badge" data-topic="${t}">${esc(labelFor(t))}</span>`)
    .join("");

  const seen = `seen in <b>${link.video_count}</b> video${link.video_count === 1 ? "" : "s"}` +
    ` across <b>${link.channel_count}</b> channel${link.channel_count === 1 ? "" : "s"}`;

  el.innerHTML = `
    <div class="card-top">
      <div class="rank"><b>${rank}</b>score ${link.score}</div>
      <div class="card-main">
        <div class="link-title">${esc(link.label)}<span class="domain">${esc(link.domain)}</span></div>
        <a class="url" href="${esc(link.url)}" target="_blank" rel="noopener noreferrer">${esc(link.url)}</a>
        <div class="badges">
          ${badges}
          <span class="stat">· ${seen}</span>
        </div>
        <button class="sources-toggle">Show ${link.sources.length} source video${link.sources.length === 1 ? "" : "s"}</button>
        <div class="sources">${sourcesHtml(link.sources)}</div>
      </div>
    </div>`;

  const toggle = el.querySelector(".sources-toggle");
  const sources = el.querySelector(".sources");
  toggle.addEventListener("click", () => {
    const open = sources.classList.toggle("open");
    toggle.textContent = open
      ? "Hide source videos"
      : `Show ${link.sources.length} source video${link.sources.length === 1 ? "" : "s"}`;
  });
  return el;
}

function sourcesHtml(sources) {
  return sources.map((s) => {
    const video = s.video_url
      ? `<a href="${esc(s.video_url)}" target="_blank" rel="noopener noreferrer">${esc(s.video_title)}</a>`
      : esc(s.video_title);
    const ch = s.channel
      ? ` <span class="ch">— ${s.channel_url
          ? `<a href="${esc(s.channel_url)}" target="_blank" rel="noopener noreferrer">${esc(s.channel)}</a>`
          : esc(s.channel)}</span>`
      : "";
    return `<div class="source">▸ ${video}${ch}</div>`;
  }).join("");
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
