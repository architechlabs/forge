const state = {
  dashboard: null,
  plan: null,
  selected: new Set(),
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg || JSON.stringify(item)).join("; ")
      : data.detail;
    throw new Error(detail || response.statusText);
  }
  return data;
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 2800);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatTime(value) {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function instanceById(id) {
  return (state.dashboard?.instances || []).find((item) => item.id === id);
}

async function loadDashboard() {
  state.dashboard = await api("./api/dashboard");
  render();
}

function render() {
  const instances = state.dashboard?.instances || [];
  const maps = state.dashboard?.entity_maps || [];
  $("summary").textContent = `${instances.length} sources, ${maps.length} imported entities`;
  renderInstances();
  renderPlanSourceOptions();
  renderEntities();
  renderImports();
  renderEvents();
}

function renderInstances() {
  const list = $("instancesList");
  const instances = state.dashboard?.instances || [];
  if (!instances.length) {
    list.innerHTML = `<div class="instance"><strong>No source instances</strong><div class="meta">Add one to begin.</div></div>`;
    return;
  }
  list.innerHTML = instances
    .map(
      (item) => `
      <article class="instance">
        <div class="instance-head">
          <div>
            <strong>${escapeHtml(item.name)}</strong>
            <div class="meta">${escapeHtml(item.url)}</div>
          </div>
          <div class="badge-row">
            <span class="badge ${item.enabled ? "ok" : "warn"}">${item.enabled ? "Enabled" : "Paused"}</span>
            <span class="badge ${item.token_configured ? "ok" : "danger"}">${item.token_configured ? "Token" : "No token"}</span>
          </div>
        </div>
        <div class="meta">Last scan: ${escapeHtml(formatTime(item.last_scan_at))} | Entities: ${escapeHtml(item.last_scan_count || 0)}</div>
        ${item.last_scan_error ? `<div class="meta danger">${escapeHtml(item.last_scan_error)}</div>` : ""}
        <div class="form-actions">
          <button data-action="edit-instance" data-id="${item.id}" class="secondary">Edit</button>
          <button data-action="test-instance" data-id="${item.id}" class="secondary">Test</button>
          <button data-action="scan-instance" data-id="${item.id}">Scan</button>
          <button data-action="delete-instance" data-id="${item.id}" class="secondary">Delete</button>
        </div>
      </article>
    `,
    )
    .join("");
}

function renderPlanSourceOptions() {
  const select = $("planInstance");
  const previous = select.value;
  const instances = state.dashboard?.instances || [];
  select.innerHTML = [
    `<option value="__all__">All enabled sources</option>`,
    ...instances.map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`),
  ]
    .join("");
  if (previous === "__all__" || instances.some((item) => item.id === previous)) {
    select.value = previous;
  }
}

function filteredEntities() {
  const instanceId = $("planInstance").value;
  const filter = $("entityFilter").value.trim().toLowerCase();
  const instances = (state.dashboard?.instances || []).filter((item) =>
    instanceId === "__all__" ? item.enabled !== false : item.id === instanceId,
  );
  const entities = instances.flatMap((instance) => {
    const snapshot = state.dashboard?.snapshots?.[instance.id];
    return (snapshot?.entities || []).map((entity) => ({
      ...entity,
      source_instance_id: instance.id,
      source_instance_name: instance.name,
      ref: `${instance.id}::${entity.entity_id}`,
    }));
  });
  return entities.filter((entity) => {
    if (!filter) return true;
    return [
      entity.source_instance_name,
      entity.entity_id,
      entity.name,
      entity.platform,
      entity.integration_label,
      entity.area_name,
      entity.device_name,
      entity.domain,
    ]
      .join(" ")
      .toLowerCase()
      .includes(filter);
  });
}

function planRowFor(ref) {
  return (state.plan?.rows || []).find((row) => `${row.source_instance_id}::${row.source_entity_id}` === ref);
}

function renderRequirements() {
  const reqs = state.plan?.native_requirements || [];
  const node = $("requirements");
  if (!reqs.length) {
    node.innerHTML = "";
    return;
  }
  node.innerHTML = reqs
    .map(
      (req) => `
      <span class="badge ${req.available_on_target ? "ok" : "warn"}">
        ${escapeHtml(req.name)}: ${req.count}${req.available_on_target ? " ready" : " needed"}
      </span>
    `,
    )
    .join("");
}

function renderEntities() {
  renderRequirements();
  const body = $("entitiesBody");
  const entities = filteredEntities();
  if (!entities.length) {
    body.innerHTML = `<tr><td colspan="6">No scan data</td></tr>`;
    $("selectAll").checked = false;
    updateSelectedCount();
    return;
  }
  body.innerHTML = entities
    .map((entity) => {
      const row = planRowFor(entity.ref);
      const local = row?.local_entity_id || `${entity.helper_domain}.pending`;
      const status = row?.status || "scan";
      const checked = state.selected.has(entity.ref) ? "checked" : "";
      const disabled = status === "skip" ? "disabled" : "";
      return `
        <tr>
          <td><input type="checkbox" data-ref="${escapeHtml(entity.ref)}" ${checked} ${disabled}></td>
          <td>
            <strong>${escapeHtml(entity.name)}</strong>
            <div class="meta">${escapeHtml(entity.entity_id)}</div>
            <div class="meta">${escapeHtml(entity.source_instance_name)}${entity.area_name || entity.device_name ? ` | ${escapeHtml(entity.area_name || entity.device_name)}` : ""}</div>
          </td>
          <td>${escapeHtml(entity.state)}</td>
          <td>
            ${escapeHtml(entity.integration_label)}
            <div class="meta">${escapeHtml(entity.capability_note)}</div>
          </td>
          <td>${escapeHtml(local)}</td>
          <td><span class="badge ${status === "ready" ? "ok" : status === "skip" ? "warn" : ""}">${escapeHtml(status)}</span></td>
        </tr>
      `;
    })
    .join("");
  const selectable = entities.filter((entity) => planRowFor(entity.ref)?.status !== "skip");
  $("selectAll").checked = selectable.length > 0 && selectable.every((entity) => state.selected.has(entity.ref));
  updateSelectedCount();
}

function renderImports() {
  const maps = state.dashboard?.entity_maps || [];
  $("importCount").textContent = String(maps.length);
  const node = $("importsList");
  if (!maps.length) {
    node.innerHTML = `<article class="entity-card"><strong>No imported entities</strong><div class="meta">Imported helpers will appear here.</div></article>`;
    return;
  }
  node.innerHTML = maps
    .map((item) => {
      const control =
        item.local_domain === "input_boolean"
          ? `
            <div class="control-row">
              <button data-action="control" data-id="${item.id}" data-value="on">On</button>
              <button data-action="control" data-id="${item.id}" data-value="off" class="secondary">Off</button>
            </div>`
          : item.local_domain === "input_number" || item.local_domain === "input_text" || item.local_domain === "input_select"
            ? `
            <div class="control-row">
              <input data-control-value="${item.id}" value="${escapeHtml(item.last_source_state || "")}" />
              <button data-action="control-input" data-id="${item.id}">Set</button>
            </div>`
            : "";
      return `
        <article class="entity-card">
          <div class="entity-head">
            <div>
              <strong>${escapeHtml(item.name || item.source_entity_id)}</strong>
              <div class="meta">${escapeHtml(item.local_entity_id)}</div>
            </div>
            <span class="badge ${item.writable ? "ok" : ""}">${item.writable ? "Control" : "Mirror"}</span>
          </div>
          <div class="meta">${escapeHtml(item.source_instance_name || item.source_instance_id)} | ${escapeHtml(item.source_entity_id)}</div>
          <div class="meta">State: ${escapeHtml(item.last_source_state)} | Synced: ${escapeHtml(formatTime(item.last_sync_at))}</div>
          ${control}
          <div class="form-actions">
            <button data-action="delete-map" data-id="${item.id}" class="secondary">Remove</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderEvents() {
  const events = state.dashboard?.events || [];
  const node = $("eventsList");
  if (!events.length) {
    node.innerHTML = `<div class="event"><strong>No activity</strong></div>`;
    return;
  }
  node.innerHTML = events
    .map(
      (event) => `
      <article class="event">
        <div class="event-head">
          <strong>${escapeHtml(event.message)}</strong>
          <span class="badge ${event.level === "warning" ? "warn" : "ok"}">${escapeHtml(event.level)}</span>
        </div>
        <div class="meta">${escapeHtml(formatTime(event.created_at))}</div>
      </article>
    `,
    )
    .join("");
}

function updateSelectedCount() {
  $("selectedCount").textContent = `${state.selected.size} selected`;
}

async function buildPlan() {
  const instanceId = $("planInstance").value;
  const instanceIds = instanceId === "__all__"
    ? (state.dashboard?.instances || []).filter((item) => item.enabled !== false).map((item) => item.id)
    : [instanceId];
  if (!instanceIds.length) {
    toast("Add a source instance first");
    return;
  }
  const entities = filteredEntities();
  const selected = entities.filter((entity) => state.selected.has(entity.ref)).map((entity) => entity.ref);
  state.plan = await api("./api/plan", {
    method: "POST",
    body: JSON.stringify({
      instance_ids: instanceIds,
      entity_refs: selected.length ? selected : null,
      prefix: $("planPrefix").value || "bridge",
      conflict_policy: $("conflictPolicy").value,
    }),
  });
  state.selected = new Set(
    state.plan.rows
      .filter((row) => row.status === "ready")
      .map((row) => `${row.source_instance_id}::${row.source_entity_id}`),
  );
  renderEntities();
  toast(`Plan ready: ${state.plan.count} entities`);
}

async function importSelected() {
  const instanceId = $("planInstance").value;
  const instanceIds = instanceId === "__all__"
    ? (state.dashboard?.instances || []).filter((item) => item.enabled !== false).map((item) => item.id)
    : [instanceId];
  const selected = [...state.selected];
  if (!selected.length) {
    toast("Select entities first");
    return;
  }
  const result = await api("./api/import", {
    method: "POST",
    body: JSON.stringify({
      instance_ids: instanceIds,
      entity_refs: selected,
      prefix: $("planPrefix").value || "bridge",
      conflict_policy: $("conflictPolicy").value,
    }),
  });
  await loadDashboard();
  toast(`Imported ${result.job.done} entities`);
}

function fillInstanceForm(item) {
  $("instanceId").value = item?.id || "";
  $("instanceName").value = item?.name || "";
  $("instanceUrl").value = item?.url || "";
  $("instanceToken").value = "";
  $("instanceSsl").checked = item?.verify_ssl !== false;
  $("instanceEnabled").checked = item?.enabled !== false;
  $("instanceSync").checked = item?.sync_enabled !== false;
}

async function handleAction(target) {
  const action = target.dataset.action;
  const id = target.dataset.id;
  if (!action) return;
  if (action === "edit-instance") {
    fillInstanceForm(instanceById(id));
  }
  if (action === "test-instance") {
    const result = await api(`./api/instances/${id}/test`, { method: "POST" });
    toast(`Connected: ${result.location_name || result.version || "ok"}`);
  }
  if (action === "scan-instance") {
    const result = await api(`./api/instances/${id}/scan`, { method: "POST" });
    await loadDashboard();
    toast(`Scanned ${result.counts.entities} entities`);
  }
  if (action === "delete-instance") {
    if (!confirm("Delete this source and its imported mappings?")) return;
    await api(`./api/instances/${id}`, { method: "DELETE" });
    await loadDashboard();
    toast("Source deleted");
  }
  if (action === "delete-map") {
    if (!confirm("Remove this imported helper from the managed package?")) return;
    await api(`./api/entities/${id}`, { method: "DELETE" });
    await loadDashboard();
    toast("Import removed");
  }
  if (action === "control") {
    await api(`./api/entities/${id}/control`, {
      method: "POST",
      body: JSON.stringify({ value: target.dataset.value }),
    });
    await loadDashboard();
    toast("Command sent");
  }
  if (action === "control-input") {
    const input = document.querySelector(`[data-control-value="${id}"]`);
    await api(`./api/entities/${id}/control`, {
      method: "POST",
      body: JSON.stringify({ value: input.value }),
    });
    await loadDashboard();
    toast("Value sent");
  }
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((node) => node.classList.remove("active"));
      document.querySelectorAll(".view").forEach((node) => node.classList.remove("active"));
      tab.classList.add("active");
      $(tab.dataset.view).classList.add("active");
    });
  });

  document.body.addEventListener("click", async (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (target.disabled) return;
    try {
      target.disabled = true;
      await handleAction(target);
    } catch (error) {
      toast(error.message);
    } finally {
      target.disabled = false;
    }
  });

  $("instanceForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      id: $("instanceId").value || null,
      name: $("instanceName").value,
      url: $("instanceUrl").value,
      token: $("instanceToken").value || null,
      verify_ssl: $("instanceSsl").checked,
      enabled: $("instanceEnabled").checked,
      sync_enabled: $("instanceSync").checked,
    };
    try {
      await api("./api/instances", { method: "POST", body: JSON.stringify(payload) });
      fillInstanceForm(null);
      await loadDashboard();
      toast("Source saved");
    } catch (error) {
      toast(error.message);
    }
  });

  $("clearFormBtn").addEventListener("click", () => fillInstanceForm(null));
  $("refreshBtn").addEventListener("click", () =>
    loadDashboard()
      .then(() => toast("Refreshed"))
      .catch((error) => toast(error.message)),
  );
  $("scanAllBtn").addEventListener("click", async () => {
    await api("./api/scan-all", { method: "POST" });
    toast("Scan queued");
    setTimeout(() => loadDashboard().catch((error) => toast(error.message)), 2500);
  });
  $("syncBtn").addEventListener("click", async () => {
    const result = await api("./api/sync", { method: "POST" });
    await loadDashboard();
    toast(`Updated ${result.updated}, forwarded ${result.forwarded}`);
  });
  $("scanSelectedBtn").addEventListener("click", async () => {
    const id = $("planInstance").value;
    if (!id) return toast("No source selected");
    if (id === "__all__") {
      const result = await api("./api/scan-all", { method: "POST" });
      toast(`Queued ${result.queued} source scans`);
      setTimeout(() => loadDashboard().catch((error) => toast(error.message)), 2500);
    } else {
      const result = await api(`./api/instances/${id}/scan`, { method: "POST" });
      await loadDashboard();
      toast(`Scanned ${result.counts.entities} entities`);
    }
  });
  $("buildPlanBtn").addEventListener("click", () => buildPlan().catch((error) => toast(error.message)));
  $("importBtn").addEventListener("click", () => importSelected().catch((error) => toast(error.message)));
  $("entityFilter").addEventListener("input", renderEntities);
  $("planInstance").addEventListener("change", () => {
    state.selected.clear();
    state.plan = null;
    renderEntities();
  });
  $("selectAll").addEventListener("change", (event) => {
    filteredEntities().forEach((entity) => {
      if (event.target.checked) state.selected.add(entity.ref);
      else state.selected.delete(entity.ref);
    });
    renderEntities();
  });
  $("entitiesBody").addEventListener("change", (event) => {
    const ref = event.target.dataset.ref;
    if (!ref) return;
    if (event.target.checked) state.selected.add(ref);
    else state.selected.delete(ref);
    updateSelectedCount();
  });
}

bindEvents();
loadDashboard().catch((error) => toast(error.message));
