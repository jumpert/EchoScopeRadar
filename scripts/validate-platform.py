"""Offline acceptance through CLI, web and persistent history on either OS."""

import json
import os
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def main():
    results = {"platform": platform.platform(), "python": platform.python_version(), "checks": []}
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("ECHOSCOPE_")
    }
    with tempfile.TemporaryDirectory(prefix="echoscope-validation-") as temporary:
        root = Path(temporary)
        environment["ECHOSCOPE_DATA_DIR"] = str(root)
        settings = root / "validation.env"
        settings.write_text("ECHOSCOPE_POLL_SLOTS=2\nECHOSCOPE_STREAM_SLOTS=1\n", encoding="utf-8")

        def run(*args):
            output = subprocess.run(
                [sys.executable, "-m", "echoscope", "--env-file", str(settings), *args],
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            if output.returncode:
                raise RuntimeError("Falló CLI " + " ".join(args[:2]))
            return output.stdout

        run("demo", "--headless", "--seconds", "3")
        results["checks"].append("CLI demo concurrente, configuración y cierre")
        assert run("--db", str(root / "demo.sqlite"), "status").strip()
        history = run("--db", str(root / "demo.sqlite"), "history")
        assert history.strip()
        results["checks"].append("Historial persistido tras reinicio")

        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        environment["ECHOSCOPE_DEMO_PORT"] = str(port)
        environment["ECHOSCOPE_ENV_FILE"] = str(settings)
        process = subprocess.Popen(
            [sys.executable, "-m", "echoscope.presentation.web", "--demo", "--no-browser"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def request(path, payload=None, token=None):
            headers = {"Origin": origin, "Content-Type": "application/json"}
            if token:
                headers["X-EchoScope-Token"] = token
            body = json.dumps(payload).encode() if payload is not None else None
            with opener.open(
                urllib.request.Request(origin + path, body, headers), timeout=5
            ) as response:
                return response.read()

        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    bootstrap = json.loads(request("/api/bootstrap"))
                    break
                except (OSError, urllib.error.URLError):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("No inició la interfaz web") from None
                    time.sleep(0.2)
            token = bootstrap["token"]
            request("/api/theme", {"value": "darkest"}, token)
            assert json.loads(request("/api/bootstrap"))["theme"] == "darkest"
            day = datetime.now(UTC).date().isoformat()
            for layout in ("brief", "complete"):
                assert request(
                    "/api/report", {"start": day, "end": day, "layout": layout}, token
                ).startswith(b"%PDF")
            results["checks"].append("HTTP local, configuración por entorno, temas y PDF")
            if os.name != "nt":
                process.send_signal(signal.SIGTERM)
            else:
                request("/api/shutdown", {}, token)
            assert process.wait(timeout=15) == 0
            results["checks"].append(
                "Cierre coordinado por SIGTERM"
                if os.name != "nt"
                else "Cierre coordinado por comando"
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
