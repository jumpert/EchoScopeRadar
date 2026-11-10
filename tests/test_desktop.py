import gc
import sys
import time

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="la prueba de ventana requiere Tk en Windows")
def test_administrator_can_start_practice_and_open_a_message(tmp_path):
    import tkinter as tk

    from echoscope.presentation.desktop import Desktop

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no hay sesión gráfica de Tk")
    root.withdraw()
    app = Desktop(root, tmp_path / "window.sqlite", practice=True)

    def wait_until(condition):
        end = time.monotonic() + 8
        while not condition():
            if time.monotonic() >= end:
                pytest.fail(app.status.get())
            root.update()
            time.sleep(0.02)

    try:
        wait_until(lambda: app.config is not None)
        assert len(app.category_tabs.tabs()) == 6
        app.category_tabs.select(5)
        root.update()
        assert app.query.category == "forum"
        app.category_tabs.select(0)
        app.theme_choice.set("Oscuro")
        app._theme_changed()
        assert app.body.cget("background") == "#1e2835"
        app.run_button.invoke()
        wait_until(lambda: bool(app.result_tree.get_children()))
        identifier = app.result_tree.get_children()[0]
        app.result_tree.selection_set(identifier)
        root.update()
        assert app.body.get("1.0", "end").strip()
        assert app.run_button.cget("text") == "Detener seguimiento"
    finally:
        app.close()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            root.update()
            try:
                root.winfo_exists()
            except tk.TclError:
                break
            time.sleep(0.02)
        app = root = wait_until = None
        gc.collect()
