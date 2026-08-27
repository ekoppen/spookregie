# MQTT-topic-prefix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Een instelbaar MQTT-topic-prefix, beheerd op de Instellingen-pagina, die de backend meteen toepast en die elke node (mirror-node, scare-node) bij het opstarten automatisch ophaalt — zodat een test-opstelling en de echte installatie op dezelfde broker nooit meer in stilte dezelfde topics delen.

**Architecture:** `shared/mqtt_contract.py` wordt een `Topics`-klasse i.p.v. losse constanten; elk proces (backend, mirror-node, scare-node) bouwt er precies één instance van bij het opstarten. De backend is de bron van waarheid (nieuw veld in `RuntimeSettings`/`app_settings`); nodes halen de actuele prefix op via een nieuw publiek `GET /api/node-config`-endpoint, met terugval op hun eigen `MQTT_TOPIC_PREFIX`-env-var als de backend onbereikbaar is. De prefix wordt op precies één plek gestript (`MqttBridge._on_message`, vóór de tracker/WebSocket-broadcast) zodat dashboard, logs-pagina en de node-status-tracker nooit een geprefixt topic zien.

**Tech Stack:** Python (FastAPI-backend, paho-mqtt in alle drie de processen), React/TypeScript-frontend, pytest, `urllib.request` voor de node→backend-HTTP-call (geen nieuwe dependency, zelfde patroon als `admin/app/ha_client.py`).

**Spec:** `docs/superpowers/specs/2026-08-27-mqtt-topic-prefix-design.md`

## Global Constraints

- Default prefix is `""` (leeg) overal — bestaande deployments blijven functioneel ongewijzigd totdat iemand expliciet een prefix instelt.
- Geen live-herconfiguratie van nodes — een prefix-wijziging vraagt een herstart van elke node om 'm op te pikken. Geen polling.
- `/api/node-config` is publiek (geen sessie-auth) en retourneert uitsluitend `{"mqtt_topic_prefix": "..."}` — geen MQTT-host/poort/credentials.
- Prefix-validatie bij `PUT /api/settings`: geen `#` of `+` toegestaan (MQTT-wildcardtekens) — `400` anders, niets weggeschreven.
- `admin/app/mqtt_state.py` en de hele frontend (behalve de Instellingen-pagina zelf) blijven ongewijzigd — de prefix wordt vóór hen al gestript.
- Fetch-met-terugval naar de backend gooit nooit een uitzondering naar de aanroeper — bij twijfel altijd de lokale env-var-fallback, consistent met de fail-safe-filosofie van de nodes.

---

## Task 1: `shared/mqtt_contract.py` → `Topics`-klasse, `shared/logging_setup.py` ontkoppelen

**Files:**
- Modify: `shared/mqtt_contract.py`
- Modify: `shared/logging_setup.py`
- Modify: `tests/test_mqtt_contract.py`
- Modify: `tests/test_logging_setup.py`

**Interfaces:**
- Produces: `Topics` (class, constructor `Topics(prefix: str = "")`, met properties
  `mirror_triggered`, `system_sleep`, `config_mirror`, `control_mirror_preview`,
  `control_mirror_test`, `status_wildcard`, `log_wildcard`,
  `scare_triggered_wildcard`, en methoden `scare(zone)`, `log(node)`,
  `status(node)`, `config_scare(zone)`, `control_scare_test(zone)`,
  `strip_prefix(topic)`), `SLEEP_PAYLOAD_ON`, `SLEEP_PAYLOAD_OFF`,
  `trigger_payload()` (ongewijzigd) — gebruikt door Task 4 (mqtt_bridge),
  Task 8/9 (nodes). `setup_logging(node_name, log_dir, mqtt_client=None,
  mqtt_log_topic=None)` — gebruikt door Task 8/9.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_mqtt_contract.py` entirely:

```python
import json
from shared.mqtt_contract import SLEEP_PAYLOAD_OFF, SLEEP_PAYLOAD_ON, Topics, trigger_payload


def test_topics_without_prefix_match_bare_names():
    topics = Topics()
    assert topics.mirror_triggered == "mirror/triggered"
    assert topics.system_sleep == "system/sleep"
    assert topics.config_mirror == "config/mirror"
    assert topics.control_mirror_preview == "control/mirror/preview"
    assert topics.control_mirror_test == "control/mirror/test-trigger"
    assert topics.status_wildcard == "status/+"
    assert topics.log_wildcard == "log/+"
    assert topics.scare_triggered_wildcard == "scare/+/triggered"


def test_topics_with_prefix_prepends_prefix():
    topics = Topics(prefix="test")
    assert topics.mirror_triggered == "test/mirror/triggered"
    assert topics.system_sleep == "test/system/sleep"
    assert topics.status_wildcard == "test/status/+"


def test_topics_prefix_strips_trailing_slash():
    topics = Topics(prefix="test/")
    assert topics.mirror_triggered == "test/mirror/triggered"


def test_scare_topic_formats_zone():
    assert Topics().scare("zone-a") == "scare/zone-a/triggered"
    assert Topics(prefix="test").scare("zone-a") == "test/scare/zone-a/triggered"


def test_log_topic_formats_node():
    assert Topics().log("mirror") == "log/mirror"


def test_status_topic_formats_node():
    assert Topics().status("mirror") == "status/mirror"
    assert Topics().status("scare-zone-a") == "status/scare-zone-a"


def test_config_scare_topic_formats_zone():
    assert Topics().config_scare("zone-a") == "config/scare/zone-a"


def test_control_scare_test_topic_formats_zone():
    assert Topics().control_scare_test("zone-a") == "control/scare/zone-a/test-trigger"


def test_strip_prefix_removes_configured_prefix():
    topics = Topics(prefix="test")
    assert topics.strip_prefix("test/status/mirror") == "status/mirror"


def test_strip_prefix_without_prefix_is_noop():
    topics = Topics()
    assert topics.strip_prefix("status/mirror") == "status/mirror"


def test_strip_prefix_leaves_unrelated_topic_unchanged():
    topics = Topics(prefix="test")
    assert topics.strip_prefix("other/status/mirror") == "other/status/mirror"


def test_sleep_payload_vocabulary():
    # Moet exact overeenkomen met home_assistant/automations/time_window.yaml.
    assert SLEEP_PAYLOAD_ON == "on"
    assert SLEEP_PAYLOAD_OFF == "off"


def test_trigger_payload_is_json_with_timestamp():
    payload = json.loads(trigger_payload())
    assert "ts" in payload
    assert isinstance(payload["ts"], float)
```

Update `tests/test_logging_setup.py`: change
`test_setup_logging_publishes_to_mqtt_when_client_given` (currently the only
test relying on `setup_logging` auto-computing the MQTT topic) to pass the
topic explicitly. Replace:

```python
def test_setup_logging_publishes_to_mqtt_when_client_given(tmp_path):
    fake_client = FakeMqttClient()
    logger = setup_logging("test-node-mqtt", str(tmp_path), mqtt_client=fake_client)
    logger.info("hello")

    assert len(fake_client.published) == 1
    topic, payload = fake_client.published[0]
    assert topic == "log/test-node-mqtt"
    data = json.loads(payload)
    assert data["msg"] == "hello"
    assert data["level"] == "INFO"
```

with:

```python
def test_setup_logging_publishes_to_mqtt_when_client_given(tmp_path):
    fake_client = FakeMqttClient()
    logger = setup_logging(
        "test-node-mqtt", str(tmp_path), mqtt_client=fake_client, mqtt_log_topic="log/test-node-mqtt"
    )
    logger.info("hello")

    assert len(fake_client.published) == 1
    topic, payload = fake_client.published[0]
    assert topic == "log/test-node-mqtt"
    data = json.loads(payload)
    assert data["msg"] == "hello"
    assert data["level"] == "INFO"


def test_setup_logging_skips_mqtt_handler_without_topic(tmp_path):
    fake_client = FakeMqttClient()
    logger = setup_logging("test-node-no-topic", str(tmp_path), mqtt_client=fake_client)
    logger.info("hello")

    assert fake_client.published == []
```

The other three tests in that file (`test_setup_logging_writes_to_file`,
`test_mqtt_log_handler_emit_publishes_json`, and the dedup test) are
unaffected — leave them exactly as they are.

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_mqtt_contract.py tests/test_logging_setup.py -v`
Expected: FAIL — `ImportError: cannot import name 'Topics'` and
`TypeError: setup_logging() got an unexpected keyword argument 'mqtt_log_topic'`

- [ ] **Step 3: Rewrite `shared/mqtt_contract.py`**

Replace the whole file:

```python
import json
import time


class Topics:
    """Bouwt alle MQTT-topics van dit project op, optioneel onder een
    gedeelde namespace-prefix. Elk proces (backend, mirror-node, scare-node)
    maakt precies één instance bij het opstarten en gebruikt die overal --
    nooit losse string-concatenatie op meerdere plekken."""

    def __init__(self, prefix: str = ""):
        self._prefix = prefix.strip("/")

    def _p(self, topic: str) -> str:
        return f"{self._prefix}/{topic}" if self._prefix else topic

    @property
    def mirror_triggered(self) -> str:
        return self._p("mirror/triggered")

    @property
    def system_sleep(self) -> str:
        return self._p("system/sleep")

    @property
    def config_mirror(self) -> str:
        return self._p("config/mirror")

    @property
    def control_mirror_preview(self) -> str:
        return self._p("control/mirror/preview")

    @property
    def control_mirror_test(self) -> str:
        return self._p("control/mirror/test-trigger")

    @property
    def status_wildcard(self) -> str:
        return self._p("status/+")

    @property
    def log_wildcard(self) -> str:
        return self._p("log/+")

    @property
    def scare_triggered_wildcard(self) -> str:
        return self._p("scare/+/triggered")

    def scare(self, zone: str) -> str:
        return self._p(f"scare/{zone}/triggered")

    def log(self, node: str) -> str:
        return self._p(f"log/{node}")

    def status(self, node: str) -> str:
        """Topic voor online/offline-status van een node (MQTT last-will)."""
        return self._p(f"status/{node}")

    def config_scare(self, zone: str) -> str:
        return self._p(f"config/scare/{zone}")

    def control_scare_test(self, zone: str) -> str:
        return self._p(f"control/scare/{zone}/test-trigger")

    def strip_prefix(self, topic: str) -> str:
        """Geeft het topic terug zonder de geconfigureerde prefix. Voor
        logica die op de kale topic-naam matcht (node-tracker, WS-broadcast)
        -- die code hoeft nooit te weten dát er een prefix is."""
        if self._prefix and topic.startswith(f"{self._prefix}/"):
            return topic[len(self._prefix) + 1:]
        return topic


# Payloads op Topics().system_sleep. Home Assistant publiceert deze exacte
# waarden (zie home_assistant/automations/time_window.yaml).
SLEEP_PAYLOAD_ON = "on"
SLEEP_PAYLOAD_OFF = "off"


def trigger_payload():
    """JSON payload voor een 'iets is getriggerd'-bericht."""
    return json.dumps({"ts": time.time()})
```

- [ ] **Step 4: Decouple `shared/logging_setup.py`**

Replace the whole file:

```python
import json
import logging
import os
import time


class MqttLogHandler(logging.Handler):
    def __init__(self, mqtt_client, topic):
        super().__init__()
        self.mqtt_client = mqtt_client
        self.topic = topic

    def emit(self, record):
        payload = json.dumps({
            "ts": time.time(),
            "level": record.levelname,
            "msg": self.format(record),
        })
        self.mqtt_client.publish(self.topic, payload)


def setup_logging(node_name, log_dir, mqtt_client=None, mqtt_log_topic=None):
    """Logger die altijd lokaal naar bestand schrijft, en optioneel
    meepublicceert naar MQTT (het topic dat de aanroeper meegeeft) zodat je
    tijdens ontwikkeling alle nodes centraal kunt meelezen. Bouwt het
    MQTT-topic zelf niet op -- de aanroeper kent zijn eigen topic-prefix,
    deze module niet."""
    logger = logging.getLogger(node_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()  # voorkomt dubbele handlers bij herhaald aanroepen

    file_handler = logging.FileHandler(os.path.join(log_dir, f"{node_name}.log"))
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)

    if mqtt_client is not None and mqtt_log_topic is not None:
        logger.addHandler(MqttLogHandler(mqtt_client, mqtt_log_topic))

    return logger
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_mqtt_contract.py tests/test_logging_setup.py -v`
Expected: PASS (11 + 5 tests)

- [ ] **Step 6: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: Several failures — `mirror_node/main.py`, `scare_node/main.py`,
`admin/app/mqtt_bridge.py`, and `admin/app/main.py`'s `setup_logging(...)`
call still use the old API. That's expected; Tasks 3-9 fix each. Confirm
the failures are ONLY in those files (via the pytest summary), nothing else
regressed.

- [ ] **Step 7: Commit**

```bash
git add shared/mqtt_contract.py shared/logging_setup.py tests/test_mqtt_contract.py tests/test_logging_setup.py
git commit -m "refactor: mqtt_contract wordt Topics-klasse, logging_setup ontkoppeld van het contract"
```

---

## Task 2: `shared/topic_prefix.py` — fetch-met-terugval

**Files:**
- Create: `shared/topic_prefix.py`
- Test: `tests/test_topic_prefix.py`

**Interfaces:**
- Consumes: niets uit eerdere tasks.
- Produces: `fetch_topic_prefix(backend_url: str, fallback: str, fetch=None, timeout=3) -> str`
  — gebruikt door Task 8/9 (nodes).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_topic_prefix.py`:

```python
from shared.topic_prefix import fetch_topic_prefix


def test_fetch_topic_prefix_returns_backend_value():
    def fake_fetch(url, timeout):
        assert url == "http://backend:8000/api/node-config"
        return b'{"mqtt_topic_prefix": "test"}'

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=fake_fetch)

    assert result == "test"


def test_fetch_topic_prefix_returns_empty_string_prefix_correctly():
    # Een backend zonder ingestelde prefix geeft expliciet "" terug -- dat
    # is een geldig antwoord, geen fout, en moet NIET op de fallback vallen.
    def empty_prefix_fetch(url, timeout):
        return b'{"mqtt_topic_prefix": ""}'

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=empty_prefix_fetch)

    assert result == ""


def test_fetch_topic_prefix_falls_back_on_connection_error():
    def failing_fetch(url, timeout):
        raise OSError("onbereikbaar")

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=failing_fetch)

    assert result == "fallback"


def test_fetch_topic_prefix_falls_back_on_malformed_json():
    def bad_fetch(url, timeout):
        return b"not json"

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=bad_fetch)

    assert result == "fallback"


def test_fetch_topic_prefix_falls_back_when_field_missing():
    def missing_field_fetch(url, timeout):
        return b"{}"

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=missing_field_fetch)

    assert result == "fallback"


def test_fetch_topic_prefix_falls_back_when_field_wrong_type():
    def wrong_type_fetch(url, timeout):
        return b'{"mqtt_topic_prefix": 123}'

    result = fetch_topic_prefix("http://backend:8000", fallback="fallback", fetch=wrong_type_fetch)

    assert result == "fallback"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_topic_prefix.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.topic_prefix'`

- [ ] **Step 3: Create `shared/topic_prefix.py`**

```python
import json
import urllib.request


def _default_fetch(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def fetch_topic_prefix(backend_url, fallback, fetch=None, timeout=3):
    """Haalt de actuele MQTT-topic-prefix op bij de backend
    (`GET {backend_url}/api/node-config`). Lukt dat niet (backend
    onbereikbaar, ongeldig antwoord, verkeerd veldtype), dan `fallback` --
    nooit een uitzondering naar de aanroeper, consistent met de fail-safe-
    filosofie van de nodes (zelfstandig blijven werken zonder backend)."""
    fetch = fetch or _default_fetch
    try:
        data = fetch(f"{backend_url}/api/node-config", timeout)
        parsed = json.loads(data)
        prefix = parsed.get("mqtt_topic_prefix")
        if isinstance(prefix, str):
            return prefix
        return fallback
    except Exception:
        return fallback
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_topic_prefix.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add shared/topic_prefix.py tests/test_topic_prefix.py
git commit -m "feat: fetch_topic_prefix -- nodes halen de topic-prefix op bij de backend, met terugval"
```

---

## Task 3: Backend — `mqtt_topic_prefix` in `RuntimeSettings`/`app_settings`

**Files:**
- Modify: `admin/app/db.py`
- Modify: `admin/app/runtime_settings.py`
- Modify: `tests/test_admin_runtime_settings.py`

**Interfaces:**
- Consumes: niets uit eerdere tasks.
- Produces: `RuntimeSettings.mqtt_topic_prefix: str` (default `""`) — gebruikt
  door Task 4 (mqtt_bridge), Task 5 (routers/settings), Task 6
  (routers/node_config).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_admin_runtime_settings.py`:

```python
def test_read_without_row_falls_back_to_env_for_topic_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_TOPIC_PREFIX", "env-prefix")
    conn = init_db(str(tmp_path / "test.db"))

    settings = read_runtime_settings(conn)

    assert settings.mqtt_topic_prefix == "env-prefix"


def test_read_without_row_defaults_topic_prefix_to_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("MQTT_TOPIC_PREFIX", raising=False)
    conn = init_db(str(tmp_path / "test.db"))

    settings = read_runtime_settings(conn)

    assert settings.mqtt_topic_prefix == ""


def test_write_then_read_roundtrip_topic_prefix(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    write_runtime_settings(conn, mqtt_topic_prefix="test")
    settings = read_runtime_settings(conn)

    assert settings.mqtt_topic_prefix == "test"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_admin_runtime_settings.py -v`
Expected: FAIL — `TypeError: RuntimeSettings.__init__() got an unexpected
keyword argument 'mqtt_topic_prefix'` (or `AttributeError` on the assertion)

- [ ] **Step 3: Add the column to `admin/app/db.py`**

In the `app_settings` table definition, add `mqtt_topic_prefix` as the last
column:

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mqtt_host TEXT NOT NULL,
            mqtt_port INTEGER NOT NULL,
            mqtt_user TEXT NOT NULL DEFAULT '',
            mqtt_pass TEXT NOT NULL DEFAULT '',
            ha_url TEXT NOT NULL,
            ha_token TEXT NOT NULL DEFAULT '',
            mirror_stream_url TEXT NOT NULL DEFAULT '',
            mqtt_topic_prefix TEXT NOT NULL DEFAULT ''
        )"""
    )
```

- [ ] **Step 4: Update `admin/app/runtime_settings.py`**

Replace the whole file:

```python
import os
from dataclasses import asdict, dataclass


@dataclass
class RuntimeSettings:
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_pass: str
    ha_url: str
    ha_token: str
    mirror_stream_url: str
    mqtt_topic_prefix: str = ""


def _env_defaults() -> RuntimeSettings:
    """Zelfde variabelenamen/defaults als config.get_settings() vroeger
    gebruikte voor deze velden -- alleen gelezen zolang er nog geen
    app_settings-rij is (eerste-opstart-seed van een bestaande deploy)."""
    return RuntimeSettings(
        mqtt_host=os.environ.get("MQTT_HOST", "homeassistant.local"),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        mqtt_user=os.environ.get("MQTT_USER", ""),
        mqtt_pass=os.environ.get("MQTT_PASS", ""),
        ha_url=os.environ.get("HA_URL", "http://homeassistant.local:8123"),
        ha_token=os.environ.get("HA_TOKEN", ""),
        mirror_stream_url="",
        mqtt_topic_prefix=os.environ.get("MQTT_TOPIC_PREFIX", ""),
    )


def read_runtime_settings(conn) -> RuntimeSettings:
    row = conn.execute(
        "SELECT mqtt_host, mqtt_port, mqtt_user, mqtt_pass, ha_url, ha_token, mirror_stream_url, "
        "mqtt_topic_prefix FROM app_settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return _env_defaults()
    return RuntimeSettings(*row)


def write_runtime_settings(conn, **updates) -> RuntimeSettings:
    """Overschrijft alleen de meegegeven velden t.o.v. de huidige effectieve
    waarden (DB-rij, of env-defaults als er nog geen rij is) en persisteert
    de volledige rij -- zelfde aanpak als put_mirror_config."""
    current = read_runtime_settings(conn)
    result = RuntimeSettings(**{**asdict(current), **updates})
    conn.execute(
        """INSERT INTO app_settings
               (id, mqtt_host, mqtt_port, mqtt_user, mqtt_pass, ha_url, ha_token, mirror_stream_url,
                mqtt_topic_prefix)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               mqtt_host=excluded.mqtt_host, mqtt_port=excluded.mqtt_port,
               mqtt_user=excluded.mqtt_user, mqtt_pass=excluded.mqtt_pass,
               ha_url=excluded.ha_url, ha_token=excluded.ha_token,
               mirror_stream_url=excluded.mirror_stream_url,
               mqtt_topic_prefix=excluded.mqtt_topic_prefix""",
        (
            result.mqtt_host, result.mqtt_port, result.mqtt_user, result.mqtt_pass,
            result.ha_url, result.ha_token, result.mirror_stream_url, result.mqtt_topic_prefix,
        ),
    )
    conn.commit()
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_admin_runtime_settings.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: Same set of pre-existing failures as after Task 1 (mirror_node,
scare_node, mqtt_bridge, admin/app/main.py's old `setup_logging` call) —
nothing new broken by this task. `RuntimeSettings.mqtt_topic_prefix`
defaults to `""`, so no other existing test that constructs
`RuntimeSettings(...)` directly needs updating.

- [ ] **Step 7: Commit**

```bash
git add admin/app/db.py admin/app/runtime_settings.py tests/test_admin_runtime_settings.py
git commit -m "feat: mqtt_topic_prefix-veld in RuntimeSettings/app_settings"
```

---

## Task 4: Backend — `MqttBridge` gebruikt `Topics`, strip prefix bij ontvangst

**Files:**
- Modify: `admin/app/mqtt_bridge.py`
- Modify: `tests/test_admin_mqtt_bridge.py`

**Interfaces:**
- Consumes: `Topics` (Task 1), `RuntimeSettings.mqtt_topic_prefix` (Task 3).
- Produces: geen nieuwe publieke interface — `MqttBridge`'s bestaande
  publieke methoden (`publish_mirror_config`, `publish_scare_config`, ...)
  blijven signatuur-gelijk, alleen hun interne topic-opbouw verandert.

- [ ] **Step 1: Write the failing tests**

Update `tests/test_admin_mqtt_bridge.py`'s `_settings()` helper to allow a
`mqtt_topic_prefix` override (the field already defaults to `""`, so
existing calls need no change), and add new tests. Add these three tests to
the file:

```python
def test_start_subscribes_with_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())
    bridge.start()
    bridge._on_connect(bridge._client, None, None, 0)

    assert bridge._client.subscribed == [
        "test/status/+", "test/log/+", "test/mirror/triggered", "test/scare/+/triggered"
    ]


def test_publish_mirror_config_uses_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())

    bridge.publish_mirror_config({"effect": "xray"})

    assert bridge._client.published[-1][0] == "test/config/mirror"


def test_on_message_strips_prefix_before_tracker_and_broadcast(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    class FakeTracker:
        def __init__(self):
            self.calls = []

        def handle_message(self, topic, payload):
            self.calls.append((topic, payload))

    tracker = FakeTracker()
    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=tracker)

    class FakeMsg:
        topic = "test/status/mirror"
        payload = b"online"

    bridge._on_message(bridge._client, None, FakeMsg())

    assert tracker.calls == [("status/mirror", "online")]
```

These tests need `FakeMqttClient` to record `subscribe`/`publish` calls.
Update the `FakeMqttClient` class at the top of the file — add two lists and
two methods:

```python
class FakeMqttClient:
    instances = []

    def __init__(self, client_id=None):
        self.client_id = client_id
        self.username = None
        self.password = None
        self.connected_to = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.subscribed = []
        self.published = []
        FakeMqttClient.instances.append(self)

    def username_pw_set(self, username, password):
        self.username = username
        self.password = password

    def reconnect_delay_set(self, min_delay=1, max_delay=30):
        pass

    def connect_async(self, host, port):
        self.connected_to = (host, port)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def publish(self, topic, payload=None, retain=False):
        self.published.append((topic, payload, retain))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_admin_mqtt_bridge.py -v`
Expected: FAIL — `AttributeError: 'RuntimeSettings' object has no attribute
'mqtt_topic_prefix'` is already fixed by Task 3, so instead expect failures
from `MqttBridge` still using the old `TOPIC_*` constants/bare strings (no
`test/` prefix applied) and `_on_message` not stripping anything.

- [ ] **Step 3: Update `admin/app/mqtt_bridge.py`**

Replace the whole file:

```python
import asyncio
import json

import paho.mqtt.client as mqtt

from shared.mqtt_contract import SLEEP_PAYLOAD_ON, SLEEP_PAYLOAD_OFF, Topics


class MqttBridge:
    """Verbindt de backend met dezelfde broker als de nodes. Leest
    status/log/trigger-topics door naar de NodeStatusTracker (en, als
    `ws_hub`/`loop` zijn ingesteld, ook live naar verbonden browsers via
    WebSocket); publiceert config/control-berichten wanneer de beheerpagina
    iets wijzigt. Alle topics lopen door een `Topics`-instance, gebouwd uit
    `settings.mqtt_topic_prefix` -- zie shared/mqtt_contract.py."""

    def __init__(self, settings, tracker, ws_hub=None, loop=None, logger=None):
        self._settings = settings
        self._tracker = tracker
        self._ws_hub = ws_hub
        self._loop = loop
        self._logger = logger
        self._topics = Topics(prefix=settings.mqtt_topic_prefix)
        self._client = self._build_client(settings)

    def _build_client(self, settings):
        client = mqtt.Client(client_id="beheerpagina-backend")
        if settings.mqtt_user:
            client.username_pw_set(settings.mqtt_user, settings.mqtt_pass)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        return client

    def _log(self, level, msg, *args):
        if self._logger is not None:
            getattr(self._logger, level)(msg, *args)

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            # Zonder deze regel is een mislukte broker-verbinding volledig
            # onzichtbaar: de beheerpagina lijkt te werken, maar niets komt aan.
            self._log("error", "MQTT-verbinding mislukt (rc=%s: %s)", rc, mqtt.connack_string(rc))
            return
        self._log("info", "verbonden met MQTT-broker %s", self._settings.mqtt_host)
        client.subscribe(self._topics.status_wildcard)
        client.subscribe(self._topics.log_wildcard)
        client.subscribe(self._topics.mirror_triggered)
        client.subscribe(self._topics.scare_triggered_wildcard)

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            self._log("warning", "MQTT-verbinding verbroken (rc=%s), paho probeert opnieuw", rc)

    def _on_message(self, client, userdata, msg):
        try:
            topic = self._topics.strip_prefix(msg.topic)
            payload = msg.payload.decode()
            self._tracker.handle_message(topic, payload)
            self._broadcast_to_websockets(topic, payload)
        except Exception:
            pass  # nooit de MQTT-netwerkthread laten crashen

    def _broadcast_to_websockets(self, topic, payload):
        if self._ws_hub is None or self._loop is None:
            return
        if topic.startswith("status/"):
            kind = "status"
        elif topic.startswith("log/"):
            kind = "log"
        else:
            return
        asyncio.run_coroutine_threadsafe(
            self._ws_hub.broadcast({"type": kind, "topic": topic, "payload": payload}),
            self._loop,
        )

    def start(self):
        self._client.connect_async(self._settings.mqtt_host, self._settings.mqtt_port)
        self._client.loop_start()

    def stop(self):
        self._client.loop_stop()

    def reconfigure(self, settings):
        """Herverbindt met nieuwe broker-instellingen zonder het hele proces
        te herstarten -- aangeroepen na een succesvolle PUT /api/settings."""
        self._settings = settings
        self._topics = Topics(prefix=settings.mqtt_topic_prefix)
        self._client.loop_stop()
        self._client.disconnect()
        self._client = self._build_client(settings)
        self.start()

    def publish_mirror_config(self, config):
        self._client.publish(self._topics.config_mirror, json.dumps(config), retain=True)

    def publish_mirror_preview(self, config):
        self._client.publish(self._topics.control_mirror_preview, json.dumps(config))

    def publish_mirror_test(self):
        self._client.publish(self._topics.control_mirror_test, "{}")

    def publish_scare_config(self, zone, enabled_hashes):
        self._client.publish(
            self._topics.config_scare(zone),
            json.dumps({"enabled_hashes": enabled_hashes}),
            retain=True,
        )

    def publish_scare_test(self, zone):
        self._client.publish(self._topics.control_scare_test(zone), "{}")

    def publish_sleep(self, is_sleeping):
        payload = SLEEP_PAYLOAD_ON if is_sleeping else SLEEP_PAYLOAD_OFF
        self._client.publish(self._topics.system_sleep, payload, retain=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_admin_mqtt_bridge.py -v`
Expected: PASS (5 tests — 2 pre-existing + 3 new)

- [ ] **Step 5: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: Only `mirror_node`/`scare_node`-related tests still fail (fixed in
Tasks 8, 9) — confirm no NEW failures beyond what Task 1 already left.

- [ ] **Step 6: Commit**

```bash
git add admin/app/mqtt_bridge.py tests/test_admin_mqtt_bridge.py
git commit -m "feat: MqttBridge gebruikt Topics, strip topic-prefix bij ontvangst"
```

---

## Task 5: Backend — `mqtt_topic_prefix` in `/api/settings`

**Files:**
- Modify: `admin/app/routers/settings.py`
- Modify: `tests/test_admin_routes_settings.py`

**Interfaces:**
- Consumes: `RuntimeSettings.mqtt_topic_prefix` (Task 3).
- Produces: `GET`/`PUT /api/settings` responsebody krijgt het veld
  `mqtt_topic_prefix` — gebruikt door Task 7 (frontend).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_admin_routes_settings.py`:

```python
def test_get_settings_includes_topic_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_TOPIC_PREFIX", "seed-prefix")
    client, app, _ = _client(tmp_path)

    response = client.get("/api/settings")

    assert response.json()["mqtt_topic_prefix"] == "seed-prefix"


def test_put_settings_persists_topic_prefix(tmp_path):
    client, app, bridge = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883,
        "mqtt_topic_prefix": "test",
    })

    assert response.status_code == 200
    assert bridge.reconfigured_with.mqtt_topic_prefix == "test"
    assert client.get("/api/settings").json()["mqtt_topic_prefix"] == "test"


def test_put_settings_rejects_hash_in_topic_prefix(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_topic_prefix": "test#",
    })

    assert response.status_code == 400


def test_put_settings_rejects_plus_in_topic_prefix(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_topic_prefix": "te+st",
    })

    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_admin_routes_settings.py -v`
Expected: FAIL — `mqtt_topic_prefix` missing from the `GET` response, and no
validation rejects `#`/`+` yet.

- [ ] **Step 3: Update `admin/app/routers/settings.py`**

Replace the whole file:

```python
from fastapi import APIRouter, HTTPException, Request

from admin.app.runtime_settings import read_runtime_settings, write_runtime_settings

router = APIRouter()


def _validate_url(value, field_name):
    if value and not (value.startswith("http://") or value.startswith("https://")):
        raise HTTPException(status_code=400, detail=f"{field_name} moet leeg zijn of met http(s):// beginnen")


def _validate_topic_prefix(value):
    if "#" in value or "+" in value:
        raise HTTPException(status_code=400, detail="mqtt_topic_prefix mag geen # of + bevatten")


@router.get("/api/settings")
def get_settings_route(request: Request):
    settings = read_runtime_settings(request.app.state.db)
    return {
        "mqtt_host": settings.mqtt_host,
        "mqtt_port": settings.mqtt_port,
        "mqtt_user": settings.mqtt_user,
        "ha_url": settings.ha_url,
        "mirror_stream_url": settings.mirror_stream_url,
        "mqtt_topic_prefix": settings.mqtt_topic_prefix,
        "mqtt_pass_set": bool(settings.mqtt_pass),
        "ha_token_set": bool(settings.ha_token),
    }


@router.put("/api/settings")
async def put_settings_route(request: Request):
    body = await request.json()

    mqtt_host = str(body.get("mqtt_host", "")).strip()
    if not mqtt_host:
        raise HTTPException(status_code=400, detail="mqtt_host mag niet leeg zijn")

    try:
        mqtt_port = int(body.get("mqtt_port"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="mqtt_port moet een getal zijn")
    if not (1 <= mqtt_port <= 65535):
        raise HTTPException(status_code=400, detail="mqtt_port moet tussen 1 en 65535 liggen")

    ha_url = str(body.get("ha_url", "")).strip()
    mirror_stream_url = str(body.get("mirror_stream_url", "")).strip()
    _validate_url(ha_url, "ha_url")
    _validate_url(mirror_stream_url, "mirror_stream_url")

    mqtt_topic_prefix = str(body.get("mqtt_topic_prefix", "")).strip()
    _validate_topic_prefix(mqtt_topic_prefix)

    updates = {
        "mqtt_host": mqtt_host,
        "mqtt_port": mqtt_port,
        "mqtt_user": str(body.get("mqtt_user", "")),
        "ha_url": ha_url,
        "mirror_stream_url": mirror_stream_url,
        "mqtt_topic_prefix": mqtt_topic_prefix,
    }
    mqtt_pass = body.get("mqtt_pass")
    if mqtt_pass:
        updates["mqtt_pass"] = mqtt_pass
    ha_token = body.get("ha_token")
    if ha_token:
        updates["ha_token"] = ha_token

    db = request.app.state.db
    new_settings = write_runtime_settings(db, **updates)
    request.app.state.runtime_settings = new_settings
    request.app.state.bridge.reconfigure(new_settings)

    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_admin_routes_settings.py -v`
Expected: PASS (10 tests — 6 pre-existing + 4 new)

- [ ] **Step 5: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: Only `mirror_node`/`scare_node`-related tests still fail (fixed in
Tasks 8, 9).

- [ ] **Step 6: Commit**

```bash
git add admin/app/routers/settings.py tests/test_admin_routes_settings.py
git commit -m "feat: mqtt_topic_prefix instelbaar via /api/settings"
```

---

## Task 6: Backend — `GET /api/node-config` (publiek)

**Files:**
- Create: `admin/app/routers/node_config.py`
- Modify: `admin/app/main.py`
- Test: `tests/test_admin_routes_node_config.py`

**Interfaces:**
- Consumes: `app.state.runtime_settings.mqtt_topic_prefix` (Task 3).
- Produces: `GET /api/node-config` → `{"mqtt_topic_prefix": "..."}`, publiek
  (geen sessie nodig) — gebruikt door Task 2's `fetch_topic_prefix` via
  Task 8/9 (nodes).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_routes_node_config.py`:

```python
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


class FakeBridge:
    def __init__(self):
        self.reconfigured_with = None

    def start(self):
        pass

    def stop(self):
        pass

    def reconfigure(self, runtime_settings):
        self.reconfigured_with = runtime_settings


def _client(tmp_path):
    """Vervangt app.state.bridge door een FakeBridge -- anders roept een PUT
    /api/settings tijdens de test een ECHTE MqttBridge.reconfigure() aan, die
    een reëel achtergrondthread + verbindingspoging start. Zelfde patroon als
    _client() in tests/test_admin_routes_settings.py."""
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    return TestClient(app), app


def test_node_config_works_without_session_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_TOPIC_PREFIX", "seed-prefix")
    client, app = _client(tmp_path)

    response = client.get("/api/node-config")

    assert response.status_code == 200
    assert response.json() == {"mqtt_topic_prefix": "seed-prefix"}


def test_node_config_reflects_saved_prefix(tmp_path):
    client, app = _client(tmp_path)
    client.post("/api/login", json={"password": "testwachtwoord"})
    client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_topic_prefix": "gewijzigd",
    })

    response = client.get("/api/node-config")

    assert response.json() == {"mqtt_topic_prefix": "gewijzigd"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_admin_routes_node_config.py -v`
Expected: FAIL with `404 Not Found` (route doesn't exist), or `401` on the
first test (path not yet public)

- [ ] **Step 3: Create `admin/app/routers/node_config.py`**

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/node-config")
def get_node_config(request: Request):
    """Publiek endpoint (geen sessie nodig) waar mirror-node/scare-node bij
    het opstarten de actuele topic-prefix ophalen -- zie shared/topic_prefix.py.
    Geeft bewust alleen de prefix terug, nooit MQTT-host/poort/credentials."""
    return {"mqtt_topic_prefix": request.app.state.runtime_settings.mqtt_topic_prefix}
```

- [ ] **Step 4: Wire the router and the public path into `admin/app/main.py`**

Add the import next to the other router imports:

```python
from admin.app.routers import node_config as node_config_router
```

Add the include next to the other `app.include_router(...)` calls:

```python
    app.include_router(node_config_router.router)
```

Add `/api/node-config` to the public-paths set:

```python
_PUBLIC_EXACT_PATHS = {"/api/login", "/docs", "/openapi.json", "/api/node-config"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_admin_routes_node_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: Only `mirror_node`/`scare_node`-related tests still fail (fixed in
Tasks 8 and 9). `admin/app/main.py`'s own `setup_logging("beheerpagina",
settings.log_dir)` call passes no `mqtt_client`, so Task 1's signature
change never affected it — nothing to investigate there.

- [ ] **Step 7: Commit**

```bash
git add admin/app/routers/node_config.py admin/app/main.py tests/test_admin_routes_node_config.py
git commit -m "feat: publiek GET /api/node-config zodat nodes de topic-prefix kunnen ophalen"
```

---

## Task 7: Frontend — topic-prefix-veld op de Instellingen-pagina

**Files:**
- Modify: `admin/frontend/src/types.ts`
- Modify: `admin/frontend/src/pages/SettingsPage.tsx`

**Interfaces:**
- Consumes: `GET`/`PUT /api/settings`'s `mqtt_topic_prefix`-veld (Task 5).
- Produces: geen nieuwe interface voor latere tasks.

- [ ] **Step 1: Update `admin/frontend/src/types.ts`**

In `AppSettings`, add the field (matches the `GET` response from Task 5):

```ts
export interface AppSettings {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  ha_url: string;
  mirror_stream_url: string;
  mqtt_topic_prefix: string;
  mqtt_pass_set: boolean;
  ha_token_set: boolean;
}
```

In `AppSettingsUpdate`, add the field (matches the `PUT` body from Task 5):

```ts
export interface AppSettingsUpdate {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  mqtt_pass?: string;
  ha_url: string;
  ha_token?: string;
  mirror_stream_url: string;
  mqtt_topic_prefix: string;
}
```

- [ ] **Step 2: Update `admin/frontend/src/pages/SettingsPage.tsx`**

Add `mqtt_topic_prefix` to the `FormState` interface and `EMPTY_FORM`:

```ts
interface FormState {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  mqtt_pass: string;
  ha_url: string;
  ha_token: string;
  mirror_stream_url: string;
  mqtt_topic_prefix: string;
}

const EMPTY_FORM: FormState = {
  mqtt_host: "",
  mqtt_port: 1883,
  mqtt_user: "",
  mqtt_pass: "",
  ha_url: "",
  ha_token: "",
  mirror_stream_url: "",
  mqtt_topic_prefix: "",
};
```

In the `useEffect` that loads settings, include the field when building the
form state from the fetched result:

```tsx
        setForm({
          mqtt_host: result.mqtt_host,
          mqtt_port: result.mqtt_port,
          mqtt_user: result.mqtt_user,
          mqtt_pass: "",
          ha_url: result.ha_url,
          ha_token: "",
          mirror_stream_url: result.mirror_stream_url,
          mqtt_topic_prefix: result.mqtt_topic_prefix,
        });
```

In `handleSave`, include the field in the `putSettings(...)` call:

```tsx
      await putSettings({
        mqtt_host: form.mqtt_host,
        mqtt_port: form.mqtt_port,
        mqtt_user: form.mqtt_user,
        ...(form.mqtt_pass ? { mqtt_pass: form.mqtt_pass } : {}),
        ha_url: form.ha_url,
        ...(form.ha_token ? { ha_token: form.ha_token } : {}),
        mirror_stream_url: form.mirror_stream_url,
        mqtt_topic_prefix: form.mqtt_topic_prefix,
      });
```

Add a new field inside the existing MQTT-broker `<section className="settings-panel">` (the one containing Host/Poort/Gebruikersnaam/Wachtwoord), right after the Wachtwoord field's closing `</label>`:

```tsx
              <label className="settings-field settings-field--wide">
                <span className="settings-field__label">Topic-prefix (optioneel)</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.mqtt_topic_prefix}
                  placeholder="bijv. spookregie of test"
                  onChange={(e) => update({ mqtt_topic_prefix: e.target.value })}
                />
              </label>
```

Directly below that `<div className="settings-grid">`'s closing tag (still
inside the MQTT-broker `<section>`), add a short explanatory line — reuse
the existing `settings-field__label`-style muted text, no new CSS class
needed:

```tsx
            <p className="settings-field__label" style={{ marginTop: "0.75rem" }}>
              Laat leeg voor geen namespace. Nodes halen deze waarde pas op bij
              hun eerstvolgende herstart — een lopende node picked een
              wijziging hier niet live op.
            </p>
```

- [ ] **Step 3: Type-check and build the frontend**

Run: `cd admin/frontend && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/types.ts admin/frontend/src/pages/SettingsPage.tsx
git commit -m "feat: topic-prefix-veld op de Instellingen-pagina"
```

---

## Task 8: `mirror_node/main.py` — `Topics` + prefix ophalen bij opstarten

**Files:**
- Modify: `mirror_node/main.py`
- Modify: `tests/test_mirror_main.py`

**Interfaces:**
- Consumes: `Topics` (Task 1), `fetch_topic_prefix` (Task 2).
- Produces: geen nieuwe interface voor latere tasks.

- [ ] **Step 1: Update the failing test expectations**

In `tests/test_mirror_main.py`, both `on_message`-related tests currently
call `mirror_main.make_on_message(logger)` with one argument and reference
module-level `mirror_main.TOPIC_CONFIG_MIRROR`/`mirror_main.TOPIC_CONTROL_MIRROR_TEST`,
which won't exist after this task. Replace these two tests:

```python
def test_on_message_survives_malformed_payload(monkeypatch):
    # Niet-UTF8 bytes: mag paho's netwerkthread niet killen.
    logger = _FakeLogger()
    topics = mirror_main.Topics()
    on_message = mirror_main.make_on_message(logger, topics)
    on_message(None, None, _FakeMsg(topics.config_mirror, b"\xff\xfe"))
    assert logger.errors


def test_on_message_sets_test_trigger_event():
    mirror_main.test_trigger_requested.clear()
    topics = mirror_main.Topics()
    on_message = mirror_main.make_on_message(_FakeLogger(), topics)

    on_message(None, None, _FakeMsg(topics.control_mirror_test, b""))

    assert mirror_main.test_trigger_requested.is_set()
    mirror_main.test_trigger_requested.clear()
```

All other tests in this file are unaffected (they test `_load_overlay`,
`_apply_config_message` directly — no topic/prefix involvement).

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_mirror_main.py -v`
Expected: FAIL — `mirror_main.Topics` doesn't exist yet (the module still
imports old `TOPIC_*` names), or `make_on_message()` doesn't accept a
second argument yet.

- [ ] **Step 3: Update `mirror_node/main.py`**

Find this block near the top of the file:

```python
from shared.mqtt_contract import (
    SLEEP_PAYLOAD_ON,
    TOPIC_MIRROR_TRIGGERED,
    TOPIC_SYSTEM_SLEEP,
    TOPIC_CONFIG_MIRROR,
    TOPIC_CONTROL_MIRROR_PREVIEW,
    TOPIC_CONTROL_MIRROR_TEST,
    status_topic,
    trigger_payload,
)
from shared.logging_setup import setup_logging
```

Replace it with:

```python
from shared.mqtt_contract import SLEEP_PAYLOAD_ON, Topics, trigger_payload
from shared.topic_prefix import fetch_topic_prefix
from shared.logging_setup import setup_logging
```

(Everything below that block — `from shared.media_sync import sync_media`
and the `mirror_node.*` imports — is untouched.)

Add a module-level env read next to the other `MQTT_*` constants (right
after `MQTT_PASS`):

```python
MQTT_TOPIC_PREFIX_ENV = os.environ.get("MQTT_TOPIC_PREFIX", "")
```

Replace `make_on_message`:

```python
def make_on_message(logger, topics):
    def on_message(client, userdata, msg):
        # Vangnet: een exception hier zou paho's netwerkthread killen — de node
        # blijft dan renderen maar reageert nergens meer op, ook niet op
        # system/sleep (de noodstop). Alles loggen en doorgaan dus.
        try:
            if msg.topic == topics.system_sleep:
                if msg.payload.decode() == SLEEP_PAYLOAD_ON:
                    sleeping.set()
                else:
                    sleeping.clear()
                return
            if msg.topic == topics.config_mirror:
                _apply_config_message(msg.payload.decode(), is_preview=False, logger=logger)
                return
            if msg.topic == topics.control_mirror_preview:
                _apply_config_message(msg.payload.decode(), is_preview=True, logger=logger)
                return
            if msg.topic == topics.control_mirror_test:
                test_trigger_requested.set()
        except Exception as exc:
            logger.error("Fout bij verwerken MQTT-bericht op topic %s: %s", msg.topic, exc)
    return on_message
```

In `main()`, right after `os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)`, add:

```python
    topic_prefix = fetch_topic_prefix(BACKEND_URL, fallback=MQTT_TOPIC_PREFIX_ENV)
    topics = Topics(prefix=topic_prefix)
```

Change the `setup_logging` call:

```python
    logger = setup_logging(NODE_NAME, LOG_DIR, mqtt_client=client, mqtt_log_topic=topics.log(NODE_NAME))
    logger.info("MQTT-topic-prefix: %r", topic_prefix)
```

Update `on_connect` (still nested inside `main()`, now closes over
`topics`):

```python
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT verbonden met %s:%s", MQTT_HOST, MQTT_PORT)
        else:
            logger.error("MQTT verbinden mislukt (rc=%s)", rc)
            return
        client.publish(topics.status(NODE_NAME), "online", retain=True)
        client.subscribe(topics.system_sleep)
        client.subscribe(topics.config_mirror)
        client.subscribe(topics.control_mirror_preview)
        client.subscribe(topics.control_mirror_test)
```

Update `client.on_message = make_on_message(logger, topics)` (was
`make_on_message(logger)`).

Update the last-will line: `client.will_set(topics.status(NODE_NAME), payload="offline", retain=True)`.

In the main render loop, update the trigger-publish line:
`client.publish(topics.mirror_triggered, trigger_payload())` (was
`client.publish(TOPIC_MIRROR_TRIGGERED, trigger_payload())`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_mirror_main.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: Only `scare_node`-related tests still fail (fixed in Task 9).

- [ ] **Step 6: Commit**

```bash
git add mirror_node/main.py tests/test_mirror_main.py
git commit -m "feat: mirror-node haalt topic-prefix op bij opstarten, gebruikt Topics"
```

---

## Task 9: `scare_node/main.py` — `Topics` + prefix ophalen bij opstarten

**Files:**
- Modify: `scare_node/main.py`

**Interfaces:**
- Consumes: `Topics` (Task 1), `fetch_topic_prefix` (Task 2).
- Produces: geen nieuwe interface voor latere tasks.

**No test file changes required** — `tests/test_scare_main.py` never calls
`make_on_message`, `trigger_scare`, or references any `TOPIC_*`/`*_topic`
name; it only tests `_normalize_string_list`, `_apply_scare_config`, and
`_pick_synced_audio`, none of which touch topics. Verify this remains true
after your edit (Step 3 below).

- [ ] **Step 1: Confirm the test file has no topic references**

Run: `grep -n "TOPIC_\|_topic(\|make_on_message\|trigger_scare" tests/test_scare_main.py`
Expected: no output. If this finds something, stop and report — the plan's
assumption doesn't hold and the task needs re-scoping.

- [ ] **Step 2: Run the current test file as a baseline**

Run: `source .venv/bin/activate && pytest tests/test_scare_main.py -v`
Expected: PASS (all tests, unchanged from before this task — this is your
baseline to compare against after Step 3).

- [ ] **Step 3: Update `scare_node/main.py`**

Find this block near the top of the file:

```python
from shared.mqtt_contract import (
    SLEEP_PAYLOAD_ON,
    TOPIC_MIRROR_TRIGGERED,
    TOPIC_SYSTEM_SLEEP,
    control_scare_test_topic,
    config_scare_topic,
    scare_topic,
    status_topic,
    trigger_payload,
)
from shared.logging_setup import setup_logging
from shared.media_sync import sync_media
```

Replace it with:

```python
from shared.mqtt_contract import SLEEP_PAYLOAD_ON, Topics, trigger_payload
from shared.topic_prefix import fetch_topic_prefix
from shared.logging_setup import setup_logging
from shared.media_sync import sync_media
```

(Everything below that block — `from scare_node.playback import
pick_audio_file` and `from scare_node.debounce import Cooldown` — is
untouched.)

Add a module-level env read next to the other `MQTT_*` constants (right
after `MQTT_PASS`):

```python
MQTT_TOPIC_PREFIX_ENV = os.environ.get("MQTT_TOPIC_PREFIX", "")
```

Change `trigger_scare`'s signature and body:

```python
def trigger_scare(client, logger, topics):
    """Enige plek waar een scare start: cooldown-check, dan meteen het
    scare-topic publiceren (zodat HA/WLED niet op het geluid hoeft te
    wachten) en pas daarna afspelen."""
    if not cooldown.ready():
        return
    client.publish(topics.scare(ZONE), trigger_payload())
    play_scare(logger)
```

Replace `make_on_message`:

```python
def make_on_message(logger, topics):
    def on_message(client, userdata, msg):
        # Vangnet: een exception hier zou paho's netwerkthread killen — de node
        # reageert dan nergens meer op, ook niet op system/sleep (de noodstop).
        try:
            if msg.topic == topics.system_sleep:
                if msg.payload.decode() == SLEEP_PAYLOAD_ON:
                    sleeping.set()
                else:
                    sleeping.clear()
                return
            if msg.topic == topics.config_scare(ZONE):
                _apply_scare_config(msg.payload.decode(), logger)
                return
            if msg.topic == topics.control_scare_test(ZONE):
                trigger_scare(client, logger, topics)
                return
            if msg.topic == topics.mirror_triggered and not sleeping.is_set():
                delay = random.uniform(0, 2)
                threading.Timer(delay, trigger_scare, args=(client, logger, topics)).start()
        except Exception as exc:
            logger.error("Fout bij verwerken MQTT-bericht op topic %s: %s", msg.topic, exc)
    return on_message
```

Update `selfcheck()` — add the prefix fetch right before the MQTT test
connection, and use `topics.scare(ZONE)`:

```python
    topic_prefix = fetch_topic_prefix(BACKEND_URL, fallback=MQTT_TOPIC_PREFIX_ENV)
    topics = Topics(prefix=topic_prefix)

    client = mqtt.Client(client_id=f"scare-selfcheck-{ZONE}")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
        client.loop_start()
        client.publish(topics.scare(ZONE), trigger_payload())
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()
        print(f"MQTT OK: {topics.scare(ZONE)} gepubliceerd")
    except OSError as exc:
        print(f"MQTT niet bereikbaar ({exc}) — audio werkte wel")
```

In `main()`, right after `os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)`, add:

```python
    topic_prefix = fetch_topic_prefix(BACKEND_URL, fallback=MQTT_TOPIC_PREFIX_ENV)
    topics = Topics(prefix=topic_prefix)
```

Change the `setup_logging` call:

```python
    logger = setup_logging(NODE_NAME, LOG_DIR, mqtt_client=client, mqtt_log_topic=topics.log(NODE_NAME))
    logger.info("MQTT-topic-prefix: %r", topic_prefix)
```

Update `on_connect` (still nested inside `main()`, now closes over
`topics`):

```python
    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            logger.error("MQTT verbinden mislukt (rc=%s)", rc)
            return
        logger.info("MQTT verbonden met %s:%s", MQTT_HOST, MQTT_PORT)
        client.publish(topics.status(NODE_NAME), "online", retain=True)
        client.subscribe(topics.mirror_triggered)
        client.subscribe(topics.system_sleep)
        client.subscribe(topics.config_scare(ZONE))
        client.subscribe(topics.control_scare_test(ZONE))
```

Update `client.on_message = make_on_message(logger, topics)` (was
`make_on_message(logger)`).

Update the last-will line: `client.will_set(topics.status(NODE_NAME), payload="offline", retain=True)`.

Update `on_motion()` (still nested inside `main()`):

```python
    def on_motion():
        if sleeping.is_set():
            return
        trigger_scare(client, logger, topics)
```

- [ ] **Step 4: Run tests to verify nothing broke**

Run: `source .venv/bin/activate && pytest tests/test_scare_main.py -v`
Expected: PASS (identical count to Step 2's baseline — this task adds no
new tests since the existing suite never touched topics).

- [ ] **Step 5: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All tests PASS — this is the last task touching Python code, so
the suite should be fully green here.

- [ ] **Step 6: Commit**

```bash
git add scare_node/main.py
git commit -m "feat: scare-node haalt topic-prefix op bij opstarten, gebruikt Topics"
```

---

## Task 10: README — nieuwe env var, endpoint, Instellingen-veld documenteren

**Files:**
- Modify: `README.md`

**Interfaces:** geen (documentatie).

- [ ] **Step 1: Add `MQTT_TOPIC_PREFIX` to both node env-var tables**

In the "Environment-variabelen" section, "Beide nodes" table, add a row
right after the `MQTT_PASS` row:

```
| `MQTT_TOPIC_PREFIX` | *(leeg)* | Terugval als de backend (`BACKEND_URL`) bij opstarten onbereikbaar is voor `GET /api/node-config` — normaal gesproken bepaalt de Instellingen-pagina dit centraal. |
```

- [ ] **Step 2: Document the new node-facing behavior**

Right after the existing paragraph about `BACKEND_URL` (in the "Environment-
variabelen" intro, before the "Alleen mirror-node" table), add:

```markdown
Bij het opstarten halen beide nodes eenmalig de actuele MQTT-topic-prefix op
bij de backend (`GET /api/node-config`, geen authenticatie nodig). Lukt dat
niet, dan valt de node terug op zijn eigen `MQTT_TOPIC_PREFIX`. Een
prefix-wijziging op de Instellingen-pagina vraagt dus een herstart van elke
node om 'm op te pikken — er is bewust geen live push.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: MQTT_TOPIC_PREFIX, /api/node-config en de Instellingen-pagina documenteren"
```

---

## Task 11: Whole-feature verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 2: Build the frontend**

Run: `cd admin/frontend && npm run build`
Expected: Succeeds, no TypeScript errors.

- [ ] **Step 3: Manual smoke test — two "installations" sharing one broker**

This is the exact scenario the feature exists for. Start the backend
(`ADMIN_PASSWORD=devpass ADMIN_DB_PATH=/tmp/task11-smoke.db LOG_DIR=/tmp/task11-logs
MQTT_HOST=localhost python -m admin.run` from the repo root, backend venv at
`.venv/`) and log in via curl:

```bash
curl -s -c /tmp/task11-cookies.txt -X POST http://localhost:8000/api/login \
  -H 'Content-Type: application/json' -d '{"password":"devpass"}'
```

Confirm the default (no prefix) round-trips:

```bash
curl -s -b /tmp/task11-cookies.txt http://localhost:8000/api/settings | grep mqtt_topic_prefix
curl -s http://localhost:8000/api/node-config
```

Expected: both show `"mqtt_topic_prefix":""`.

Set a prefix and confirm both endpoints reflect it immediately:

```bash
curl -s -b /tmp/task11-cookies.txt -X PUT http://localhost:8000/api/settings \
  -H 'Content-Type: application/json' \
  -d '{"mqtt_host":"localhost","mqtt_port":1883,"mqtt_topic_prefix":"test"}'
curl -s -b /tmp/task11-cookies.txt http://localhost:8000/api/settings | grep mqtt_topic_prefix
curl -s http://localhost:8000/api/node-config
```

Expected: both show `"mqtt_topic_prefix":"test"` — `/api/node-config`
required no session cookie.

Confirm validation rejects wildcard characters:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/task11-cookies.txt -X PUT http://localhost:8000/api/settings \
  -H 'Content-Type: application/json' \
  -d '{"mqtt_host":"localhost","mqtt_port":1883,"mqtt_topic_prefix":"bad#prefix"}'
```

Expected: `400`.

Clean up: stop the backend process, remove `/tmp/task11-smoke.db`,
`/tmp/task11-cookies.txt`, and `/tmp/task11-logs`.

- [ ] **Step 4: Verify no stray references to the old API remain**

Run: `grep -rn "TOPIC_MIRROR_TRIGGERED\|TOPIC_SYSTEM_SLEEP\|TOPIC_CONFIG_MIRROR\|TOPIC_CONTROL_MIRROR\|scare_topic(\|status_topic(\|log_topic(\|config_scare_topic(\|control_scare_test_topic(" admin mirror_node scare_node shared tests 2>/dev/null | grep -v __pycache__`
(list directories explicitly rather than `--include=*.py .` — zsh expands an
unquoted `*.py` glob itself and errors with "no matches found" if the cwd
has none, which is not what you want here)
Expected: no output (everything now goes through `Topics`).

- [ ] **Step 5: Final whole-branch review**

Dispatch a final review pass over every file touched by Tasks 1–10 (same
convention as prior plans in this repo): check that `mqtt_state.py` and the
frontend outside `SettingsPage.tsx` truly received zero changes (confirms
the "strip once, at the boundary" design held), that no secret-handling
regression was introduced in `routers/settings.py`'s edits, and that
`mirror_node/main.py`/`scare_node/main.py` fetch the prefix exactly once at
startup (no accidental per-message or per-loop-iteration fetch).
