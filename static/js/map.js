const map = L.map("map", { zoomControl: true, preferCanvas: true, maxZoom: 20 }).setView([22.7196, 75.8577], 12);

// Base maps: clean Google-like style by default, retina sharp tiles
const baseMaps = {
  "OpenStreetMap": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 20, maxNativeZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }),
  "Esri Street (clean)": L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 20, maxNativeZoom: 19,
    attribution: "Tiles &copy; Esri",
  }),
  "Satellite": L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 20, maxNativeZoom: 19,
    attribution: "Tiles &copy; Esri",
  }),
};
baseMaps["OpenStreetMap"].addTo(map);

const HEAT_ZOOM_POINTS = 15; // from this zoom, show individual demand points
const layers = {
  heat: L.heatLayer([], { radius: 14, blur: 18, minOpacity: 0.05, max: 1.0 }).addTo(map),
  demandPts: L.layerGroup(),
  chargers: L.layerGroup().addTo(map),
  candidates: L.layerGroup(),
  selected: L.layerGroup().addTo(map),
  radius: L.layerGroup().addTo(map),
};
L.control.layers(baseMaps, {
  "Demand heatmap": layers.heat,
  "Demand points": layers.demandPts,
  "Existing chargers": layers.chargers,
  "Candidate sites": layers.candidates,
  "Recommended sites": layers.selected,
  "Coverage radius": layers.radius,
}, { collapsed: true }).addTo(map);

// Heatmap is fainter/smaller when zoomed in so roads and places stay readable
function adjustHeat() {
  const z = map.getZoom();
  const radius = z <= 12 ? 16 : z <= 14 ? 12 : 8;
  layers.heat.setOptions({ radius, blur: Math.round(radius * 1.2) });
  const canvas = document.querySelector(".leaflet-heatmap-layer");
  if (canvas) canvas.style.opacity = z >= HEAT_ZOOM_POINTS ? 0.25 : z >= 13 ? 0.5 : 0.7;
  if (z >= HEAT_ZOOM_POINTS) { if (!map.hasLayer(layers.demandPts)) map.addLayer(layers.demandPts); }
  else if (map.hasLayer(layers.demandPts)) map.removeLayer(layers.demandPts);
}
map.on("zoomend", adjustHeat);

const $ = (id) => document.getElementById(id);
const pct = (v) => (v == null ? "n/a" : v.toFixed(1) + "%");
const km = (v) => (v == null ? "n/a" : v.toFixed(2));
const HINTS = {
  pan: "Pan mode: map normal chalega.",
  "add-charger": "Map par click karo: naya existing charger add hoga.",
  "add-demand": "Map par click karo: us jagah demand hotspot add hoga.",
  "remove-charger": "Kisi blue charger par click karo: wo hat jayega.",
};
let mode = "pan";
let busy = false;
let rerunTimer = null;
let candidatesLoaded = false;

/* ---------- dataset rendering ---------- */
async function loadDataset() {
  const d = await (await fetch("/api/dataset")).json();
  $("s-chargers").textContent = d.counts.chargers;
  $("s-demand").textContent = d.counts.demand;
  $("s-cands").textContent = d.counts.candidates;
  $("data-note").textContent =
    d.source === "synthetic"
      ? "Demo mode: synthetic data. Real data ke liye download_osm.py --osm chalao."
      : "Data source: " + (d.source || "unknown");

  layers.heat.setLatLngs(d.demand.map((p) => [p[0], p[1], p[2]]));
  layers.demandPts.clearLayers();
  d.demand.forEach((p) =>
    L.circleMarker([p[0], p[1]], { radius: 3, weight: 0, fillColor: "#7b2cbf", fillOpacity: 0.55, interactive: false })
      .addTo(layers.demandPts));
  adjustHeat();

  layers.chargers.clearLayers();
  d.chargers.forEach((c, idx) => {
    const m = L.circleMarker(c, { radius: 8, color: "#fff", weight: 2, fillColor: "#0d6efd", fillOpacity: 0.95 });
    m.bindTooltip(`Existing charger #${idx}`);
    m.on("click", (e) => {
      if (mode === "remove-charger") {
        L.DomEvent.stopPropagation(e);
        removeCharger(idx);
      }
    });
    m.addTo(layers.chargers);
  });

  if (!candidatesLoaded) {
    d.candidates.forEach((c) => L.circleMarker(c, { radius: 2, color: "#6c757d", weight: 1 }).addTo(layers.candidates));
    candidatesLoaded = true;
  }
  return d;
}

/* ---------- optimization ---------- */
function numOrNull(id) {
  const v = $(id).value;
  return v === "" ? null : Number(v);
}

function showResult(r) {
  layers.selected.clearLayers();
  layers.radius.clearLayers();
  r.selected.forEach((s) => {
    L.marker([s.lat, s.lon], {
      icon: L.divIcon({
        className: "",
        html: `<div style="background:#dc3545;color:#fff;border-radius:50%;width:22px;height:22px;line-height:22px;text-align:center;font-size:12px;font-weight:600;border:2px solid #fff">${s.rank}</div>`,
        iconSize: [22, 22],
      }),
    }).bindTooltip(`#${s.rank} · +${s.new_demand_covered.toFixed(1)} demand`).addTo(layers.selected);
    L.circle([s.lat, s.lon], { radius: r.params.radius_km * 1000, color: "#dc3545", weight: 1, fillOpacity: 0.04 }).addTo(layers.radius);
  });

  $("result-card").hidden = false;
  $("r-before-cov").textContent = pct(r.existing_coverage.weighted_coverage_pct);
  $("r-after-cov").textContent = pct(r.greedy.weighted_coverage_pct);
  $("r-before-dist").textContent = km(r.existing_coverage.avg_distance_km);
  $("r-after-dist").textContent = km(r.greedy.avg_distance_km);
  $("r-rand").textContent = pct(r.random_baseline.mean_coverage_pct);
  $("r-impr").textContent = r.improvement_over_random_pct_points.toFixed(1);
  $("r-n").textContent = r.greedy.stations;
  $("r-cost").textContent = r.greedy.estimated_cost == null ? "n/a" : r.greedy.estimated_cost.toLocaleString();
  const tb = $("sel-table").querySelector("tbody");
  tb.innerHTML = "";
  r.selected.forEach((s) => {
    const tr = document.createElement("tr");
    [s.rank, s.lat.toFixed(4), s.lon.toFixed(4), s.new_demand_covered.toFixed(1)].forEach((v) => {
      const td = document.createElement("td");
      td.textContent = v;
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  const saved = !!r.run_id;
  $("links").hidden = !saved;
  $("unsaved").hidden = saved;
  if (saved) {
    $("export").href = `/export/${r.run_id}.csv`;
    $("details").href = `/results/${r.run_id}`;
  }
}

async function runOptimization({ save = true, fit = true } = {}) {
  $("error").textContent = "";
  $("run").disabled = true;
  try {
    const res = await fetch("/api/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        k: numOrNull("k"),
        radius_km: numOrNull("radius"),
        cost_per_station: numOrNull("cost"),
        budget: numOrNull("budget"),
        save,
      }),
    });
    const r = await res.json();
    if (!res.ok) throw new Error(r.error || "Request failed");
    showResult(r);
    if (fit && r.selected.length) map.fitBounds(L.latLngBounds(r.selected.map((s) => [s.lat, s.lon])).pad(0.4));
    if (save) loadHistory();
    setStatus(`Updated ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    $("error").textContent = e.message;
  } finally {
    $("run").disabled = false;
  }
}

/* ---------- live editing ---------- */
function setStatus(t) {
  $("live-status").textContent = t;
}

async function api(path, method, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await res.json();
  if (!res.ok) throw new Error(j.error || "Request failed");
  return j;
}

async function afterEdit(msg) {
  await loadDataset();
  setStatus(msg);
  if ($("auto").checked) {
    clearTimeout(rerunTimer);
    rerunTimer = setTimeout(() => runOptimization({ save: false, fit: false }), 300);
  }
}

async function guarded(fn) {
  if (busy) return;
  busy = true;
  try {
    await fn();
  } catch (e) {
    $("error").textContent = e.message;
  } finally {
    busy = false;
  }
}

const addCharger = (ll) => guarded(async () => {
  await api("/api/charger", "POST", { lat: ll.lat, lon: ll.lng });
  await afterEdit("Charger added");
});
const removeCharger = (idx) => guarded(async () => {
  await api(`/api/charger/${idx}`, "DELETE");
  await afterEdit("Charger removed");
});
const addDemand = (ll) => guarded(async () => {
  await api("/api/demand", "POST", {
    lat: ll.lat, lon: ll.lng, category: $("dcat").value, count: Number($("dcount").value) || 40,
  });
  await afterEdit("Demand hotspot added");
});

map.on("click", (e) => {
  if (mode === "add-charger") addCharger(e.latlng);
  else if (mode === "add-demand") addDemand(e.latlng);
});

document.querySelectorAll("button.mode").forEach((b) =>
  b.addEventListener("click", () => {
    mode = b.dataset.mode;
    document.querySelectorAll("button.mode").forEach((x) => x.classList.toggle("active", x === b));
    $("mode-hint").textContent = HINTS[mode];
    $("demand-opts").hidden = mode !== "add-demand";
    const c = map.getContainer();
    c.className = c.className.replace(/\bmode-\S+/g, "").trim() + " mode-" + mode;
  }));

$("reset").addEventListener("click", () => guarded(async () => {
  if (!confirm("Saare live edits hat jayenge. Original data par wapas jaye?")) return;
  await api("/api/reset", "POST");
  await afterEdit("Reset to original data");
}));

/* ---------- comparison + history ---------- */
async function loadCompare() {
  const radius = numOrNull("radius") || 2;
  const rows = await (await fetch(`/api/compare?radius_km=${radius}`)).json();
  const tb = $("cmp-table").querySelector("tbody");
  tb.innerHTML = "";
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    [r.k, pct(r.greedy_pct), pct(r.random_mean_pct), km(r.avg_distance_km)].forEach((v) => {
      const td = document.createElement("td");
      td.textContent = v;
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  $("cmp-table").hidden = false;
}

async function loadHistory() {
  const rows = await (await fetch("/api/history")).json();
  const tb = $("hist-table").querySelector("tbody");
  tb.innerHTML = "";
  rows.slice(0, 8).forEach((r) => {
    const tr = document.createElement("tr");
    const a = document.createElement("a");
    a.href = `/results/${r.id}`;
    a.textContent = r.id;
    const td0 = document.createElement("td");
    td0.appendChild(a);
    tr.appendChild(td0);
    [r.k, r.radius_km, r.greedy_pct.toFixed(1) + "%"].forEach((v) => {
      const td = document.createElement("td");
      td.textContent = v;
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
}

$("run").addEventListener("click", () => runOptimization({ save: true, fit: true }));
$("compare").addEventListener("click", loadCompare);

// re-optimize live when K / radius / cost controls change
["k", "radius", "cost", "budget"].forEach((id) =>
  $(id).addEventListener("change", () => {
    if ($("auto").checked) runOptimization({ save: false, fit: false });
  }));

loadDataset().then(loadHistory);