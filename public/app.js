const API_BASE = "";

const defaults = {
  latitude: 49.47,
  longitude: 10.9,
  radius: 50,
  maximumStations: 5,
  startYear: 1960,
  endYear: 2025
};

const fieldIds = ["latitude", "longitude", "radius", "maximumStations", "startYear", "endYear"];

const elements = {
  body: document.body,
  themeToggle: document.getElementById("themeToggle"),
  searchForm: document.getElementById("searchForm"),
  searchButton: document.getElementById("searchButton"),
  resetButton: document.getElementById("resetButton"),
  loadingText: document.getElementById("loadingText"),
  stationList: document.getElementById("stationList"),
  stationStatus: document.getElementById("stationStatus"),
  resultStatus: document.getElementById("resultStatus"),
  dataCoverageHint: document.getElementById("dataCoverageHint"),
  viewMode: document.getElementById("viewMode"),
  chartContainer: document.getElementById("chartContainer"),
  tempBody: document.getElementById("tempBody"),
  tempEmpty: document.getElementById("tempEmpty")
};

const inputs = Object.fromEntries(fieldIds.map((id) => [id, document.getElementById(id)]));
const errorFields = Object.fromEntries(fieldIds.map((id) => [id, document.getElementById(`error-${id}`)]));

const state = {
  loading: false,
  stations: [],
  selectedStationId: null,
  query: { ...defaults },
  earliestYear: 1800,
  latestYear: 2025,
  lastAnnual: [],
  lastSeasons: {
    spring: [],
    summer: [],
    autumn: [],
    winter: []
  },
  currentView: "annual",
  annualCache: new Map()
};

let chartInstance = null;
let chartResizeHandlerBound = false;

function emptySeasons() {
  return {
    spring: [],
    summer: [],
    autumn: [],
    winter: []
  };
}

function buildAnnualCacheKey(stationId, startYear, endYear) {
  return `${stationId}_${startYear}_${endYear}`;
}

function readAnnualCache(stationId, startYear, endYear) {
  const key = buildAnnualCacheKey(stationId, startYear, endYear);
  const value = state.annualCache.get(key);
  if (!value) {
    return null;
  }
  state.annualCache.delete(key);
  state.annualCache.set(key, value);
  return value;
}

function writeAnnualCache(stationId, startYear, endYear, value) {
  const key = buildAnnualCacheKey(stationId, startYear, endYear);
  if (state.annualCache.has(key)) {
    state.annualCache.delete(key);
  }
  state.annualCache.set(key, value);
  if (state.annualCache.size > 128) {
    const oldestKey = state.annualCache.keys().next().value;
    state.annualCache.delete(oldestKey);
  }
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function rowsForCurrentView() {
  if (state.currentView === "annual") {
    return state.lastAnnual;
  }

  if (state.currentView in state.lastSeasons) {
    return state.lastSeasons[state.currentView];
  }

  return [];
}

function renderCurrentView() {
  const rows = rowsForCurrentView();
  renderChart(rows);
  renderTemperatureTable(rows);
  renderDataCoverageHint(rows);
}

function renderDataCoverageHint(rows) {
  if (!elements.dataCoverageHint) {
    return;
  }

  if (!Array.isArray(rows) || rows.length === 0) {
    elements.dataCoverageHint.textContent = "";
    return;
  }

  const missingBoth = rows.filter((row) => row.tmin == null && row.tmax == null).length;
  const partial = rows.filter((row) => (row.tmin == null) !== (row.tmax == null)).length;

  if (missingBoth === 0 && partial === 0) {
    elements.dataCoverageHint.textContent = "";
    return;
  }

  const viewLabels = {
    annual: "Jahresansicht",
    spring: "Frühling",
    summer: "Sommer",
    autumn: "Herbst",
    winter: "Winter"
  };
  const label = viewLabels[state.currentView] || "Anzeige";
  elements.dataCoverageHint.textContent =
    `Hinweis (${label}): ${missingBoth} Jahr(e) ohne Werte, ${partial} Jahr(e) mit unvollständigen Werten.`;
}

function setTheme(isDark) {
  elements.body.classList.toggle("dark", isDark);
  elements.body.classList.toggle("light", !isDark);
  elements.themeToggle.checked = isDark;
  if (chartInstance && (state.lastAnnual.length > 0 || Object.values(state.lastSeasons).some((rows) => rows.length > 0))) {
    renderCurrentView();
  }
}

function setFormValues(values) {
  fieldIds.forEach((id) => {
    inputs[id].value = values[id];
  });
}

function setLoading(active, text = "") {
  state.loading = active;
  elements.searchButton.disabled = active;
  elements.resetButton.disabled = active;
  if (elements.viewMode) {
    elements.viewMode.disabled = active;
  }
  elements.loadingText.textContent = text;
}

function clearErrors() {
  fieldIds.forEach((id) => {
    errorFields[id].textContent = "";
    inputs[id].setAttribute("aria-invalid", "false");
  });
}

function showError(id, message) {
  errorFields[id].textContent = message;
  inputs[id].setAttribute("aria-invalid", "true");
}

function readNumber(id) {
  const value = inputs[id].value.trim();
  if (!value) {
    return NaN;
  }
  return Number(value);
}

function validateForm() {
  clearErrors();

  const values = {
    latitude: readNumber("latitude"),
    longitude: readNumber("longitude"),
    radius: readNumber("radius"),
    maximumStations: readNumber("maximumStations"),
    startYear: readNumber("startYear"),
    endYear: readNumber("endYear")
  };

  let hasError = false;

  if (!Number.isFinite(values.latitude) || values.latitude < -90 || values.latitude > 90) {
    showError("latitude", "Breitengrad muss zwischen -90 und 90 liegen.");
    hasError = true;
  }
  if (!Number.isFinite(values.longitude) || values.longitude < -180 || values.longitude > 180) {
    showError("longitude", "Laengengrad muss zwischen -180 und 180 liegen.");
    hasError = true;
  }
  if (!Number.isFinite(values.radius) || values.radius < 0 || values.radius > 100) {
    showError("radius", "Radius muss zwischen 0 und 100 liegen.");
    hasError = true;
  }
  if (!Number.isInteger(values.maximumStations) || values.maximumStations < 1 || values.maximumStations > 10) {
    showError("maximumStations", "Stationsanzahl muss zwischen 1 und 10 liegen.");
    hasError = true;
  }
  if (!Number.isInteger(values.startYear) || values.startYear < state.earliestYear) {
    showError("startYear", `Startjahr muss >= ${state.earliestYear} sein.`);
    hasError = true;
  }
  if (!Number.isInteger(values.endYear) || values.endYear > state.latestYear) {
    showError("endYear", `Endjahr darf nicht groesser als ${state.latestYear} sein.`);
    hasError = true;
  }
  if (
    Number.isInteger(values.startYear) &&
    Number.isInteger(values.endYear) &&
    values.startYear > values.endYear
  ) {
    showError("startYear", "Startjahr muss <= Endjahr sein.");
    showError("endYear", "Endjahr muss >= Startjahr sein.");
    hasError = true;
  }

  return hasError ? null : values;
}

function buildApiUrl(path, params = {}) {
  const url = new URL(path, API_BASE || window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    url.searchParams.set(key, String(value));
  });
  return url.toString();
}

async function fetchJson(path, params = {}, requestOptions = {}) {
  const url = buildApiUrl(path, params);
  const response = await fetch(url, requestOptions);

  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body && typeof body.message === "string") {
        message = body.message;
      } else if (body && typeof body.detail === "string") {
        message = body.detail;
      }
    } catch (_error) {
      // Antwort war kein JSON.
    }
    throw new Error(message);
  }

  return response.json();
}

function clearClientAnnualCache() {
  state.annualCache.clear();
}

async function clearServerCache() {
  const response = await fetch(buildApiUrl("/api/cache/clear"), {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json().catch(() => null);
}

async function clearCachesOnPageLoad() {
  clearClientAnnualCache();
  try {
    await clearServerCache();
  } catch (error) {
    elements.loadingText.textContent = `Hinweis: Cache konnte nicht geleert werden (${error.message}).`;
  }
}

function clearCachesOnPageLeave() {
  clearClientAnnualCache();
  const url = buildApiUrl("/api/cache/clear");
  if (navigator.sendBeacon) {
    const payload = new Blob(["{}"], { type: "application/json" });
    navigator.sendBeacon(url, payload);
    return;
  }
  fetch(url, {
    method: "POST",
    keepalive: true,
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  }).catch(() => {});
}

function formatOneDecimal(value) {
  return Number(value).toFixed(1);
}

function clearResult() {
  if (chartInstance) {
    chartInstance.dispose();
    chartInstance = null;
  }
  state.selectedStationId = null;
  state.lastAnnual = [];
  state.lastSeasons = emptySeasons();
  state.currentView = "annual";
  if (elements.viewMode) {
    elements.viewMode.value = "annual";
  }
  elements.resultStatus.textContent = "Bitte Station auswaehlen.";
  if (elements.dataCoverageHint) {
    elements.dataCoverageHint.textContent = "";
  }
  elements.chartContainer.innerHTML = '<div class="chart-placeholder">Keine Jahreswerte in diesem Modus</div>';
  elements.tempBody.innerHTML = "";
  elements.tempEmpty.hidden = false;
  elements.tempEmpty.textContent = "Jahresmittel benoetigen zusaetzliche Tagesdaten.";
}

function renderStations(stations) {
  if (!stations.length) {
    elements.stationStatus.textContent = "Keine Stationen gefunden.";
    elements.stationList.innerHTML = "";
    return;
  }

  elements.stationStatus.textContent = `${stations.length} Stationen gefunden.`;
  const listHtml = stations
    .map((station) => {
      const tminRange = `${station.tminFirst ?? "-"}-${station.tminLast ?? "-"}`;
      const tmaxRange = `${station.tmaxFirst ?? "-"}-${station.tmaxLast ?? "-"}`;
      const distance = `${formatOneDecimal(station.distanceKm)} km`;
      const isActive = station.id === state.selectedStationId ? " active" : "";
      return `
        <li>
          <button type="button" class="station-item${isActive}" data-id="${escapeHtml(station.id)}">
            <span class="station-main">${escapeHtml(station.name)}</span>
            <span class="station-meta">${escapeHtml(distance)} | TMIN ${escapeHtml(tminRange)} | TMAX ${escapeHtml(
              tmaxRange
            )}</span>
          </button>
        </li>
      `;
    })
    .join("");
  elements.stationList.innerHTML = listHtml;
}

function renderTemperatureTable(annual) {
  if (!annual.length) {
    elements.tempBody.innerHTML = "";
    elements.tempEmpty.hidden = false;
    return;
  }

  const rowsHtml = annual
    .map(
      (row) => `
      <div class="temp-row">
        <div>${row.year}</div>
        <div>${row.tmin == null ? "-" : formatOneDecimal(row.tmin)}</div>
        <div>${row.tmax == null ? "-" : formatOneDecimal(row.tmax)}</div>
      </div>
    `
    )
    .join("");

  elements.tempBody.innerHTML = rowsHtml;
  elements.tempEmpty.hidden = true;
}

function renderChart(annual) {
  if (!Array.isArray(annual) || annual.length === 0) {
    if (chartInstance) {
      chartInstance.dispose();
      chartInstance = null;
    }
    elements.chartContainer.innerHTML = '<div class="chart-placeholder">Keine Daten</div>';
    return;
  }

  const startYear = Number.isInteger(state.query.startYear) ? state.query.startYear : annual[0].year;
  const endYear = Number.isInteger(state.query.endYear)
    ? state.query.endYear
    : annual[annual.length - 1].year;
  if (!Number.isInteger(startYear) || !Number.isInteger(endYear) || startYear > endYear) {
    elements.chartContainer.innerHTML = '<div class="chart-placeholder">Keine Daten</div>';
    return;
  }

  const sorted = [...annual].filter((row) => Number.isInteger(row.year)).sort((a, b) => a.year - b.year);
  const map = new Map(sorted.map((row) => [row.year, row]));

  const years = [];
  const tmin = [];
  const tmax = [];

  for (let year = startYear; year <= endYear; year += 1) {
    years.push(String(year));
    const row = map.get(year);
    tmin.push(row && Number.isFinite(row.tmin) ? row.tmin : null);
    tmax.push(row && Number.isFinite(row.tmax) ? row.tmax : null);
  }

  const hasAnyValue = [...tmin, ...tmax].some(Number.isFinite);
  if (!hasAnyValue) {
    if (chartInstance) {
      chartInstance.dispose();
      chartInstance = null;
    }
    elements.chartContainer.innerHTML = '<div class="chart-placeholder">Keine Daten</div>';
    return;
  }

  let dom = document.getElementById("echartsChart");
  if (!dom) {
    elements.chartContainer.innerHTML = '<div id="echartsChart" style="width:100%;height:500px;"></div>';
    dom = document.getElementById("echartsChart");
  }
  if (!dom || typeof echarts === "undefined") {
    elements.chartContainer.innerHTML = '<div class="chart-placeholder">Diagramm-Bibliothek nicht verfuegbar</div>';
    return;
  }

  if (chartInstance && chartInstance.getDom() !== dom) {
    chartInstance.dispose();
    chartInstance = null;
  }
  if (!chartInstance) {
    chartInstance = echarts.init(dom, null, { renderer: "canvas" });
  }
  const isDark = document.body.classList.contains("dark");
  const range = endYear - startYear;
  let axisInterval = 9;
  if (range <= 10) {
    axisInterval = 0;
  } else if (range <= 20) {
    axisInterval = 1;
  } else if (range <= 50) {
    axisInterval = 4;
  }

  chartInstance.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    legend: {
      data: ["Tmin", "Tmax"],
      textStyle: { color: isDark ? "#9ca3af" : "#6b7280" }
    },
    grid: { left: 60, right: 20, top: 30, bottom: 55 },
    xAxis: {
      type: "category",
      data: years,
      name: "Jahr",
      nameLocation: "middle",
      nameGap: 35,
      axisLine: {
        lineStyle: { color: isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.25)" }
      },
      axisLabel: {
        color: isDark ? "#9ca3af" : "#6b7280",
        interval: axisInterval
      }
    },
    yAxis: {
      type: "value",
      name: "Temperatur (°C)",
      nameLocation: "middle",
      nameGap: 45,
      axisLine: {
        lineStyle: { color: isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.25)" }
      },
      axisLabel: { color: isDark ? "#9ca3af" : "#6b7280" },
      splitLine: {
        lineStyle: {
          color: isDark ? "rgba(255,255,255,0.14)" : "rgba(0,0,0,0.08)",
          type: "dashed"
        }
      }
    },
    series: [
      {
        name: "Tmin",
        type: "line",
        data: tmin,
        connectNulls: false,
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 2, color: "#60a5fa" }
      },
      {
        name: "Tmax",
        type: "line",
        data: tmax,
        connectNulls: false,
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 2, color: "#f59e0b" }
      }
    ]
  }, true);

  if (!chartResizeHandlerBound) {
    window.addEventListener(
      "resize",
      () => {
        if (chartInstance) {
          chartInstance.resize();
        }
      },
      { passive: true }
    );
    chartResizeHandlerBound = true;
  }
}

async function selectStation(stationId) {
  const station = state.stations.find((item) => item.id === stationId);
  if (!station || state.loading) return;

  const previousSelectedStationId = state.selectedStationId;
  const previousAnnual = state.lastAnnual;
  const previousSeasons = state.lastSeasons;
  const previousView = state.currentView;
  const hadPreviousRows =
    previousAnnual.length > 0 || Object.values(previousSeasons).some((rows) => Array.isArray(rows) && rows.length > 0);

  state.selectedStationId = stationId;
  renderStations(state.stations);

  const distance = `${formatOneDecimal(station.distanceKm)} km`;
  elements.resultStatus.textContent =
    `Station ${station.name} ausgewählt – Entfernung ${distance} – Laden...`;
  setLoading(true, "Lade Stationsdaten...");

  try {
    const cachedData = readAnnualCache(stationId, state.query.startYear, state.query.endYear);
    const data =
      cachedData ||
      (await fetchJson(
        `/api/stations/${encodeURIComponent(stationId)}/annual`,
        {
          startYear: state.query.startYear,
          endYear: state.query.endYear
        },
        { cache: "no-store" }
      ));

    let annualRows = [];
    let seasonRows = emptySeasons();

    if (Array.isArray(data)) {
      annualRows = data;
    } else if (data && typeof data === "object") {
      annualRows = Array.isArray(data.annual) ? data.annual : [];
      const seasons = data.seasons && typeof data.seasons === "object" ? data.seasons : {};
      seasonRows = {
        spring: Array.isArray(seasons.spring) ? seasons.spring : [],
        summer: Array.isArray(seasons.summer) ? seasons.summer : [],
        autumn: Array.isArray(seasons.autumn) ? seasons.autumn : [],
        winter: Array.isArray(seasons.winter) ? seasons.winter : []
      };
    }

    if (!cachedData) {
      writeAnnualCache(stationId, state.query.startYear, state.query.endYear, {
        annual: annualRows,
        seasons: seasonRows
      });
    }

    state.lastAnnual = annualRows;
    state.lastSeasons = seasonRows;
    state.currentView = elements.viewMode ? elements.viewMode.value : "annual";
    elements.resultStatus.textContent =
      `Station ${station.name} ausgewählt – Entfernung ${distance} – Jahre ${state.query.startYear}-${state.query.endYear}`;

    renderCurrentView();
  } catch (error) {
    state.selectedStationId = previousSelectedStationId;
    state.lastAnnual = previousAnnual;
    state.lastSeasons = previousSeasons;
    state.currentView = previousView;
    if (elements.viewMode) {
      elements.viewMode.value = previousView;
    }
    renderStations(state.stations);

    elements.resultStatus.textContent = `Fehler: ${error.message}`;
    if (hadPreviousRows) {
      renderCurrentView();
    } else {
      elements.chartContainer.innerHTML = '<div class="chart-placeholder">Keine Daten</div>';
      renderTemperatureTable([]);
      renderDataCoverageHint([]);
      elements.tempEmpty.textContent = "Jahreswerte konnten nicht geladen werden.";
    }
  } finally {
    setLoading(false, "");
  }
}
async function loadMeta() {
  try {
    const meta = await fetchJson("/api/meta", {}, { cache: "no-store" });
    if (Number.isInteger(meta.earliestYear)) {
      state.earliestYear = meta.earliestYear;
      inputs.startYear.min = String(meta.earliestYear);
      if (Number(inputs.startYear.value) < meta.earliestYear) {
        inputs.startYear.value = String(meta.earliestYear);
      }
    }
    if (Number.isInteger(meta.latestYear)) {
      state.latestYear = meta.latestYear;
      inputs.endYear.max = String(meta.latestYear);
      if (Number(inputs.endYear.value) > meta.latestYear) {
        inputs.endYear.value = String(meta.latestYear);
      }
    }
  } catch (_error) {
    elements.loadingText.textContent = "Hinweis: /api/meta nicht erreichbar.";
  }
}

async function handleSearch(event) {
  event.preventDefault();
  if (state.loading) {
    return;
  }

  const values = validateForm();
  if (!values) {
    return;
  }

  state.query = { ...values };
  clearResult();
  setLoading(true, "Suche laeuft...");

  try {
    const stations = await fetchJson(
      "/api/stations",
      {
        lat: values.latitude,
        lon: values.longitude,
        radiusKm: values.radius,
        limit: values.maximumStations,
        startYear: values.startYear,
        endYear: values.endYear
      },
      { cache: "no-store" }
    );

    state.stations = Array.isArray(stations) ? stations : [];
    renderStations(state.stations);
  } catch (error) {
    state.stations = [];
    renderStations([]);
    elements.stationStatus.textContent = `Fehler: ${error.message}`;
  } finally {
    setLoading(false, "");
  }
}

function resetAll() {
  setFormValues({
    ...defaults,
    startYear: Math.max(defaults.startYear, state.earliestYear),
    endYear: Math.min(defaults.endYear, state.latestYear)
  });
  clearErrors();
  state.stations = [];
  state.selectedStationId = null;
  state.query = {
    latitude: Number(inputs.latitude.value),
    longitude: Number(inputs.longitude.value),
    radius: Number(inputs.radius.value),
    maximumStations: Number(inputs.maximumStations.value),
    startYear: Number(inputs.startYear.value),
    endYear: Number(inputs.endYear.value)
  };
  elements.stationStatus.textContent = "Noch keine Suche.";
  elements.stationList.innerHTML = "";
  setLoading(false, "");
  clearResult();
}

async function init() {
  setTheme(true);
  setFormValues(defaults);
  clearErrors();
  clearResult();

  elements.themeToggle.addEventListener("change", (event) => {
    setTheme(event.target.checked);
  });
  if (elements.viewMode) {
    elements.viewMode.addEventListener("change", (event) => {
      state.currentView = event.target.value;
      renderCurrentView();
    });
  }
  elements.searchForm.addEventListener("submit", handleSearch);
  elements.resetButton.addEventListener("click", resetAll);
  elements.stationList.addEventListener("click", (event) => {
    const button = event.target.closest(".station-item");
    if (!button || state.loading) {
      return;
    }
    selectStation(button.dataset.id);
  });
  window.addEventListener("pagehide", clearCachesOnPageLeave, { passive: true });

  setLoading(true, "Cache wird aktualisiert...");
  await clearCachesOnPageLoad();
  await loadMeta();
  setLoading(false, "");
}

init();



