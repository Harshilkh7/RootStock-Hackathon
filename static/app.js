const queryInput = document.getElementById("query");
const runButton = document.getElementById("runButton");
const statusLabel = document.getElementById("status");
const planList = document.getElementById("plan");
const queriesList = document.getElementById("queries");
const sourcesList = document.getElementById("sources");
const evidenceList = document.getElementById("evidence");
const reportBlock = document.getElementById("report");

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
      <p><strong>Confidence:</strong> ${item.confidence.toFixed(2)}${item.contradiction_flag ? " · uncertainty flagged" : ""}</p>
    `;
    evidenceList.appendChild(card);
  });
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
    renderList(planList, result.research_plan, true);
    renderList(queriesList, result.generated_queries, false);
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
window.addEventListener("load", runResearch);
