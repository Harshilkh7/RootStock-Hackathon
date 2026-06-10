const queryInput = document.getElementById("query");
const runButton = document.getElementById("runButton");
const downloadMarkdownButton = document.getElementById("downloadMarkdownButton");
const downloadHtmlButton = document.getElementById("downloadHtmlButton");
const statusLabel = document.getElementById("status");
const planList = document.getElementById("plan");
const queriesList = document.getElementById("queries");
const loopTraceList = document.getElementById("loopTrace");
const sourcesList = document.getElementById("sources");
const evidenceList = document.getElementById("evidence");
const reportBlock = document.getElementById("report");
let latestResult = null;

function renderList(container, items, ordered = false) {
  container.innerHTML = "";
  items.forEach((item) => {
    const node = document.createElement(ordered ? "li" : "li");
    node.textContent = item;
    container.appendChild(node);
  });
}

function renderSources(sources) {
  sourcesList.innerHTML = "";
  sources.forEach((source) => {
    const card = document.createElement("article");
    card.className = "card";
    card.innerHTML = `
      <h3><a href="${source.url}" target="_blank" rel="noreferrer">${source.title}</a></h3>
      <p>${source.publisher} · ${source.source_type} · ${source.published_at}</p>
      <p><strong>VGRH:</strong> ${source.scores.vgrh.toFixed(2)}</p>
      <p><strong>Breakdown:</strong> V ${source.scores.veracity.toFixed(2)} · G ${source.scores.grounding.toFixed(2)} · R ${source.scores.relevance.toFixed(2)} · H ${source.scores.helpfulness.toFixed(2)}</p>
      <p>${source.reason}</p>
    `;
    sourcesList.appendChild(card);
  });
}

function renderEvidence(evidence) {
  evidenceList.innerHTML = "";
  evidence.forEach((item) => {
    const card = document.createElement("article");
    card.className = "card";
    card.innerHTML = `
      <h3>${item.claim}</h3>
      <p>${item.snippet}</p>
      <p><a href="${item.source_url}" target="_blank" rel="noreferrer">${item.source_title}</a></p>
      <p><strong>Confidence:</strong> ${item.confidence.toFixed(2)} · <strong>Support:</strong> ${item.support_count} sources · <strong>Status:</strong> ${item.verification}${item.contradiction_flag ? " · uncertainty flagged" : ""}</p>
    `;
    evidenceList.appendChild(card);
  });
}

function renderLoopTrace(items) {
  loopTraceList.innerHTML = "";
  items.forEach((item) => {
    const node = document.createElement("li");
    const addedQueries = item.added_queries.length ? item.added_queries.join(" | ") : "none";
    node.textContent = `Iteration ${item.iteration}: ${item.note} (avg grounding ${item.avg_grounding}, added queries: ${addedQueries})`;
    loopTraceList.appendChild(node);
  });
}

function downloadTextFile(filename, body, mimeType) {
  const blob = new Blob([body], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function runResearch() {
  const query = queryInput.value.trim();
  if (!query) {
    statusLabel.textContent = "Enter a query first";
    return;
  }

  runButton.disabled = true;
  statusLabel.textContent = "Running pipeline...";

  try {
    const response = await fetch("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query })
    });

    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }

    const result = await response.json();
    latestResult = result;
    renderList(planList, result.research_plan, true);
    renderList(queriesList, result.generated_queries, false);
    renderLoopTrace(result.iterative_trace || []);
    renderSources(result.sources);
    renderEvidence(result.evidence);
    reportBlock.textContent = result.report_markdown;
    statusLabel.textContent = "Completed";
  } catch (error) {
    statusLabel.textContent = `Error: ${error.message}`;
  } finally {
    runButton.disabled = false;
  }
}

runButton.addEventListener("click", runResearch);
downloadMarkdownButton.addEventListener("click", () => {
  if (!latestResult) {
    statusLabel.textContent = "Run research first";
    return;
  }
  downloadTextFile("research-report.md", latestResult.report_markdown, "text/markdown;charset=utf-8");
});
downloadHtmlButton.addEventListener("click", () => {
  if (!latestResult) {
    statusLabel.textContent = "Run research first";
    return;
  }
  downloadTextFile("research-report.html", latestResult.report_html, "text/html;charset=utf-8");
});
window.addEventListener("load", runResearch);
