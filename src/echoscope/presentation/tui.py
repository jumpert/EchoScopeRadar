import asyncio
from dataclasses import replace

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from echoscope.application.ports import JobCommand, StorageUnavailable
from echoscope.connectors.syndication import parse_date
from echoscope.domain.models import HistoryQuery, Severity, State

from .render import LABELS, STYLES, display, line, preview

COLORS = ("#46cadd", "#c194f1", "#73dba6")
PANEL_LIMIT = 50


class Detail(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Volver")]

    def __init__(self, title, body):
        super().__init__()
        self.heading = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(Text(self.heading, style="bold"), markup=False)
            with VerticalScroll():
                yield Static(self.body, markup=False)
            yield Button("Volver", id="close")

    @on(Button.Pressed, "#close")
    def close_dialog(self):
        self.dismiss()


class FilterScreen(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Volver")]

    def __init__(self, query):
        super().__init__()
        self.history_filter = query

    def compose(self):
        with Vertical(classes="dialog form"):
            yield Label("Filtro histórico · aplicado a los paneles")
            query = self.history_filter
            yield Input(query.text or "", placeholder="Texto del mensaje", id="filter-text")
            yield Input(
                query.severity or "",
                placeholder="Severidad: info, important, critical",
                id="filter-severity",
            )
            yield Input(
                query.since.isoformat() if query.since else "",
                placeholder="Desde (ISO-8601 UTC)",
                id="filter-since",
            )
            yield Input(
                query.until.isoformat() if query.until else "",
                placeholder="Hasta (ISO-8601 UTC)",
                id="filter-until",
            )
            yield Static("", id="form-error")
            with Horizontal():
                yield Button("Aplicar", id="filter-apply", variant="primary")
                yield Button("Limpiar", id="filter-clear")

    @on(Button.Pressed, "#filter-clear")
    def clear(self):
        self.dismiss(HistoryQuery())

    @on(Button.Pressed, "#filter-apply")
    @on(Input.Submitted)
    def apply_filter(self):
        def field(name):
            return self.query_one(f"#filter-{name}", Input).value.strip()

        try:
            severity = Severity(field("severity").lower()) if field("severity") else None
            since, until = parse_date(field("since")), parse_date(field("until"))
            if (
                (field("since") and not since)
                or (field("until") and not until)
                or (since and until and since > until)
            ):
                raise ValueError
        except ValueError:
            self.query_one("#form-error", Static).update("Revisá fechas y severidad")
            return
        self.dismiss(
            HistoryQuery(text=field("text") or None, severity=severity, since=since, until=until)
        )


class Cycles(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Volver")]

    def __init__(self, summary, job):
        super().__init__()
        self.summary = summary
        self.job = job

    def compose(self):
        with Vertical(classes="dialog"):
            yield Label("Ciclos e historial de ejecución")
            with VerticalScroll():
                yield Static(self.summary, markup=False)
            if self.job:
                yield Input(
                    str(self.job.interval_s),
                    placeholder="Intervalo en segundos",
                    id="cycle-interval",
                )
                with Horizontal():
                    yield Button("Intervalo", id="interval")
                    yield Button("Ahora", id="run_now")
                    yield Button("Recuperar", id="recover")
                    yield Button(
                        "Deshabilitar" if self.job.enabled else "Habilitar",
                        id="disable" if self.job.enabled else "enable",
                    )
            yield Static("", id="cycle-error")

    @on(Button.Pressed)
    def command(self, event):
        action = event.button.id
        interval = None
        if action == "interval":
            try:
                interval = float(self.query_one("#cycle-interval", Input).value)
            except ValueError:
                self.query_one("#cycle-error", Static).update("Ingresá un intervalo en segundos")
                return
        self.dismiss(JobCommand(self.job.id, action, interval))


class RadarConsole(App):
    TITLE = "EchoScope Radar"
    CSS = """
    Screen { background: #10151d; color: #f2f4f8; }
    #headline { height: 2; background: #1d2937; padding: 0 1; text-style: bold; }
    #tabs { height: 1; background: #17212e; padding: 0 1; }
    #boards { height: 1fr; }
    .board { width: 1fr; height: 1fr; border: round #46cadd; }
    .board.selected { border: heavy #f2f4f8; }
    .job-meta { height: 2; padding: 0 1; color: #c3cbd8; }
    OptionList { height: 1fr; padding: 0 1; background: #10151d; }
    #alerts { height: 6; border: round #9c253b; }
    #activity { height: 1; padding: 0 1; color: #c3cbd8; }
    ModalScreen { align: center middle; background: #000000aa; }
    .dialog { width: 90%; max-width: 100; height: 85%; border: round #46cadd; padding: 1 2; background: #192332; }
    .dialog VerticalScroll { height: 1fr; }
    .dialog Horizontal { height: 3; }
    .form { height: auto; }
    """
    BINDINGS = [
        Binding("tab", "next_panel", "Panel", priority=True),
        Binding("shift+tab", "previous_panel", "Panel anterior", show=False, priority=True),
        ("p", "pause", "Pausar"),
        ("r", "resume", "Reanudar"),
        ("g", "global_control", "Global"),
        ("c", "cycles", "Ciclos"),
        ("f", "filter", "Filtrar"),
        ("m", "maximize", "Ampliar"),
        ("a", "alerts", "Alertas"),
        ("space", "freeze", "Congelar vista"),
        Binding("pageup", "older", "Historial", priority=True),
        Binding("end", "latest", "Últimos", priority=True),
        ("q", "quit", "Salir"),
    ]

    def __init__(self, radar, executions):
        super().__init__()
        self.radar = radar
        self.executions = executions
        self.keys = sorted(radar.jobs)
        self.selected = 0
        self.maximized = False
        self.frozen = False
        self.before = None
        self.filter_query = HistoryQuery()
        self.panel_rows = {}
        self.alert_rows = []
        self.seen = -1
        self.dirty = True
        self.displayed_at = {}
        self.visible_since = {}

    @property
    def selected_job(self):
        return self.keys[self.selected] if self.keys else None

    def compose(self) -> ComposeResult:
        yield Static("ECHOSCOPE RADAR", id="headline", markup=False)
        yield Static("", id="tabs", markup=False)
        with Horizontal(id="boards"):
            for index, key in enumerate(self.keys):
                with Container(id=f"board-{index}", classes="board") as board:
                    board.border_title = line(self.radar.jobs[key].source.label or key)
                    board.styles.border = ("round", COLORS[index % len(COLORS)])
                    yield Static("", id=f"meta-{index}", classes="job-meta", markup=False)
                    yield OptionList(id=f"messages-{index}", markup=False, compact=True)
        alerts = OptionList(id="alerts", markup=False, compact=True)
        alerts.border_title = "Alertas"
        yield alerts
        yield Static("", id="activity", markup=False)
        yield Footer()

    async def on_mount(self):
        self._layout()
        if self.keys:
            self.query_one("#messages-0", OptionList).focus()
        await self._refresh()
        self.set_interval(0.10, self._refresh)

    def on_resize(self, _: Resize):
        if self.is_mounted and len(self.screen_stack) == 1:
            self._layout()

    def check_action(self, action, parameters):
        if (
            action in {"next_panel", "previous_panel", "older", "latest"}
            and len(self.screen_stack) > 1
        ):
            return False
        return super().check_action(action, parameters)

    def _layout(self):
        count = 1 if self.maximized or self.size.width < 100 else 3
        start = min(self.selected, max(0, len(self.keys) - count))
        now = asyncio.get_running_loop().time()
        for index, key in enumerate(self.keys):
            board = self.query_one(f"#board-{index}", Container)
            board.display = start <= index < start + count
            board.set_class(index == self.selected, "selected")
            if board.display:
                self.visible_since.setdefault(key, now)
            else:
                self.visible_since.pop(key, None)
        self.query_one("#tabs", Static).update(
            Text(
                "  ".join(
                    ("▸ " if index == self.selected else "  ")
                    + line(self.radar.jobs[key].source.label or key)
                    for index, key in enumerate(self.keys)
                )
            )
        )
        self.dirty = True

    def _pinned(self, widget):
        return (widget.highlighted or 0) > 0 or widget.scroll_y > 0

    async def _refresh(self):
        if len(self.screen_stack) > 1:
            return
        revision = self.radar.revision
        if not self.dirty and self.seen == revision:
            return
        db = "DB OK" if self.radar.database_ok else "DB REINTENTANDO"
        active = sum(item.state == State.RUNNING for item in self.radar.jobs.values())
        self.query_one("#headline", Static).update(
            f"ECHOSCOPE RADAR  ·  {active} EN CURSO  ·  {db}"
        )
        pending = False
        panels = []
        for index, key in enumerate(self.keys):
            if not self.query_one(f"#board-{index}", Container).display:
                continue
            snapshot = self.radar.jobs[key]
            definition = self.radar.registry[snapshot.source.type]
            mode = ("SIMULADO · " if definition.simulated else "") + (
                "LIVE" if definition.mode == "stream" else "POLL"
            )
            if not definition.persistent:
                mode += " · SOLO SESIÓN"
            due = f" · próximo {snapshot.next_at.astimezone():%H:%M:%S}" if snapshot.next_at else ""
            gap = " · CAPTURA PARCIAL" if snapshot.coverage_gap else ""
            state = f" · {snapshot.availability}" if snapshot.availability else ""
            detail = f" · {snapshot.detail}" if snapshot.detail else ""
            self.query_one(f"#meta-{index}", Static).update(
                Text(f"{mode}\n{snapshot.state}{state}{due}{detail}{gap}")
            )
            widget = self.query_one(f"#messages-{index}", OptionList)
            if self.frozen or (not self.dirty and self._pinned(widget)):
                pending |= revision != self.seen
                continue
            before = self.before if index == self.selected else None
            query = replace(self.filter_query, job_id=key, before=before, limit=PANEL_LIMIT)
            panels.append((key, widget, query))
        alert_widget = self.query_one("#alerts", OptionList)
        refresh_alerts = not self.frozen and (self.dirty or not self._pinned(alert_widget))
        queries = [self.radar.messages(query) for _, _, query in panels]
        if refresh_alerts:
            queries.append(self.radar.messages(HistoryQuery(matches_only=True, limit=20)))
        try:
            pages = await asyncio.gather(*queries)
        except StorageUnavailable:
            self.query_one("#activity", Static).update("SQLite temporalmente inaccesible")
            return
        for (key, widget, _), rows in zip(panels, pages):
            if rows != self.panel_rows.get(key):
                widget.clear_options().add_options(
                    Option(preview(row.observation), id=str(row.id)) for row in rows
                )
                widget.highlighted = 0 if rows else None
                self.panel_rows[key] = rows
                received_at = self.radar.last_batch_received.get(key)
                if received_at is not None and received_at >= self.visible_since.get(
                    key, float("inf")
                ):
                    self.call_after_refresh(self._displayed, key, revision, received_at)
        if refresh_alerts:
            alerts = pages[-1]
            for key in self.radar.session:
                alerts += await self.radar.messages(
                    HistoryQuery(job_id=key, matches_only=True, limit=20)
                )
            alerts = sorted(
                alerts, key=lambda item: item.observation.message.captured_at, reverse=True
            )[:20]
            if alerts != self.alert_rows:
                alert_widget.clear_options().add_options(self._alert(row) for row in alerts)
                alert_widget.highlighted = 0 if alerts else None
                self.alert_rows = alerts
        hint = (
            "REVISANDO HISTORIAL · Fin para volver"
            if self.before is not None
            else "Repág carga mensajes anteriores · Fin vuelve a los últimos"
        )
        if self.frozen:
            hint = "VISTA CONGELADA · Espacio para continuar"
        if pending:
            hint += " · Hay novedades"
        self.query_one("#activity", Static).update(hint)
        self.seen = revision
        self.dirty = False

    def _displayed(self, key, revision, received_at):
        self.displayed_at[key] = revision, received_at, asyncio.get_running_loop().time()

    def _alert(self, row):
        matches = sorted(
            row.observation.matches, key=lambda match: STYLES[match.severity][0], reverse=True
        )
        text = Text(LABELS[matches[0].severity], style=STYLES[matches[0].severity][1])
        terms = " · ".join(dict.fromkeys(line(match.term) for match in matches))
        when = row.observation.message.captured_at.astimezone()
        text.append(f"  {when:%H:%M:%S} · {line(row.source_id)} · {terms}")
        return Option(text, id=str(row.id))

    @on(OptionList.OptionSelected)
    def inspect_row(self, event):
        widget_id = event.option_list.id
        if widget_id == "alerts":
            rows = self.alert_rows
        else:
            index = int(widget_id.rsplit("-", 1)[1])
            self.selected = index
            rows = self.panel_rows.get(self.keys[index], [])
        row = next((item for item in rows if str(item.id) == event.option.id), None)
        if row:
            text = display(row.observation, details=True)
            for match in row.observation.matches:
                text.append(
                    f"\n{LABELS[match.severity]} · {line(match.rule_id)} · {line(match.term)}"
                )
            self.push_screen(Detail(f"{row.source_id} · {row.observation.message.kind}", text))

    def _select(self, delta):
        if self.keys:
            self.selected = (self.selected + delta) % len(self.keys)
            self.before = None
            self._layout()
            self.query_one(f"#messages-{self.selected}", OptionList).focus()

    def action_next_panel(self):
        self._select(1)

    def action_previous_panel(self):
        self._select(-1)

    def action_maximize(self):
        self.maximized = not self.maximized
        self._layout()

    def action_alerts(self):
        self.query_one("#alerts", OptionList).focus()

    async def _control(self, command):
        try:
            await self.radar.execute(command)
        except ValueError as error:
            self.notify(line(str(error)), severity="warning")

    async def action_pause(self):
        if self.selected_job:
            await self._control(JobCommand(self.selected_job, "pause"))

    async def action_resume(self):
        if self.selected_job:
            await self._control(JobCommand(self.selected_job, "resume"))

    async def action_global_control(self):
        action = (
            "pause"
            if any(item.job.enabled and not item.paused for item in self.radar.jobs.values())
            else "resume"
        )
        await self._control(JobCommand(None, action))

    def action_freeze(self):
        self.frozen = not self.frozen
        self.dirty = True

    def action_latest(self):
        self.before = None
        self.frozen = False
        if self.selected_job:
            widget = self.query_one(f"#messages-{self.selected}", OptionList)
            widget.highlighted = 0 if widget.option_count else None
            widget.scroll_home(animate=False)
        self.dirty = True

    async def action_older(self):
        rows = self.panel_rows.get(self.selected_job)
        if rows and not self.frozen:
            cursor = rows[-1].id
            next_page = await self.radar.messages(
                replace(self.filter_query, job_id=self.selected_job, before=cursor, limit=1)
            )
            if next_page:
                self.before = cursor
                self.dirty = True
            else:
                self.notify("Fin del historial disponible")

    def action_filter(self):
        def apply(query):
            if query is not None:
                self.filter_query = query
                self.action_latest()

        self.push_screen(FilterScreen(self.filter_query), apply)

    async def action_cycles(self):
        text = Text()
        for snapshot in self.radar.jobs.values():
            last = (
                snapshot.last_at.astimezone().isoformat(timespec="seconds")
                if snapshot.last_at
                else "—"
            )
            due = (
                snapshot.next_at.astimezone().isoformat(timespec="seconds")
                if snapshot.next_at
                else "—"
            )
            text.append(
                f"{snapshot.job.id} · {snapshot.state} · {snapshot.job.interval_s:g}s\n",
                style="bold",
            )
            text.append(f"  último {last} · próximo {due} · {snapshot.detail or '—'}\n")
        if self.selected_job:
            for execution in (await self.executions(self.selected_job))[:20]:
                text.append(f"\n{execution.started} · {execution.outcome}")
        job = self.radar.jobs[self.selected_job].job if self.selected_job else None

        async def apply(command):
            if command:
                await self._control(command)

        self.push_screen(Cycles(text, job), apply)
