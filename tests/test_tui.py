from conftest import demo_radar, until
from textual.widgets import OptionList

from echoscope.domain.models import State
from echoscope.presentation.tui import Detail, FilterScreen, RadarConsole


async def test_tui_panel_navigation_pause_detail_and_freeze(tmp_path):
    async with demo_radar(tmp_path / "radar.sqlite") as (radar, store):
        app = RadarConsole(radar, store.executions)
        async with app.run_test(size=(125, 34)) as pilot:
            await until(lambda: bool(app.panel_rows.get("comentarios")))
            await pilot.press("tab")
            assert app.selected_job == "comentarios"
            await pilot.press("p")
            assert radar.jobs["comentarios"].state == State.PAUSED
            await pilot.press("enter")
            assert isinstance(app.screen, Detail)
            await pilot.press("escape")
            await pilot.press("space")
            assert app.frozen
            snapshot = dict(app.panel_rows)
            revision = radar.revision
            await until(lambda: radar.revision > revision)
            await pilot.pause(0.2)
            assert snapshot == app.panel_rows
            await pilot.press("end", "f")
            assert isinstance(app.screen, FilterScreen)
            await pilot.press("escape", "r", "m")
            assert not radar.jobs["comentarios"].paused
            assert app.maximized
            assert sum(widget.display for widget in app.query(".board")) == 1
            assert app.query_one("#messages-1", OptionList).option_count > 0
