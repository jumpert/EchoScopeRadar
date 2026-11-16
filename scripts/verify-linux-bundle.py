"""Offline smoke test of the distributed Linux artifact in a disposable container."""

import json
import os
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="echoscope-bundle-"))
archive = next(Path("/artifacts").glob("EchoScopeRadar-*-linux-x86_64.tar.gz"))
with tarfile.open(archive) as bundle:
    bundle.extractall(root, filter="data")
package = root / "EchoScopeRadar-linux-x86_64"
subprocess.run(["sh", "-n", str(package / "install-linux-service.sh")], check=True)
environment = os.environ | {"ECHOSCOPE_DATA_DIR": str(root / "data")}
worker = subprocess.Popen([str(package / "EchoScopeRadar"), "--demo", "--no-browser", "--port", "18765"],
                          env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try:
    endpoint = "http://127.0.0.1:18765"
    deadline = time.monotonic() + 30
    while True:
        try:
            with urllib.request.urlopen(endpoint + "/api/bootstrap", timeout=2) as response:
                bootstrap = json.load(response)
            break
        except (urllib.error.URLError, TimeoutError):
            if worker.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(worker.communicate(timeout=5)[0].decode())
            time.sleep(.2)
    assert bootstrap["version"] == "0.15.0" and bootstrap["practice"]
    time.sleep(2)
    request = urllib.request.Request(endpoint + "/api/data-storage", data=b"{}", headers={
        "Origin": endpoint, "Content-Type": "application/json",
        "X-EchoScope-Token": bootstrap["token"],
    })
    with urllib.request.urlopen(request, timeout=3) as response:
        stats = json.load(response)
    assert stats["counts"]["message_sources"] > 0
    request = urllib.request.Request(endpoint + "/api/shutdown", data=b"{}", headers={
        "Origin": endpoint, "Content-Type": "application/json",
        "X-EchoScope-Token": bootstrap["token"],
    })
    with urllib.request.urlopen(request, timeout=3) as response:
        response.read()
    worker.communicate(timeout=10)
    assert worker.returncode == 0
    print(json.dumps({"version": bootstrap["version"], "platform": "Linux x86_64",
                      "captures": stats["counts"]["message_sources"], "exit": worker.returncode,
                      "service_script_syntax": "ok"}))
finally:
    if worker.poll() is None:
        worker.terminate()
        worker.communicate(timeout=10)
