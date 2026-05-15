function toggleMenu() {
  const navbar = document.getElementById("myNavbar");
  navbar.className = navbar.className === "navbar" ? "navbar responsive" : "navbar";
}

const pageState = {
  rowsByTrack: {},
  summariesByTrack: {},
  profileSvgsByTrack: {},
  currentRows: [],
  currentTrack: "",
};

function parseTsv(text) {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length === 0) {
    return [];
  }

  const headers = lines[0].split("\t");
  return lines.slice(1).map((line) => {
    const values = line.split("\t");
    const row = {};
    headers.forEach((header, index) => {
      row[header] = values[index] || "";
    });
    return row;
  });
}

function parseEmbeddedJson(id) {
  const element = document.getElementById(id);
  if (!element) {
    return null;
  }

  const raw = element.textContent.trim();
  if (!raw) {
    return null;
  }

  return JSON.parse(raw);
}

const EMBEDDED_EXPERIMENTS = Array.isArray(parseEmbeddedJson("embeddedExperiments")) ? parseEmbeddedJson("embeddedExperiments") : [];
const EXPERIMENTS_BY_ID = Object.fromEntries(EMBEDDED_EXPERIMENTS.map((experiment) => [experiment.experiment_id, experiment]));
const DEFAULT_EXPERIMENT_ID = parseEmbeddedJson("embeddedDefaultExperimentId") || "";

function uniqueValues(rows, key) {
  return [...new Set(rows.map((row) => row[key]).filter(Boolean))].sort();
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function formatSeconds(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return value || "-";
  }
  if (number < 0.001) {
    return number.toExponential(2);
  }
  if (number < 1) {
    return number.toFixed(4);
  }
  return number.toFixed(3);
}

function currentExperiment(trackName = pageState.currentTrack) {
  return EXPERIMENTS_BY_ID[trackName] || null;
}

function availableTracks() {
  return EMBEDDED_EXPERIMENTS.map((experiment) => experiment.experiment_id);
}

function softwareNameFromRow(row) {
  return `${row.software}${row.version ? ` ${row.version}` : ""}`;
}

function softwareDisplayNameFromRow(row) {
  const base = softwareNameFromRow(row);
  const threads = String(row.threads || "").trim();
  return threads ? `${base} (${threads}t)` : base;
}

function normalizeMachine(machine) {
  const value = String(machine || "").trim().toLowerCase();
  if (!value) {
    return "";
  }
  if (value === "amd64" || value === "x86_64") {
    return "x86_64";
  }
  if (value === "arm64" || value === "aarch64") {
    return "aarch64";
  }
  if (value === "x86" || value === "i386" || value === "i686") {
    return "i686";
  }
  return value.replace(/\s+/g, "-");
}

function osFamilyLabel(osText) {
  const text = String(osText || "").toLowerCase();
  if (text.includes("windows")) {
    return "Windows";
  }
  if (text.includes("linux")) {
    return "Linux";
  }
  if (text.includes("darwin") || text.includes("mac")) {
    return "macOS";
  }
  return String(osText || "").split(/[\s-]/)[0] || "Unknown";
}

function juliaTargetTriple(osText, machineText) {
  const machine = normalizeMachine(machineText);
  const text = String(osText || "").toLowerCase();
  if (!machine && !text) {
    return "";
  }
  if (text.includes("windows")) {
    return `${machine || "unknown"}-w64-mingw32`;
  }
  if (text.includes("linux")) {
    return `${machine || "unknown"}-linux-gnu`;
  }
  if (text.includes("darwin") || text.includes("mac")) {
    return `${machine || "unknown"}-apple-darwin`;
  }
  return machine;
}

function parseHardwareSummary(summary) {
  const parts = String(summary || "")
    .split("|")
    .map((part) => part.trim())
    .filter(Boolean);

  return {
    track: parts[0] || "",
    host: parts[1] || "",
    os: parts.slice(2).join(" | ") || "",
  };
}

function latestExperimentTimestamp(rows) {
  const timestamps = rows
    .map((row) => row.finished_at_utc || row.started_at_utc || "")
    .filter(Boolean)
    .sort();
  return timestamps.length ? timestamps[timestamps.length - 1] : "";
}

function formatUtcTimestamp(value) {
  if (!value) {
    return "Not recorded";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes} UTC`;
}

function populateFilters(rows) {
  const familyFilter = document.getElementById("familyFilter");
  const softwareFilter = document.getElementById("softwareFilter");
  const previousFamily = familyFilter.value;
  const previousSoftware = softwareFilter.value;

  familyFilter.innerHTML = '<option value="">All families</option>';
  softwareFilter.innerHTML = '<option value="">All software</option>';

  uniqueValues(rows, "system_id").forEach((family) => {
    const option = document.createElement("option");
    option.value = family;
    option.textContent = family;
    familyFilter.appendChild(option);
  });

  uniqueValues(rows, "software").forEach((software) => {
    const option = document.createElement("option");
    option.value = software;
    option.textContent = software;
    softwareFilter.appendChild(option);
  });

  if ([...familyFilter.options].some((option) => option.value === previousFamily)) {
    familyFilter.value = previousFamily;
  }

  if ([...softwareFilter.options].some((option) => option.value === previousSoftware)) {
    softwareFilter.value = previousSoftware;
  }
}

function compareRows(left, right) {
  return left.instance_id.localeCompare(right.instance_id) || left.software.localeCompare(right.software);
}

function formatTimingCell(row) {
  if (!row) {
    return "-";
  }
  if (row.status !== "ok") {
    return row.status || "-";
  }
  if (row.wall_time_seconds) {
    return formatSeconds(row.wall_time_seconds);
  }
  return formatSeconds(row.process_wall_time_seconds);
}

function renderTimingsMatrix(rows) {
  const table = document.getElementById("timingsMatrixTable");
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  const downloadLink = document.getElementById("downloadTimingsCsv");
  const softwareNames = uniqueValues(rows, "software");
  const orderedInstances = uniqueValues(rows, "instance_id");

  if (softwareNames.length === 0) {
    thead.innerHTML = '<tr><th>Example</th></tr>';
    tbody.innerHTML = '<tr><td>No software selected.</td></tr>';
    if (downloadLink) {
      downloadLink.hidden = true;
      downloadLink.removeAttribute("href");
    }
    return;
  }

  thead.innerHTML = `
    <tr>
      <th>Example</th>
      ${softwareNames.map((software) => `<th>${escapeHtml(software)}</th>`).join("")}
    </tr>
  `;

  const rowsByInstanceAndSoftware = new Map();
  const sampleRowByInstance = new Map();
  rows.forEach((row) => {
    rowsByInstanceAndSoftware.set(`${row.instance_id}::${row.software}`, row);
    if (!sampleRowByInstance.has(row.instance_id)) {
      sampleRowByInstance.set(row.instance_id, row);
    }
  });

  tbody.innerHTML = orderedInstances.map((instanceId) => `
    <tr>
      <td>${(() => {
        const sample = sampleRowByInstance.get(instanceId);
        const href = sample && sample.system_ref ? `./${encodeURI(sample.system_ref)}` : "";
        const label = escapeHtml(instanceId);
        return href ? `<a class="instance-link" href="${href}">${label}</a>` : label;
      })()}</td>
      ${softwareNames.map((software) => {
        const row = rowsByInstanceAndSoftware.get(`${instanceId}::${software}`);
        return `<td>${escapeHtml(formatTimingCell(row))}</td>`;
      }).join("")}
    </tr>
  `).join("");

  if (downloadLink) {
    const csvLines = [
      ["Example", ...softwareNames].map(csvEscape).join(","),
      ...orderedInstances.map((instanceId) => [
        instanceId,
        ...softwareNames.map((software) => formatTimingCell(rowsByInstanceAndSoftware.get(`${instanceId}::${software}`))),
      ].map(csvEscape).join(",")),
    ];
    const fileStem = (pageState.currentTrack || "benchmark_results").replace(/[^a-z0-9_-]+/gi, "_").toLowerCase();
    downloadLink.href = `data:text/csv;charset=utf-8,${encodeURIComponent(csvLines.join("\r\n"))}`;
    downloadLink.download = `${fileStem}_timings.csv`;
    downloadLink.hidden = false;
  }
}

function renderResultsTable(rows) {
  const tbody = document.querySelector("#resultsTable tbody");
  const family = document.getElementById("familyFilter").value;
  const software = document.getElementById("softwareFilter").value;
  const search = document.getElementById("searchFilter").value.trim().toLowerCase();

  const filtered = rows
    .filter((row) => !family || row.system_id === family)
    .filter((row) => !software || row.software === software)
    .filter((row) => !search || row.instance_id.toLowerCase().includes(search));

  const ordered = filtered.slice().sort(compareRows);
  if (ordered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10">No rows match the current filters.</td></tr>';
    return;
  }

  tbody.innerHTML = ordered.map((row) => {
    const statusClass = `status-${row.status || "error"}`;
    const systemHref = row.system_ref ? `./${encodeURI(row.system_ref)}` : "";
    return `
      <tr>
        <td>${row.instance_id}</td>
        <td>${row.system_id}</td>
        <td>${row.software}</td>
        <td>${row.threads}</td>
        <td class="${statusClass}">${row.status}</td>
        <td>${formatSeconds(row.wall_time_seconds)}</td>
        <td>${formatSeconds(row.process_wall_time_seconds)}</td>
        <td>${systemHref ? `<a href="${systemHref}">${row.system_id}</a>` : row.system_id}</td>
        <td><a href="./${row.input_ref}">${row.input_ref}</a></td>
        <td><a href="./${row.log_ref}">log</a></td>
      </tr>
    `;
  }).join("");
}

function renderProfileSvg(trackName) {
  const mount = document.getElementById("profileFigure");
  const svgText = pageState.profileSvgsByTrack[trackName];

  if (!svgText) {
    mount.textContent = "No profile available.";
    return;
  }

  mount.innerHTML = svgText;
}

function renderCurrentTrackArtifacts(trackName, rows) {
  const info = currentExperiment(trackName);
  if (!info) {
    document.getElementById("currentExperimentDate").textContent = "";
    document.getElementById("currentExperimentSoftwareSummary").textContent = "";
    document.getElementById("currentExperimentSoftware").innerHTML = "";
    document.getElementById("currentExperimentInstanceSummary").textContent = "";
    document.getElementById("currentExperimentInstances").innerHTML = "";
    document.getElementById("currentExperimentOs").textContent = "";
    document.getElementById("currentExperimentCpu").textContent = "";
    document.getElementById("currentExperimentFlags").textContent = "";
    document.getElementById("reproduceCommand").textContent = "";
    const downloadLink = document.getElementById("downloadTimingsCsv");
    if (downloadLink) {
      downloadLink.hidden = true;
      downloadLink.removeAttribute("href");
    }
    return;
  }

  const softwareNames = [...new Set(rows.map((row) => softwareDisplayNameFromRow(row)).filter(Boolean))].sort();
  const instances = uniqueValues(rows, "instance_id");
  const hardwareFallback = parseHardwareSummary(info.hardware_summary);
  const osValues = [...new Set(rows.map((row) => (row.runner_os || "").trim()).filter(Boolean))].sort();
  const processors = [...new Set(rows.map((row) => (row.runner_processor || "").trim()).filter(Boolean))].sort();
  const cpuCounts = [...new Set(rows.map((row) => (row.runner_cpu_count || "").trim()).filter(Boolean))].sort();
  const wordSizes = [...new Set(rows.map((row) => (row.runner_word_size || "").trim()).filter(Boolean))].sort();
  const machines = [...new Set(rows.map((row) => (row.runner_machine || "").trim()).filter(Boolean))].sort();
  const date = formatUtcTimestamp(latestExperimentTimestamp(rows));
  const replayCommand = info.replay_command || `python bench/benchmark.py ${trackName}`;
  const osText = osValues[0] || hardwareFallback.os;
  const processorText = processors.join(", ");
  const cpuCountText = cpuCounts.length === 1 ? cpuCounts[0] : cpuCounts.join(", ");
  const wordSizeText = wordSizes.length === 1 ? wordSizes[0] : wordSizes.join(", ");
  const machineText = machines.length === 1 ? machines[0] : machines[0] || "";
  const targetTriple = juliaTargetTriple(osText, machineText);
  const cpuLine = processorText
    ? `${cpuCountText ? `${cpuCountText} × ` : ""}${processorText}`
    : "Not recorded";
  const osLine = `${osFamilyLabel(osText)}${targetTriple ? ` (${targetTriple})` : ""}`;

  document.getElementById("currentExperimentDate").textContent = date;
  document.getElementById("currentExperimentSoftwareSummary").textContent = softwareNames.length
    ? `${softwareNames.length} software entries`
    : "No software listed";
  document.getElementById("currentExperimentSoftware").innerHTML = softwareNames.length
    ? softwareNames.map((name) => `<li>${escapeHtml(name)}</li>`).join("")
    : '<li class="muted">No software listed.</li>';
  document.getElementById("currentExperimentInstanceSummary").textContent = instances.length
    ? `${instances.length} benchmark instances`
    : "No benchmark instances";
  document.getElementById("currentExperimentInstances").innerHTML = instances.length
    ? instances.map((instance) => `<li>${escapeHtml(instance)}</li>`).join("")
    : '<li class="muted">No benchmark instances listed.</li>';
  document.getElementById("currentExperimentOs").textContent = osLine;
  document.getElementById("currentExperimentCpu").textContent = `${cpuLine}${wordSizeText ? `, WORD_SIZE ${wordSizeText}` : ""}`;
  document.getElementById("currentExperimentFlags").textContent = "Not recorded";

  document.getElementById("reproduceCommand").textContent = [
    "git clone https://github.com/sumiya11/GroebnerBenchmark.git",
    "cd GroebnerBenchmark",
    "python -m pip install -r requirements.txt",
    replayCommand,
  ].join("\n");
}

async function fetchText(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to fetch ${path}: ${response.status}`);
  }
  return response.text();
}

async function ensureTrackData(trackName) {
  if (pageState.rowsByTrack[trackName] && pageState.summariesByTrack[trackName] && pageState.profileSvgsByTrack[trackName]) {
    return;
  }

  const embeddedRuns = parseEmbeddedJson("embeddedTrackRuns") || {};
  const embeddedSummaries = parseEmbeddedJson("embeddedTrackSummaries") || {};
  const embeddedProfiles = parseEmbeddedJson("embeddedTrackProfiles") || {};
  let runsText = embeddedRuns[trackName] || null;
  let summaryText = embeddedSummaries[trackName] || null;
  let profileText = embeddedProfiles[trackName] || null;

  if (runsText === null || summaryText === null || profileText === null) {
    const info = currentExperiment(trackName);
    [runsText, summaryText, profileText] = await Promise.all([
      fetchText(info.results_path),
      fetchText(info.summary_path),
      fetchText(info.profile_path),
    ]);
  }

  pageState.rowsByTrack[trackName] = parseTsv(runsText);
  pageState.summariesByTrack[trackName] = parseTsv(summaryText);
  pageState.profileSvgsByTrack[trackName] = profileText;
}

function refreshCurrentTrackView() {
  renderCurrentTrackArtifacts(pageState.currentTrack, pageState.currentRows);
  renderProfileSvg(pageState.currentTrack);
  renderTimingsMatrix(pageState.currentRows);
  populateFilters(pageState.currentRows);
  renderResultsTable(pageState.currentRows);
}

async function setTrack(trackName) {
  await ensureTrackData(trackName);
  pageState.currentTrack = trackName;
  pageState.currentRows = pageState.rowsByTrack[trackName];

  document.getElementById("familyFilter").value = "";
  document.getElementById("softwareFilter").value = "";
  document.getElementById("searchFilter").value = "";

  refreshCurrentTrackView();
}

async function loadPage() {
  const trackSelector = document.getElementById("trackSelector");
  const tracks = availableTracks();
  if (tracks.length === 0) {
    throw new Error("No benchmark experiments were found in the built results directory.");
  }

  trackSelector.innerHTML = tracks.map((track) => `<option value="${track}">${escapeHtml(currentExperiment(track).label)}</option>`).join("");
  const defaultTrack = tracks.includes(DEFAULT_EXPERIMENT_ID) ? DEFAULT_EXPERIMENT_ID : (tracks.includes("test") ? "test" : tracks[0]);
  trackSelector.value = defaultTrack;

  trackSelector.addEventListener("change", (event) => {
    setTrack(event.target.value).catch((error) => {
      document.querySelector("#resultsTable tbody").innerHTML = `<tr><td colspan="10">Failed to load results: ${error}</td></tr>`;
    });
  });

  ["familyFilter", "softwareFilter", "searchFilter"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => renderResultsTable(pageState.currentRows));
    document.getElementById(id).addEventListener("change", () => renderResultsTable(pageState.currentRows));
  });

  await setTrack(defaultTrack);
}

loadPage().catch((error) => {
  document.querySelector("#resultsTable tbody").innerHTML = `<tr><td colspan="10">Failed to load results: ${error}</td></tr>`;
});
