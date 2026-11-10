"use strict";

const $ = (id) => document.getElementById(id);
const labels = {
  live: "Chat en vivo", press: "Comentarios de prensa", reviews: "Reseñas",
  news: "Noticias", youtube: "Videos de YouTube", forum: "Foros",
};
const names = {
  COMMENT: "Comentario", REVIEW: "Reseña", LIVE_CHAT: "Chat en vivo", FEED_ENTRY: "Publicación",
  NEWS_ARTICLE: "Noticia", YOUTUBE_VIDEO: "Video", YOUTUBE_LIVE: "Directo", FORUM_POST: "Foro", PRESS_COMMENT: "Comentario de prensa",
};
const severity = { info: "Info", important: "Importante", critical: "Crítica", review: "Para revisar" };
const tones = {
  positive: ["＋", "Positivo"], negative: ["−", "Negativo"], mixed: ["±", "Mixto"], neutral: ["·", "Neutro"],
};
const jobStates = {
  DISABLED: "Desactivada", IDLE: "Finalizada", SCHEDULED: "Programada", RUNNING: "Consultando",
  PAUSED: "En pausa", RETRYING: "Reintentando", RATE_LIMITED: "Cuota alcanzada", ERROR: "Revisar conexión",
};
const styles = new Set(Object.keys(severity));
const ui = {
  token: "", practice: false, jobs: [], types: [], visible: [], focus: null, theme: "dark",
  alertsVisible: true, alertMode: "confirmed", frozen: false, running: false, statuses: [],
  limit: 45, page: "board", sequence: 0, noticeUntil: 0, timer: null, closed: false,
  columns: 3, widths: {}, order: [], defaults: [], projection: false,
};
const streams = new Map();
const time = new Intl.DateTimeFormat("es-UY", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const detailTime = new Intl.DateTimeFormat("es-UY", { dateStyle: "medium", timeStyle: "short", hourCycle: "h23" });

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function button(text, className, callback, title) {
  const element = node("button", className, text);
  element.type = "button";
  if (title) {
    element.title = title;
    element.setAttribute("aria-label", title);
  }
  element.addEventListener("click", callback);
  return element;
}

function preference(key, fallback) {
  try { return JSON.parse(localStorage.getItem(`radar.${key}`)) ?? fallback; }
  catch { return fallback; }
}

function remember(key, value) {
  try { localStorage.setItem(`radar.${key}`, JSON.stringify(value)); } catch { /* Session layout still works. */ }
}

async function api(path, payload, signal) {
  const options = { cache: "no-store", signal: signal ?? AbortSignal.timeout(18000) };
  if (payload !== undefined) {
    options.method = "POST";
    options.headers = { "Content-Type": "application/json", "X-EchoScope-Token": ui.token };
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(`/api/${path}`, options);
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || "No se pudo completar la operación.");
  return result;
}

function notice(message, failure = false) {
  ui.noticeUntil = Date.now() + (failure ? 9500 : 4500);
  $("status").textContent = message;
}

function setTheme(theme) {
  ui.theme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = ui.theme;
  $("theme").textContent = ui.theme === "dark" ? "☼" : "☾";
  const label = ui.theme === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro";
  $("theme").setAttribute("aria-label", label);
  $("theme").title = label;
}

function applyConfig(data, updateTopic = false) {
  ui.jobs = data.jobs;
  ui.types = data.types;
  if (updateTopic) $("topic").value = data.topic.join("\n");
  renderSources();
}

function activePanels() { return ui.focus ? [ui.focus] : ui.visible; }

function updateLayout() {
  const active = activePanels();
  $("restore-layout").hidden = !ui.focus;
  $("projection-restore").hidden = !ui.focus;
  for (const key of Object.keys(labels)) {
    const tab = $(`panel-toggle-${key}`);
    tab.setAttribute("aria-pressed", String(active.includes(key)));
    tab.title = active.includes(key) ? `Ocultar ${labels[key]}` : `Mostrar ${labels[key]}`;
    const stream = streams.get(key);
    stream.panel.dataset.width = ui.widths[key] ?? 2;
    stream.arrange.disabled = active.length < 2;
    stream.arrange.options[1].disabled = active[0] === key;
    stream.arrange.options[2].disabled = active.at(-1) === key;
    stream.arrange.options[3].disabled = (ui.widths[key] ?? 2) === 3;
    stream.arrange.options[4].disabled = (ui.widths[key] ?? 2) === 1;
    stream.expand.textContent = ui.focus === key ? "↙" : "⤢";
    const label = ui.focus === key ? "Restaurar vista de paneles" : `Maximizar ${labels[key]}`;
    stream.expand.setAttribute("aria-label", label);
    stream.expand.title = label;
  }
  const scrolled = active.map((key) => [streams.get(key).list, streams.get(key).list.scrollTop]);
  const rows = [];
  for (let start = 0; start < active.length; start += ui.columns) {
    const row = node("div", "panel-row");
    row.append(...active.slice(start, start + ui.columns).map((key) => streams.get(key).panel));
    rows.push(row);
  }
  $("panels").replaceChildren(...(rows.length ? rows : [node("div", "empty empty-grid", "Elegí un flujo en la barra de paneles para volver a mostrarlo.")]));
  for (const [list, offset] of scrolled) list.scrollTop = offset;
  $("panel-controls").append(...ui.order.map((key) => $(`panel-toggle-${key}`)));
  remember(`panels.${ui.practice}`, ui.visible);
  remember(`layout.${ui.practice}`, { columns: ui.columns, widths: ui.widths, order: ui.order });
}

function movePanel(key, target) {
  if (key === target || !ui.visible.includes(key) || !ui.visible.includes(target)) return;
  const index = ui.visible.indexOf(target);
  ui.visible.splice(ui.visible.indexOf(key), 1);
  ui.visible.splice(index, 0, key);
  const visible = [...ui.visible];
  ui.order = ui.order.map((item) => ui.visible.includes(item) ? visible.shift() : item);
  updateLayout();
}

function arrangePanel(key, action) {
  if (action === "wider" || action === "narrower") {
    ui.widths[key] = Math.min(3, Math.max(1, (ui.widths[key] ?? 2) + (action === "wider" ? 1 : -1)));
    updateLayout();
  } else {
    const target = ui.visible[ui.visible.indexOf(key) + (action === "before" ? -1 : 1)];
    if (target) movePanel(key, target);
  }
  streams.get(key).arrange.focus();
}

function enablePanelDrag(handle, key) {
  let target;
  let pointer;
  function clear() {
    target?.classList.remove("drop-target");
    target = null;
    pointer = null;
  }
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || ui.focus || ui.visible.length < 2 || pointer != null) return;
    pointer = event.pointerId;
    handle.setPointerCapture(pointer);
  });
  function locate(event) {
    const panel = document.elementFromPoint(event.clientX, event.clientY)?.closest(".stream");
    return panel && panel.dataset.panel !== key ? panel : null;
  }
  handle.addEventListener("pointermove", (event) => {
    if (event.pointerId !== pointer) return;
    target?.classList.remove("drop-target");
    target = locate(event);
    target?.classList.add("drop-target");
  });
  handle.addEventListener("pointerup", (event) => {
    if (event.pointerId !== pointer) return;
    const destination = locate(event)?.dataset.panel;
    clear();
    if (destination) movePanel(key, destination);
  });
  handle.addEventListener("lostpointercapture", clear);
}

function hidePanel(key) {
  ui.focus = null;
  ui.visible = ui.visible.filter((item) => item !== key);
  updateLayout();
  $(`panel-toggle-${key}`).focus();
  refresh(true);
}

function togglePanel(key) {
  if (ui.focus === key || (!ui.focus && ui.visible.includes(key))) return hidePanel(key);
  ui.focus = null;
  if (!ui.visible.includes(key)) ui.visible = ui.order.filter((item) => item === key || ui.visible.includes(item));
  updateLayout();
  refresh(true);
}

function focusPanel(key) {
  ui.focus = ui.focus === key ? null : key;
  updateLayout();
  streams.get(key).expand.focus();
  refresh(true);
}

function buildLayout() {
  for (const [key, label] of Object.entries(labels)) {
    const toggle = button(label, "", () => togglePanel(key));
    toggle.dataset.panel = key;
    toggle.id = `panel-toggle-${key}`;
    toggle.setAttribute("aria-controls", `stream-${key}`);
    $("panel-controls").append(toggle);
    const panel = node("section", "stream");
    panel.id = `stream-${key}`;
    panel.dataset.panel = key;
    panel.setAttribute("aria-labelledby", `stream-title-${key}`);
    const title = node("h2", "", label);
    title.id = `stream-title-${key}`;
    title.title = label;
    const expand = button("⤢", "icon-button", () => focusPanel(key), `Maximizar ${label}`);
    const actions = node("div", "panel-actions");
    const arrange = node("select", "panel-arrange");
    arrange.setAttribute("aria-label", `Mover o reajustar ${label}`);
    arrange.title = `Mover o reajustar ${label}`;
    for (const [value, text] of [["", "↔"], ["before", "Mover antes"], ["after", "Mover después"], ["wider", "Más ancho"], ["narrower", "Más angosto"]]) {
      const option = node("option", "", text);
      option.value = value;
      arrange.append(option);
    }
    arrange.options[0].disabled = true;
    arrange.value = "";
    arrange.addEventListener("change", () => {
      const action = arrange.value;
      arrange.value = "";
      arrangePanel(key, action);
    });
    const handle = node("span", "drag-handle", "⠿");
    handle.title = `Arrastrar ${label} sobre otro panel`;
    handle.setAttribute("aria-hidden", "true");
    enablePanelDrag(handle, key);
    actions.append(handle, arrange, expand, button("−", "icon-button", () => hidePanel(key), `Ocultar ${label}`));
    const head = node("header", "stream-head");
    head.append(title, actions);
    const meta = node("div", "stream-meta", "Preparando flujo…");
    const list = node("div", "stream-list");
    list.setAttribute("role", "list");
    const load = button("Cargar más historial", "text-button", () => {
      ui.limit = Math.min(200, ui.limit + 45);
      refresh(true);
    });
    panel.append(head, meta, list, load);
    streams.set(key, { panel, meta, list, expand, load, arrange, signature: null });
  }
  updateLayout();
}

function richText(container, fragments) {
  for (const [text, match] of fragments) {
    if (styles.has(match)) {
      const mark = node("mark", "", text);
      mark.dataset.match = match;
      container.append(mark);
    } else {
      container.append(document.createTextNode(text));
    }
  }
}

function toneBadge(tone, full = false) {
  const value = Object.hasOwn(tones, tone) ? tone : "neutral";
  const [symbol, label] = tones[value];
  const badge = node("span", "tone", full ? `${symbol} ${label}` : symbol);
  badge.dataset.tone = value;
  badge.title = `Tono estimado: ${label.toLowerCase()}`;
  badge.setAttribute("aria-label", badge.title);
  if (!full) badge.setAttribute("role", "img");
  return badge;
}

function showDetails(item) {
  $("details-type").textContent = names[item.kind] ?? "Resultado";
  $("details-title").textContent = item.source;
  $("details-meta").textContent = [detailTime.format(new Date(item.date)), item.author].filter(Boolean).join(" · ");
  $("details-tone").replaceChildren(node("span", "", "Tono estimado "), toneBadge(item.tone, true));
  $("details-text").replaceChildren();
  richText($("details-text"), item.fragments);
  $("details-matches").replaceChildren(...item.matches.map(([raw, canonical, method]) =>
    node("li", "", `${method === "review" ? "Para revisar · " : ""}${raw}${canonical ? ` → ${canonical}` : ""}`)
  ));
  $("details-link").hidden = !item.url;
  if (item.url) $("details-link").href = item.url;
  else $("details-link").removeAttribute("href");
  $("details").showModal();
}

function replaceRecords(container, rows, makeRow, emptyText) {
  const first = Array.from(container.children).find((row) => row.offsetTop + row.offsetHeight > container.scrollTop);
  const anchor = first && container.scrollTop > 0 ? first.dataset.record : null;
  const offset = anchor ? container.scrollTop - first.offsetTop : 0;
  const selected = container.contains(document.activeElement) ? document.activeElement.dataset.record : null;
  const children = rows.map((row) => {
    const control = makeRow(row);
    control.dataset.record = String(row.id);
    return control;
  });
  container.replaceChildren(...(children.length ? children : [node("div", "empty", emptyText)]));
  if (anchor) {
    const row = children.find((item) => item.dataset.record === anchor);
    if (row) container.scrollTop = row.offsetTop + offset;
  }
  if (selected) children.find((item) => item.dataset.record === selected)?.focus({ preventScroll: true });
}

function renderPanel(key, rows, statuses) {
  const stream = streams.get(key);
  const applicable = statuses.filter((item) => item.categories.includes(key));
  const next = applicable.filter((item) => item.next).map((item) => item.next).sort()[0];
  const live = applicable.some((item) => item.availability === "LIVE");
  const watching = applicable.some((item) => item.state === "RUNNING");
  const issue = applicable.find((item) => ["ERROR", "RATE_LIMITED"].includes(item.state));
  const status = live ? "En directo" : watching ? "Consultando" : issue ? (jobStates[issue.state] ?? "Revisar conexión") :
    applicable.some((item) => item.availability === "WAITING") ? "En espera de un directo" : next && ui.running ? `Próxima ${time.format(new Date(next))}` :
    applicable.length ? (ui.running ? "Disponible" : "Seguimiento pausado") : "Sin fuentes configuradas";
  stream.meta.textContent = `● ${status} · ${rows.length} resultados${ui.practice ? " · práctica" : ""}`;
  stream.meta.title = applicable.map((item) => `${item.name} · ${item.detail || jobStates[item.state]}`).join("\n");
  stream.load.hidden = rows.length < ui.limit || ui.limit >= 200;
  const signature = JSON.stringify(rows);
  if (signature === stream.signature) return;
  stream.signature = signature;
  replaceRecords(stream.list, rows, (item) => {
    const control = button("", "record", () => showDetails(item));
    control.append(node("span", "record-time", time.format(new Date(item.date))), toneBadge(item.tone));
    const text = node("span", "record-body");
    text.append(node("span", "author", item.author || item.source));
    richText(text, item.fragments);
    control.append(text);
    return control;
  }, applicable.length ? "Todavía no hay resultados para este filtro." : "Agregá una fuente para empezar a seguir este flujo.");
}

let alertSignature;
function renderAlerts(rows) {
  $("alert-count").textContent = rows.length;
  const signature = JSON.stringify([ui.alertMode, rows]);
  if (signature === alertSignature) return;
  alertSignature = signature;
  replaceRecords($("alert-rows"), rows, (item) => {
    const level = ui.alertMode === "review" ? "review" : item.severity;
    const control = button("", "alert-record", () => showDetails(item));
    const label = node("span", "severity", severity[level] || "Info");
    label.dataset.level = level;
    const terms = [...new Set(item.matches.filter((match) => (match[2] === "review") === (ui.alertMode === "review")).map((match) => match[0]))];
    const summary = node("span", "alert-summary");
    summary.append(node("span", "alert-source", item.source));
    for (const term of terms) {
      const mark = node("mark", "alert-term", term);
      mark.dataset.match = level;
      summary.append(mark);
    }
    control.append(label, node("span", "record-time", time.format(new Date(item.captured))), toneBadge(item.tone), summary);
    return control;
  }, ui.alertMode === "review" ? "Sin coincidencias aproximadas." : "Sin alertas confirmadas para este filtro.");
}

let sourcesSignature;
function renderSources() {
  const signature = JSON.stringify([ui.jobs, ui.statuses, ui.running]);
  if (signature === sourcesSignature) return;
  sourcesSignature = signature;
  const states = new Map(ui.statuses.map((item) => [item.id, item]));
  const rows = ui.jobs.map((job) => {
    const row = node("tr");
    const title = node("td", "", job.name);
    title.append(node("div", "metadata", job.type_label ?? "Fuente simulada"));
    const info = states.get(job.id);
    const status = node("td", "", !job.enabled ? "Desactivada" : !ui.running ? "Seguimiento pausado" : (jobStates[info?.state] ?? "Disponible"));
    if (info?.detail) status.append(node("div", "metadata", info.detail));
    const actions = node("td");
    if (job.type_label) actions.append(button("Editar", "button subtle", () => showSource(job)));
    if (job.type_label) {
      actions.append(button("Quitar", "button subtle", () => {
        if (window.confirm(`¿Quitar ${job.name} del seguimiento? El historial local se conserva.`)) {
          runAction("remove", { value: job.id }, "Fuente eliminada.");
        }
      }));
    }
    if (!ui.running && job.enabled && job.polling) actions.append(button("Consultar", "button subtle", () => runAction("probe", { value: job.id })));
    row.append(title, node("td", "", job.categories.includes("live") && job.minutes < 2 ? "En vivo" : `${job.minutes.toLocaleString("es-UY", { maximumFractionDigits: 2 })} min`), status, actions);
    return row;
  });
  $("source-rows").replaceChildren(...rows);
}

async function refresh(force = false) {
  if (!ui.token || ui.closed) return;
  const number = ++ui.sequence;
  const params = new URLSearchParams({ panels: activePanels().join(","), q: $("filter").value,
    mode: $("match-mode").value, alerts: ui.alertMode, limit: ui.limit });
  try {
    const data = await api(`board?${params}`);
    if (number !== ui.sequence || ui.closed) return;
    ui.running = data.running;
    ui.statuses = data.statuses;
    $("monitor").disabled = false;
    $("monitor").textContent = data.running ? "Pausar seguimiento" : "Iniciar seguimiento";
    $("run-status").classList.toggle("is-live", data.running);
    $("run-status").lastElementChild.textContent = data.running ? "EN CURSO" : "EN PAUSA";
    $("key-status").textContent = data.key_loaded ? "Clave cargada para esta sesión." : "Clave pendiente para consultar YouTube.";
    $("web-key-status").textContent = data.web_key_loaded ? "Clave cargada para esta sesión." : "Búsqueda web abierta sin habilitar.";
    if (!ui.frozen || force) {
      for (const [key, rows] of Object.entries(data.panels)) renderPanel(key, rows, data.statuses);
      renderAlerts(data.alerts);
    }
    if (ui.page === "sources") renderSources();
    if (Date.now() > ui.noticeUntil) $("status").textContent = ui.frozen ? "Vista congelada · el motor conserva su estado" :
      (ui.practice ? "Modo de práctica · datos simulados" : "Conexión local · base de datos disponible");
    $("updated").textContent = `Actualizado ${time.format(new Date())}`;
  } catch (error) {
    if (number !== ui.sequence || ui.closed) return;
    $("run-status").classList.remove("is-live");
    $("run-status").lastElementChild.textContent = "SIN CONEXIÓN";
    $("monitor").disabled = true;
    notice(`Conexión interrumpida. ${error.message}`, true);
  }
}

async function tick() {
  await refresh();
  if (!ui.closed) ui.timer = setTimeout(tick, 2000);
}

async function runAction(name, payload, success) {
  try {
    const data = await api(name, payload);
    if (data.jobs) applyConfig(data, name === "topic");
    if (success || data.detail) notice(success || data.detail);
    await refresh(true);
    return data;
  } catch (error) {
    notice(error.message, true);
    return null;
  }
}

function sourceFields() {
  const type = $("source-type").value;
  const feed = type.includes("RSS");
  const comments = type.startsWith("Comentarios de un sitio");
  $("address-label").textContent = feed ? (comments ? "Enlace del feed o de la nota" : "Enlace HTTPS al RSS/Atom") :
    (type.startsWith("Canal") ? "Enlace o @nombre del canal de YouTube" : "Enlace del video o directo");
  $("discover").hidden = !comments;
  $("feed-token").hidden = !feed;
  const minutes = $("source-minutes");
  minutes.min = type.includes("directos automáticos") ? "30" : (type.includes("videos automáticos") || type.includes("Comentarios de un video") ? "5" : "1");
  if (Number(minutes.value) < Number(minutes.min)) minutes.value = minutes.min;
}

function showSource(job = {}) {
  if (!ui.types.length) return;
  $("source-form").reset();
  $("source-title").textContent = job.id ? "Editar fuente" : "Agregar fuente";
  $("source-id").value = job.id ?? "";
  $("source-name").value = job.name ?? "";
  $("source-address").value = job.address ?? "";
  $("source-type").replaceChildren(...ui.types.map((name) => node("option", "", name)));
  $("source-type").value = job.type_label ?? ui.types[0];
  $("source-minutes").value = Math.max(1, Math.ceil(job.minutes ?? 15));
  $("source-enabled").checked = job.enabled ?? true;
  $("source-relevant").checked = job.relevant_only ?? false;
  $("source-feedback").textContent = "";
  $("source-token").placeholder = job.protected ? "Vacío conserva el acceso de la fuente" : "Solo si el medio lo requiere";
  sourceFields();
  $("source-dialog").showModal();
}

function choosePage(page) {
  ui.page = page;
  for (const tab of document.querySelectorAll("[data-page]")) {
    const selected = tab.dataset.page === page;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    $(`${tab.dataset.page}-page`).hidden = !selected;
  }
  if (page === "sources") renderSources();
}

async function setProjection(enabled) {
  if (enabled) choosePage("board");
  ui.projection = enabled;
  document.body.classList.toggle("is-projecting", enabled);
  $("projection-bar").hidden = !enabled;
  (enabled ? $("exit-projection") : $("enter-projection")).focus();
  if (enabled && !document.fullscreenElement) {
    try { await document.documentElement.requestFullscreen?.(); } catch { /* Embedded browsers still get the expanded layout. */ }
  } else if (!enabled && document.fullscreenElement) {
    await document.exitFullscreen().catch(() => {});
  }
}

$("enter-projection").addEventListener("click", () => setProjection(true));
$("exit-projection").addEventListener("click", () => setProjection(false));
$("projection-restore").addEventListener("click", () => {
  if (ui.focus) focusPanel(ui.focus);
});
document.addEventListener("fullscreenchange", () => {
  if (ui.projection && !document.fullscreenElement) setProjection(false);
});
document.addEventListener("keydown", (event) => {
  if (event.defaultPrevented || document.querySelector("dialog[open]")) return;
  if (event.key === "Escape" && ui.projection) setProjection(false);
  if (event.key.toLowerCase() === "p" && !event.ctrlKey && !event.altKey && !event.metaKey &&
      !event.target.closest("input,textarea,select,[contenteditable]")) {
    event.preventDefault();
    setProjection(!ui.projection);
  }
});
$("columns").addEventListener("change", () => {
  ui.columns = Number($("columns").value);
  updateLayout();
});
$("reset-layout").addEventListener("click", () => {
  ui.columns = 3;
  $("columns").value = "3";
  ui.widths = {};
  ui.visible = [...ui.defaults];
  ui.order = [...new Set([...ui.defaults, ...Object.keys(labels)])];
  ui.focus = null;
  updateLayout();
  refresh(true);
});

document.querySelectorAll("[data-page]").forEach((tab) => {
  tab.addEventListener("click", () => choosePage(tab.dataset.page));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const tabs = Array.from(document.querySelectorAll("[data-page]"));
    const index = tabs.indexOf(tab);
    const target = tabs[event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 :
      (index + tabs.length + (event.key === "ArrowRight" ? 1 : -1)) % tabs.length];
    choosePage(target.dataset.page);
    target.focus();
  });
});
document.querySelectorAll("[data-close]").forEach((control) => control.addEventListener("click", () => $(control.dataset.close).close()));
$("monitor").addEventListener("click", () => runAction("monitor", { enabled: !ui.running }));
$("theme").addEventListener("click", async () => {
  const previous = ui.theme;
  setTheme(previous === "dark" ? "light" : "dark");
  try { await api("theme", { value: ui.theme }); }
  catch (error) { setTheme(previous); notice(error.message, true); }
});
$("restore-layout").addEventListener("click", () => {
  if (ui.focus) focusPanel(ui.focus);
});
$("freeze").addEventListener("click", () => {
  ui.frozen = !ui.frozen;
  $("freeze").setAttribute("aria-pressed", String(ui.frozen));
  $("freeze").textContent = ui.frozen ? "Actualizar vista" : "Congelar vista";
  if (!ui.frozen) refresh(true);
});
let searchTimer;
$("filter").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => refresh(true), 230);
});
$("match-mode").addEventListener("change", () => refresh(true));
$("alert-review").addEventListener("click", () => {
  ui.alertMode = ui.alertMode === "review" ? "confirmed" : "review";
  $("alert-review").setAttribute("aria-pressed", String(ui.alertMode === "review"));
  $("alerts-title").textContent = ui.alertMode === "review" ? "Para revisar" : "Alertas";
  $("alert-review").textContent = ui.alertMode === "review" ? "Alertas confirmadas" : "Para revisar";
  refresh(true);
});
function toggleAlerts() {
  $("alert-rows").hidden = !ui.alertsVisible;
  $("hide-alerts").textContent = ui.alertsVisible ? "Ocultar" : "Mostrar";
  $("hide-alerts").setAttribute("aria-expanded", String(ui.alertsVisible));
}
$("hide-alerts").addEventListener("click", () => {
  ui.alertsVisible = !ui.alertsVisible;
  remember("alerts", ui.alertsVisible);
  toggleAlerts();
});
$("add-source").addEventListener("click", () => showSource());
$("source-type").addEventListener("change", sourceFields);
$("discover").addEventListener("click", async () => {
  $("source-feedback").textContent = "Buscando un feed anunciado por la nota…";
  try {
    const data = await api("discover", { value: $("source-address").value });
    if (data.url) $("source-address").value = data.url;
    $("source-feedback").textContent = data.url ? "Feed encontrado. Guardá la fuente para consultarlo." : "La nota no anuncia un feed público de comentarios.";
  } catch (error) { $("source-feedback").textContent = error.message; }
});
$("source-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.submitter;
  if (submit) submit.disabled = true;
  $("source-feedback").textContent = "Guardando…";
  try {
    const data = await api("source", {
      id: $("source-id").value || null, label: $("source-name").value, type_label: $("source-type").value,
      address: $("source-address").value, minutes: Number($("source-minutes").value), enabled: $("source-enabled").checked,
      relevant_only: $("source-relevant").checked, token: $("source-token").value,
    });
    applyConfig(data);
    $("source-token").value = "";
    $("source-dialog").close();
    notice("Fuente guardada.");
    refresh(true);
  } catch (error) { $("source-feedback").textContent = error.message; }
  finally { if (submit) submit.disabled = false; }
});
$("source-dialog").addEventListener("close", () => { $("source-token").value = ""; });
$("topic-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runAction("topic", { lines: $("topic").value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean) }, "Lista blanca actualizada.");
});
$("key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = $("youtube-key").value;
  $("youtube-key").value = "";
  await runAction("key", { value }, "Clave cargada para esta sesión.");
});
$("web-key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = $("web-key").value;
  $("web-key").value = "";
  await runAction("web-key", { value }, "Búsqueda web habilitada para esta sesión.");
});

const discoveryGroups = {
  live: "Directos en YouTube", video: "Videos de YouTube", article: "Noticias en feeds",
  feed: "Comentarios, foros y reseñas en feeds", web: "Sitios de la web abierta",
};

function candidateCard(item) {
  const card = node("article", "discovery-result");
  card.append(node("h4", "", item.title || "Resultado"), node("p", "metadata", item.source));
  if (item.excerpt) card.append(node("p", "", item.excerpt));
  if (!item.url) return card;
  const actions = node("div", "discovery-actions");
  const link = node("a", "button subtle", "Abrir ↗");
  link.href = item.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  actions.append(link);
  const source = { name: (item.title || item.source).slice(0, 80), address: item.url };
  if (item.kind === "live" || item.kind === "video") {
    actions.append(button(item.kind === "live" ? "Seguir chat" : "Seguir comentarios", "button subtle", () => {
      showSource({ ...source, type_label: item.kind === "live" ? "Chat de un directo de YouTube" : "Comentarios de un video de YouTube" });
    }));
  } else if (["article", "web"].includes(item.kind) && item.url.startsWith("https://")) {
    const feedback = node("p", "metadata");
    feedback.setAttribute("role", "status");
    const discover = button("Buscar comentarios", "button subtle", async () => {
      discover.disabled = true;
      feedback.textContent = "Comprobando si el sitio publica un feed de comentarios…";
      try {
        const data = await api("discover", { value: item.url });
        if (data.url) {
          feedback.textContent = "Feed de comentarios encontrado.";
          showSource({ ...source, address: data.url, type_label: "Comentarios de un sitio (RSS)" });
        } else feedback.textContent = "El sitio no anuncia un feed público de comentarios.";
      } catch (error) { feedback.textContent = error.message; }
      finally { discover.disabled = false; }
    });
    actions.append(discover);
    card.append(actions, feedback);
    return card;
  }
  card.append(actions);
  return card;
}

function renderDiscovery(data) {
  const results = $("topic-search-results");
  const groups = [];
  for (const [kind, label] of Object.entries(discoveryGroups)) {
    const candidates = data.candidates.filter((item) => item.kind === kind);
    if (!candidates.length) continue;
    const section = node("section", "discovery-group");
    section.append(node("h3", "", `${label} · ${candidates.length}`), ...candidates.map(candidateCard));
    groups.push(section);
  }
  if (data.history.length) {
    const section = node("section", "discovery-group");
    section.append(node("h3", "", `Historial de EchoScope · ${data.history.length}`));
    for (const item of data.history) {
      const control = button("", "discovery-result discovery-history", () => showDetails(item));
      const text = node("span", "");
      const excerpt = item.fragments.map(([part]) => part).join("").slice(0, 100);
      text.textContent = `${item.source} · ${excerpt || "Abrir mensaje"}`;
      control.append(toneBadge(item.tone), text);
      section.append(control);
    }
    groups.unshift(section);
  }
  if (data.notes.length) {
    const notes = node("details", "discovery-notes");
    notes.append(node("summary", "", "Cobertura y estado de la búsqueda"));
    const list = node("ul", "");
    list.append(...data.notes.map((note) => node("li", "", note)));
    notes.append(list);
    notes.open = !groups.length;
    groups.push(notes);
  }
  results.replaceChildren(...groups);
  const total = data.candidates.length + data.history.length;
  $("topic-search-status").textContent = total ? `${total} resultados en las fuentes consultadas.` : "Sin resultados en las fuentes consultadas.";
}

$("open-topic-search").addEventListener("click", () => $("topic-search-dialog").showModal());
$("topic-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = $("topic-search-form").querySelector("button[type=submit]");
  if (submit.disabled) return;
  submit.disabled = true;
  $("topic-search-status").textContent = "Buscando en las fuentes disponibles…";
  $("topic-search-results").replaceChildren();
  try { renderDiscovery(await api("topic-search", { value: $("topic-search").value })); }
  catch (error) { $("topic-search-status").textContent = error.message; }
  finally { submit.disabled = false; }
});
$("youtube-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("video-results").replaceChildren(node("p", "", "Buscando…"));
  try {
    const data = await api("search", { value: $("youtube-search").value });
    const buttons = data.videos.map((video) => button(`${video.title} · ${video.channel}`, "text-button", () => showSource({
      name: video.title.slice(0, 80), address: `https://www.youtube.com/watch?v=${video.id}`, type_label: "Comentarios de un video de YouTube",
    })));
    $("video-results").replaceChildren(...(buttons.length ? buttons : [node("p", "", "No se encontraron videos.")]));
  } catch (error) { $("video-results").replaceChildren(node("p", "", error.message)); }
});
$("shutdown").addEventListener("click", async () => {
  if (!window.confirm("¿Cerrar EchoScope y detener el seguimiento?")) return;
  try {
    await api("shutdown", {});
    ui.closed = true;
    clearTimeout(ui.timer);
    $("monitor").disabled = true;
    $("run-status").classList.remove("is-live");
    $("run-status").lastElementChild.textContent = "CERRADO";
    $("status").textContent = "EchoScope se cerró. Podés cerrar esta pestaña.";
  } catch (error) { notice(error.message, true); }
});

(async () => {
  choosePage("board");
  try {
    const data = await api("bootstrap");
    ui.token = data.token;
    ui.practice = data.practice;
    const defaults = ui.practice ? ["live", "press", "reviews"] : ["news", "youtube", "live"];
    ui.defaults = defaults;
    const layout = preference(`panels.${ui.practice}`, defaults);
    ui.visible = Array.isArray(layout) ? [...new Set(layout.filter((key) => Object.hasOwn(labels, key)))] : defaults;
    const options = preference(`layout.${ui.practice}`, {});
    ui.columns = [1, 2, 3].includes(options.columns) ? options.columns : 3;
    $("columns").value = String(ui.columns);
    const order = Array.isArray(options.order) ? options.order.filter((key) => Object.hasOwn(labels, key)) : ui.visible;
    ui.order = [...new Set([...order, ...Object.keys(labels)])];
    for (const key of Object.keys(labels)) {
      if ([1, 2, 3].includes(options.widths?.[key])) ui.widths[key] = options.widths[key];
    }
    ui.alertsVisible = preference("alerts", true) !== false;
    setTheme(data.theme);
    $("edition").textContent = `${data.practice ? "PRÁCTICA" : "LOCAL"} · ${data.version}`;
    applyConfig(data, true);
    buildLayout();
    $("open-topic-search").disabled = false;
    toggleAlerts();
    await tick();
  } catch (error) {
    notice(`No se pudo abrir la mesa. ${error.message}`, true);
  }
})();
