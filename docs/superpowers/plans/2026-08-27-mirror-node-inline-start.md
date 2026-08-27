# Mirror-node starten/stoppen vanaf de Spiegel-pagina Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Een Start/Stop-knop + live logpaneel op de Spiegel-pagina waarmee
je `mirror_node.main` headless (zonder beamer) kunt starten/stoppen als
kindproces van de beheerpagina-backend, om het spiegeleffect te
ontwerpen/testen tegen een netwerkcamera zonder SSH.

**Architecture:** De beheerpagina-backend (Docker) krijgt `mirror_node`'s
code en dependencies erbij en start het als eigen kindproces via
`subprocess.Popen` (`MIRROR_HEADLESS=1` geforceerd). Drie nieuwe,
auth-vereiste endpoints (`start`/`stop`/`status`). Subprocess-stdout wordt
regelsgewijs doorgestuurd via de al bestaande `WebSocketHub` (zelfde
berichtformaat als de huidige MQTT-logbroadcast), zodat de Spiegel-pagina
live logregels kan tonen zonder een nieuw transportmechanisme.

**Tech Stack:** Python (FastAPI, `subprocess`, `threading`), TypeScript/React.

**Spec:** `docs/superpowers/specs/2026-08-27-mirror-node-inline-start-design.md`

## Global Constraints

- `MIRROR_HEADLESS=1` wordt altijd geforceerd door het kindproces-commando
  zelf — geen instelbare optie, dit is uitsluitend voor ontwerp/test zonder
  hardware.
- Eén globale instantie: nogmaals starten terwijl het al draait, of stoppen
  terwijl het al stil staat, is idempotent (200, geen foutmelding).
- Geen automatisch herstarten bij een crash van het kindproces — `status()`
  detecteert dat het gestopt is, verder niets.
- Alle drie nieuwe endpoints (`/api/mirror-node/start|stop|status`) vereisen
  de bestaande sessie-auth — niet toevoegen aan `_PUBLIC_EXACT_PATHS` in
  `admin/app/main.py`.
- `opencv-python-headless` en `numpy` worden exact gepind op
  `4.9.0.80`/`1.24.4` in `admin/requirements.txt` — niet naar de nieuwste
  versies, want lan01 (het deploy-target) is een KVM-VM zonder SSSE3 en
  nieuwere numpy-wheels laden daar niet. Deze combinatie is al handmatig
  geverifieerd te werken op lan01.
- Geen wijziging aan `scare_node`, `mirror-node.service`, of hoe de échte
  Pi-gebaseerde node-deployment werkt.

---

### Task 1: MirrorProcessManager

**Files:**
- Create: `admin/app/mirror_process.py`
- Test: `tests/test_admin_mirror_process.py`

**Interfaces:**
- Produces: `MirrorProcessManager(settings, ws_hub=None, loop=None,
  log_dir="./logs")` met methoden `start() -> dict`, `stop() -> dict`,
  `status() -> dict` (elk `{"running": bool, "pid": int | None}`), en
  attribuut `_reader_thread` (voor Task 2 zelf niet nodig, maar door tests
  gebruikt om te wachten tot de leesthread klaar is). `log_dir` is niet
  hardcoded op `/data/logs` (dat pad bestaat alleen in de Docker-container)
  -- Task 2 geeft de backend's eigen, al juist resolvende `settings.log_dir`
  door.
- Consumes: `settings.mqtt_host`, `settings.mqtt_port`, `settings.mqtt_user`,
  `settings.mqtt_pass` (bestaande velden op `RuntimeSettings`, zie
  `admin/app/runtime_settings.py`).

- [ ] **Step 1: Schrijf `admin/app/mirror_process.py`**

```python
import asyncio
import os
import subprocess
import sys
import threading


class MirrorProcessManager:
    """Start/stopt mirror_node.main als kindproces van de beheerpagina-
    backend, puur voor ontwerp/test zonder fysieke node -- MIRROR_HEADLESS=1
    wordt altijd geforceerd. Zie
    docs/superpowers/specs/2026-08-27-mirror-node-inline-start-design.md."""

    def __init__(self, settings, ws_hub=None, loop=None, log_dir="./logs"):
        self._settings = settings
        self._ws_hub = ws_hub
        self._loop = loop
        self._log_dir = log_dir
        self._proc = None
        self._reader_thread = None

    def _running(self):
        return self._proc is not None and self._proc.poll() is None

    def start(self):
        if self._running():
            return self.status()
        env = {
            **os.environ,
            "MIRROR_HEADLESS": "1",
            "MQTT_HOST": self._settings.mqtt_host,
            "MQTT_PORT": str(self._settings.mqtt_port),
            "MQTT_USER": self._settings.mqtt_user,
            "MQTT_PASS": self._settings.mqtt_pass,
            "BACKEND_URL": "http://localhost:8000",
            "LOG_DIR": self._log_dir,
        }
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "mirror_node.main"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()
        return self.status()

    def stop(self):
        if not self._running():
            return self.status()
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        return self.status()

    def status(self):
        running = self._running()
        return {"running": running, "pid": self._proc.pid if running else None}

    def _read_output(self):
        for line in self._proc.stdout:
            self._broadcast(line.rstrip())

    def _broadcast(self, line):
        if self._ws_hub is None or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._ws_hub.broadcast({"type": "log", "topic": "process/mirror-node", "payload": line}),
            self._loop,
        )
```

- [ ] **Step 2: Schrijf `tests/test_admin_mirror_process.py`**

```python
from admin.app.mirror_process import MirrorProcessManager


class FakeSettings:
    mqtt_host = "localhost"
    mqtt_port = 1883
    mqtt_user = ""
    mqtt_pass = ""


class FakeProc:
    def __init__(self, pid=1234, lines=None):
        self.pid = pid
        self.stdout = iter(lines or [])
        self._terminated = False
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self._terminated = True
        self._returncode = 0

    def wait(self, timeout=None):
        return self._returncode

    def kill(self):
        self._returncode = -9


def test_start_spawns_process_with_expected_env(monkeypatch):
    captured = {}

    def fake_popen(cmd, env=None, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = env
        return FakeProc()

    monkeypatch.setattr("admin.app.mirror_process.subprocess.Popen", fake_popen)
    manager = MirrorProcessManager(FakeSettings())

    result = manager.start()

    assert result == {"running": True, "pid": 1234}
    assert captured["cmd"][1:] == ["-m", "mirror_node.main"]
    assert captured["env"]["MIRROR_HEADLESS"] == "1"
    assert captured["env"]["MQTT_HOST"] == "localhost"
    assert captured["env"]["MQTT_PORT"] == "1883"
    assert captured["env"]["BACKEND_URL"] == "http://localhost:8000"
    assert captured["env"]["LOG_DIR"] == "./logs"  # default, Task 2 geeft de echte settings.log_dir door


def test_start_twice_is_a_no_op(monkeypatch):
    calls = []

    def fake_popen(cmd, env=None, **kwargs):
        calls.append(1)
        return FakeProc()

    monkeypatch.setattr("admin.app.mirror_process.subprocess.Popen", fake_popen)
    manager = MirrorProcessManager(FakeSettings())

    manager.start()
    manager.start()

    assert len(calls) == 1


def test_stop_terminates_running_process(monkeypatch):
    proc = FakeProc()
    monkeypatch.setattr("admin.app.mirror_process.subprocess.Popen", lambda *a, **k: proc)
    manager = MirrorProcessManager(FakeSettings())
    manager.start()

    result = manager.stop()

    assert result == {"running": False, "pid": None}
    assert proc._terminated is True


def test_stop_when_not_running_is_a_no_op():
    manager = MirrorProcessManager(FakeSettings())

    result = manager.stop()

    assert result == {"running": False, "pid": None}


def test_status_detects_process_that_exited_on_its_own(monkeypatch):
    proc = FakeProc()
    monkeypatch.setattr("admin.app.mirror_process.subprocess.Popen", lambda *a, **k: proc)
    manager = MirrorProcessManager(FakeSettings())
    manager.start()

    proc._returncode = 1  # simuleert een proces dat zelfstandig is gestopt (bv. foute RTSP-URL)

    assert manager.status() == {"running": False, "pid": None}


def test_read_output_broadcasts_each_line():
    proc = FakeProc(lines=["mirror-node gestart\n", "mirror triggered\n"])
    manager = MirrorProcessManager(FakeSettings())
    manager._proc = proc
    broadcasts = []
    manager._broadcast = broadcasts.append

    manager._read_output()

    assert broadcasts == ["mirror-node gestart", "mirror triggered"]


def test_broadcast_is_noop_without_ws_hub():
    manager = MirrorProcessManager(FakeSettings())

    manager._broadcast("een regel")  # mag niet crashen zonder ws_hub/loop
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_admin_mirror_process.py -v`
Expected: 7 PASS.

- [ ] **Step 4: Commit**

```bash
git add admin/app/mirror_process.py tests/test_admin_mirror_process.py
git commit -m "feat: MirrorProcessManager -- start/stop mirror_node.main als kindproces"
```

---

### Task 2: Router + wiring in main.py

**Files:**
- Create: `admin/app/routers/mirror_process.py`
- Modify: `admin/app/main.py`
- Test: `tests/test_admin_routes_mirror_process.py`

**Interfaces:**
- Consumes: `MirrorProcessManager` van Task 1 (exacte methode-namen
  `start()`/`stop()`/`status()`, exacte return-vorm
  `{"running": bool, "pid": int | None}`).
- Produces: `POST /api/mirror-node/start`, `POST /api/mirror-node/stop`,
  `GET /api/mirror-node/status` -- alle drie geven de manager's return-dict
  direct terug als JSON.

- [ ] **Step 1: Schrijf `admin/app/routers/mirror_process.py`**

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/api/mirror-node/start")
def post_mirror_node_start(request: Request):
    return request.app.state.mirror_process.start()


@router.post("/api/mirror-node/stop")
def post_mirror_node_stop(request: Request):
    return request.app.state.mirror_process.stop()


@router.get("/api/mirror-node/status")
def get_mirror_node_status(request: Request):
    return request.app.state.mirror_process.status()
```

- [ ] **Step 2: Wire in `admin/app/main.py`**

Voeg de import toe bij de overige klasse-imports (naast de bestaande
`from admin.app.mqtt_bridge import MqttBridge`):

```python
from admin.app.mirror_process import MirrorProcessManager
```

en bij de router-imports (naast de bestaande `from admin.app.routers import
node_config as node_config_router`):

```python
from admin.app.routers import mirror_process as mirror_process_router
```

In `create_app()`, direct na de `app.state.bridge = MqttBridge(...)`-blok
(regel 64-66 in het huidige bestand):

```python
    app.state.mirror_process = MirrorProcessManager(
        app.state.runtime_settings,
        ws_hub=app.state.ws_hub,
        log_dir=os.path.join(settings.log_dir, "mirror-node"),
    )
```

(`settings` hier is de functie-parameter van `create_app(settings=None)` --
dezelfde `Settings`-instantie die verderop `app.state.settings` wordt, met
`log_dir` die al correct resolvt: `/data/logs` in Docker, `./logs` lokaal.
Niet de `RuntimeSettings`/`app.state.runtime_settings` die als eerste
positional argument gaat -- dat zijn twee verschillende objecten in deze
codebase.)

Bij de `app.include_router(...)`-regels, als laatste regel van dat blok
(ná `app.include_router(node_config_router.router)`):

```python
    app.include_router(mirror_process_router.router)
```

In `_startup()`, direct na de regel `app.state.bridge._loop =
asyncio.get_event_loop()`:

```python
        app.state.mirror_process._loop = asyncio.get_event_loop()
```

In `_shutdown()`, als laatste regel:

```python
        app.state.mirror_process.stop()
```

- [ ] **Step 3: Schrijf `tests/test_admin_routes_mirror_process.py`**

```python
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


class FakeMirrorProcess:
    def __init__(self):
        self.calls = []
        self._running = False

    def start(self):
        self.calls.append("start")
        self._running = True
        return {"running": True, "pid": 1234}

    def stop(self):
        self.calls.append("stop")
        self._running = False
        return {"running": False, "pid": None}

    def status(self):
        return {"running": self._running, "pid": 1234 if self._running else None}


def _settings(tmp_path):
    return Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"),
        media_dir=str(tmp_path / "media"),
        port=8000,
    )


def _client(tmp_path):
    app = create_app(settings=_settings(tmp_path))
    app.state.mirror_process = FakeMirrorProcess()
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app.state.mirror_process


def test_start_requires_auth(tmp_path):
    app = create_app(settings=_settings(tmp_path))
    app.state.mirror_process = FakeMirrorProcess()
    client = TestClient(app)  # geen login

    response = client.post("/api/mirror-node/start")

    assert response.status_code == 401


def test_start_calls_manager_and_returns_status(tmp_path):
    client, manager = _client(tmp_path)

    response = client.post("/api/mirror-node/start")

    assert response.status_code == 200
    assert response.json() == {"running": True, "pid": 1234}
    assert manager.calls == ["start"]


def test_stop_calls_manager_and_returns_status(tmp_path):
    client, manager = _client(tmp_path)
    client.post("/api/mirror-node/start")

    response = client.post("/api/mirror-node/stop")

    assert response.status_code == 200
    assert response.json() == {"running": False, "pid": None}
    assert manager.calls == ["start", "stop"]


def test_status_returns_current_state(tmp_path):
    client, manager = _client(tmp_path)

    response = client.get("/api/mirror-node/status")

    assert response.status_code == 200
    assert response.json() == {"running": False, "pid": None}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_admin_routes_mirror_process.py tests/test_admin_mirror_process.py -v`
Expected: alle PASS.

- [ ] **Step 5: Run de volledige suite (regressiecheck)**

Run: `pytest tests/ -q`
Expected: alle bestaande tests blijven ook slagen.

- [ ] **Step 6: Commit**

```bash
git add admin/app/routers/mirror_process.py admin/app/main.py tests/test_admin_routes_mirror_process.py
git commit -m "feat: /api/mirror-node/start|stop|status endpoints"
```

---

### Task 3: Docker-image krijgt mirror_node erbij

**Files:**
- Modify: `admin/requirements.txt`
- Modify: `Dockerfile`

**Interfaces:**
- Consumes: niets van eerdere tasks (onafhankelijk qua code, maar
  logisch ná Task 1/2 zodat het kindproces-commando ook echt bestaat).
- Produces: een Docker-image waarin `python -m mirror_node.main` werkt
  (dependencies + broncode aanwezig).

- [ ] **Step 1: Werk `admin/requirements.txt` bij**

Vervang de inhoud door:

```
fastapi
uvicorn[standard]
python-multipart
paho-mqtt
# Voor de "start mirror-node vanaf de Spiegel-pagina"-testfunctie (zie
# docs/superpowers/specs/2026-08-27-mirror-node-inline-start-design.md).
# Exact deze combinatie gepind: lan01 (huidige deploy-target) is een KVM-VM
# zonder SSSE3, nieuwere numpy-wheels laden daar niet (RuntimeError: NumPy
# was built with baseline optimizations ... X86_V2). Deze combinatie is al
# handmatig geverifieerd te werken (import + echte array-encode/decode) op
# lan01.
opencv-python-headless==4.9.0.80
numpy==1.24.4
```

- [ ] **Step 2: Werk `Dockerfile` bij**

Vervang de bovenste toelichtings-comment:

```dockerfile
# Multi-stage build voor de beheerpagina (backend + gebouwde frontend in één image).
# Mirror-node en scare-node draaien op hun eigen Pi's met camera/GPIO/audio-
# toegang en horen hier bewust niet bij — dit image is alleen de centrale
# beheerpagina.
```

door:

```dockerfile
# Multi-stage build voor de beheerpagina (backend + gebouwde frontend in één image).
# Scare-node draait op zijn eigen Pi met GPIO/audio-toegang en hoort hier
# bewust niet bij. mirror_node's code zit wél in dit image, maar alleen om
# 'm headless (MIRROR_HEADLESS=1) als test-/ontwerp-hulpmiddel te kunnen
# starten vanaf de Spiegel-pagina (zie admin/app/mirror_process.py) -- de
# échte node-deployment (Pi + beamer + systemd) blijft hier volledig los
# van staan.
```

En voeg, direct na `COPY shared/ ./shared/`, een nieuwe regel toe:

```dockerfile
COPY shared/ ./shared/
COPY mirror_node/ ./mirror_node/
COPY admin/app/ ./admin/app/
```

(de bestaande `COPY admin/app/ ./admin/app/`-regel blijft staan, alleen de
`mirror_node/`-regel is nieuw, ertussen.)

- [ ] **Step 3: Bouw het image en verifieer dat mirror_node importeert**

Run: `docker compose build`
Expected: bouwt zonder fouten.

Run: `docker compose run --rm beheerpagina python3 -c "import mirror_node.main; print('OK')"`
Expected: `OK` (geen `ModuleNotFoundError`, geen numpy-baseline-crash).

- [ ] **Step 4: Commit**

```bash
git add admin/requirements.txt Dockerfile
git commit -m "feat: mirror_node-code + headless-opencv/numpy in het beheerpagina-image"
```

---

### Task 4: Frontend API-client

**Files:**
- Create: `admin/frontend/src/api/mirrorProcess.ts`

**Interfaces:**
- Consumes: `apiFetch` van `./client` (bestaand, zie
  `admin/frontend/src/api/settings.ts` voor het patroon).
- Produces: `MirrorProcessStatus` type
  (`{ running: boolean; pid: number | null }`), en
  `startMirrorProcess()`, `stopMirrorProcess()`,
  `getMirrorProcessStatus()`, elk `Promise<MirrorProcessStatus>` -- gebruikt
  door Task 5.

- [ ] **Step 1: Schrijf `admin/frontend/src/api/mirrorProcess.ts`**

```typescript
import { apiFetch } from "./client";

export interface MirrorProcessStatus {
  running: boolean;
  pid: number | null;
}

export function startMirrorProcess(): Promise<MirrorProcessStatus> {
  return apiFetch<MirrorProcessStatus>("/api/mirror-node/start", { method: "POST" });
}

export function stopMirrorProcess(): Promise<MirrorProcessStatus> {
  return apiFetch<MirrorProcessStatus>("/api/mirror-node/stop", { method: "POST" });
}

export function getMirrorProcessStatus(): Promise<MirrorProcessStatus> {
  return apiFetch<MirrorProcessStatus>("/api/mirror-node/status");
}
```

- [ ] **Step 2: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: geen fouten.

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/api/mirrorProcess.ts
git commit -m "feat: frontend-API-client voor mirror-node start/stop/status"
```

---

### Task 5: Start/Stop-knop + logpaneel op de Spiegel-pagina

**Files:**
- Modify: `admin/frontend/src/pages/MirrorPage.tsx`
- Modify: `admin/frontend/src/pages/MirrorPage.css`

**Interfaces:**
- Consumes: `startMirrorProcess`, `stopMirrorProcess`,
  `getMirrorProcessStatus` van Task 4; bestaande `useWebSocket`-hook
  (`admin/frontend/src/hooks/useWebSocket.ts`) en `WsMessage`-type
  (`admin/frontend/src/types.ts`, al `{ type: "status" | "log"; topic:
  string; payload: string }`).

- [ ] **Step 1: Voeg imports toe aan `MirrorPage.tsx`**

Bovenaan het bestand, bij de bestaande imports:

```typescript
import { startMirrorProcess, stopMirrorProcess, getMirrorProcessStatus } from "../api/mirrorProcess";
import { useWebSocket } from "../hooks/useWebSocket";
import type { MirrorConfig, WsMessage } from "../types";
```

(vervangt de bestaande `import type { MirrorConfig } from "../types";`-regel.)

- [ ] **Step 2: Voeg state en effects toe binnen `MirrorPage()`**

Direct na de bestaande `const [streamUrl, setStreamUrl] = useState("");`:

```typescript
  const [running, setRunning] = useState(false);
  const [processBusy, setProcessBusy] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
```

In de bestaande eerste `useEffect` (die `getMirrorConfig`/`getSettings`
aanroept), voeg een derde call toe naast de bestaande twee:

```typescript
    getMirrorProcessStatus()
      .then((result) => setRunning(result.running))
      .catch(() => {
        /* status blijft "gestopt" tonen bij een netwerkfout */
      });
```

Voeg een nieuwe `useWebSocket`-call toe, na de bestaande `useEffect`-blokken
(vóór `function update(...)`):

```typescript
  useWebSocket((msg: WsMessage) => {
    if (msg.type === "log" && msg.topic === "process/mirror-node") {
      setLogLines((prev) => [...prev, msg.payload].slice(-200));
    }
  });
```

- [ ] **Step 3: Voeg handlers toe**

Na de bestaande `handleTest`-functie:

```typescript
  async function handleStartProcess() {
    setProcessBusy(true);
    try {
      const status = await startMirrorProcess();
      setRunning(status.running);
      setError(null);
    } catch {
      setError("Mirror-node starten is mislukt.");
    } finally {
      setProcessBusy(false);
    }
  }

  async function handleStopProcess() {
    setProcessBusy(true);
    try {
      const status = await stopMirrorProcess();
      setRunning(status.running);
      setError(null);
    } catch {
      setError("Mirror-node stoppen is mislukt.");
    } finally {
      setProcessBusy(false);
    }
  }
```

- [ ] **Step 4: Voeg de UI-sectie toe**

Direct vóór de bestaande `<section className="mirror-panel">` met
`Live preview` als eyebrow-tekst, voeg een nieuwe sectie toe:

```tsx
          <section className="mirror-panel">
            <p className="mirror-panel__eyebrow">Mirror-node testen (zonder hardware)</p>
            <div className="mirror-process-row">
              <span
                className={`mirror-process-status ${running ? "mirror-process-status--running" : ""}`}
              >
                {running ? "Draait" : "Gestopt"}
              </span>
              <button
                className="mirror-apply"
                type="button"
                onClick={handleStartProcess}
                disabled={processBusy || running}
              >
                {processBusy ? "Bezig…" : "Start"}
              </button>
              <button
                className="mirror-test"
                type="button"
                onClick={handleStopProcess}
                disabled={processBusy || !running}
              >
                {processBusy ? "Bezig…" : "Stop"}
              </button>
            </div>
            <pre className="mirror-process-log">
              {logLines.length
                ? logLines.join("\n")
                : "Nog geen logregels — start de mirror-node om ze hier te zien."}
            </pre>
          </section>

```

- [ ] **Step 5: Voeg CSS toe aan `MirrorPage.css`**

Aan het einde van het bestand, vóór de `@media (prefers-reduced-motion:
reduce)`-regel:

```css
.mirror-process-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
}

.mirror-process-status {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.75rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ash);
}

.mirror-process-status--running {
  color: var(--signal);
}

.mirror-process-log {
  max-height: 220px;
  overflow-y: auto;
  margin: 0;
  padding: 0.75rem 1rem;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--ash);
  white-space: pre-wrap;
  word-break: break-word;
}
```

- [ ] **Step 6: Build**

Run: `cd admin/frontend && npm run build`
Expected: succeeds, geen TypeScript-fouten.

- [ ] **Step 7: Commit**

```bash
git add admin/frontend/src/pages/MirrorPage.tsx admin/frontend/src/pages/MirrorPage.css
git commit -m "feat: Start/Stop-knop + live logpaneel op de Spiegel-pagina"
```

---

### Task 6: Whole-feature verification

**Files:** geen (alleen verificatie).

- [ ] **Step 1: Volledige backend-testsuite**

Run: `pytest tests/ -q`
Expected: alle tests PASS.

- [ ] **Step 2: Frontend build**

Run: `cd admin/frontend && npm run build`
Expected: succeeds, geen TypeScript-fouten.

- [ ] **Step 3: Lokale smoke-test — start/stop via curl**

Start de backend lokaal (`ADMIN_PASSWORD=devpass ADMIN_DB_PATH=/tmp/task6-smoke.db
LOG_DIR=/tmp/task6-logs MQTT_HOST=localhost python -m admin.run`), log in,
dan:

```bash
curl -s -b /tmp/task6-cookies.txt -X POST http://localhost:8000/api/mirror-node/start
curl -s -b /tmp/task6-cookies.txt http://localhost:8000/api/mirror-node/status
curl -s -b /tmp/task6-cookies.txt -X POST http://localhost:8000/api/mirror-node/stop
curl -s -b /tmp/task6-cookies.txt http://localhost:8000/api/mirror-node/status
```

Expected: eerste `status` toont `"running":true`, tweede toont
`"running":false`. (Lokaal draait `mirror_node.main` mogelijk meteen af
omdat er geen camera/RTSP-bron is -- dat is prima, de bedoeling van deze
stap is de start/stop-plumbing verifiëren, niet een echte stream.) Stop de
backend, ruim `/tmp/task6-smoke.db`, `/tmp/task6-cookies.txt`,
`/tmp/task6-logs` op.

- [ ] **Step 4: Verificatie tegen lan01 met de echte Reolink-stream**

Bouw en herstart de container op lan01 (`git pull && docker compose build
&& docker compose up -d`), open de Spiegel-pagina in de browser, klik
Start, en controleer:
- de statusindicator springt naar "Draait"
- er verschijnen logregels in het paneel (o.a. "mirror-node gestart")
- de live-preview (als `mirror_stream_url` correct staat ingesteld) toont
  het effect

Klik daarna Stop en controleer dat de status teruggaat naar "Gestopt".

- [ ] **Step 5: Eindreview**

Dispatch een eindreview over alle bestanden uit Tasks 1-5 (zelfde conventie
als eerdere plannen in deze repo): controleer specifiek dat
`_shutdown()` het kindproces altijd stopt (geen wees-proces na een
backend-herstart), dat de drie nieuwe endpoints geen van drie in
`_PUBLIC_EXACT_PATHS` terechtgekomen zijn, en dat er geen ongebruikte
`MirrorConfig`-import of andere lint-achtige rommel is achtergebleven in
`MirrorPage.tsx`.
