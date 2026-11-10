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
const jobStates = {
  DISABLED: "Desactivada", IDLE: "Finalizada", SCHEDULED: "Programada", RUNNING: "Consultando",
  PAUSED: "En pausa", RETRYING: "Reintentando", RATE_LIMITED: "Cuota alcanzada", ERROR: "Revisar conexión",
};
const styles = new Set(Object.keys(severity));
const ui = {
  token: "", practice: false, jobs: [], types: [], visible: [], focus: null, theme: "dark",
  alertsVisible: true, alertMode: "confirmed", frozen: false, running: false, statuses: [],
  limit: 45, page: "board", sequence: 0, noticeUntil: 0, timer: null, closed: false,
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
  $("panels").dataset.count = String(active.length);
  $("restore-layout").hidden = !ui.focus;
  for (const key of Object.keys(labels)) {
    const tab = $(`panel-toggle-${key}`);
    tab.setAttribute("aria-pressed", String(active.includes(key)));
    tab.title = active.includes(key) ? `Ocultar ${labels[key]}` : `Mostrar ${labels[key]}`;
    const stream = streams.get(key);
    stream.panel.hidden = !active.includes(key);
    stream.expand.textContent = ui.focus === key ? "↙" : "⤢";
    const label = ui.focus === key ? "Restaurar vista de paneles" : `Maximizar ${labels[key]}`;
    stream.expand.setAttribute("aria-label", label);
    stream.expand.title = label;
  }
  $("empty-grid").hidden = active.length > 0;
  if (active.length) $("panels").append(...active.map((key) => streams.get(key).panel));
  remember(`panels.${ui.practice}`, ui.visible);
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
  if (!ui.visible.includes(key)) ui.visible.push(key);
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
    const expand = button("⤢", "icon-button", () => focusPanel(key), `Maximizar ${label}`);
    const actions = node("div", "panel-actions");
    actions.append(expand, button("−", "icon-button", () => hidePanel(key), `Ocultar ${label}`));
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
    $("panels").append(panel);
    streams.set(key, { panel, meta, list, expand, load, signature: null });
  }
  const empty = node("div", "empty empty-grid", "Elegí un flujo en la barra de paneles para volver a mostrarlo.");
  empty.id = "empty-grid";
  $("panels").append(empty);
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

function showDetails(item) {
  $("details-type").textContent = names[item.kind] ?? "Resultado";
  $("details-title").textContent = item.source;
  $("details-meta").textContent = [detailTime.format(new Date(item.date)), item.author].filter(Boolean).join(" · ");
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
    control.append(node("span", "record-time", time.format(new Date(item.date))));
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
    control.append(label, node("span", "record-time", time.format(new Date(item.captured))), node("span", "", `${item.source} · ${terms.join(" · ")}`));
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
    const layout = preference(`panels.${ui.practice}`, defaults);
    ui.visible = Array.isArray(layout) ? [...new Set(layout.filter((key) => Object.hasOwn(labels, key)))] : defaults;
    ui.alertsVisible = preference("alerts", true) !== false;
    setTheme(data.theme);
    $("edition").textContent = `${data.practice ? "PRÁCTICA" : "LOCAL"} · ${data.version}`;
    applyConfig(data, true);
    buildLayout();
    toggleAlerts();
    await tick();
  } catch (error) {
    notice(`No se pudo abrir la mesa. ${error.message}`, true);
  }
})();
