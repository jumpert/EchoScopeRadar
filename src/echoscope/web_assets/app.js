"use strict";

const $ = (id) => document.getElementById(id);
const labels = {
  live: "Chat en vivo", press: "Comentarios de prensa", reviews: "Reseñas",
  news: "Noticias", youtube: "Videos de YouTube", forum: "Foros",
  social: "Redes sociales",
};
const helpText = {
  board: ["Cómo usar la mesa", "Elegí qué pestañas ver y buscá dentro de lo ya recibido. «Alertas» muestra las coincidencias confirmadas. Congelar vista mantiene lo que ves mientras la captura sigue. Para buscar publicaciones nuevas, elegí Buscar por tema."],
  news: ["Noticias", "Titulares y extractos de los medios que seguís. Abrí el enlace de origen para leer la nota completa."],
  press: ["Comentarios de prensa", "Primero se seleccionan las notas cuyo título coincide con la lista blanca. Después se lee la nota y se analizan por separado los comentarios públicos accesibles mediante RSS, WordPress, Disqus o HTML reconocible. Usá el filtro Alertas para priorizar los comentarios con coincidencias. Los comentarios cargados por sistemas no compatibles pueden quedar fuera."],
  youtube: ["Videos de YouTube", "Agregá tu clave en Claves API y verificá el acceso en Tema y acceso. Los canales automáticos consultan videos recientes relacionados con tus términos. Para leer un video concreto, agregá su enlace en Fuentes."],
  live: ["Chat en vivo", "Los canales automáticos esperan un directo relacionado con tus términos. Para probar uno que está al aire, agregá el enlace del directo en Fuentes. YouTube debe tener el chat habilitado y accesible."],
  reviews: ["Cómo recibir reseñas", ""],
  forum: ["Foros", "Agregá el RSS o Atom público del foro para recibir sus publicaciones. Abrí el enlace de origen para ver la conversación completa."],
  social: ["Redes sociales", "Podés seguir respuestas de un hilo público de Bluesky. Las publicaciones de otras redes encontradas por búsqueda abren en su sitio de origen."],
  alerts: ["Cómo leer las alertas", "Una alerta confirma que apareció un término de tu lista. «Para revisar» reúne aproximaciones. Abrí un resultado para ver el contexto o descargá un PDF por fechas."],
  sources: ["Configurar fuentes", "Agregá un enlace, elegí qué querés leer y guardá la fuente. Con el seguimiento activo, «Consultar ahora» solicita un nuevo ciclo respetando el intervalo mínimo. El estado indica qué ocurrió."],
  access: ["Configurar tema y acceso", "Escribí un término o frase por línea. En Claves API agregá tu clave de YouTube Data API y elegí cuál usar. Volvé aquí para verificar el acceso."],
};
const names = {
  COMMENT: "Comentario", REVIEW: "Reseña", LIVE_CHAT: "Chat en vivo", FEED_ENTRY: "Publicación",
  NEWS_ARTICLE: "Noticia", YOUTUBE_VIDEO: "Video", YOUTUBE_LIVE: "Directo", FORUM_POST: "Foro", PRESS_COMMENT: "Comentario de prensa",
  SOCIAL_COMMENT: "Respuesta en red social",
};
const severity = { info: "Info", important: "Importante", critical: "Crítica", review: "Para revisar" };
const reviewLabels = { open: "Sin verificar", verified: "Verificada", threat: "Amenaza", dismissed: "Descartada" };
const tones = {
  positive: ["＋", "Positivo"], negative: ["−", "Negativo"], mixed: ["±", "Mixto"], neutral: ["·", "Neutro"],
};
const jobStates = {
  DISABLED: "Desactivada", IDLE: "Finalizada", SCHEDULED: "Programada", RUNNING: "Consultando",
  PAUSED: "En pausa", RETRYING: "Reintentando", RATE_LIMITED: "Cuota alcanzada", ERROR: "Revisar conexión",
};
const sourceDetails = {
  "CREDENCIAL AUSENTE O INVÁLIDA": "Cargá o verificá la clave de YouTube",
  "ESPERANDO DIRECTO": "Sin directos pertinentes activos",
  "DIRECTO ENCONTRADO, CHAT NO DISPONIBLE": "Directo encontrado sin chat accesible",
  "CHAT NO DISPONIBLE": "Chat no disponible en YouTube",
  "DIRECTO FINALIZADO": "El directo terminó",
  "SIN PERMISO": "El proveedor rechazó el acceso",
  "LÍMITE DE CONSUMO": "Límite de consultas del proveedor",
};
const styles = new Set(Object.keys(severity));
const ui = {
  token: "", practice: false, jobs: [], types: [], visible: [], focus: null, theme: "dark",
  alertsVisible: true, alertMode: "confirmed", frozen: false, running: false, statuses: [],
  limit: 45, page: "board", sequence: 0, noticeUntil: 0, timer: null, closed: false,
  columns: 3, widths: {}, order: [], defaults: [], projection: false, youtubeKeyLoaded: false,
  alertLimit: 20, alertRows: [], selectedAlerts: new Set(), username: null,
  sourceGroups: {}, sourceLayout: { categories: [], groups: {} }, sourceDrag: null,
  savingSources: false,
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

function showHelp(key) {
  if (key === "reviews") {
    $("reviews-guide").showModal();
    return;
  }
  const [title, body] = helpText[key];
  $("help-title").textContent = title;
  $("help-text").textContent = body;
  $("help-dialog").showModal();
}

function originLink(url, label = null, className = "origin-link") {
  const link = node("a", className, label ?? `${new URL(url).hostname.replace(/^www\./, "")} ↗`);
  link.href = url;
  link.title = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function preference(key, fallback) {
  try { return JSON.parse(localStorage.getItem(`radar.${ui.username ? `${ui.username}.` : ""}${key}`)) ?? fallback; }
  catch { return fallback; }
}

function remember(key, value) {
  try { localStorage.setItem(`radar.${ui.username ? `${ui.username}.` : ""}${key}`, JSON.stringify(value)); } catch { /* Session layout still works. */ }
}

async function api(path, payload, signal) {
  const options = { cache: "no-store", signal: signal ?? AbortSignal.timeout(18000) };
  if (payload !== undefined) {
    options.method = "POST";
    options.headers = { "Content-Type": "application/json", "X-EchoScope-Token": ui.token };
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(`/api/${path}`, options);
  if (response.status === 401 && ui.username) window.location.reload();
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || "No se pudo completar la operación.");
  return result;
}

function notice(message, failure = false) {
  ui.noticeUntil = Date.now() + (failure ? 9500 : 4500);
  $("status").textContent = message;
}

const themeNames = new Set(["light", "middle-light", "dark", "darkest"]);
function setTheme(theme) {
  ui.theme = themeNames.has(theme) ? theme : "dark";
  document.documentElement.dataset.theme = ui.theme;
  $("theme").value = ui.theme;
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
    actions.append(button("ⓘ", "icon-button help-point", () => showHelp(key), `Ayuda sobre ${label}`), handle, arrange, expand,
      button("−", "icon-button", () => hidePanel(key), `Ocultar ${label}`));
    const head = node("header", "stream-head");
    head.append(title, actions);
    const meta = node("div", "stream-meta", "Preparando flujo…");
    const coverage = node("div", "stream-coverage");
    const list = node("div", "stream-list");
    list.setAttribute("role", "list");
    const load = button("Cargar más historial", "text-button", () => {
      ui.limit = Math.min(200, ui.limit + 45);
      refresh(true);
    });
    panel.append(head, meta, coverage, list, load);
    streams.set(key, { panel, meta, coverage, list, expand, load, arrange, signature: null });
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

function appendContext(parent, item, tag = "span", preview = false) {
  if (item.fragments?.length) {
    const excerpt = node(tag, "match-context");
    richText(excerpt, item.fragments);
    parent.append(excerpt);
  } else if (preview && item.preview) parent.append(node(tag, "match-context", item.preview));
}

function appendTitle(parent, item, tag = "strong", fallback = "") {
  if (!item.title && !fallback) return;
  const title = node(tag, "publication-title");
  richText(title, item.title_fragments?.length ? item.title_fragments : [[item.title || fallback, null]]);
  parent.append(title);
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
  $("details-title").replaceChildren();
  appendTitle($("details-title"), item, "span", item.resource_title || item.source);
  $("details-meta").textContent = [item.title ? item.source : null, detailTime.format(new Date(item.date)), item.author].filter(Boolean).join(" · ");
  $("details-tone").replaceChildren(node("span", "", "Tono estimado "), toneBadge(item.tone, true));
  $("details-text").replaceChildren();
  if (item.fragments.length) appendContext($("details-text"), item);
  else $("details-text").textContent = "Sin coincidencias en el cuerpo.";
  $("details-matches").replaceChildren(...item.matches.map(([raw, canonical, method]) =>
    node("li", "", `${method === "review" ? "Para revisar · " : ""}${raw}${canonical ? ` → ${canonical}` : ""}`)
  ));
  const links = $("details-origins");
  links.replaceChildren();
  if (item.url) links.append(originLink(item.url));
  if (item.resource_url && item.resource_url !== item.url) links.append(originLink(item.resource_url, "Publicación relacionada ↗"));
  $("details-conversation").replaceChildren();
  const kind = { NEWS_ARTICLE: "article", YOUTUBE_VIDEO: "video", YOUTUBE_LIVE: "live" }[item.kind];
  if (kind && item.url?.startsWith("https://") && !ui.practice) {
    $("details-conversation").append(conversationPanel({ kind, url: item.url, title: item.title || item.source, source: item.source }).box);
  }
  $("details").showModal();
}

function replaceRecords(container, rows, makeRow, emptyText) {
  const first = Array.from(container.children).find((row) => row.offsetTop + row.offsetHeight > container.scrollTop);
  const anchor = first && container.scrollTop > 0 ? first.dataset.record : null;
  const offset = anchor ? container.scrollTop - first.offsetTop : 0;
  const active = document.activeElement;
  const selected = container.contains(active) ? active.closest("[data-record]")?.dataset.record : null;
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
  if (selected) {
    const row = children.find((item) => item.dataset.record === selected);
    const control = row?.querySelector(active.tagName === "A" ? "a" : "button") ?? row;
    control?.focus({ preventScroll: true });
  }
}

function withOrigin(control, item) {
  if (!item.url) return control;
  const row = node("div", "linked-record");
  row.append(control, originLink(item.url));
  return row;
}

function messageRow(item, group = null) {
  const control = button("", "record", () => showDetails(item));
  control.append(node("span", "record-time", time.format(new Date(item.date))), toneBadge(item.tone));
  const text = node("span", "record-body");
  if (!group || !["YOUTUBE_VIDEO", "YOUTUBE_LIVE"].includes(item.kind)) appendTitle(text, item);
  text.append(node("span", "author", item.author || item.source));
  appendContext(text, item, "span", true);
  control.append(text);
  return group && item.url === group.url ? control : withOrigin(control, item);
}

function renderVideoGroups(container, rows, empty, live) {
  const groups = new Map();
  for (const item of rows) {
    const id = JSON.stringify(item.resource_key);
    if (!groups.has(id)) groups.set(id, { id, title: "", source: item.source, resource: item.resource_id, url: item.resource_url, rows: [], seen: new Set() });
    const group = groups.get(id);
    if (item.resource_title || item.title) group.title = item.resource_title || item.title;
    const identity = JSON.stringify(item.message_key);
    if (!group.seen.has(identity)) {
      group.seen.add(identity);
      group.rows.push(item);
    }
  }
  replaceRecords(container, [...groups.values()], (group) => {
    const section = node("section", "video-group");
    const title = group.title || `${live ? "Directo" : "Video"} · ${group.resource || group.source}`;
    const heading = node("h3", "publication-title");
    heading.append(group.url ? originLink(group.url, title, "video-title-link") : document.createTextNode(title));
    section.append(heading, ...group.rows.map((item) => messageRow(item, group)));
    return section;
  }, empty);
}

function renderPanel(key, rows, statuses) {
  const stream = streams.get(key);
  const applicable = statuses.filter((item) => item.categories.includes(key));
  const configured = new Set(applicable.map((item) => item.source_id)).size;
  const enabled = new Set(applicable.filter((item) => item.enabled).map((item) => item.source_id)).size;
  const resources = new Set(rows.map((item) => JSON.stringify(item.resource_key))).size;
  stream.coverage.textContent = `Fuentes: ${enabled} de ${configured} · Recursos visibles: ${resources}`;
  stream.coverage.title = "Fuentes habilitadas sobre el total configurado. Los recursos son publicaciones, conversaciones o feeds distintos en los resultados visibles.";
  const next = applicable.filter((item) => item.next).map((item) => item.next).sort()[0];
  const live = applicable.some((item) => item.availability === "LIVE" && item.state === "RUNNING");
  const watching = applicable.some((item) => item.state === "RUNNING");
  const issue = applicable.find((item) => ["ERROR", "RATE_LIMITED"].includes(item.state));
  const waiting = applicable.find((item) => item.availability === "WAITING");
  const status = live ? "Chat conectado" : watching ? "Consultando" : issue ? (sourceDetails[issue.detail] ?? jobStates[issue.state]) :
    waiting ? (sourceDetails[waiting.detail] ?? "En espera de un directo") : next && ui.running ? `Próxima ${time.format(new Date(next))}` :
    applicable.length ? (ui.running ? "Disponible" : "Seguimiento pausado") : "Sin fuentes configuradas";
  stream.meta.textContent = `● ${status} · ${rows.length} resultados${ui.practice ? " · práctica" : ""}`;
  stream.meta.title = applicable.map((item) => `${item.name} · ${item.detail || jobStates[item.state]}`).join("\n");
  stream.load.hidden = rows.length < ui.limit || ui.limit >= 200;
  let empty = applicable.length ? "Todavía no hay resultados para este filtro." : "Agregá una fuente para empezar a seguir este flujo.";
  const needsKey = !ui.practice && ["live", "youtube"].includes(key) && !ui.youtubeKeyLoaded && applicable.length && applicable.every((item) => item.uses_session_key);
  if (needsKey) empty = "Agregá una clave en Claves API y verificá el acceso a YouTube desde Tema y acceso.";
  else if (key === "live" && waiting) empty = "Podés esperar al siguiente ciclo o agregar el enlace de un directo que esté al aire y tenga chat habilitado.";
  else if (key === "youtube" && applicable.some((item) => item.detail === "SIN RESULTADOS")) empty = "La última consulta no devolvió resultados para alguna fuente. Revisá los términos del canal o agregá un video por su enlace.";
  else if (key === "reviews" && !ui.practice) empty = applicable.length
    ? "No hay reseñas para mostrar con los filtros actuales. Podés revisar el estado de tus fuentes o consultar la guía."
    : "Todavía no hay páginas de reseñas configuradas. Empezá con el enlace de la página donde las leés.";
  const signature = JSON.stringify([empty, rows]);
  if (signature === stream.signature) return;
  stream.signature = signature;
  if (key === "youtube" || key === "live") renderVideoGroups(stream.list, rows, empty, key === "live");
  else replaceRecords(stream.list, rows, (item) => messageRow(item), empty);
  if (!rows.length && (needsKey || (key === "reviews" && !ui.practice))) {
    const action = needsKey ? button("Ir a Claves API", "button subtle", () => {
      choosePage("credentials");
      $("credential-provider").value = "youtube";
      $("credential-name").focus();
    }) : button("Cómo recibir reseñas", "button subtle", () => showHelp("reviews"));
    stream.list.firstElementChild.append(node("br", ""), action);
  }
}

let alertSignature;
function updateAlertSelection() {
  const count = ui.selectedAlerts.size;
  const all = $("alert-select-all");
  all.checked = !!ui.alertRows.length && count === ui.alertRows.length;
  all.indeterminate = count > 0 && !all.checked;
  all.disabled = !ui.alertRows.length;
  $("alert-apply").disabled = !count;
  $("alert-selected").textContent = count ? `${count} seleccionada${count === 1 ? "" : "s"}` : "";
  for (const input of $("alert-rows").querySelectorAll("input[data-review-key]")) input.checked = ui.selectedAlerts.has(input.dataset.reviewKey);
}

function renderAlerts(rows) {
  ui.alertRows = rows;
  const visible = new Set(rows.map((item) => item.review_key));
  for (const key of ui.selectedAlerts) if (!visible.has(key)) ui.selectedAlerts.delete(key);
  $("alert-more").hidden = rows.length < ui.alertLimit || ui.alertLimit >= 500;
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
    appendTitle(summary, item);
    summary.append(node("span", "alert-source", item.source));
    const review = node("span", "review-state", reviewLabels[item.review_state]);
    review.dataset.state = item.review_state;
    summary.append(review);
    for (const term of terms) {
      const mark = node("mark", "alert-term", term);
      mark.dataset.match = level;
      summary.append(mark);
    }
    control.append(label, node("span", "record-time", time.format(new Date(item.captured))), toneBadge(item.tone), summary);
    const row = node("div", "selectable-alert");
    const select = node("input", "alert-check");
    select.type = "checkbox";
    select.dataset.reviewKey = item.review_key;
    select.setAttribute("aria-label", `Seleccionar alerta de ${item.source} a las ${time.format(new Date(item.captured))}`);
    select.addEventListener("change", () => {
      if (select.checked) ui.selectedAlerts.add(item.review_key);
      else ui.selectedAlerts.delete(item.review_key);
      updateAlertSelection();
    });
    row.append(select, withOrigin(control, item));
    return row;
  }, ui.alertMode === "review" ? "Sin coincidencias aproximadas." : "Sin alertas confirmadas para este filtro.");
  updateAlertSelection();
}

let sourcesSignature;
function arrangedSources() {
  const groups = Object.fromEntries(
    [...Object.keys(ui.sourceGroups), ...ui.sourceLayout.categories.map((item) => item.id)]
      .map((id) => [id, []]),
  );
  const pending = new Set(ui.jobs.map((job) => job.id));
  for (const [key, ids] of Object.entries(ui.sourceLayout.groups)) {
    if (!groups[key]) continue;
    for (const id of ids) if (pending.delete(id)) groups[key].push(id);
  }
  for (const job of ui.jobs) {
    if (pending.has(job.id)) (groups[job.default_group] ?? groups.other)?.push(job.id);
  }
  return groups;
}

async function saveSourceLayout(groups, categories = ui.sourceLayout.categories, focus = null) {
  if (ui.savingSources) return false;
  ui.savingSources = true;
  const status = $("source-layout-status");
  try {
    ui.sourceLayout = await api("source-layout", { groups, categories });
    status.textContent = "Organización guardada.";
    return true;
  } catch (error) {
    status.textContent = error.message;
    return false;
  } finally {
    ui.savingSources = false;
    renderSources();
    if (focus) document.getElementById(focus)?.focus();
  }
}

function moveSource(id, destination, before = null, focus = null) {
  if (id === before) return;
  const groups = arrangedSources();
  for (const ids of Object.values(groups)) {
    const index = ids.indexOf(id);
    if (index >= 0) ids.splice(index, 1);
  }
  const ids = groups[destination];
  const target = ids.indexOf(before);
  ids.splice(target < 0 ? ids.length : target, 0, id);
  saveSourceLayout(groups, ui.sourceLayout.categories, focus);
}

function renderSources() {
  if (ui.sourceDrag || ui.savingSources) return;
  const signature = JSON.stringify([ui.jobs, ui.statuses, ui.running, ui.sourceLayout, ui.sourceGroups]);
  if (signature === sourcesSignature) return;
  sourcesSignature = signature;
  const states = new Map(ui.statuses.map((item) => [item.id, item]));
  const jobs = new Map(ui.jobs.map((job) => [job.id, job]));
  const groups = arrangedSources();
  const names = { ...ui.sourceGroups, ...Object.fromEntries(ui.sourceLayout.categories.map(({ id, name }) => [id, name])) };
  const sections = Object.entries(groups).map(([key, ids]) => {
    const section = node("section", "source-group");
    const heading = node("h2", "", `${names[key]} · ${ids.length}`);
    const wrap = node("div", "table-wrap");
    const table = node("table");
    table.setAttribute("aria-label", names[key]);
    const header = table.createTHead().insertRow();
    for (const label of ["Fuente", "Intervalo", "Estado", "Acciones"]) {
      const cell = node("th", "", label);
      cell.scope = "col";
      header.append(cell);
    }
    const body = table.createTBody();
    for (const [index, id] of ids.entries()) {
      const job = jobs.get(id);
      const row = node("tr");
      row.dataset.sourceId = id;
      const title = node("td", "", job.name);
      title.append(node("div", "metadata", job.type_label ?? "Fuente simulada"));
      title.append(node("div", "metadata", job.tracking === "owned" ? "Cuenta propia · propiedad declarada" : "Por tema · títulos relacionados"));
      const controls = node("div", "source-order");
      const handle = node("span", "drag-handle", "⠿");
      handle.draggable = true;
      handle.title = "Arrastrar para mover la fuente";
      handle.setAttribute("aria-hidden", "true");
      handle.addEventListener("dragstart", (event) => {
        ui.sourceDrag = id;
        event.dataTransfer.setData("text/plain", id);
        event.dataTransfer.effectAllowed = "move";
      });
      handle.addEventListener("dragend", () => {
        ui.sourceDrag = null;
        document.querySelectorAll(".source-drop").forEach((element) => element.classList.remove("source-drop"));
        renderSources();
      });
      const category = node("select");
      category.id = `source-category-${id}`;
      category.setAttribute("aria-label", `Categoría de ${job.name}`);
      for (const [group, name] of Object.entries(names)) {
        const option = node("option", "", name);
        option.value = group;
        category.append(option);
      }
      category.value = key;
      category.addEventListener("change", () => {
        const destination = category.value;
        category.value = key;
        moveSource(id, destination, null, category.id);
      });
      const up = button("↑", "button subtle", () => moveSource(id, key, ids[index - 1], up.id), `Subir ${job.name}`);
      const down = button("↓", "button subtle", () => moveSource(id, key, ids[index + 2], down.id), `Bajar ${job.name}`);
      up.id = `source-up-${id}`;
      down.id = `source-down-${id}`;
      up.disabled = index === 0;
      down.disabled = index === ids.length - 1;
      controls.append(handle, category, up, down);
      title.append(controls);
      const info = states.get(job.id);
      const status = node("td", "", !job.enabled ? "Desactivada" : !ui.running ? "Seguimiento pausado" : (jobStates[info?.state] ?? "Disponible"));
      if (info?.detail) status.append(node("div", "metadata", sourceDetails[info.detail] ?? info.detail));
      if (job.type_label?.includes("acceso pendiente")) status.append(node("div", "metadata", "Acceso pendiente de conector y permisos"));
      else status.append(node("div", "metadata", info?.last ? `Última consulta: ${detailTime.format(new Date(info.last))}` : "Acceso todavía sin comprobar"));
      if (info?.next && ui.running) status.append(node("div", "metadata", `Próxima consulta: ${time.format(new Date(info.next))}`));
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
      if (ui.running && job.enabled && !["RUNNING", "PAUSED", "RATE_LIMITED"].includes(info?.state)) actions.append(button("Consultar ahora", "button subtle", () => runAction("run-source", { value: job.id })));
      row.append(title, node("td", "", job.categories.includes("live") && job.minutes < 2 ? "En vivo" : `${job.minutes.toLocaleString("es-UY", { maximumFractionDigits: 2 })} min`), status, actions);
      body.append(row);
    }
    section.addEventListener("dragover", (event) => {
      if (!ui.sourceDrag) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      section.classList.add("source-drop");
    });
    section.addEventListener("dragleave", (event) => {
      if (!section.contains(event.relatedTarget)) section.classList.remove("source-drop");
    });
    section.addEventListener("drop", (event) => {
      if (!ui.sourceDrag) return;
      event.preventDefault();
      const id = ui.sourceDrag;
      ui.sourceDrag = null;
      section.classList.remove("source-drop");
      const target = event.target.closest("tr[data-source-id]");
      const index = target ? ids.indexOf(target.dataset.sourceId) : -1;
      const after = target && event.clientY > target.getBoundingClientRect().top + target.offsetHeight / 2;
      moveSource(id, key, index < 0 ? null : ids[index + (after ? 1 : 0)]);
    });
    wrap.append(table);
    section.append(heading, ids.length ? wrap : node("p", "metadata", "Arrastrá una fuente a esta categoría."));
    return section;
  });
  $("source-rows").replaceChildren(...sections);
}

$("source-category-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const field = $("source-category-name");
  if (!field.value.trim()) return;
  const category = { id: `custom-${crypto.randomUUID()}`, name: field.value.trim() };
  if (await saveSourceLayout(arrangedSources(), [...ui.sourceLayout.categories, category])) field.value = "";
});

async function refresh(force = false) {
  if (!ui.token || ui.closed) return;
  const number = ++ui.sequence;
  const params = new URLSearchParams({ panels: activePanels().join(","), q: $("filter").value,
    mode: $("match-mode").value, alerts: ui.alertMode, limit: ui.limit, alert_limit: ui.alertLimit,
    review: $("alert-state-filter").value, tone: $("alert-tone-filter").value });
  try {
    const data = await api(`board?${params}`);
    if (number !== ui.sequence || ui.closed) return;
    ui.running = data.running;
    ui.youtubeKeyLoaded = data.key_loaded;
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
  const pending = type.includes("acceso pendiente");
  $("source-pending-help").hidden = !pending;
  $("source-enabled").disabled = pending;
  if (pending) $("source-enabled").checked = false;
  const feed = type.includes("RSS");
  const comments = type.startsWith("Comentarios de un sitio");
  const reviews = type.startsWith("Reseñas de un sitio");
  $("address-label").textContent = pending ? "Enlace HTTPS de la página o canal" : reviews ? "Enlace de la página de reseñas" : feed ? (comments ? "Enlace del feed o de la página" : "Enlace HTTPS al RSS/Atom") :
    (type.includes("Bluesky") ? "Enlace de la publicación de Bluesky" : type.startsWith("Canal") ? "Enlace o @nombre del canal de YouTube" : "Enlace del video o directo");
  $("discover").hidden = !comments && !reviews;
  $("discover").textContent = reviews ? "Buscar reseñas en la página" : "Detectar feed";
  $("review-source-hint").hidden = !reviews;
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
  $("source-parent").value = job.resource_url ?? "";
  $("source-type").replaceChildren(...ui.types.map((name) => node("option", "", name)));
  $("source-type").value = job.type_label ?? ui.types[0];
  $("source-minutes").value = Math.max(1, Math.ceil(job.minutes ?? 15));
  $("source-enabled").checked = job.enabled ?? true;
  $("source-relevant").checked = job.relevant_only ?? false;
  $("source-tracking").value = job.tracking ?? "topic";
  $("source-resource-id").value = job.resource_id ?? "";
  $("source-comment-provider").value = job.comment_provider ?? "";
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
  if (page === "database") {
    refreshDataSources();
    if (!dataView.query && ui.token) loadData();
  }
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
for (const [selector, key] of [[".board-heading h1", "board"], ["#sources-page h1", "sources"], ["#settings-page h1", "access"], ["#alert-count", "alerts"]]) {
  const point = button("ⓘ", "icon-button help-point", () => showHelp(key), helpText[key][0]);
  document.querySelector(selector).after(point);
}
$("monitor").addEventListener("click", () => runAction("monitor", { enabled: !ui.running }));
$("theme").addEventListener("change", async () => {
  const previous = ui.theme;
  setTheme($("theme").value);
  $("theme").disabled = true;
  try { await api("theme", { value: ui.theme }); }
  catch (error) { setTheme(previous); notice(error.message, true); }
  finally { $("theme").disabled = false; }
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
for (const id of ["alert-state-filter", "alert-tone-filter"]) $(id).addEventListener("change", () => {
  ui.selectedAlerts.clear();
  ui.alertLimit = 20;
  refresh(true);
});
$("alert-select-all").addEventListener("change", (event) => {
  ui.selectedAlerts = new Set(event.target.checked ? ui.alertRows.map((item) => item.review_key) : []);
  updateAlertSelection();
});
$("alert-more").addEventListener("click", () => {
  ui.alertLimit = Math.min(500, ui.alertLimit + 50);
  refresh(true);
});
$("alert-apply").addEventListener("click", async () => {
  const keys = [...ui.selectedAlerts];
  if (!keys.length) return;
  $("alert-apply").disabled = true;
  try {
    const result = await api("alert-review", { keys, state: $("alert-state-action").value });
    ui.selectedAlerts.clear();
    notice(result.detail);
    await refresh(true);
  } catch (error) { notice(error.message, true); }
  finally { updateAlertSelection(); }
});
$("alert-review").addEventListener("click", () => {
  ui.selectedAlerts.clear();
  ui.alertMode = ui.alertMode === "review" ? "confirmed" : "review";
  $("alert-review").setAttribute("aria-pressed", String(ui.alertMode === "review"));
  $("alerts-title").textContent = ui.alertMode === "review" ? "Para revisar" : "Alertas";
  $("alert-review").textContent = ui.alertMode === "review" ? "Alertas confirmadas" : "Para revisar";
  refresh(true);
});
function toggleAlerts() {
  $("alert-content").hidden = !ui.alertsVisible;
  $("hide-alerts").textContent = ui.alertsVisible ? "Ocultar" : "Mostrar";
  $("hide-alerts").setAttribute("aria-expanded", String(ui.alertsVisible));
}
$("hide-alerts").addEventListener("click", () => {
  ui.alertsVisible = !ui.alertsVisible;
  remember("alerts", ui.alertsVisible);
  toggleAlerts();
});
$("add-source").addEventListener("click", () => showSource());
$("add-review-source").addEventListener("click", () => {
  $("reviews-guide").close();
  showSource({ type_label: "Reseñas de un sitio (RSS/Atom)" });
});
$("source-type").addEventListener("change", sourceFields);
$("source-address").addEventListener("input", () => { $("source-parent").value = ""; });
$("discover").addEventListener("click", async () => {
  const reviews = $("source-type").value.startsWith("Reseñas de un sitio");
  if (!$("source-address").reportValidity()) return;
  $("discover").disabled = true;
  $("source-feedback").textContent = reviews ? "Buscando una lista pública de reseñas…" : "Buscando un feed anunciado por la página…";
  try {
    const address = $("source-address").value.trim();
    const data = await api(reviews ? "discover-reviews" : "discover", { value: address });
    if (!$("source-dialog").open || $("source-address").value.trim() !== address) return;
    if (data.url) {
      $("source-address").value = data.url;
      if (reviews && data.url !== address) $("source-parent").value = address;
    }
    $("source-feedback").textContent = reviews
      ? (data.url ? "Encontramos una lista de reseñas. Elegí Guardar fuente para empezar a consultarla." : "No encontramos una lista pública de reseñas. Probá con otra página o pedile al sitio el enlace a su lista de reseñas (RSS o Atom).")
      : (data.url ? "Feed encontrado. Guardá la fuente para consultarlo." : "La página no anuncia un feed público de comentarios.");
  } catch (error) { $("source-feedback").textContent = error.message; }
  finally { $("discover").disabled = false; }
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
      resource_url: $("source-parent").value || null,
      tracking: $("source-tracking").value,
      resource_id: $("source-resource-id").value || null,
      comment_provider: $("source-comment-provider").value || null,
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
const youtubeCheckStatus = node("p", "feedback");
youtubeCheckStatus.setAttribute("role", "status");
const youtubeCheck = button("Verificar acceso", "button subtle", async () => {
  youtubeCheck.disabled = true;
  youtubeCheckStatus.textContent = "Verificando con YouTube…";
  try {
    const result = await api("check-youtube", {});
    youtubeCheckStatus.textContent = result.detail;
  } catch (error) { youtubeCheckStatus.textContent = error.message; }
  finally { youtubeCheck.disabled = false; }
});
$("youtube-access").append(button("Administrar claves", "button subtle", () => choosePage("credentials")), youtubeCheck, youtubeCheckStatus);

function credentialFields() {
  const select = $("credential-provider");
  const custom = select.value === "other";
  $("credential-custom").hidden = !custom;
  $("credential-provider-label").required = custom;
  $("credential-mode").textContent = select.selectedOptions[0]?.dataset.integrated === "true"
    ? "EchoScope puede usar esta clave para consultar el servicio."
    : "Solo almacenamiento: esta clave se guarda para una futura integración.";
}

function renderVault(data, nextProvider = null) {
  const select = $("credential-provider");
  const previous = nextProvider ?? select.value;
  const groups = new Map();
  for (const { id, label, group, integrated } of data.providers) {
    if (!groups.has(group)) {
      const section = node("optgroup");
      section.label = group;
      groups.set(group, section);
    }
    const option = node("option", "", label);
    option.value = id;
    option.dataset.integrated = String(integrated);
    groups.get(group).append(option);
  }
  const other = node("option", "", "Otro proveedor…");
  other.value = "other";
  select.replaceChildren(...groups.values(), other);
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  credentialFields();
  $("vault-status").textContent = data.persistent ? "Las claves se guardan cifradas en tu cuenta." : "En modo local las claves agregadas se usan durante esta sesión.";
  const providers = new Map(data.providers.map((item) => [item.id, item]));
  const available = data.providers.filter((item) => item.available).map((item) => item.label);
  if (data.searx_available) available.push("SearXNG");
  $("credential-providers").textContent = `Proveedores con acceso: ${available.join(", ") || "ninguno"}.`;
  const entries = data.entries.map((entry) => {
    const row = node("div", "credential-entry");
    const provider = providers.get(entry.provider);
    row.append(node("strong", "", entry.name), node("p", "metadata", `${provider.label} · ${provider.integrated ? (entry.active ? "En uso" : "Disponible") : "Solo almacenamiento"}`));
    if (provider.integrated && !entry.active) row.append(button("Usar", "button subtle", () => changeCredential("credential-use", { value: entry.id })));
    row.append(button("Quitar", "button subtle", () => {
      if (window.confirm(`¿Quitar la clave «${entry.name}»?`)) changeCredential("credential-remove", { value: entry.id });
    }));
    return row;
  });
  $("credential-list").replaceChildren(...(entries.length ? entries : [node("p", "", "Todavía no agregaste claves.")]));
}

async function changeCredential(action, payload) {
  try {
    const data = await api(action, payload);
    const created = payload.provider === "other" ? data.entries.at(-1)?.provider : null;
    renderVault(data, created);
    $("credential-feedback").textContent = "Claves actualizadas.";
    await refresh(true);
    return true;
  } catch (error) {
    $("credential-feedback").textContent = error.message;
    return false;
  }
}

$("credential-provider").addEventListener("change", credentialFields);
$("credential-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  event.submitter.disabled = true;
  const value = $("credential-value").value;
  $("credential-value").value = "";
  const provider = $("credential-provider").value;
  if (await changeCredential("credential-add", {
    provider, name: $("credential-name").value, value,
    provider_label: provider === "other" ? $("credential-provider-label").value : null,
  })) {
    $("credential-name").value = "";
    $("credential-provider-label").value = "";
  }
  event.submitter.disabled = false;
});

const discoveryGroups = {
  live: "Directos en YouTube", video: "Videos de YouTube", article: "Noticias en feeds",
  feed: "Comentarios, foros y reseñas en feeds", web: "Sitios uruguayos en la web abierta",
  social: "Publicaciones públicas de redes sociales",
};

function conversationPanel(item) {
  const box = node("details", "conversation");
  const label = item.kind === "live" ? "Chat en vivo" : "Comentarios y reseñas";
  const summary = node("summary", "", label);
  const feedback = node("p", "metadata", "Abrí esta sección para consultar la conversación.");
  feedback.setAttribute("role", "status");
  const list = node("div", "conversation-messages");
  const actions = node("div", "discovery-actions");
  let loading = false;
  let loaded = false;
  const load = async (force = false) => {
    if (loading || (loaded && !force)) return;
    loading = true;
    feedback.textContent = "Consultando la conversación…";
    try {
      const data = await api("conversation", { kind: item.kind, url: item.url });
      const count = data.messages.length;
      summary.textContent = `${label} · ${count ? count : data.status ? "Ver estado" : "Sin mensajes"}`;
      feedback.textContent = [count ? `${count} mensajes recuperados.` : "Sin mensajes recuperados.", data.status,
        data.partial ? "Cobertura parcial. Podés seguir la fuente para recibir mensajes nuevos." : ""].filter(Boolean).join(" ");
      list.replaceChildren(...data.messages.map((message) => {
        const row = node("article", "conversation-message");
        const meta = node("div", "conversation-meta");
        meta.append(toneBadge(message.tone), node("span", "", `${names[message.kind] ?? "Mensaje"} · ${message.author || "Autor no informado"} · ${detailTime.format(new Date(message.date))}`));
        if (message.url) meta.append(originLink(message.url));
        appendTitle(row, message, "h5");
        row.append(meta);
        appendContext(row, message, "p");
        return row;
      }));
      actions.replaceChildren(...data.feeds.map(([url, kind]) => button(kind === "REVIEW" ? "Seguir reseñas" : "Seguir comentarios", "button subtle", () => showSource({
        name: (item.title || item.source).slice(0, 80), address: url,
        type_label: kind === "REVIEW" ? "Reseñas de un sitio (RSS/Atom)" : "Comentarios de un sitio (RSS)",
      }))));
      actions.append(button("Volver a consultar", "text-button", () => load(true)));
      if (count) box.open = true;
      loaded = true;
    } catch (error) {
      feedback.textContent = error.message;
      actions.replaceChildren(button("Volver a consultar", "text-button", () => load(true)));
    } finally { loading = false; }
  };
  box.append(summary, feedback, actions, list);
  box.addEventListener("toggle", () => { if (box.open) load(); });
  return { box, load };
}

function candidateCard(item, queue) {
  const card = node("article", "discovery-result");
  appendTitle(card, item, "h4", item.source || "Resultado");
  if (item.title) card.append(node("p", "metadata", item.source));
  if (item.providers?.length) card.append(node("p", "metadata", `Encontrado mediante ${item.providers.join(", ")}`));
  appendContext(card, item, "p");
  if (!item.url) return card;
  const actions = node("div", "discovery-actions");
  actions.append(originLink(item.url));
  card.append(actions);
  const source = { name: (item.title || item.source).slice(0, 80), address: item.url };
  if (item.kind === "live" || item.kind === "video") {
    actions.append(button(item.kind === "live" ? "Seguir chat" : "Seguir comentarios", "button subtle", () => {
      showSource({ ...source, type_label: item.kind === "live" ? "Chat de un directo de YouTube" : "Comentarios de un video de YouTube" });
    }));
  }
  const bluesky = item.kind === "social" && /^https:\/\/bsky\.app\/profile\/[^/]+\/post\//.test(item.url);
  if (bluesky) {
    actions.append(button("Seguir respuestas", "button subtle", () => showSource({ ...source, type_label: "Respuestas de una publicación de Bluesky" })));
  }
  if (item.kind === "social" && !bluesky) {
    card.append(node("p", "metadata", "Publicación indexada. Abrí el enlace para ver la conversación en la plataforma."));
  } else if ((bluesky || ["article", "web", "video", "live"].includes(item.kind)) && item.url.startsWith("https://")) {
    const discussion = conversationPanel(item);
    card.append(discussion.box);
    if (queue) queue.push(discussion);
    if (item.kind === "live") card.append(conversationPanel({ ...item, kind: "video" }).box);
  }
  return card;
}

function renderDiscovery(data) {
  const results = $("topic-search-results");
  const groups = [];
  const queue = [];
  for (const [kind, label] of Object.entries(discoveryGroups)) {
    const candidates = data.candidates.filter((item) => item.kind === kind);
    if (!candidates.length) continue;
    const section = node("section", "discovery-group");
    section.append(node("h3", "", `${label} · ${candidates.length}`), ...candidates.map((item, index) => candidateCard(item, index < 2 ? queue : null)));
    groups.push(section);
  }
  if (data.history.length) {
    const section = node("section", "discovery-group");
    section.append(node("h3", "", `Historial de EchoScope · ${data.history.length}`));
    for (const item of data.history) {
      const control = button("", "discovery-result discovery-history", () => showDetails(item));
      const text = node("span", "record-body");
      appendTitle(text, item);
      text.append(node("span", "author", item.source));
      appendContext(text, item);
      control.append(toneBadge(item.tone), text);
      section.append(withOrigin(control, item));
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
  const loadNext = async () => {
    while (queue.length && $("topic-search-dialog").open && queue[0].box.isConnected) await queue.shift().load();
  };
  for (let worker = 0; worker < 3; worker++) loadNext();
}

$("open-topic-search").addEventListener("click", () => $("topic-search-dialog").showModal());
$("open-report").addEventListener("click", () => {
  if (!$('report-start').value) $('report-start').value = new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10);
  if (!$('report-end').value) $('report-end').value = new Date().toISOString().slice(0, 10);
  $("report-status").textContent = "";
  $("report-dialog").showModal();
});
$("report-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.submitter;
  if (submit) submit.disabled = true;
  const start = $("report-start").value;
  const end = $("report-end").value;
  $("report-status").textContent = "Generando reporte…";
  try {
    const response = await fetch("/api/report", {
      method: "POST", headers: { "Content-Type": "application/json", "X-EchoScope-Token": ui.token },
      body: JSON.stringify({ start, end, layout: $("report-layout").value }), signal: AbortSignal.timeout(90000),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || "No se pudo generar el PDF.");
    }
    const address = URL.createObjectURL(await response.blob());
    const link = node("a", "");
    link.href = address;
    link.download = `EchoScope-alertas-${start}-${end}.pdf`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(address), 10000);
    $("report-status").textContent = "PDF generado. Revisá las descargas del navegador.";
  } catch (error) { $("report-status").textContent = error.message; }
  finally { if (submit) submit.disabled = false; }
});
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
$("logout").addEventListener("click", async () => {
  try { await api("logout", {}); window.location.reload(); }
  catch (error) { notice(error.message, true); }
});

const dataView = { query: null, pages: [null], index: 0, next: null, busy: false };
function refreshDataSources() {
  const selected = $("db-source").value;
  $("db-source").replaceChildren(new Option("Todas las fuentes", ""));
  const sources = new Map(ui.jobs.map((job) => [job.source_id || job.id, job.name]));
  for (const [id, name] of sources) $("db-source").add(new Option(name, id));
  $("db-source").value = selected;
  if (!$("db-kind").dataset.ready) {
    for (const [key, label] of Object.entries(names)) $("db-kind").add(new Option(label, key));
    $("db-kind").dataset.ready = "true";
  }
}
function dataFilters() {
  return {
    text: $("db-text").value.trim(), source: $("db-source").value || null,
    kind: $("db-kind").value || null, severity: $("db-severity").value || null,
    start: $("db-start").value || null, end: $("db-end").value || null,
    review: $("db-review").value, tone: $("db-tone").value,
    matches_only: $("db-matches").checked,
  };
}
function dataButtons() {
  for (const control of $("database-form").querySelectorAll("input,select,button")) control.disabled = dataView.busy;
  $("db-export").disabled = dataView.busy || !dataView.query;
  $("db-prev").disabled = dataView.busy || !dataView.query || dataView.index === 0;
  $("db-next").disabled = dataView.busy || !dataView.query || !dataView.next;
}
async function loadData(index = 0, fresh = true) {
  if (dataView.busy) return;
  dataView.busy = true;
  dataButtons();
  $("db-status").textContent = "Consultando registros almacenados…";
  try {
    const query = fresh ? dataFilters() : { ...dataView.query };
    const data = await api("data-query", { ...query, before: fresh ? null : dataView.pages[index] });
    dataView.query = { ...query, snapshot: data.snapshot };
    if (fresh) dataView.pages = [null];
    dataView.index = index;
    dataView.next = data.next_before;
    $("db-page").textContent = `Página ${index + 1}`;
    $("db-rows").replaceChildren();
    for (const row of data.rows) {
      const tr = node("tr");
      const captured = node("td", "", row.captured.replace("T", " ").slice(0, 19));
      captured.append(node("small", "metadata", `Registro #${row.id}`));
      const source = node("td");
      source.append(node("strong", "", row.title), node("small", "metadata", `${row.source} · ${names[row.kind] || row.kind}`));
      const content = node("td");
      const details = node("details");
      details.append(node("summary", "", "Ver contenido completo"), node("p", "db-full-text", row.text));
      content.append(node("strong", "", row.author), node("p", "db-excerpt", row.text.slice(0, 220) + (row.text.length > 220 ? "…" : "")), details);
      const alert = node("td");
      alert.append(node("strong", "", row.terms.join(" · ") || (row.approximate_terms?.length ? `Para revisar: ${row.approximate_terms.join(" · ")}` : "Sin coincidencias")),
        node("small", "metadata", `${severity[row.severity] || "Sin prioridad"} · ${reviewLabels[row.review] || "Sin alerta"}`),
        node("small", "metadata", `Tono: ${tones[row.tone]?.[1] || row.tone}`));
      const link = node("td");
      try { if (row.url && new URL(row.url).protocol === "https:") link.append(originLink(row.url, "Abrir origen ↗")); } catch { /* Invalid legacy link. */ }
      tr.append(captured, source, content, alert, link);
      $("db-rows").append(tr);
    }
    $("db-status").textContent = data.rows.length
      ? `${data.rows.length} registros en esta página${data.has_more ? " · hay más resultados" : " · fin de los resultados"}. Consulta fijada al ${detailTime.format(new Date(data.snapshot))}.`
      : "No hay registros almacenados para estos filtros. Probá ampliar las fechas o cambiar las palabras.";
  } catch (error) {
    $("db-status").textContent = error.message;
    dataView.query = null;
  } finally { dataView.busy = false; dataButtons(); }
}
$("database-form").addEventListener("submit", (event) => { event.preventDefault(); loadData(); });
$("database-form").addEventListener("input", () => {
  dataView.query = null; dataButtons();
  $("db-status").textContent = "Los filtros cambiaron. Presioná Consultar para actualizar los resultados.";
});
$("db-reset").addEventListener("click", () => { $("database-form").reset(); loadData(); });
$("db-prev").addEventListener("click", () => loadData(dataView.index - 1, false));
$("db-next").addEventListener("click", () => {
  dataView.pages[dataView.index + 1] = dataView.next;
  loadData(dataView.index + 1, false);
});
$("db-export").addEventListener("click", async () => {
  if (!dataView.query || dataView.busy) return;
  const format = $("db-format").value;
  dataView.busy = true; dataButtons();
  $("db-status").textContent = "Preparando todos los resultados de la consulta…";
  try {
    const response = await fetch("/api/data-export", {
      method: "POST", headers: { "Content-Type": "application/json", "X-EchoScope-Token": ui.token },
      body: JSON.stringify({ ...dataView.query, format }), signal: AbortSignal.timeout(90000),
    });
    if (!response.ok) throw new Error((await response.json()).error || "No se pudo exportar.");
    const url = URL.createObjectURL(await response.blob());
    const link = node("a"); link.href = url; link.download = `EchoScope-datos.${format}`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    $("db-status").textContent = "Archivo generado. Revisá las descargas del navegador.";
  } catch (error) { $("db-status").textContent = error.message; }
  finally { dataView.busy = false; dataButtons(); }
});

(async () => {
  choosePage("board");
  try {
    const data = await api("bootstrap");
    ui.token = data.token;
    ui.practice = data.practice;
    ui.username = data.username;
    ui.sourceGroups = data.source_groups;
    ui.sourceLayout = data.source_layout;
    $("shutdown").hidden = !!ui.username;
    $("logout").hidden = !ui.username;
    $("account-name").hidden = !ui.username;
    $("account-name").textContent = ui.username || "";
    renderVault(data.credentials);
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
    $("edition").textContent = `${data.practice ? "PRÁCTICA" : ui.username ? "SERVIDOR" : "LOCAL"} · ${data.version}`;
    applyConfig(data, true);
    buildLayout();
    $("open-topic-search").disabled = false;
    $("open-report").disabled = false;
    toggleAlerts();
    await tick();
  } catch (error) {
    notice(`No se pudo abrir la mesa. ${error.message}`, true);
  }
})();
