const get = (id) => document.getElementById(id);

const defaults = {
  latitude: 49.47,
  longitude: 10.9,
  radius: 50,
  maximumStations: 5,
  startYear: 1960,
  endYear: 2025
};

const fields = Object.keys(defaults);

// Zwischengespeicherte DOM-Elemente und einfacher Zustand.
const el = {
  searchForm: get("searchForm"),
  searchButton: get("searchButton"),
  resetButton: get("resetButton"),
  loadingText: get("loadingText"),
  stationList: get("stationList"),
  stationStatus: get("stationStatus"),
  resultStatus: get("resultStatus"),
  chartPlaceholder: get("chartPlaceholder"),
  tableBody: get("tableBody"),
  tableEmpty: get("tableEmpty"),
  darkModeToggle: get("darkModeToggle")
};

const inputs = Object.fromEntries(fields.map((id) => [id, get(id)]));
const errorFields = Object.fromEntries(fields.map((id) => [id, get(`error-${id}`)]));

const state = {
  loading: false,
  query: { ...defaults },
  stations: [],
  selectedId: null
};

function setInputs(values) {
  fields.forEach((id) => {
    inputs[id].value = values[id];
  });
}

function readValue(id) {
  const text = inputs[id].value.trim();
  return text === "" ? NaN : Number(text);
}

function readForm() {
  return Object.fromEntries(fields.map((id) => [id, readValue(id)]));
}

function isNumber(value) {
  return Number.isFinite(value);
}

// Die Validierung liefert ein Objekt: Feldname -> Fehlermeldung.
function validate(d) {
  const e = {};
  const need = (id, msg) => {
    if (!isNumber(d[id])) {
      e[id] = msg;
      return false;
    }
    return true;
  };

  if (need("latitude", "Bitte eine Breite angeben.") && (d.latitude < -90 || d.latitude > 90)) {
    e.latitude = "Breite muss zwischen -90 und 90 liegen.";
  }
  if (need("longitude", "Bitte eine Länge angeben.") && (d.longitude < -180 || d.longitude > 180)) {
    e.longitude = "Länge muss zwischen -180 und 180 liegen.";
  }
  if (need("radius", "Bitte einen Radius angeben.") && (d.radius < 1 || d.radius > 100)) {
    e.radius = "Radius muss zwischen 1 und 100 liegen.";
  }
  if (
    need("maximumStations", "Bitte eine Stationsanzahl angeben.") &&
    (!Number.isInteger(d.maximumStations) || d.maximumStations < 1 || d.maximumStations > 10)
  ) {
    e.maximumStations = "Stationsanzahl muss zwischen 1 und 10 liegen.";
  }
  if (!isNumber(d.startYear)) {
    e.startYear = "Bitte ein Startjahr angeben.";
  }
  if (!isNumber(d.endYear)) {
    e.endYear = "Bitte ein Endjahr angeben.";
  }
  if (isNumber(d.startYear) && isNumber(d.endYear) && d.startYear > d.endYear) {
    e.startYear = "Startjahr muss vor Endjahr liegen.";
    e.endYear = "Endjahr muss nach Startjahr liegen.";
  }
  if (isNumber(d.endYear) && d.endYear > 2025) {
    e.endYear = "Endjahr darf nicht größer als 2025 sein.";
  }

  return e;
}

function showErrors(errors) {
  fields.forEach((id) => {
    const msg = errors[id] || "";
    errorFields[id].textContent = msg;
    inputs[id].classList.toggle("invalid", Boolean(msg));
    inputs[id].setAttribute("aria-invalid", msg ? "true" : "false");
  });
}

function setLoading(active) {
  state.loading = active;
  el.searchButton.disabled = active;
  el.resetButton.disabled = active;
  el.loadingText.textContent = active ? "Suche läuft..." : "";

  if (active) {
    el.stationStatus.textContent = "Suche läuft...";
    el.stationList.innerHTML = "";
  }
}

function clearResult() {
  state.selectedId = null;
  el.resultStatus.textContent = "Bitte Station auswählen.";
  el.chartPlaceholder.textContent = "Diagramm (TMIN/TMAX) folgt später.";
  el.tableBody.innerHTML = "";
  el.tableEmpty.hidden = false;
}

function randomBetween(min, max) {
  return Math.random() * (max - min) + min;
}

function round1(value) {
  return Math.round(value * 10) / 10;
}

function createStations(data) {
  const count = Math.min(10, Math.max(1, data.maximumStations));
  const maxDistance = Math.min(100, Math.max(1, data.radius));
  return Array.from({ length: count }, (_, i) => ({
    id: `ST-${String(i + 1).padStart(3, "0")}`,
    name: i === 0 ? "Nürnberg" : `Station ${i + 1}`,
    distance: round1(randomBetween(1, maxDistance))
  }));
}

function createYearValues(start, end) {
  const values = [];
  for (let year = start; year <= end; year += 1) {
    const base = randomBetween(-6, 12);
    const tmin = round1(base + randomBetween(-8, 2));
    values.push({ year, tmin, tmax: round1(tmin + randomBetween(5, 14)) });
  }
  return values;
}





function renderStations(stations) {
  if (!stations.length) {
    el.stationStatus.textContent = "Keine Stationen gefunden.";
    el.stationList.innerHTML = "";
    return;
  }

  el.stationStatus.textContent = `${stations.length} Stationen gefunden. Bitte auswählen.`;
  el.stationList.innerHTML = stations
    .map(
      (s) => `
        <li>
          <button class="station-button${s.id === state.selectedId ? " selected" : ""}" type="button" data-id="${s.id}">
            <span class="station-name">${s.name}</span>
            <span class="station-distance">${s.distance} km</span>
          </button>
        </li>
      `
    )
    .join("");
}

function renderTable(values) {
  if (!values.length) {
    el.tableBody.innerHTML = "";
    el.tableEmpty.hidden = false;
    return;
  }

  el.tableBody.innerHTML = values
    .map(
      (v) => `
        <tr>
          <td>${v.year}</td>
          <td>${v.tmin.toFixed(1)}</td>
          <td>${v.tmax.toFixed(1)}</td>
        </tr>
      `
    )
    .join("");
  el.tableEmpty.hidden = true;
}

function selectStation(id) {
  const station = state.stations.find((s) => s.id === id);
  if (!station) {
    return;
  }

  state.selectedId = station.id;
  const years = `${state.query.startYear}–${state.query.endYear}`;
  el.resultStatus.textContent = `Ausgewählte Station: ${station.name} (${station.id}) · Entfernung: ${station.distance} km · Jahre: ${years}`;
  el.chartPlaceholder.textContent = `Diagramm (TMIN/TMAX) für ${station.name}.`;

  renderTable(createYearValues(state.query.startYear, state.query.endYear));
  renderStations(state.stations);
}



function handleSearch(event) {
  event.preventDefault();
  if (state.loading) {
    return;
  }

  const data = readForm();
  const errors = validate(data);
  showErrors(errors);

  if (Object.keys(errors).length) {
    return;
  }

  state.query = { ...data };
  setLoading(true);
  clearResult();

  window.setTimeout(() => {
    state.stations = createStations(data);
    renderStations(state.stations);
    setLoading(false);
  }, 300);
}

function resetForm() {
  setInputs(defaults);
  showErrors({});
  state.query = { ...defaults };
  state.stations = [];
  el.stationList.innerHTML = "";
  el.stationStatus.textContent = "Noch keine Suche.";
  el.loadingText.textContent = "";
  clearResult();
}

function setTheme(dark) {
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  el.darkModeToggle.checked = dark;
}

// Ereignisse einmalig verbinden.
function init() {
  setInputs(defaults);
  showErrors({});
  setTheme(false);
  clearResult();

  el.searchForm.addEventListener("submit", handleSearch);
  el.resetButton.addEventListener("click", resetForm);
  el.darkModeToggle.addEventListener("change", (event) => setTheme(event.target.checked));
  el.stationList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-id]");
    if (!button || state.loading) {
      return;
    }
    selectStation(button.dataset.id);
  });
}

init();
