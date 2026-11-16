import argparse
import asyncio
import threading
import tkinter as tk
import webbrowser
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

from pydantic import ValidationError

from echoscope.application.administration import (
    CHANNEL_TYPES,
    SOURCE_TYPES,
    WEB_TYPES,
    Administration,
    SourceForm,
)
from echoscope.application.ports import AuthRequired, ConnectorError, StorageUnavailable
from echoscope.domain.models import HistoryQuery, Kind, State
from echoscope.settings import load_environment

from .palette import paint
from .render import safe

TABS = {
    "Todos": None,
    "Noticias": "news",
    "Comentarios de prensa": "press",
    "YouTube": "youtube",
    "Directos": "live",
    "Foros": "forum",
}
KIND_LABELS = {
    Kind.NEWS_ARTICLE: "Nota",
    Kind.COMMENT: "Comentario",
    Kind.PRESS_COMMENT: "Comentario",
    Kind.LIVE_CHAT: "Chat en vivo",
    Kind.REVIEW: "Reseña",
    Kind.YOUTUBE_VIDEO: "Video",
    Kind.FORUM_POST: "Foro",
    Kind.YOUTUBE_LIVE: "Directo",
}
DEFAULT_FORMS = {
    "news": "Noticias de un sitio (RSS)",
    "press": "Comentarios de un sitio (RSS)",
    "forum": "Foro o comunidad (RSS/Atom)",
    "youtube": "Canal de YouTube · videos automáticos",
    "live": "Canal de YouTube · directos automáticos",
}
STATES = {
    State.SCHEDULED: "Programada",
    State.RUNNING: "Consultando",
    State.PAUSED: "En pausa",
    State.RETRYING: "Reintentando",
    State.ERROR: "Revisar conexión",
    State.DISABLED: "Desactivada",
    State.IDLE: "Finalizada",
    State.RATE_LIMITED: "Cuota alcanzada",
}


def user_error(error):
    if isinstance(error, AuthRequired):
        return "Falta una clave válida. Revisá el acceso en la pestaña Tema y acceso."
    if isinstance(error, ConnectorError):
        return str(error).capitalize()
    if isinstance(error, StorageUnavailable):
        return "El historial está temporalmente inaccesible. Volvé a intentar."
    if isinstance(error, ValidationError):
        return "Revisá los datos ingresados. El nombre admite hasta 80 caracteres."
    if isinstance(error, ValueError):
        return str(error)
    return (
        "No se pudo completar la operación. Cerrá otras ventanas de EchoScope y volvé a intentar."
    )


class Background:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            remaining = asyncio.all_tasks(self.loop)
            for task in remaining:
                task.cancel()
            if remaining:
                self.loop.run_until_complete(asyncio.gather(*remaining, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.run_until_complete(self.loop.shutdown_default_executor(timeout=1))
            self.loop.close()

    def submit(self, action):
        return asyncio.run_coroutine_threadsafe(action, self.loop)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=3)


class SourceDialog(tk.Toplevel):
    def __init__(
        self, parent, save, discover, source=None, job=None, suggestion=None, preferred=None
    ):
        super().__init__(parent)
        self.transient(parent)
        self.title("Editar fuente" if job else "Agregar fuente")
        self.resizable(False, False)
        self.grab_set()
        current_kind = (source.type, source.params.get("kind", "NEWS_ARTICLE")) if source else None
        if source and (source.type.startswith("youtube_") or source.type == "bluesky_thread"):
            current_kind = next(spec for spec in SOURCE_TYPES.values() if spec[0] == source.type)
        if current_kind == ("syndication", "COMMENT"):
            current_kind = "syndication", "PRESS_COMMENT"
        initial_type = next(
            (name for name, spec in SOURCE_TYPES.items() if spec == current_kind),
            preferred or next(iter(SOURCE_TYPES)),
        )
        if suggestion:
            initial_type = "Comentarios de un video de YouTube"
        self.form = {
            "label": tk.StringVar(
                value=(source.label or source.id)
                if source
                else (suggestion.title[:80] if suggestion else "")
            ),
            "type": tk.StringVar(value=initial_type),
            "address": tk.StringVar(
                value=(
                    source.params.get("url")
                    or source.params.get("video_id")
                    or source.params.get("channel")
                    or ""
                )
                if source
                else (suggestion.id if suggestion else "")
            ),
            "minutes": tk.StringVar(
                value=str(max(1, int(job.interval_s / 60)))
                if job
                else ("60" if SOURCE_TYPES[initial_type][0] == "youtube_channel_live" else "15")
            ),
            "enabled": tk.BooleanVar(value=job.enabled if job else True),
            "relevant": tk.BooleanVar(
                value=job.relevant_only
                if job
                else SOURCE_TYPES[initial_type][1] in {"NEWS_ARTICLE", "FORUM_POST"}
            ),
            "token": tk.StringVar(),
        }
        self.note = tk.StringVar()
        body = ttk.Frame(self, padding=20)
        body.grid(sticky="nsew")
        ttk.Label(body, text="Nombre visible").grid(row=0, column=0, sticky="w", pady=(0, 5))
        name = ttk.Entry(body, width=62, textvariable=self.form["label"])
        name.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(body, text="Qué querés seguir").grid(row=2, column=0, sticky="w")
        kinds = ttk.Combobox(
            body, state="readonly", values=list(SOURCE_TYPES), textvariable=self.form["type"]
        )
        kinds.grid(row=3, column=0, sticky="ew", pady=(3, 12))
        kinds.bind("<<ComboboxSelected>>", self._changed)
        ttk.Label(body, textvariable=self.note, wraplength=460).grid(row=4, column=0, sticky="w")
        address = ttk.Frame(body)
        address.grid(row=5, column=0, sticky="ew", pady=(3, 12))
        ttk.Entry(address, textvariable=self.form["address"]).pack(
            side="left", fill="x", expand=True
        )
        self.discover_button = ttk.Button(
            address, text="Detectar feed", command=lambda: discover(self)
        )
        ttk.Label(body, text="Consultar cada cuántos minutos").grid(row=6, column=0, sticky="w")
        ttk.Spinbox(body, from_=1, to=1440, width=8, textvariable=self.form["minutes"]).grid(
            row=7, column=0, sticky="w", pady=(3, 8)
        )
        self.token_group = ttk.Frame(body)
        self.token_group.grid(row=8, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(self.token_group, text="Token del feed (opcional, para esta sesión)").pack(
            anchor="w"
        )
        ttk.Entry(self.token_group, textvariable=self.form["token"], show="•", width=62).pack(
            fill="x"
        )
        ttk.Checkbutton(
            body,
            text="Guardar solo resultados que coincidan con el tema",
            variable=self.form["relevant"],
        ).grid(row=9, column=0, sticky="w")
        ttk.Checkbutton(body, text="Activar esta fuente", variable=self.form["enabled"]).grid(
            row=10, column=0, sticky="w", pady=(3, 12)
        )
        buttons = ttk.Frame(body)
        buttons.grid(row=11, column=0, sticky="e")
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="left", padx=(0, 8))

        def submit():
            try:
                minutes = int(self.form["minutes"].get())
            except ValueError:
                messagebox.showerror(
                    "Revisá el intervalo", "Escribí un número de minutos.", parent=self
                )
                return
            form = SourceForm(
                self.form["label"].get(),
                self.form["type"].get(),
                self.form["address"].get(),
                minutes,
                self.form["enabled"].get(),
                self.form["relevant"].get(),
                source.credential.env
                if source and source.credential and source.credential.kind == "bearer"
                else "",
            )
            save(form, job.id if job else None, self.form["token"].get().strip(), self)

        self.save_button = ttk.Button(
            buttons, text="Guardar fuente", style="Primary.TButton", command=submit
        )
        self.save_button.pack(side="left")
        self.bind("<Escape>", lambda _: self.destroy())
        self._changed()
        name.focus_set()

    def _changed(self, event=None):
        connector, kind = SOURCE_TYPES[self.form["type"].get()]
        if connector in WEB_TYPES:
            if connector == "press_page":
                self.note.set("Enlace HTTPS de la portada de noticias del medio")
                self.token_group.grid_remove()
                self.discover_button.pack_forget()
                return
            content = {"PRESS_COMMENT": "comentarios", "FORUM_POST": "publicaciones del foro"}.get(
                kind, "noticias"
            )
            self.note.set(f"Enlace HTTPS al feed RSS/Atom de {content} publicado por el sitio")
            self.token_group.grid()
            if kind == "PRESS_COMMENT":
                self.note.set("Pegá el enlace del feed o pegá el de la nota y elegí Detectar feed.")
                self.discover_button.pack(side="right", padx=(6, 0))
            else:
                self.discover_button.pack_forget()
        else:
            address = (
                "canal de YouTube o su @nombre"
                if connector in CHANNEL_TYPES
                else "video o directo de YouTube"
            )
            self.note.set(
                "Enlace público de una publicación de Bluesky."
                if connector == "bluesky_thread"
                else f"Enlace del {address}. Cargá la clave en Tema y acceso."
            )
            self.token_group.grid_remove()
            self.discover_button.pack_forget()
        if event:
            self.form["relevant"].set(kind in {"NEWS_ARTICLE", "FORUM_POST"})
            if connector == "youtube_channel_live":
                self.form["minutes"].set("60")


class Desktop:
    def __init__(self, root, path, practice=False):
        self.root, self.practice = root, practice
        self.service = Administration(path, practice)
        self.background = Background()
        self.config = None
        self.running = False
        self.pending = False
        self.closing = False
        self.results = {}
        self.result_signature = None
        self.source_signature = None
        self.current_url = None
        self.text = tk.StringVar()
        self.match_mode = tk.StringVar(value="Todos")
        self.theme_choice = tk.StringVar(value="Claro")
        self.match_note = tk.StringVar()
        self.status = tk.StringVar(value="Preparando el historial local…")
        self.key_status = tk.StringVar(value="Sin clave cargada")
        self.detail_title = tk.StringVar(
            value="Seleccioná un resultado para ver el texto completo."
        )
        self.query = HistoryQuery(limit=120)
        self._build()
        self._submit(self.service.open(), self._ready)

    def _build(self):
        self.root.title(
            f"EchoScope Radar {version('echoscope-radar')}"
            + (" · Práctica" if self.practice else "")
        )
        self.root.geometry("1080x720")
        self.root.minsize(850, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)

        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        header = ttk.Frame(frame)
        header.pack(fill="x", pady=(0, 14))
        self.run_button = ttk.Button(
            header,
            text="Iniciar seguimiento",
            style="Primary.TButton",
            state="disabled",
            command=self.toggle,
        )
        self.run_button.pack(side="right", pady=(6, 0))
        theme = ttk.Combobox(
            header,
            state="readonly",
            width=8,
            values=("Claro", "Oscuro"),
            textvariable=self.theme_choice,
        )
        theme.pack(side="right", padx=10, pady=(6, 0))
        theme.bind("<<ComboboxSelected>>", self._theme_changed)
        ttk.Label(header, text="EchoScope Radar", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Modo de práctica · fuentes simuladas"
            if self.practice
            else "Seguimiento automático · Defensa y Ejército · Uruguay",
        ).pack(anchor="w")

        tabs = ttk.Notebook(frame)
        tabs.pack(fill="both", expand=True)
        results, sources, settings = (ttk.Frame(tabs, padding=14) for _ in range(3))
        tabs.add(results, text="Resultados")
        tabs.add(sources, text="Fuentes")
        tabs.add(settings, text="Tema y acceso")

        self.category_tabs = ttk.Notebook(results, height=2)
        self.category_tabs.pack(fill="x", pady=(0, 9))
        for label in TABS:
            self.category_tabs.add(ttk.Frame(self.category_tabs, height=2), text=label)
        self.category_tabs.bind("<<NotebookTabChanged>>", lambda _: self.apply_filter())

        filters = ttk.Frame(results)
        filters.pack(fill="x", pady=(0, 8))
        search = ttk.Entry(filters, textvariable=self.text)
        search.pack(side="left", fill="x", expand=True, padx=6)
        search.bind("<Return>", lambda _: self.apply_filter())
        ttk.Button(filters, text="Buscar en resultados", command=self.apply_filter).pack(
            side="left", padx=6
        )
        mode = ttk.Combobox(
            filters,
            state="readonly",
            width=15,
            values=("Todos", "Alertas", "Para revisar"),
            textvariable=self.match_mode,
        )
        mode.pack(side="right")
        mode.bind("<<ComboboxSelected>>", lambda _: self.apply_filter())
        self.result_tree = self._table(
            results, ("Hora", "Fuente", "Tipo", "Resultado"), (122, 190, 105, 450)
        )
        self.result_tree.bind("<<TreeviewSelect>>", self._detail)
        detail = ttk.Frame(results)
        detail.pack(fill="both", pady=(10, 0))
        self.open_button = ttk.Button(
            detail, text="Abrir publicación", command=self.open_result, state="disabled"
        )
        self.open_button.pack(side="right")
        ttk.Label(detail, textvariable=self.detail_title, style="Heading.TLabel").pack(anchor="w")
        ttk.Label(results, textvariable=self.match_note, wraplength=760).pack(
            anchor="w", pady=(3, 0)
        )
        self.body = tk.Text(
            results,
            height=6,
            wrap="word",
            relief="flat",
            padx=8,
            pady=6,
            font=("Segoe UI", 10),
            state="disabled",
        )
        self.body.pack(fill="x", pady=(6, 0))

        ttk.Label(
            sources, text="Elegí qué medios y videos querés seguir.", style="Heading.TLabel"
        ).pack(anchor="w", pady=(0, 8))
        self.source_tree = self._table(
            sources, ("Fuente", "Contenido", "Intervalo", "Estado"), (250, 130, 80, 400)
        )
        self.source_tree.bind("<Double-1>", lambda _: self.edit_source())
        source_buttons = ttk.Frame(sources)
        source_buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(
            source_buttons, text="Agregar fuente", command=self.add_source, style="Primary.TButton"
        ).pack(side="left", padx=(0, 8))
        ttk.Button(source_buttons, text="Editar", command=self.edit_source).pack(
            side="left", padx=4
        )
        ttk.Button(source_buttons, text="Consultar ahora", command=self.probe).pack(
            side="left", padx=4
        )
        ttk.Button(source_buttons, text="Quitar fuente", command=self.remove).pack(side="right")

        ttk.Label(settings, text="Palabras y frases del tema", style="Heading.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            settings,
            text="Una por línea. Para aprobar una variante usá: Ejército | ejersito.",
        ).pack(anchor="w", pady=(3, 6))
        self.terms = tk.Text(settings, height=7, wrap="word", font=("Segoe UI", 11))
        self.terms.pack(fill="x")
        ttk.Button(settings, text="Guardar tema", command=self.save_topic).pack(
            anchor="w", pady=(6, 14)
        )
        ttk.Separator(settings).pack(fill="x", pady=(0, 14))
        ttk.Label(settings, text="Acceso a YouTube", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            settings, text="La clave se usa durante esta sesión y queda fuera del historial."
        ).pack(anchor="w", pady=(4, 6))
        access = ttk.Frame(settings)
        access.pack(fill="x")
        self.key = tk.StringVar()
        ttk.Entry(access, textvariable=self.key, show="•", width=38).pack(side="left")
        ttk.Button(access, text="Cargar clave", command=self.save_key).pack(side="left", padx=8)
        ttk.Label(access, textvariable=self.key_status).pack(side="left")
        self.video_search = tk.StringVar(value="Ministerio de Defensa Nacional Ejército Uruguay")
        video = ttk.Frame(settings)
        video.pack(fill="x", pady=(10, 0))
        ttk.Entry(video, textvariable=self.video_search).pack(side="left", fill="x", expand=True)
        ttk.Button(video, text="Buscar videos", command=self.search_videos).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(10, 0))
        paint(self.root, "light", self.body, self.terms)

    def _table(self, parent, columns, widths):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)
        table = ttk.Treeview(
            container, columns=columns, show="headings", selectmode="browse", height=8
        )
        bar = ttk.Scrollbar(container, command=table.yview)
        table.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        table.pack(side="left", fill="both", expand=True)
        for index, (name, width) in enumerate(zip(columns, widths)):
            table.heading(name, text=name)
            table.column(name, width=width, minwidth=70, stretch=index == len(columns) - 1)
        return table

    def _submit(self, action, done, failed=None):
        future = self.background.submit(action)

        def check():
            if not future.done():
                self.root.after(50, check)
                return
            try:
                value = future.result()
            except Exception as error:
                if failed:
                    failed(error)
                elif not self.closing:
                    self.status.set(user_error(error))
            else:
                done(value)

        self.root.after(30, check)

    def _ready(self, config):
        self._configured(config, update_terms=True)
        self.run_button.configure(state="normal")
        self.status.set("Elegí Iniciar seguimiento para consultar las fuentes activas.")
        self.refresh()
        self._submit(self.service.theme(), self._restore_theme)
        if not self.practice and not self.closing:
            self.toggle()

    def _restore_theme(self, name):
        dark = name in {"dark", "darkest"}
        self.theme_choice.set("Oscuro" if dark else "Claro")
        paint(self.root, "dark" if dark else "light", self.body, self.terms)

    def _theme_changed(self, _event=None):
        name = "dark" if self.theme_choice.get() == "Oscuro" else "light"
        paint(self.root, name, self.body, self.terms)
        if self.config:
            self._submit(self.service.set_theme(name), lambda _: None)

    def _configured(self, config, update_terms=False):
        self.config = config
        if update_terms:
            self.terms.delete("1.0", "end")
            rules = next(iter(config.rule_sets.values()), [])
            self.terms.insert(
                "1.0", "\n".join(" | ".join((rule.phrase, *rule.aliases)) for rule in rules)
            )
        self.source_signature = None

    def refresh(self):
        if self.closing:
            return
        query = self.query

        def done(value):
            if query == self.query and not self.closing:
                self._render(value)
            if not self.closing:
                self.root.after(800, self.refresh)

        def failed(error):
            if not self.closing:
                self.status.set(user_error(error))
                self.root.after(1500, self.refresh)

        self._submit(self.service.snapshot(query), done, failed)

    def _render(self, value):
        snapshots, results, running, key_present = value
        self.running = running
        self.run_button.configure(text="Detener seguimiento" if running else "Iniciar seguimiento")
        self.key_status.set("Clave cargada" if key_present else "Sin clave cargada")
        source_rows = []
        labels = {item.id: item.label or item.id for item in self.config.sources}
        for identifier, snapshot in snapshots.items():
            source = snapshot.source
            labels[source.id] = source.label or source.id
            state = STATES[snapshot.state]
            if snapshot.detail:
                state += f" · {safe(snapshot.detail).lower()}"
            if snapshot.coverage_gap:
                state += " · cobertura parcial"
            if source.type in {"youtube_live", "youtube_channel_live"}:
                state += " · solo sesión"
            if source.type in WEB_TYPES:
                kind = KIND_LABELS.get(Kind(source.params.get("kind", "FEED_ENTRY")), "Feed")
            else:
                kind = {
                    "youtube_live": "Chat de YouTube",
                    "youtube_comments": "Comentarios de YouTube",
                    "youtube_channel": "Videos automáticos",
                    "youtube_channel_live": "Directos automáticos",
                }.get(source.type, "Práctica")
            minutes = (
                f"{snapshot.job.interval_s / 60:g} min"
                if source.type != "youtube_live"
                else "En vivo"
            )
            source_rows.append((identifier, (labels[source.id], kind, minutes, state)))
        if source_rows != self.source_signature:
            self._replace_rows(self.source_tree, source_rows)
            self.source_signature = source_rows
        rows = []
        for item in results:
            message = item.observation.message
            when = (message.published_at or message.captured_at).astimezone()
            title = (
                safe(message.text).splitlines()[0][:135] if message.text.strip() else "(sin texto)"
            )
            rows.append(
                (
                    str(item.id),
                    (
                        when.strftime("%d/%m %H:%M"),
                        labels.get(item.source_id, item.source_id),
                        (
                            "Para revisar"
                            if any(not match.confirmed for match in item.observation.matches)
                            else KIND_LABELS.get(message.kind, "Entrada")
                        ),
                        title,
                    ),
                )
            )
        self.results = {str(item.id): item for item in results}
        if rows != self.result_signature:
            self._replace_rows(self.result_tree, rows)
            self.result_signature = rows
            self._detail()

    def _replace_rows(self, table, rows):
        selected = table.selection()
        position = table.yview()[0]
        table.delete(*table.get_children())
        for identifier, values in rows:
            table.insert("", "end", iid=identifier, values=values)
        if selected and table.exists(selected[0]):
            table.selection_set(selected[0])
        table.yview_moveto(position)

    def _detail(self, _event=None):
        selected = self.result_tree.selection()
        item = self.results.get(selected[0]) if selected else None
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        self.current_url = None
        self.match_note.set("")
        if item:
            message = item.observation.message
            when = (message.published_at or message.captured_at).astimezone()
            self.detail_title.set(
                f"{safe(message.author or 'Publicación')} · {when:%d/%m/%Y %H:%M}"
            )
            self.body.insert("1.0", safe(message.text))
            variants = []
            for match in item.observation.matches:
                self.body.tag_add(
                    match.severity if match.confirmed else "review",
                    f"1.0+{match.start} chars",
                    f"1.0+{match.end} chars",
                )
                if match.canonical:
                    prefix = "" if match.confirmed else "Para revisar: "
                    variants.append(f"{prefix}{safe(match.term)} → {safe(match.canonical)}")
            self.match_note.set(" · ".join(list(dict.fromkeys(variants))[:5]))
            self.current_url = message.url
        else:
            empty = (
                "Agregá un RSS/Atom autorizado para seguir un foro."
                if self.query.category == "forum"
                else "Todavía no hay resultados en esta vista."
            )
            self.detail_title.set(
                "Seleccioná un resultado para ver el texto completo." if self.results else empty
            )
        self.body.configure(state="disabled")
        self.open_button.configure(state="normal" if self.current_url else "disabled")

    def open_result(self):
        if self.current_url:
            parsed = urlsplit(self.current_url)
            if parsed.scheme in {"https", "http"} and parsed.hostname and parsed.username is None:
                webbrowser.open(self.current_url)

    def toggle(self):
        if self.pending:
            return
        self.pending = True
        enabled = not self.running
        self.run_button.configure(state="disabled")

        def done(_):
            self.running = enabled
            self.pending = False
            self.run_button.configure(
                state="normal", text="Detener seguimiento" if enabled else "Iniciar seguimiento"
            )
            self.status.set(
                "Seguimiento activo. Los resultados aparecen al consultar las fuentes."
                if enabled
                else "Seguimiento detenido. El historial sigue disponible."
            )

        def failed(error):
            self.pending = False
            self.run_button.configure(state="normal")
            self.status.set(user_error(error))

        self._submit(self.service.set_running(enabled), done, failed)

    def apply_filter(self):
        self.query = HistoryQuery(
            text=self.text.get().strip() or None,
            category=self._category(),
            matches_only=self.match_mode.get() == "Alertas",
            review_only=self.match_mode.get() == "Para revisar",
            limit=120,
        )

    def _category(self):
        active = self.category_tabs.select()
        return TABS[self.category_tabs.tab(active, "text")] if active else None

    def add_source(self, suggestion=None):
        if self.config:
            SourceDialog(
                self.root,
                self._save_source,
                self._detect_comments,
                suggestion=suggestion,
                preferred=DEFAULT_FORMS.get(self._category()),
            )

    def _selected_job(self):
        selected = self.source_tree.selection()
        if not selected:
            self.status.set("Seleccioná una fuente en la lista.")
        return selected[0] if selected else None

    def edit_source(self):
        if self.config and (identifier := self._selected_job()):
            job = next(item for item in self.config.jobs if item.id == identifier)
            source = next(item for item in self.config.sources if item.id == job.source)
            if source.type.startswith("sim_"):
                self.status.set("La fuente simulada está preparada para la práctica.")
                return
            SourceDialog(self.root, self._save_source, self._detect_comments, source, job)

    def _detect_comments(self, dialog):
        dialog.discover_button.configure(state="disabled")

        def done(endpoint):
            if not dialog.winfo_exists():
                return
            dialog.discover_button.configure(state="normal")
            if endpoint:
                dialog.form["address"].set(endpoint)
                dialog.note.set(
                    "Feed público de comentarios detectado. Guardá la fuente para seguirlo."
                )
            else:
                dialog.note.set(
                    "La nota no anuncia un feed de comentarios. Podés usar un feed autorizado o seguir su video de YouTube."
                )

        def failed(error):
            if dialog.winfo_exists():
                dialog.discover_button.configure(state="normal")
                dialog.note.set(user_error(error))

        self._submit(self.service.detect_comments(dialog.form["address"].get()), done, failed)

    def _save_source(self, form, identifier, token, dialog):
        dialog.save_button.configure(state="disabled")

        def done(config):
            self._configured(config)
            dialog.destroy()
            self.status.set("Fuente guardada.")

        def failed(error):
            if dialog.winfo_exists():
                dialog.save_button.configure(state="normal")
                messagebox.showerror("No se guardó la fuente", user_error(error), parent=dialog)

        self._submit(self.service.save_source(form, identifier, token), done, failed)

    def remove(self):
        if self.config and (identifier := self._selected_job()):
            if messagebox.askyesno(
                "Quitar fuente",
                "¿Querés dejar de consultar esta fuente? El historial guardado seguirá disponible.",
                parent=self.root,
            ):
                self._submit(self.service.remove_source(identifier), self._configured)

    def probe(self):
        if self.config and (identifier := self._selected_job()):
            self.status.set("Consultando la fuente seleccionada…")
            self._submit(
                self.service.probe(identifier),
                lambda item: self.status.set(
                    safe(item.detail).capitalize()
                    if item.detail
                    else "Consulta completa. Revisá la pestaña Resultados."
                ),
            )

    def save_topic(self):
        if self.config:

            def saved(config):
                self._configured(config, update_terms=True)
                self.status.set("Tema actualizado.")

            self._submit(self.service.save_topic(self.terms.get("1.0", "end").splitlines()), saved)

    def save_key(self):
        key = self.key.get().strip()
        self.key.set("")
        self._submit(
            self.service.credentials(key),
            lambda _: self.status.set(
                "Clave cargada. Ya podés buscar videos o consultar una fuente de YouTube."
            ),
        )

    def search_videos(self):
        if not self.config:
            return
        self.status.set("Buscando en YouTube…")
        self._submit(self.service.search(self.video_search.get()), self._show_videos)

    def _show_videos(self, videos):
        if not videos:
            self.status.set("YouTube no devolvió videos para ese tema.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Videos encontrados")
        dialog.transient(self.root)
        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)
        table = self._table(body, ("Video", "Canal"), (490, 175))
        for item in videos:
            table.insert("", "end", iid=item.id, values=(safe(item.title), safe(item.channel)))

        def choose():
            selected = table.selection()
            if selected:
                item = next(item for item in videos if item.id == selected[0])
                dialog.destroy()
                self.add_source(item)

        ttk.Button(
            body, text="Seguir comentarios del video", style="Primary.TButton", command=choose
        ).pack(anchor="e", pady=(10, 0))
        table.bind("<Double-1>", lambda _: choose())
        self.status.set(f"YouTube devolvió {len(videos)} videos.")

    def request_close(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Cerrar EchoScope Radar")
        dialog.transient(self.root)
        body = ttk.Frame(dialog, padding=20)
        body.pack()
        ttk.Label(body, text="La aplicación quedará en segundo plano y seguirá capturando.",
                  wraplength=350).pack(pady=8)

        def background():
            dialog.destroy()
            self.root.iconify()

        def exit_app():
            dialog.destroy()
            self.close()

        ttk.Button(body, text="Confirmar segundo plano", command=background).pack(fill="x", pady=4)
        ttk.Button(body, text="Salir y detener captura", command=exit_app).pack(fill="x", pady=4)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.status.set("Cerrando el seguimiento…")

        def finish(_):
            self.background.stop()
            self.root.destroy()

        self._submit(self.service.close(), finish, finish)


def main():
    parser = argparse.ArgumentParser(description="EchoScope Radar para personal administrativo")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    settings = load_environment(args.env_file)
    from .lifecycle import configure_logging

    configure_logging(settings.data_dir, practice=args.demo)
    path = args.db or (
        settings.data_dir / "practica.sqlite"
        if args.demo
        else settings.database_target("administracion.sqlite")
    )
    root = tk.Tk()
    root.iconphoto(
        True,
        tk.PhotoImage(
            data=files("echoscope").joinpath("web_assets", "ciberdefensa.png").read_bytes()
        ),
    )
    Desktop(root, path, args.demo)
    root.mainloop()


if __name__ == "__main__":
    main()
