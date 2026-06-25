const LATEST_DATA_URL = "../api/data/latest";
const NAMES_URL = "../api/om-names";
const MONTHS_URL = "../api/months";
const CONFIG_URL = "../api/config";
const GROUPS_URL = "../api/groups";
const SYNC_URL = "../api/sync";
const SYNC_STATUS_URL = "../api/sync-status";
const STATIC_CONFIG_URL = "static-config.json";
let currentData = null;
let selectedMonth = null;
let intervalMode = "day";
let availableMonths = [];
let appConfig = null;
let availableGroups = [];
let activeGroup = "";
let syncMode = "single";
let syncPollTimer = null;
let staticMode = false;
let staticManifest = null;

const SHARING_POTENTIAL_LABEL = "Potenciál lepšího sdílení";
const SHARING_POTENTIAL_HINT = "Nejde o celkový přetok do sítě, ale o část, která mohla být při lepším nastavení poměrů ještě nasdílena.";

const fmt = new Intl.NumberFormat("cs-CZ", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const monthFmt = new Intl.DateTimeFormat("cs-CZ", {
  month: "long",
  year: "numeric",
});

function kwh(value) {
  return `${fmt.format(value || 0)} kWh`;
}

function percent(value) {
  return `${fmt.format(value || 0)} %`;
}

function sharePercent(part, total) {
  return total ? part / total * 100 : 0;
}

function sharingPotentialHelpContent() {
  return `
    <h3>Co to znamená?</h3>
    <p>Tato hodnota ukazuje, kolik elektřiny se ve stejném 15min intervalu zároveň prodávalo do sítě a zároveň ji některé odběrné místo nakupovalo ze sítě.</p>
    <h3>Proč k tomu dochází?</h3>
    <p>Typicky kvůli nastavení alokačních poměrů. Jedno odběrné místo už dostalo svůj limit, zatímco jiné by ještě energii využilo, ale musí ji dokoupit ze sítě.</p>
    <h3>Příklad</h3>
    <p>FVE vyrobí 5 kWh. 2 kWh se nasdílí. 3 kWh odtečou do sítě. Zároveň jiné odběrné místo ještě koupí 1 kWh ze sítě. V tomto intervalu je potenciál lepšího sdílení 1 kWh.</p>
    <h3>Jak to číst?</h3>
    <ul>
      <li>Prodej do sítě = vše, co po sdílení zůstalo.</li>
      <li>Potenciál lepšího sdílení = jen část, která možná šla ještě rozdělit lépe.</li>
    </ul>
  `;
}

function questionIcon() {
  return `
    <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" stroke-width="1.5"></circle>
      <path d="M7.8 7.5a2.3 2.3 0 0 1 2.4-2 2.25 2.25 0 0 1 2.45 2.2c0 1.2-.75 1.75-1.55 2.28-.62.42-.95.78-.95 1.52" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"></path>
      <circle cx="10.1" cy="14.45" r="0.9" fill="currentColor"></circle>
    </svg>
  `;
}

function timeLabel(value) {
  return new Date(value).toLocaleString("cs-CZ", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function intervalLabel(start, mode) {
  const date = new Date(start);
  if (mode === "day") {
    return date.toLocaleDateString("cs-CZ", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  }
  if (mode === "hour") {
    return date.toLocaleString("cs-CZ", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return timeLabel(start);
}

function intervalModeName(mode) {
  return {
    quarter: "15min intervalů",
    hour: "hodin",
    day: "dnů",
  }[mode] || "intervalů";
}

function monthLabel(monthRef) {
  const label = monthFmt.format(new Date(monthRef.year, monthRef.month - 1, 1));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function monthFromData(data) {
  const start = new Date(data.date_from);
  return {
    year: start.getFullYear(),
    month: start.getMonth() + 1,
  };
}

function addMonths(monthRef, delta) {
  const date = new Date(monthRef.year, monthRef.month - 1 + delta, 1);
  return {
    year: date.getFullYear(),
    month: date.getMonth() + 1,
  };
}

function dataUrl(monthRef) {
  if (staticMode) {
    const group = staticGroup(activeGroup);
    if (!group) {
      return "";
    }
    if (!monthRef) {
      return group.latest_path || "";
    }
    const month = (group.months || []).find(item => sameMonth(item, monthRef));
    return month?.path || "";
  }
  const group = groupQuery();
  if (!monthRef) {
    return `${LATEST_DATA_URL}${group}`;
  }
  return `../api/data/month?year=${monthRef.year}&month=${monthRef.month}${group ? `&${group.slice(1)}` : ""}`;
}

function cacheUrl(url) {
  return `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
}

function groupQuery() {
  return activeGroup ? `?group=${encodeURIComponent(activeGroup)}` : "";
}

function staticGroup(groupName) {
  return (staticManifest?.groups || []).find(group => group.name === groupName);
}

function sameMonth(first, second) {
  return first && second && first.year === second.year && first.month === second.month;
}

function latestAvailableMonth(months) {
  return [...months].sort((first, second) => {
    if (first.year !== second.year) {
      return second.year - first.year;
    }
    return second.month - first.month;
  })[0] || null;
}

function initialMonth(months) {
  const now = new Date();
  const current = {
    year: now.getFullYear(),
    month: now.getMonth() + 1,
  };
  return months.find(month => sameMonth(month, current)) || latestAvailableMonth(months);
}

function omName(data, ean) {
  return data.om_names?.[ean] || ean;
}

function omLabel(name, ean) {
  if (staticMode) {
    return `
      <span class="om-edit static-om-label">
        <strong>${name}</strong>
        <code>${ean}</code>
      </span>
    `;
  }
  return `
    <button class="om-edit" type="button" data-ean="${ean}">
      <strong>${name}</strong>
      <code>${ean}</code>
    </button>
  `;
}

function evenAllocations(count) {
  if (!count) {
    return [];
  }
  const base = Math.floor(100 / count);
  const allocations = Array(count).fill(base);
  for (let index = 0; index < 100 - base * count; index += 1) {
    allocations[index] += 1;
  }
  return allocations;
}

function currentAllocations(data) {
  return data.current_allocations || evenAllocations(data.consumers.length);
}

function sameAllocations(first, second) {
  return first.length === second.length && first.every((value, index) => value === second[index]);
}

function allocationText(data, allocations) {
  return allocations.map((allocation, index) => {
    const ean = data.consumers[index];
    return `${omName(data, ean)} ${allocation} %`;
  }).join(" / ");
}

function allocationRows(data, allocations) {
  return allocations.map((allocation, index) => {
    const ean = data.consumers[index];
    return `
    <div class="allocation">
      ${omLabel(omName(data, ean), ean)}
      <div class="bar"><i style="width:${allocation}%"></i></div>
      <strong>${allocation} %</strong>
    </div>
  `;
  }).join("");
}

function findScenario(data, allocations) {
  const recommendation = data.recommendation.recommended;
  const candidates = [
    recommendation,
    ...(data.recommendation.alternatives || []),
  ].filter(Boolean);
  return candidates.find(item => sameAllocations(item.allocations, allocations)) || null;
}

function topPurchasedConsumer(data) {
  return [...data.eans.consumers].sort((first, second) => second.after_kwh - first.after_kwh)[0] || null;
}

function intervalBucketKey(value, mode) {
  const date = new Date(value);
  if (mode === "day") {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }
  if (mode === "hour") {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}`;
  }
  return `${date.toISOString()}-${Math.random()}`;
}

function emptyIntervalBucket(item) {
  return {
    start: item.start,
    production_before_kwh: 0,
    consumption_before_kwh: 0,
    shared_kwh: 0,
    missed_kwh: 0,
    production_after_kwh: 0,
    consumption_after_kwh: 0,
  };
}

function emptyConsumerBucket(item) {
  return {
    start: item.start,
    before_kwh: 0,
    shared_kwh: 0,
    after_kwh: 0,
  };
}

function aggregateIntervals(intervals, mode) {
  if (mode === "quarter") {
    return intervals;
  }

  const buckets = new Map();
  for (const item of intervals) {
    const key = intervalBucketKey(item.start, mode);
    if (!buckets.has(key)) {
      buckets.set(key, emptyIntervalBucket(item));
    }
    const bucket = buckets.get(key);
    bucket.production_before_kwh += item.production_before_kwh;
    bucket.consumption_before_kwh += item.consumption_before_kwh;
    bucket.shared_kwh += item.shared_kwh;
    bucket.missed_kwh += item.missed_kwh;
    bucket.production_after_kwh += item.production_after_kwh;
    bucket.consumption_after_kwh += item.consumption_after_kwh;
  }
  return [...buckets.values()];
}

function aggregateConsumerSeries(data, ean, mode) {
  const buckets = new Map();
  for (const interval of data.intervals) {
    const measurement = interval.consumers.find(item => item.ean === ean);
    if (!measurement) {
      continue;
    }
    const key = intervalBucketKey(interval.start, mode);
    if (!buckets.has(key)) {
      buckets.set(key, emptyConsumerBucket(interval));
    }
    const bucket = buckets.get(key);
    bucket.before_kwh += measurement.before_kwh;
    bucket.shared_kwh += measurement.shared_kwh;
    bucket.after_kwh += measurement.after_kwh;
  }
  return [...buckets.values()];
}

function topIntervals(intervals, key, limit = 3) {
  return [...intervals]
    .filter(item => item[key] > 0)
    .sort((first, second) => second[key] - first[key])
    .slice(0, limit);
}

function topOverlapIntervals(intervals, limit = 3) {
  return [...intervals]
    .map(item => ({
      ...item,
      overlap_kwh: Math.min(item.production_after_kwh, item.consumption_after_kwh),
    }))
    .filter(item => item.overlap_kwh > 0)
    .sort((first, second) => second.overlap_kwh - first.overlap_kwh)
    .slice(0, limit);
}

function peakRows(items, valueKey) {
  if (!items.length) {
    return `<p class="muted">Bez významných hodnot.</p>`;
  }
  return `
    <ol class="peak-list">
      ${items.map(item => `
        <li>
          <span>${intervalLabel(item.start, "hour")}</span>
          <strong>${kwh(item[valueKey])}</strong>
        </li>
      `).join("")}
    </ol>
  `;
}

function overlapRows(items) {
  if (!items.length) {
    return `<p class="muted">Bez souběhu prodeje a nákupu.</p>`;
  }
  return `
    <ol class="peak-list">
      ${items.map(item => `
        <li>
          <span>${intervalLabel(item.start, "hour")}</span>
          <strong>${kwh(item.overlap_kwh)}</strong>
          <small>prodej ${kwh(item.production_after_kwh)}, nákup ${kwh(item.consumption_after_kwh)}</small>
        </li>
      `).join("")}
    </ol>
  `;
}

async function loadData(monthRef) {
  const url = dataUrl(monthRef);
  if (!url) {
    throw new Error("Pro vybranou skupinu nejsou dostupná žádná data.");
  }
  const response = await fetch(cacheUrl(url));
  if (!response.ok) {
    if (monthRef) {
      throw new Error(`Data pro ${monthLabel(monthRef)} zatím nejsou stažená nebo naparsovaná.`);
    }
    throw new Error("Analysis JSON nebyl nalezen. Nejdřív stáhni nebo naparsuj data.");
  }
  return response.json();
}

async function loadAvailableMonths() {
  if (staticMode) {
    return staticGroup(activeGroup)?.months || [];
  }
  try {
    const response = await fetch(cacheUrl(`${MONTHS_URL}${groupQuery()}`));
    if (!response.ok) {
      return [];
    }
    const payload = await response.json();
    return payload.months || [];
  } catch {
    return [];
  }
}

async function loadConfig() {
  if (!staticManifest) {
    try {
      const configResponse = await fetch(cacheUrl(STATIC_CONFIG_URL));
      if (configResponse.ok) {
        const staticConfig = await configResponse.json();
        const manifestResponse = await fetch(cacheUrl(staticConfig.manifest || "data/manifest.json"));
        if (manifestResponse.ok) {
          staticManifest = await manifestResponse.json();
          staticMode = true;
          return {
            project_code: staticManifest.project_code || "",
            group: staticManifest.default_group || staticManifest.groups?.[0]?.name || "",
            group_slug: staticManifest.default_group_slug || staticManifest.groups?.[0]?.slug || "",
          };
        }
      }
    } catch {
      staticManifest = null;
      staticMode = false;
    }
  }
  try {
    const response = await fetch(cacheUrl(CONFIG_URL));
    if (!response.ok) {
      return null;
    }
    return response.json();
  } catch {
    return null;
  }
}

async function loadGroups() {
  if (staticMode) {
    return staticManifest?.groups || [];
  }
  try {
    const response = await fetch(cacheUrl(GROUPS_URL));
    if (!response.ok) {
      return [];
    }
    const payload = await response.json();
    return payload.groups || [];
  } catch {
    return [];
  }
}

function renderConfig(config) {
  const group = activeGroup || config?.group || "nezvolená";
  const project = config?.project_code || "";
  const suffix = project ? ` (${project})` : "";
  document.querySelector("#group-label").textContent = `Skupina sdílení: ${group}${suffix}`;
  document.querySelector("#recommendation-group").textContent = `Skupina: ${group}`;
  document.querySelector("#sync-open").hidden = staticMode;
}

function renderGroupSwitcher() {
  const box = document.querySelector("#group-switcher");
  if (!availableGroups.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = availableGroups.map(group => `
    <button
      type="button"
      class="${group.name === activeGroup ? "selected" : ""}"
      data-group-name="${group.name}"
    >
      ${group.name}
    </button>
  `).join("");
}

function adminTokenFromUrl() {
  return new URLSearchParams(window.location.search).get("token") || "";
}

function adminToken() {
  return document.querySelector("#sync-token").value.trim();
}

function saveAdminToken(value) {
  if (value) {
    localStorage.setItem("edcAdminToken", value);
  }
}

function initialAdminToken() {
  const token = adminTokenFromUrl() || localStorage.getItem("edcAdminToken") || "";
  document.querySelector("#sync-token").value = token;
}

function setSyncMode(mode) {
  syncMode = mode;
  document.querySelectorAll("[data-sync-mode]").forEach(button => {
    button.classList.toggle("selected", button.dataset.syncMode === mode);
  });
  document.querySelector("#sync-single-fields").hidden = mode !== "single";
  document.querySelector("#sync-range-fields").hidden = mode !== "range";
}

function currentMonthRef() {
  const now = new Date();
  return {
    year: now.getFullYear(),
    month: now.getMonth() + 1,
  };
}

function fillSyncMonth(monthRef) {
  document.querySelector("#sync-month").value = monthRef.month;
  document.querySelector("#sync-year").value = monthRef.year;
  document.querySelector("#sync-from-month").value = monthRef.month;
  document.querySelector("#sync-from-year").value = monthRef.year;
  document.querySelector("#sync-to-month").value = monthRef.month;
  document.querySelector("#sync-to-year").value = monthRef.year;
}

function syncPayload() {
  if (syncMode === "range") {
    return {
      token: adminToken(),
      group: activeGroup,
      from: {
        month: Number(document.querySelector("#sync-from-month").value),
        year: Number(document.querySelector("#sync-from-year").value),
      },
      to: {
        month: Number(document.querySelector("#sync-to-month").value),
        year: Number(document.querySelector("#sync-to-year").value),
      },
    };
  }
  return {
    token: adminToken(),
    group: activeGroup,
    month: Number(document.querySelector("#sync-month").value),
    year: Number(document.querySelector("#sync-year").value),
  };
}

function renderSyncStatus(status) {
  const box = document.querySelector("#sync-status");
  if (!status) {
    box.textContent = activeGroup ? `Připraveno pro ${activeGroup}.` : "Připraveno.";
    return;
  }
  const requested = (status.requested_months || [])
    .map(item => monthLabel(item))
    .join(", ");
  const statusGroup = status.group || "";
  const group = statusGroup || activeGroup;
  if (status.running) {
    box.textContent = requested ? `Stahuji ${group}: ${requested}` : `Stahování běží${group ? ` pro ${group}` : ""}.`;
    return;
  }
  if (!statusGroup || statusGroup !== activeGroup) {
    box.textContent = activeGroup ? `Připraveno pro ${activeGroup}.` : "Připraveno.";
    return;
  }
  if (status.error) {
    box.textContent = "Stahování skončilo chybou.";
    document.querySelector("#sync-error").textContent = status.error;
    return;
  }
  if (status.results?.length) {
    const withData = status.results.filter(item => !item.no_data);
    const withoutData = status.results.filter(item => item.no_data);
    const parts = [];
    if (withData.length) {
      parts.push(`Hotovo ${group}: ${withData.map(item => monthLabel(item)).join(", ")}`);
    }
    if (withoutData.length) {
      parts.push(`Bez dat ${group}: ${withoutData.map(item => monthLabel(item)).join(", ")}`);
    }
    box.textContent = parts.join(". ");
    return;
  }
  box.textContent = "Připraveno.";
}

async function loadSyncStatus() {
  if (staticMode) {
    return null;
  }
  const response = await fetch(cacheUrl(SYNC_STATUS_URL));
  if (!response.ok) {
    throw new Error("Stav stahování není dostupný.");
  }
  return response.json();
}

function stopSyncPolling() {
  if (syncPollTimer) {
    clearInterval(syncPollTimer);
    syncPollTimer = null;
  }
}

function startSyncPolling() {
  stopSyncPolling();
  syncPollTimer = setInterval(async () => {
    try {
      const status = await loadSyncStatus();
      renderSyncStatus(status);
      if (!status.running) {
        stopSyncPolling();
        if (!status.error) {
          availableMonths = await loadAvailableMonths();
          if (status.results?.length) {
            const last = [...status.results].reverse().find(item => !item.no_data);
            if (last) {
              selectedMonth = { year: last.year, month: last.month };
            }
          }
          await render();
        }
      }
    } catch (error) {
      document.querySelector("#sync-error").textContent = error.message;
      stopSyncPolling();
    }
  }, 2500);
}

async function submitSync() {
  if (staticMode) {
    throw new Error("Statický export neumí spouštět stahování dat.");
  }
  const token = adminToken();
  if (!token) {
    throw new Error("Zadej admin token.");
  }
  saveAdminToken(token);
  document.querySelector("#sync-error").textContent = "";
  renderSyncStatus({ running: true, requested_months: [] });
  const response = await fetch(SYNC_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-EDC-Admin-Token": token,
    },
    body: JSON.stringify(syncPayload()),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) {
    throw new Error(result.error || "Stahování se nepodařilo spustit.");
  }
  renderSyncStatus(result.status);
  startSyncPolling();
}

function renderEmpty(message) {
  currentData = null;
  document.querySelector("#period").textContent = message;
  renderConfig(appConfig);
  document.querySelector("#metrics").innerHTML = "";
  document.querySelector("#strategy").textContent = "";
  document.querySelector("#recommendation").innerHTML = `<p class="muted">${message}</p>`;
  document.querySelector("#analysis-status").textContent = "";
  document.querySelector("#analysis").innerHTML = "";
  document.querySelector("#charts-status").textContent = "";
  document.querySelector("#consumer-charts").innerHTML = "";
  document.querySelector("#producers").innerHTML = "";
  document.querySelector("#consumers").innerHTML = "";
  document.querySelector("#interval-count").textContent = "";
  document.querySelector("#intervals").innerHTML = "";
}

function renderMonthSwitch() {
  document.querySelector("#month-label").textContent = selectedMonth ? monthLabel(selectedMonth) : "Načítám...";
}

function moveMonth(delta) {
  const now = new Date();
  const baseMonth = selectedMonth || (currentData ? monthFromData(currentData) : {
    year: now.getFullYear(),
    month: now.getMonth() + 1,
  });
  selectedMonth = addMonths(baseMonth, delta);
  render();
}

function renderMetric(metric, type) {
  const help = metric.help ? `
    <span class="metric-help">
      <button
        type="button"
        class="metric-help-toggle"
        aria-label="Vysvětlit potenciál lepšího sdílení"
        aria-expanded="false"
      >
        ${questionIcon()}
      </button>
      <div class="metric-popover" role="dialog" aria-label="${metric.label}" hidden>
        ${sharingPotentialHelpContent()}
      </div>
    </span>
  ` : "";
  const hint = metric.hint ? `<p class="metric-hint">${metric.hint}</p>` : "";

  return `
    <div class="metric metric-${type}">
      <div class="metric-label-row">
        <label>${metric.label}</label>
        ${help}
      </div>
      <strong>${metric.value}</strong>
      ${hint}
    </div>
  `;
}

function renderMetrics(data) {
  const groups = [
    {
      title: "Výroba",
      type: "producer",
      metrics: [
        { label: "Vyrobeno", value: kwh(data.totals.production_kwh) },
        {
          label: SHARING_POTENTIAL_LABEL,
          value: kwh(data.totals.missed_kwh),
          hint: SHARING_POTENTIAL_HINT,
          help: true,
        },
        { label: "Prodej do sítě", value: kwh(data.totals.sold_to_network_kwh) },
      ],
    },
    {
      title: "Sdílení",
      type: "shared",
      metrics: [
        { label: "Sdíleno", value: kwh(data.totals.shared_kwh) },
        { label: "Efektivita sdílení", value: percent(data.totals.sharing_efficiency_percent) },
      ],
    },
    {
      title: "Odběr",
      type: "consumer",
      metrics: [
        { label: "Spotřeba", value: kwh(data.totals.consumption_kwh) },
        { label: "Pokrytí odběru sdílením", value: percent(sharePercent(data.totals.shared_kwh, data.totals.consumption_kwh)) },
        { label: "Nákup ze sítě", value: kwh(data.totals.purchased_from_network_kwh) },
      ],
    },
  ];

  document.querySelector("#metrics").innerHTML = groups.map(group => `
    <section class="metric-group metric-group-${group.type}">
      <h2>${group.title}</h2>
      <div class="metric-row">
        ${group.metrics.map(metric => renderMetric(metric, group.type)).join("")}
      </div>
    </section>
  `).join("");
}

function renderRecommendation(data) {
  const box = document.querySelector("#recommendation");
  const strategy = document.querySelector("#strategy");
  const recommendation = data.recommendation.recommended;
  const allocations = currentAllocations(data);
  strategy.textContent = recommendation ? "report EDC" : "";

  if (!recommendation) {
    box.innerHTML = `<p class="muted">${data.recommendation.reason || "Doporučení není k dispozici."}</p>`;
    return;
  }

  box.innerHTML = `
    <p class="muted">
      Poměry níže odpovídají aktuálnímu nastavení skupiny. Hodnoty kWh jsou skutečný výsledek
      z reportu EDC za vybrané období.
    </p>
    ${allocationRows(data, allocations)}
    <div class="comparison">
      <div>
        <span>Reálně nasdíleno</span>
        <strong>${kwh(data.totals.shared_kwh)}</strong>
      </div>
      <div>
        <span>Výroba po sdílení</span>
        <strong>${kwh(data.totals.sold_to_network_kwh)}</strong>
      </div>
      <div>
        <span>Odběr ze sítě</span>
        <strong>${kwh(data.totals.purchased_from_network_kwh)}</strong>
      </div>
    </div>
    <p class="muted">
      Tato část zatím nepočítá změnu nastavení. Jen zobrazuje aktuální poměry a skutečný dopad sdílení
      podle exportovaných dat z EDC.
    </p>
  `;
}

function renderAnalysis(data) {
  const box = document.querySelector("#analysis");
  const status = document.querySelector("#analysis-status");
  const recommendation = data.recommendation.recommended;
  const allocations = currentAllocations(data);
  const currentScenario = findScenario(data, allocations);
  const strongestPurchase = topPurchasedConsumer(data);
  const hourly = aggregateIntervals(data.intervals, "hour");
  const purchasePeaks = topIntervals(hourly, "consumption_after_kwh");
  const exportPeaks = topIntervals(hourly, "production_after_kwh");
  const overlapPeaks = topOverlapIntervals(hourly);

  if (!recommendation || data.consumers.length < 2) {
    status.textContent = "bez doporučení";
    box.innerHTML = `
      <p class="muted">
        Pro doporučení změny poměrů jsou potřeba alespoň dvě odběrová OM ve skupině.
      </p>
    `;
    return;
  }

  const baselineShared = currentScenario?.shared_kwh ?? data.totals.shared_kwh;
  const bestShared = recommendation.shared_kwh;
  const gain = Math.max(0, bestShared - baselineShared);
  const sameAsCurrent = sameAllocations(allocations, recommendation.allocations) || gain < 0.05;
  const purchasedText = strongestPurchase
    ? `${strongestPurchase.name} mělo největší odběr ze sítě: ${kwh(strongestPurchase.after_kwh)}.`
    : "";

  status.textContent = sameAsCurrent ? "poměr je v pořádku" : "doporučená změna";

  if (sameAsCurrent) {
    box.innerHTML = `
      <div class="analysis-summary good">
        <strong>Současný poměr vychází pro tato data dobře.</strong>
        <p>
          Přepočet možných poměrů nad reálnými 15min daty z EDC nenašel významně lepší rozdělení.
          ${purchasedText} Přesto zůstalo ${kwh(data.totals.sold_to_network_kwh)} výroby po sdílení,
          takže hlavní rezerva bude spíš v časovém krytí výroby a odběru než v samotném poměru.
        </p>
      </div>
      ${allocationComparisonTable(data, allocations, recommendation.allocations)}
      <div class="analysis-kpis">
        <div><span>Aktuálně nasdíleno</span><strong>${kwh(data.totals.shared_kwh)}</strong></div>
        <div><span>Nejlepší prověřený výsledek</span><strong>${kwh(bestShared)}</strong></div>
        <div><span>Potenciál změnou poměru</span><strong>${kwh(gain)}</strong></div>
      </div>
      ${renderPeaks(purchasePeaks, exportPeaks, overlapPeaks)}
    `;
    return;
  }

  box.innerHTML = `
    <div class="analysis-summary action">
      <strong>Zvaž změnu poměru sdílení.</strong>
      <p>
        Nad reálnými 15min daty z EDC by tento poměr využil přibližně o ${kwh(gain)} více elektřiny
        ve sdílení. ${purchasedText}
      </p>
    </div>
    ${allocationComparisonTable(data, allocations, recommendation.allocations)}
    <div class="analysis-kpis">
      <div><span>Současný poměr v přepočtu</span><strong>${kwh(baselineShared)}</strong></div>
      <div><span>Doporučený poměr v přepočtu</span><strong>${kwh(bestShared)}</strong></div>
      <div><span>Možné navýšení sdílení</span><strong>+${kwh(gain)}</strong></div>
    </div>
    ${renderPeaks(purchasePeaks, exportPeaks, overlapPeaks)}
  `;
}

function allocationComparisonTable(data, current, recommended) {
  const currentTotal = data.consumers.reduce((sum, _, index) => sum + (current[index] || 0), 0);
  const recommendedTotal = data.consumers.reduce((sum, _, index) => sum + (recommended[index] || 0), 0);
  return `
    <div class="allocation-compare">
      <div class="allocation-compare-head">
        <span>Odběrné OM</span>
        <span>Současně</span>
        <span>Doporučeno</span>
      </div>
      ${data.consumers.map((ean, index) => `
        <div class="allocation-compare-row">
          <div>
            <strong>${omName(data, ean)}</strong>
            <code>${ean}</code>
          </div>
          <span>${current[index] || 0} %</span>
          <span class="${(current[index] || 0) !== (recommended[index] || 0) ? "changed" : ""}">${recommended[index] || 0} %</span>
        </div>
      `).join("")}
      <div class="allocation-compare-row allocation-compare-total">
        <strong>Součet</strong>
        <span>${currentTotal} %</span>
        <span class="${currentTotal !== recommendedTotal ? "changed" : ""}">${recommendedTotal} %</span>
      </div>
    </div>
  `;
}

function renderPeaks(purchasePeaks, exportPeaks, overlapPeaks) {
  return `
    <div class="peak-grid">
      <section>
        <h3>Špičky nákupu ze sítě</h3>
        ${peakRows(purchasePeaks, "consumption_after_kwh")}
      </section>
      <section>
        <h3>Špičky výroby po sdílení</h3>
        ${peakRows(exportPeaks, "production_after_kwh")}
      </section>
      <section>
        <h3>Současný prodej i nákup</h3>
        ${overlapRows(overlapPeaks)}
      </section>
    </div>
  `;
}

function chartPoints(series, key, width, height, padding, maxValue) {
  if (series.length === 1) {
    const y = height - padding - (series[0][key] / maxValue) * (height - padding * 2);
    return `${padding},${y} ${width - padding},${y}`;
  }
  return series.map((item, index) => {
    const x = padding + (index / (series.length - 1)) * (width - padding * 2);
    const y = height - padding - (item[key] / maxValue) * (height - padding * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function chartArea(points, width, height, padding) {
  return `${padding},${height - padding} ${points} ${width - padding},${height - padding}`;
}

function renderConsumerCharts(data) {
  const box = document.querySelector("#consumer-charts");
  const status = document.querySelector("#charts-status");
  const mode = intervalMode === "quarter" ? "hour" : intervalMode;
  status.textContent = mode === "hour" ? "hodinový pohled" : "denní pohled";

  if (!data.consumers.length) {
    box.innerHTML = `<p class="muted">Žádná odběrná OM nejsou v reportu k dispozici.</p>`;
    return;
  }

  const width = 900;
  const height = 260;
  const padding = 42;
  box.innerHTML = data.consumers.map(ean => {
    const series = aggregateConsumerSeries(data, ean, mode);
    const totals = data.eans.consumers.find(item => item.ean === ean);
    const maxValue = Math.max(0.01, ...series.map(item => Math.max(item.before_kwh, item.shared_kwh)));
    const consumptionPoints = chartPoints(series, "before_kwh", width, height, padding, maxValue);
    const sharedPoints = chartPoints(series, "shared_kwh", width, height, padding, maxValue);
    const coverage = totals ? sharePercent(totals.shared_kwh, totals.before_kwh) : 0;
    const firstLabel = series[0] ? intervalLabel(series[0].start, mode) : "";
    const lastLabel = series.length ? intervalLabel(series[series.length - 1].start, mode) : "";

    return `
      <article class="consumer-chart">
        <div class="chart-head">
          ${omLabel(omName(data, ean), ean)}
          <div>
            <span>Soběstačnost</span>
            <strong>${percent(coverage)}</strong>
          </div>
        </div>
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Spotřeba a sdílení pro ${omName(data, ean)}">
          <line class="chart-grid" x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="#d9e0e7" stroke-width="1"></line>
          <line class="chart-grid" x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" stroke="#d9e0e7" stroke-width="1"></line>
          <polygon class="chart-consumption" points="${chartArea(consumptionPoints, width, height, padding)}" fill="#d9e8ff" fill-opacity="0.55" stroke="none"></polygon>
          <polyline class="chart-consumption-line" points="${consumptionPoints}" fill="none" stroke="#246bce" stroke-width="2.2" stroke-linejoin="round"></polyline>
          <polyline class="chart-shared-line" points="${sharedPoints}" fill="none" stroke="#7b4fc9" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"></polyline>
          <text x="${padding}" y="${height - 8}" fill="#607080" font-size="11">${firstLabel}</text>
          <text x="${width - padding}" y="${height - 8}" text-anchor="end" fill="#607080" font-size="11">${lastLabel}</text>
          <text x="${width - padding}" y="${padding - 14}" text-anchor="end" fill="#607080" font-size="11">max ${kwh(maxValue)}</text>
        </svg>
        <div class="chart-legend">
          <span class="legend-consumption">Spotřeba</span>
          <span class="legend-shared">Ze sdílení</span>
          <span>Nákup ze sítě ${kwh(totals?.after_kwh || 0)}</span>
        </div>
      </article>
    `;
  }).join("");
}

function consumerStats(item) {
  const selfSufficiency = sharePercent(item.shared_kwh, item.before_kwh);
  return `
    <div class="self-stats">
      <div><span>Spotřeba</span><strong>${kwh(item.before_kwh)}</strong></div>
      <div><span>Ze sdílení</span><strong>${kwh(item.shared_kwh)}</strong></div>
      <div><span>Nákup ze sítě</span><strong>${kwh(item.after_kwh)}</strong></div>
      <div><span>Soběstačnost</span><strong>${percent(selfSufficiency)}</strong></div>
    </div>
  `;
}

function producerStats(item) {
  return `
    <div class="self-stats producer-stats">
      <div><span>Vyrobeno</span><strong>${kwh(item.before_kwh)}</strong></div>
      <div><span>Nasdíleno</span><strong>${kwh(item.shared_kwh)}</strong></div>
      <div><span>Po sdílení</span><strong>${kwh(item.after_kwh)}</strong></div>
      <div><span>Využití ve sdílení</span><strong>${percent(sharePercent(item.shared_kwh, item.before_kwh))}</strong></div>
    </div>
  `;
}

function renderEans(selector, items, kind) {
  const totalLabel = kind === "consumer" ? "Spotřeba" : "Výroba";
  document.querySelector(selector).innerHTML = `
    <div class="ean-list">
      ${items.map(item => `
        <div class="ean-row">
          <div>
            ${omLabel(item.name || item.ean, item.ean)}
            ${kind === "consumer" ? consumerStats(item) : producerStats(item)}
          </div>
          <div class="ean-total">
            <span>${totalLabel}</span>
            <strong>${kwh(item.before_kwh)}</strong>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderIntervals(data) {
  const intervals = aggregateIntervals(data.intervals, intervalMode);
  document.querySelector("#interval-count").textContent = `${intervals.length} ${intervalModeName(intervalMode)}`;
  document.querySelector("#intervals").innerHTML = intervals.map(item => `
    <tr>
      <td>${intervalLabel(item.start, intervalMode)}</td>
      <td class="producer-cell">${kwh(item.production_before_kwh)}</td>
      <td class="consumer-cell">${kwh(item.consumption_before_kwh)}</td>
      <td class="shared-cell ok">${kwh(item.shared_kwh)}</td>
      <td class="producer-cell ${item.missed_kwh > 0 ? "warn" : ""}">${kwh(item.missed_kwh)}</td>
      <td class="producer-cell">${kwh(item.production_after_kwh)}</td>
      <td class="consumer-cell">${kwh(item.consumption_after_kwh)}</td>
    </tr>
  `).join("");
}

function renderIntervalSwitcher() {
  document.querySelectorAll("[data-interval-mode]").forEach(button => {
    button.classList.toggle("selected", button.dataset.intervalMode === intervalMode);
  });
}

async function render() {
  try {
    if (!appConfig) {
      appConfig = await loadConfig();
      activeGroup = appConfig?.group || activeGroup;
    }
    if (!availableGroups.length) {
      availableGroups = await loadGroups();
      if (!activeGroup && availableGroups.length) {
        activeGroup = availableGroups[0].name;
      }
    }
    renderConfig(appConfig);
    renderGroupSwitcher();
    if (!selectedMonth) {
      availableMonths = await loadAvailableMonths();
      selectedMonth = initialMonth(availableMonths);
    }
    renderMonthSwitch();
    const data = await loadData(selectedMonth);
    currentData = data;
    selectedMonth = monthFromData(data);
    renderMonthSwitch();
    document.querySelector("#period").textContent = `${timeLabel(data.date_from)} - ${timeLabel(data.date_to)}`;
    renderMetrics(data);
    renderRecommendation(data);
    renderAnalysis(data);
    renderConsumerCharts(data);
    renderEans("#producers", data.eans.producers, "producer");
    renderEans("#consumers", data.eans.consumers, "consumer");
    renderIntervalSwitcher();
    renderIntervals(data);
  } catch (error) {
    renderEmpty(error.message);
  }
}

function openNameDialog(ean) {
  const dialog = document.querySelector("#name-dialog");
  document.querySelector("#name-ean").value = ean;
  document.querySelector("#name-value").value = currentData?.om_names?.[ean] === ean ? "" : currentData?.om_names?.[ean] || "";
  document.querySelector("#name-error").textContent = "";
  dialog.showModal();
  document.querySelector("#name-value").focus();
}

async function saveName(ean, name) {
  if (staticMode) {
    throw new Error("Statický export neumí ukládat názvy OM.");
  }
  const response = await fetch(`${NAMES_URL}${groupQuery()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ean, name }),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) {
    throw new Error(result.error || "Název se nepodařilo uložit.");
  }
}

function closeMetricHelp(exceptButton = null) {
  document.querySelectorAll(".metric-help-toggle").forEach(button => {
    if (button === exceptButton) {
      return;
    }
    button.setAttribute("aria-expanded", "false");
    const popover = button.parentElement?.querySelector(".metric-popover");
    if (popover) {
      popover.hidden = true;
    }
  });
}

function toggleMetricHelp(button) {
  const popover = button.parentElement?.querySelector(".metric-popover");
  if (!popover) {
    return;
  }
  const willOpen = button.getAttribute("aria-expanded") !== "true";
  closeMetricHelp(button);
  button.setAttribute("aria-expanded", String(willOpen));
  popover.hidden = !willOpen;
}

document.querySelector("#sync-open").addEventListener("click", async () => {
  const base = selectedMonth || currentMonthRef();
  fillSyncMonth(base);
  initialAdminToken();
  document.querySelector("#sync-error").textContent = "";
  try {
    renderSyncStatus(await loadSyncStatus());
  } catch {
    renderSyncStatus(null);
  }
  document.querySelector("#sync-dialog").showModal();
});
document.querySelector("#group-switcher").addEventListener("click", event => {
  const button = event.target.closest("[data-group-name]");
  if (!button || button.dataset.groupName === activeGroup) {
    return;
  }
  activeGroup = button.dataset.groupName;
  selectedMonth = null;
  currentData = null;
  availableMonths = [];
  document.querySelector("#sync-error").textContent = "";
  renderSyncStatus(null);
  render();
});
document.querySelector("#sync-close").addEventListener("click", () => {
  document.querySelector("#sync-dialog").close();
});
document.querySelectorAll("[data-sync-mode]").forEach(button => {
  button.addEventListener("click", () => {
    setSyncMode(button.dataset.syncMode);
  });
});
document.querySelector("#sync-previous-month").addEventListener("click", () => {
  const previous = addMonths(currentMonthRef(), -1);
  setSyncMode("single");
  fillSyncMonth(previous);
});
document.querySelector("#sync-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await submitSync();
  } catch (error) {
    document.querySelector("#sync-error").textContent = error.message;
    renderSyncStatus(null);
  }
});
document.querySelector("#month-prev").addEventListener("click", () => {
  moveMonth(-1);
});
document.querySelector("#month-next").addEventListener("click", () => {
  moveMonth(1);
});
document.querySelectorAll("[data-interval-mode]").forEach(button => {
  button.addEventListener("click", () => {
    intervalMode = button.dataset.intervalMode;
    renderIntervalSwitcher();
    if (currentData) {
      renderConsumerCharts(currentData);
      renderIntervals(currentData);
    }
  });
});
document.addEventListener("click", event => {
  const helpTrigger = event.target.closest(".metric-help-toggle");
  if (helpTrigger) {
    toggleMetricHelp(helpTrigger);
    return;
  }
  if (!event.target.closest(".metric-help")) {
    closeMetricHelp();
  }

  const trigger = event.target.closest(".om-edit");
  if (trigger) {
    openNameDialog(trigger.dataset.ean);
  }
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    closeMetricHelp();
  }
});

document.querySelector("#name-close").addEventListener("click", () => {
  document.querySelector("#name-dialog").close();
});

document.querySelector("#name-form").addEventListener("submit", async event => {
  event.preventDefault();
  const ean = document.querySelector("#name-ean").value;
  const name = document.querySelector("#name-value").value.trim();
  try {
    await saveName(ean, name);
    document.querySelector("#name-dialog").close();
    await render();
  } catch (error) {
    document.querySelector("#name-error").textContent = error.message;
  }
});

document.querySelector("#name-remove").addEventListener("click", async () => {
  const ean = document.querySelector("#name-ean").value;
  try {
    await saveName(ean, "");
    document.querySelector("#name-dialog").close();
    await render();
  } catch (error) {
    document.querySelector("#name-error").textContent = error.message;
  }
});

setSyncMode(syncMode);
render();
