const pageState = {
  rowsByTrack: {},
  currentRows: [],
  currentTrack: "",
  profileThresholdIndex: 2,
  matrixSort: {
    column: "__example__",
    direction: "asc",
  },
};

const PROFILE_THRESHOLDS = [0, 0.01, 0.1, 1, 10];
const PROFILE_COLORS = ["#0b6e4f", "#c84c09", "#005f99", "#8f2d56", "#6b8e23", "#6a4c93"];

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
const GITHUB_REPO_BASE = "https://github.com/sumiya11/Polynomial_systems_benchmark";

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

function formatDuration(seconds) {
  const totalSeconds = Math.round(Number(seconds));
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) {
    return "Not recorded";
  }

  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(remainingSeconds).padStart(2, "0")}s`;
  }
  if (minutes > 0) {
    return `${minutes}m ${String(remainingSeconds).padStart(2, "0")}s`;
  }
  return `${remainingSeconds}s`;
}

function formatMemoryMb(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return value || "-";
  }
  if (number >= 1024) {
    return `${(number / 1024).toFixed(2)} GB`;
  }
  return `${number.toFixed(0)} MB`;
}

function geometricMean(values) {
  if (!values.length) {
    return Number.POSITIVE_INFINITY;
  }
  return Math.exp(values.reduce((sum, value) => sum + Math.log(value), 0) / values.length);
}

function estimatedSvgTextWidth(text, fontSize = 16) {
  return Math.max(0, String(text).length * fontSize * 0.58);
}

function formatTauTickLabel(tick) {
  if (tick < 10) {
    return Number(tick.toPrecision(6)).toString();
  }
  return tick.toFixed(0);
}

function profileXTicks(maxTau) {
  const ticks = [1.0, 1.25, 1.5, 2.0, 3.0, 5.0].filter((tick) => tick <= maxTau);
  let scale = 10.0;
  while (scale <= maxTau * 1.001) {
    [1.0, 2.0, 5.0].forEach((multiplier) => {
      const tick = scale * multiplier;
      if (tick <= maxTau * 1.001) {
        ticks.push(tick);
      }
    });
    scale *= 10.0;
  }
  return ticks.map((tick) => [tick, formatTauTickLabel(tick)]);
}

function profileProblemName(row) {
  return [row.instance_id, row.field, row.order, row.hardware_track].join(" | ");
}

function profileDisplayName(row) {
  return softwareDisplayNameFromRow(row);
}

function currentProfileThresholdSeconds() {
  return PROFILE_THRESHOLDS[pageState.profileThresholdIndex] ?? PROFILE_THRESHOLDS[2];
}

function formatProfileThreshold(thresholdSeconds) {
  if (thresholdSeconds <= 0) {
    return "all solved cases";
  }
  return `${Number(thresholdSeconds.toPrecision(6)).toString()} s`;
}

function computeProfileData(rows, minBestTimeSeconds) {
  const validRows = rows.filter((row) => row.status === "ok" && Number.isFinite(Number(row.wall_time_seconds)));
  const solvedProblems = new Map();

  validRows.forEach((row) => {
    const key = profileProblemName(row);
    if (!solvedProblems.has(key)) {
      solvedProblems.set(key, []);
    }
    solvedProblems.get(key).push(row);
  });

  const eligibleProblems = [];
  solvedProblems.forEach((problemRows) => {
    const bestTime = Math.min(...problemRows.map((row) => Number(row.wall_time_seconds)));
    if (minBestTimeSeconds > 0 && bestTime <= minBestTimeSeconds) {
      return;
    }
    eligibleProblems.push({ rows: problemRows, bestTime });
  });

  const totalSolvedCases = solvedProblems.size;
  const eligibleCaseCount = eligibleProblems.length;
  if (!eligibleCaseCount) {
    return {
      totalSolvedCases,
      eligibleCaseCount,
      thresholdSeconds: minBestTimeSeconds,
      taus: [1.0],
      series: [],
      summaryRows: [],
    };
  }

  const ratiosByProfile = new Map();
  const winsByProfile = new Map();
  const solvedByProfile = new Map();
  const softwareByProfile = new Map();

  eligibleProblems.forEach(({ rows: problemRows, bestTime }) => {
    problemRows.forEach((row) => {
      const profile = profileDisplayName(row);
      const ratio = Number(row.wall_time_seconds) / bestTime;
      if (!ratiosByProfile.has(profile)) {
        ratiosByProfile.set(profile, []);
      }
      ratiosByProfile.get(profile).push(ratio);
      solvedByProfile.set(profile, (solvedByProfile.get(profile) || 0) + 1);
      if (!softwareByProfile.has(profile)) {
        softwareByProfile.set(profile, row.software || profile);
      }
      if (Math.abs(ratio - 1.0) <= 1e-12 || Math.abs(ratio - 1.0) / Math.max(1, Math.abs(ratio)) <= 1e-9) {
        winsByProfile.set(profile, (winsByProfile.get(profile) || 0) + 1);
      }
    });
  });

  const maxRatio = Math.max(...Array.from(ratiosByProfile.values(), (ratios) => Math.max(...ratios)));
  const upper = Math.max(2.0, maxRatio * 1.05);
  const taus = Array.from({ length: 80 }, (_, index) => Math.exp(Math.log(upper) * index / 79.0));
  taus[0] = 1.0;

  const series = Array.from(ratiosByProfile.keys()).sort().map((profile, index) => {
    const ratios = [...ratiosByProfile.get(profile)].sort((left, right) => left - right);
    const points = taus.map((tau) => {
      const covered = ratios.filter((ratio) => ratio <= tau).length;
      return [tau, covered / eligibleCaseCount];
    });
    return {
      profile,
      software: softwareByProfile.get(profile) || profile,
      color: PROFILE_COLORS[index % PROFILE_COLORS.length],
      ratios,
      points,
    };
  });

  const summaryRows = series.map((entry) => ({
    profile: entry.profile,
    cases: eligibleCaseCount,
    solved: solvedByProfile.get(entry.profile) || 0,
    wins: winsByProfile.get(entry.profile) || 0,
    geomean_ratio: geometricMean(entry.ratios),
  }));

  return {
    totalSolvedCases,
    eligibleCaseCount,
    thresholdSeconds: minBestTimeSeconds,
    taus,
    series,
    summaryRows,
  };
}

function renderProfileSvgMarkup(profileData) {
  const thresholdSeconds = profileData.thresholdSeconds;
  const left = 84;
  const top = 24;
  const right = 28;
  const plotWidth = 700;
  const plotHeight = 348;
  const legendGapX = 24;
  const legendRowHeight = 30;
  const legendLineWidth = 30;
  const legendTextGap = 10;
  const legendLabels = profileData.series.map((entry) => entry.profile);
  const legendLabelWidth = Math.max(0, ...legendLabels.map((label) => estimatedSvgTextWidth(label)));
  const legendCellWidth = Math.max(172, Math.ceil(legendLineWidth + legendTextGap + legendLabelWidth + 8));
  const legendColumns = legendLabels.length > 1 ? 2 : 1;
  const legendRows = legendLabels.length ? Math.ceil(legendLabels.length / legendColumns) : 0;
  const legendBlockWidth = legendLabels.length
    ? legendColumns * legendCellWidth + Math.max(0, legendColumns - 1) * legendGapX
    : 0;
  const tickLabelBand = 36;
  const axisLabelBand = 30;
  const legendGapTop = legendRows ? 18 : 0;
  const legendTop = top + plotHeight + tickLabelBand + axisLabelBand + legendGapTop;
  const height = legendTop + legendRows * legendRowHeight + (legendRows ? 20 : 12);
  const width = left + Math.max(plotWidth, legendBlockWidth) + right;

  if (!profileData.series.length) {
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title desc" class="interactive-profile-svg">\n`
      + `  <title id="title">Performance profile</title>\n`
      + `  <desc id="desc">No profile data was available for the selected threshold.</desc>\n`
      + `  <text x="${width / 2}" y="${height / 2}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="20" fill="#444">No profile data available</text>\n`
      + `</svg>\n`;
  }

  const maxTau = Math.max(...profileData.taus);
  const logMax = Math.log(maxTau);
  const xCoord = (tau) => (logMax === 0 ? left : left + plotWidth * Math.log(tau) / logMax);
  const yCoord = (value) => top + plotHeight * (1 - value);

  const gridLines = [];
  [0.0, 0.25, 0.5, 0.75, 1.0].forEach((yTick) => {
    const y = yCoord(yTick);
    gridLines.push(`<line x1="${left}" y1="${y.toFixed(1)}" x2="${left + plotWidth}" y2="${y.toFixed(1)}" stroke="#d8d2c4" stroke-width="1"/>`);
    gridLines.push(`<text x="${left - 12}" y="${(y + 5).toFixed(1)}" text-anchor="end" font-size="15" fill="#444">${yTick.toFixed(2)}</text>`);
  });

  let previousXLabelRight = Number.NEGATIVE_INFINITY;
  profileXTicks(maxTau).forEach(([tick, tickLabel]) => {
    const x = xCoord(tick);
    gridLines.push(`<line x1="${x.toFixed(1)}" y1="${top}" x2="${x.toFixed(1)}" y2="${top + plotHeight}" stroke="#ece6da" stroke-width="1"/>`);
    const labelHalfWidth = estimatedSvgTextWidth(tickLabel, 15) / 2;
    if (x - labelHalfWidth <= previousXLabelRight + 8) {
      return;
    }
    gridLines.push(`<text x="${x.toFixed(1)}" y="${top + plotHeight + 28}" text-anchor="middle" font-size="15" fill="#444">${escapeHtml(tickLabel)}</text>`);
    previousXLabelRight = x + labelHalfWidth;
  });

  const legendOriginX = left + Math.max(0, (plotWidth - legendBlockWidth) / 2);
  const paths = [];
  const legend = [];

  profileData.series.forEach((entry, index) => {
    const pathCommands = entry.points.map(([tau, value], pointIndex) => `${pointIndex === 0 ? "M" : "L"} ${xCoord(tau).toFixed(2)} ${yCoord(value).toFixed(2)}`);
    const tooltip = escapeHtml(`${entry.profile} | ${entry.software}`);
    const profileAttr = escapeHtml(entry.profile);
    const softwareAttr = escapeHtml(entry.software);
    paths.push(
      `<g class="profile-series" data-profile="${profileAttr}" data-software="${softwareAttr}" tabindex="0">`
      + `<title>${tooltip}</title>`
      + `<path class="profile-series-hitbox" d="${pathCommands.join(" ")}" fill="none" stroke="transparent" stroke-width="14"/>`
      + `<path class="profile-series-line" d="${pathCommands.join(" ")}" fill="none" stroke="${entry.color}" stroke-width="3"/>`
      + `</g>`
    );

    const legendRow = Math.floor(index / legendColumns);
    const legendColumn = index % legendColumns;
    const legendX = legendOriginX + legendColumn * (legendCellWidth + legendGapX);
    const legendY = legendTop + legendRow * legendRowHeight;
    legend.push(
      `<g class="profile-legend-entry" data-profile="${profileAttr}" data-software="${softwareAttr}" tabindex="0">`
      + `<title>${tooltip}</title>`
      + `<line class="profile-legend-line" x1="${legendX.toFixed(1)}" y1="${legendY.toFixed(1)}" x2="${(legendX + legendLineWidth).toFixed(1)}" y2="${legendY.toFixed(1)}" stroke="${entry.color}" stroke-width="4"/>`
      + `<text class="profile-legend-label" x="${(legendX + legendLineWidth + legendTextGap).toFixed(1)}" y="${(legendY + 6).toFixed(1)}" font-size="16" fill="#222">${escapeHtml(entry.profile)}</text>`
      + `</g>`
    );
  });

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title desc" class="interactive-profile-svg">\n`
    + `  <title id="title">Performance profile</title>\n`
    + `  <desc id="desc">Fraction of cases with best runtime above ${escapeHtml(formatProfileThreshold(thresholdSeconds))} solved within a factor tau of the best runtime.</desc>\n`
    + `  <rect x="${left}" y="${top}" width="${plotWidth}" height="${plotHeight}" fill="none" stroke="#b7ae98" stroke-width="1.5"/>\n`
    + `  ${gridLines.join("")}\n`
    + `  ${paths.join("")}\n`
    + `  ${legend.join("")}\n`
    + `  <text x="${left + plotWidth / 2}" y="${top + plotHeight + tickLabelBand + 18}" text-anchor="middle" font-size="16" fill="#333">tau = runtime / best-runtime-on-case</text>\n`
    + `  <text x="26" y="${top + plotHeight / 2}" text-anchor="middle" transform="rotate(-90 26 ${top + plotHeight / 2})" font-size="16" fill="#333">fraction of cases</text>\n`
    + `</svg>\n`;
}

function updateProfileFilterText(profileData) {
  const thresholdSeconds = profileData.thresholdSeconds;
  const summary = document.getElementById("profileThresholdSummary");
  const note = document.getElementById("profileNoteText");
  const slider = document.getElementById("profileThreshold");
  if (!summary || !note) {
    return;
  }

  if (thresholdSeconds <= 0) {
    note.textContent = "Using all solved cases.";
  } else {
    note.textContent = `Using cases with fastest run > ${formatProfileThreshold(thresholdSeconds)}.`;
  }

  summary.textContent = `${profileData.eligibleCaseCount} of ${profileData.totalSolvedCases} solved cases shown.`;
  if (slider) {
    slider.setAttribute("aria-valuetext", thresholdSeconds <= 0 ? "all solved cases" : formatProfileThreshold(thresholdSeconds));
  }
}

function currentExperiment(trackName = pageState.currentTrack) {
  return EXPERIMENTS_BY_ID[trackName] || null;
}

function availableTracks() {
  return EMBEDDED_EXPERIMENTS.map((experiment) => experiment.experiment_id);
}

function isAxf4Row(row) {
  return String(row.runner || "").trim() === "axf4" || String(row.software || "").trim().startsWith("axf4");
}

function softwareNameFromRow(row) {
  if (isAxf4Row(row)) {
    return row.software || "";
  }
  return `${row.software}${row.version ? ` ${row.version}` : ""}`;
}

function softwareDisplayNameFromRow(row) {
  const base = softwareNameFromRow(row);
  if (isAxf4Row(row)) {
    return base;
  }
  const threads = String(row.threads || "").trim();
  return threads ? `${base} (${threads}t)` : base;
}

function uniqueTrimmedValues(rows, key) {
  return [...new Set(rows.map((row) => String(row[key] || "").trim()).filter(Boolean))].sort();
}

function joinOrFallback(values, fallback = "Not recorded") {
  return values.length ? values.join(", ") : fallback;
}

function summarizeDetails(values) {
  if (!values.length) {
    return "0 jobs";
  }
  return `${values.length} job${values.length === 1 ? "" : "s"}`;
}

function renderDetailList(rows, emptyMessage) {
  if (!rows.length) {
    return `<li class="muted">${escapeHtml(emptyMessage)}</li>`;
  }
  return rows.map((row) => {
    const label = row.job_id || row.instance_id || row.system_id || "job";
    const details = [row.instance_id, softwareDisplayNameFromRow(row)].filter(Boolean).join(" · ");
    return `<li>${escapeHtml(label)}${details ? `<span class="muted"> — ${escapeHtml(details)}</span>` : ""}</li>`;
  }).join("");
}

function renderSetupItem(label, value) {
  return `<li class="info-row"><span class="info-label">${escapeHtml(label)}</span><span class="info-value">${escapeHtml(value)}</span></li>`;
}

function statusRows(rows, statusName) {
  return rows.filter((row) => String(row.status || "").trim().toLowerCase() === statusName);
}

function runDurationText(rows) {
  const timestamps = rows
    .flatMap((row) => [row.started_at_utc, row.finished_at_utc])
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .map((value) => new Date(value).getTime())
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => left - right);

  if (!timestamps.length) {
    return "Not recorded";
  }

  const durationSeconds = (timestamps[timestamps.length - 1] - timestamps[0]) / 1000;
  if (!Number.isFinite(durationSeconds) || durationSeconds < 0) {
    return "Not recorded";
  }
  return formatDuration(durationSeconds);
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

function githubExperimentUrl(pathValue) {
  const normalized = String(pathValue || "")
    .trim()
    .replace(/^\.\//, "")
    .replace(/\\/g, "/")
    .replace(/^\/+/, "");
  if (!normalized) {
    return "";
  }

  const slashIndex = normalized.lastIndexOf("/");
  const directory = slashIndex >= 0 ? normalized.slice(0, slashIndex) : normalized;
  if (!directory) {
    return GITHUB_REPO_BASE;
  }
  return `${GITHUB_REPO_BASE}/tree/master/${encodeURI(directory)}`;
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

function timingValue(row) {
  if (!row || row.status !== "ok") {
    return Number.POSITIVE_INFINITY;
  }

  const measured = Number(row.wall_time_seconds || row.process_wall_time_seconds || "");
  return Number.isFinite(measured) ? measured : Number.POSITIVE_INFINITY;
}

function matrixSortIndicator(columnKey) {
  const isActive = pageState.matrixSort.column === columnKey;
  if (!isActive) {
    return "&harr;";
  }
  return pageState.matrixSort.direction === "asc" ? "&uarr;" : "&darr;";
}

function setMatrixSort(columnKey) {
  if (pageState.matrixSort.column === columnKey) {
    pageState.matrixSort.direction = pageState.matrixSort.direction === "asc" ? "desc" : "asc";
  } else {
    pageState.matrixSort.column = columnKey;
    pageState.matrixSort.direction = columnKey === "__example__" ? "asc" : "asc";
  }
}

function renderTimingsMatrix(rows) {
  const table = document.getElementById("timingsMatrixTable");
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  const downloadLink = document.getElementById("downloadTimingsCsv");
  const softwareNames = uniqueValues(rows, "software");

  if (softwareNames.length === 0) {
    thead.innerHTML = '<tr><th>Example</th></tr>';
    tbody.innerHTML = '<tr><td>No software selected.</td></tr>';
    if (downloadLink) {
      downloadLink.hidden = true;
      downloadLink.removeAttribute("href");
    }
    return;
  }

  const rowsByInstanceAndSoftware = new Map();
  const sampleRowByInstance = new Map();
  rows.forEach((row) => {
    rowsByInstanceAndSoftware.set(`${row.instance_id}::${row.software}`, row);
    if (!sampleRowByInstance.has(row.instance_id)) {
      sampleRowByInstance.set(row.instance_id, row);
    }
  });

  const orderedInstances = uniqueValues(rows, "instance_id").sort((left, right) => {
    const direction = pageState.matrixSort.direction === "desc" ? -1 : 1;
    if (pageState.matrixSort.column === "__example__") {
      return left.localeCompare(right, undefined, { numeric: true }) * direction;
    }

    const leftRow = rowsByInstanceAndSoftware.get(`${left}::${pageState.matrixSort.column}`);
    const rightRow = rowsByInstanceAndSoftware.get(`${right}::${pageState.matrixSort.column}`);
    const leftValue = timingValue(leftRow);
    const rightValue = timingValue(rightRow);
    const leftSolved = Number.isFinite(leftValue);
    const rightSolved = Number.isFinite(rightValue);

    if (leftSolved !== rightSolved) {
      return leftSolved ? -1 : 1;
    }
    if (leftSolved && rightSolved && leftValue !== rightValue) {
      return (leftValue - rightValue) * direction;
    }
    return left.localeCompare(right, undefined, { numeric: true });
  });

  const bestTimingByInstance = new Map();
  orderedInstances.forEach((instanceId) => {
    const best = Math.min(...softwareNames.map((software) => timingValue(rowsByInstanceAndSoftware.get(`${instanceId}::${software}`))));
    bestTimingByInstance.set(instanceId, Number.isFinite(best) ? best : null);
  });

  thead.innerHTML = `
    <tr>
      <th><button class="matrix-sort-button" type="button" data-matrix-sort="__example__">Example <span class="matrix-sort-indicator">${matrixSortIndicator("__example__")}</span></button></th>
      ${softwareNames.map((software) => `<th><button class="matrix-sort-button" type="button" data-matrix-sort="${escapeHtml(software)}">${escapeHtml(software)} <span class="matrix-sort-indicator">${matrixSortIndicator(software)}</span></button></th>`).join("")}
    </tr>
  `;

  thead.querySelectorAll("[data-matrix-sort]").forEach((element) => {
    element.addEventListener("click", () => {
      setMatrixSort(element.getAttribute("data-matrix-sort") || "__example__");
      renderTimingsMatrix(pageState.currentRows);
    });
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
        const best = bestTimingByInstance.get(instanceId);
        const value = timingValue(row);
        const isBest = best !== null && Number.isFinite(value) && Math.abs(value - best) <= 1e-12;
        return `<td class="${isBest ? "matrix-best" : ""}">${escapeHtml(formatTimingCell(row))}</td>`;
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
        <td>${formatMemoryMb(row.peak_memory_mb)}</td>
        <td>${systemHref ? `<a href="${systemHref}">${row.system_id}</a>` : row.system_id}</td>
        <td><a href="./${row.input_ref}">${row.input_ref}</a></td>
        <td><a href="./${row.log_ref}">log</a></td>
      </tr>
    `;
  }).join("");
}

function renderProfileSvg(trackName) {
  const mount = document.getElementById("profileFigure");
  const profileData = computeProfileData(pageState.rowsByTrack[trackName] || [], currentProfileThresholdSeconds());
  const svgText = renderProfileSvgMarkup(profileData);

  mount.innerHTML = svgText;
  updateProfileFilterText(profileData);
  enhanceProfileSvg(mount);
}

function setActiveProfile(profileFigure, profileName) {
  const series = profileFigure.querySelectorAll(".profile-series");
  const legends = profileFigure.querySelectorAll(".profile-legend-entry");
  const hasActive = Boolean(profileName);

  series.forEach((element) => {
    const isActive = hasActive && element.dataset.profile === profileName;
    element.classList.toggle("is-active", isActive);
    element.classList.toggle("is-muted", hasActive && !isActive);
  });

  legends.forEach((element) => {
    const isActive = hasActive && element.dataset.profile === profileName;
    element.classList.toggle("is-active", isActive);
    element.classList.toggle("is-muted", hasActive && !isActive);
  });
}

function bindProfileHover(element, profileFigure) {
  const activate = () => setActiveProfile(profileFigure, element.dataset.profile || "");
  const clear = () => setActiveProfile(profileFigure, "");

  element.addEventListener("mouseenter", activate);
  element.addEventListener("mouseleave", clear);
  element.addEventListener("focus", activate);
  element.addEventListener("blur", clear);
  element.addEventListener("click", activate);
}

function enhanceProfileSvg(mount) {
  const profileFigure = mount.querySelector("svg");
  if (!profileFigure) {
    return;
  }

  profileFigure.querySelectorAll(".profile-series, .profile-legend-entry").forEach((element) => {
    bindProfileHover(element, profileFigure);
  });
}

function renderCurrentTrackArtifacts(trackName, rows) {
  const info = currentExperiment(trackName);
  const sourceRow = document.getElementById("currentExperimentSourceRow");
  const sourceLink = document.getElementById("currentExperimentSource");
  const detailIds = [
    "currentExperimentSetupSummary",
    "currentExperimentSetup",
  ];
  if (!info) {
    document.getElementById("currentExperimentDate").textContent = "";
    document.getElementById("currentExperimentSoftwareSummary").textContent = "";
    document.getElementById("currentExperimentSoftware").innerHTML = "";
    document.getElementById("currentExperimentInstanceSummary").textContent = "";
    document.getElementById("currentExperimentInstances").innerHTML = "";
    document.getElementById("currentExperimentOs").textContent = "";
    document.getElementById("currentExperimentCpu").textContent = "";
    document.getElementById("currentExperimentFlags").textContent = "";
    detailIds.forEach((id) => {
      const element = document.getElementById(id);
      if (element) {
        if (element.tagName === "UL") {
          element.innerHTML = "";
        } else {
          element.textContent = "";
        }
      }
    });
    if (sourceRow) {
      sourceRow.hidden = true;
    }
    if (sourceLink) {
      sourceLink.removeAttribute("href");
      sourceLink.textContent = "";
    }
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
  const experimentSourceUrl = githubExperimentUrl(info.results_table || info.experiment_bundle || "");
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
  const field = joinOrFallback(uniqueTrimmedValues(rows, "field"));
  const order = joinOrFallback(uniqueTrimmedValues(rows, "order"));
  const timeout = joinOrFallback(uniqueTrimmedValues(rows, "timeout_s").map((value) => `${value} s`));
  const memoryLimit = joinOrFallback(uniqueTrimmedValues(rows, "memory_limit_mb").map((value) => `${value} MB`));

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
  document.getElementById("currentExperimentDuration").textContent = runDurationText(rows);
  document.getElementById("currentExperimentSetupSummary").textContent = "Setup";
  document.getElementById("currentExperimentSetup").innerHTML = [
    renderSetupItem("Field / order", `${field} / ${order}`),
    renderSetupItem("Timeout", timeout),
    renderSetupItem("Memory limit", memoryLimit),
  ].join("");
  if (sourceRow && sourceLink) {
    if (experimentSourceUrl) {
      sourceRow.hidden = false;
      sourceLink.href = experimentSourceUrl;
      sourceLink.textContent = "Files on github";
    } else {
      sourceRow.hidden = true;
      sourceLink.removeAttribute("href");
      sourceLink.textContent = "";
    }
  }

  document.getElementById("reproduceCommand").textContent = [
    "git clone https://github.com/sumiya11/Polynomial_systems_benchmark.git",
    "cd Polynomial_systems_benchmark",
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
  if (pageState.rowsByTrack[trackName]) {
    return;
  }

  const embeddedRuns = parseEmbeddedJson("embeddedTrackRuns") || {};
  let runsText = embeddedRuns[trackName] || null;

  if (runsText === null) {
    const info = currentExperiment(trackName);
    runsText = await fetchText(info.results_path);
  }

  pageState.rowsByTrack[trackName] = parseTsv(runsText);
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
  pageState.matrixSort = {
    column: "__example__",
    direction: "asc",
  };

  document.getElementById("familyFilter").value = "";
  document.getElementById("softwareFilter").value = "";
  document.getElementById("searchFilter").value = "";

  refreshCurrentTrackView();
}

async function loadPage() {
  const trackSelector = document.getElementById("trackSelector");
  const profileThreshold = document.getElementById("profileThreshold");
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

  if (profileThreshold) {
    profileThreshold.value = String(pageState.profileThresholdIndex);
    profileThreshold.addEventListener("input", (event) => {
      pageState.profileThresholdIndex = Number(event.target.value);
      renderProfileSvg(pageState.currentTrack);
    });
  }

  await setTrack(defaultTrack);
}

loadPage().catch((error) => {
  document.querySelector("#resultsTable tbody").innerHTML = `<tr><td colspan="10">Failed to load results: ${error}</td></tr>`;
});
