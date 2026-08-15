# Voortuin Halloween-ervaring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bouw de mirror-node (camera + ghost-effect + beamer op raam), scare-node(s) (PIR + speaker) en de Home Assistant/MQTT-koppeling (incl. WLED) uit de goedgekeurde spec.

**Architecture:** Losstaande Python-nodes per fysieke zone die alleen via MQTT-topics met Home Assistant praten, nooit rechtstreeks met elkaar. Elke node blijft lokaal functioneren als MQTT wegvalt. Een gedeelde `shared/`-module bevat het MQTT-topic-contract en logging, zodat alle nodes hetzelfde "vocabulaire" spreken.

**Tech Stack:** Python 3, OpenCV (`opencv-python`), `paho-mqtt`, `gpiozero` (PIR op Raspberry Pi), `pytest` voor de testbare logica, systemd voor procesbeheer, Home Assistant + Mosquitto (bestaand) voor coördinatie.

**Spec:** `docs/superpowers/specs/2026-08-15-voortuin-halloween-ervaring-design.md`

## Global Constraints

- Nodes praten uitsluitend via MQTT-topics met HA — nooit rechtstreeks met een andere node.
- Elke node moet **altijd lokaal blijven werken** als MQTT/HA onbereikbaar is (fail-safe, geen harde afhankelijkheid).
- Geen aparte logstack — logging loopt via lokale bestanden + een `log/<node>`-MQTT-topic.
- Trigger-detectie in de mirror-node zit achter een vervangbare interface (nu frame-diff, later evt. PIR/detectiemodel) — niet hardcoded verweven met de rest van de node.
- WLED-aansturing loopt via Home Assistant's native WLED-integratie/automations, geen eigen Python-code daarvoor.
- Geen geautomatiseerde tests voor fysieke effecten (camera/audio/licht/HA-YAML); wel pytest-dekking voor alle pure logica (frame-diff, effect-transform, audio-selectie, cooldown, MQTT-contract, logging).

---

## File Structure

```
halloween/
├── shared/
│   ├── __init__.py
│   ├── mqtt_contract.py       # topic-namen + payload-helpers
│   └── logging_setup.py       # lokale + MQTT-logging
├── mirror_node/
│   ├── __init__.py
│   ├── trigger.py              # frame-diff motion-detectie (vervangbaar)
│   ├── effect.py                # ghost-effect op een frame
│   ├── main.py                   # camera-loop, MQTT, idle/sleep
│   ├── requirements.txt
│   └── mirror-node.service
├── scare_node/
│   ├── __init__.py
│   ├── playback.py               # audiobestand kiezen
│   ├── debounce.py                # cooldown-logica
│   ├── main.py                     # PIR + MQTT + afspelen
│   ├── requirements.txt
│   └── scare-node.service
├── home_assistant/
│   ├── automations/
│   │   ├── time_window.yaml
│   │   └── wled_trigger.yaml
│   └── README.md
├── tests/
│   ├── test_mqtt_contract.py
│   ├── test_logging_setup.py
│   ├── test_trigger.py
│   ├── test_effect.py
│   ├── test_playback.py
│   └── test_debounce.py
└── requirements-dev.txt
```

---

### Task 1: Gedeeld MQTT-contract + logging

**Files:**
- Create: `shared/__init__.py`
- Create: `shared/mqtt_contract.py`
- Create: `shared/logging_setup.py`
- Create: `requirements-dev.txt`
- Test: `tests/test_mqtt_contract.py`
- Test: `tests/test_logging_setup.py`

**Interfaces:**
- Produces:
  - `shared.mqtt_contract.TOPIC_MIRROR_TRIGGERED: str`
  - `shared.mqtt_contract.TOPIC_SYSTEM_SLEEP: str`
  - `shared.mqtt_contract.trigger_payload() -> str` (JSON met `ts`)
  - `shared.mqtt_contract.scare_topic(zone: str) -> str`
  - `shared.mqtt_contract.log_topic(node: str) -> str`
  - `shared.logging_setup.setup_logging(node_name: str, log_dir: str, mqtt_client=None) -> logging.Logger`
  - `shared.logging_setup.MqttLogHandler(mqtt_client, topic)`

- [ ] **Step 1: Maak de package-map en lege `__init__.py`**

```bash
mkdir -p shared tests
touch shared/__init__.py
```

- [ ] **Step 2: Schrijf de falende tests voor het MQTT-contract**

`tests/test_mqtt_contract.py`:
```python
import json
from shared.mqtt_contract import (
    TOPIC_MIRROR_TRIGGERED,
    TOPIC_SYSTEM_SLEEP,
    trigger_payload,
    scare_topic,
    log_topic,
)


def test_topic_constants():
    assert TOPIC_MIRROR_TRIGGERED == "mirror/triggered"
    assert TOPIC_SYSTEM_SLEEP == "system/sleep"


def test_scare_topic_formats_zone():
    assert scare_topic("zone-a") == "scare/zone-a/triggered"


def test_log_topic_formats_node():
    assert log_topic("mirror") == "log/mirror"


def test_trigger_payload_is_json_with_timestamp():
    payload = json.loads(trigger_payload())
    assert "ts" in payload
    assert isinstance(payload["ts"], float)
```

- [ ] **Step 3: Run de tests, verwacht FAIL (module bestaat nog niet)**

Run: `pytest tests/test_mqtt_contract.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'shared.mqtt_contract'`

- [ ] **Step 4: Implementeer `shared/mqtt_contract.py`**

```python
import json
import time

TOPIC_MIRROR_TRIGGERED = "mirror/triggered"
TOPIC_SYSTEM_SLEEP = "system/sleep"

_SCARE_TOPIC_TEMPLATE = "scare/{zone}/triggered"
_LOG_TOPIC_TEMPLATE = "log/{node}"


def trigger_payload():
    """JSON payload voor een 'iets is getriggerd'-bericht."""
    return json.dumps({"ts": time.time()})


def scare_topic(zone):
    return _SCARE_TOPIC_TEMPLATE.format(zone=zone)


def log_topic(node):
    return _LOG_TOPIC_TEMPLATE.format(node=node)
```

- [ ] **Step 5: Run de tests, verwacht PASS**

Run: `pytest tests/test_mqtt_contract.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Schrijf de falende tests voor logging**

`tests/test_logging_setup.py`:
```python
import json
import logging
from shared.logging_setup import setup_logging, MqttLogHandler


class FakeMqttClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload):
        self.published.append((topic, payload))


def test_setup_logging_writes_to_file(tmp_path):
    logger = setup_logging("test-node-file", str(tmp_path))
    logger.info("hello")
    for handler in logger.handlers:
        handler.flush()

    log_file = tmp_path / "test-node-file.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text()


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


def test_mqtt_log_handler_emit_publishes_json():
    fake_client = FakeMqttClient()
    handler = MqttLogHandler(fake_client, "log/x")
    logger = logging.getLogger("mqtt-handler-test")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.warning("careful")

    topic, payload = fake_client.published[0]
    assert topic == "log/x"
    data = json.loads(payload)
    assert data["level"] == "WARNING"
    assert data["msg"] == "careful"
```

- [ ] **Step 7: Run de tests, verwacht FAIL**

Run: `pytest tests/test_logging_setup.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'shared.logging_setup'`

- [ ] **Step 8: Implementeer `shared/logging_setup.py`**

```python
import json
import logging
import os
import time

from shared.mqtt_contract import log_topic


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


def setup_logging(node_name, log_dir, mqtt_client=None):
    """Logger die altijd lokaal naar bestand schrijft, en optioneel
    meepublicceert naar MQTT (`log/<node_name>`) zodat je tijdens
    ontwikkeling alle nodes centraal kunt meelezen."""
    logger = logging.getLogger(node_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()  # voorkomt dubbele handlers bij herhaald aanroepen

    file_handler = logging.FileHandler(os.path.join(log_dir, f"{node_name}.log"))
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)

    if mqtt_client is not None:
        logger.addHandler(MqttLogHandler(mqtt_client, log_topic(node_name)))

    return logger
```

- [ ] **Step 9: Run de tests, verwacht PASS**

Run: `pytest tests/test_logging_setup.py -v`
Expected: PASS (3 tests)

- [ ] **Step 10: Voeg dev-dependencies toe**

`requirements-dev.txt`:
```
pytest
numpy
opencv-python
```

- [ ] **Step 11: Commit**

```bash
git add shared requirements-dev.txt tests/test_mqtt_contract.py tests/test_logging_setup.py
git commit -m "feat: shared MQTT-contract en logging"
```

---

### Task 2: Mirror-node trigger-detectie (frame-diff)

**Files:**
- Create: `mirror_node/__init__.py`
- Create: `mirror_node/trigger.py`
- Test: `tests/test_trigger.py`

**Interfaces:**
- Produces: `mirror_node.trigger.FrameDiffTrigger(threshold=25, min_changed_ratio=0.02)` met methode `.detect(frame_gray: np.ndarray) -> bool`

- [ ] **Step 1: Maak de package-map**

```bash
mkdir -p mirror_node
touch mirror_node/__init__.py
```

- [ ] **Step 2: Schrijf de falende tests**

`tests/test_trigger.py`:
```python
import numpy as np
from mirror_node.trigger import FrameDiffTrigger


def test_first_frame_never_triggers():
    trigger = FrameDiffTrigger()
    frame = np.zeros((10, 10), dtype=np.uint8)
    assert trigger.detect(frame) is False


def test_identical_frames_do_not_trigger():
    trigger = FrameDiffTrigger()
    frame = np.zeros((10, 10), dtype=np.uint8)
    trigger.detect(frame)
    assert trigger.detect(frame) is False


def test_large_change_triggers():
    trigger = FrameDiffTrigger(threshold=25, min_changed_ratio=0.02)
    frame1 = np.zeros((10, 10), dtype=np.uint8)
    trigger.detect(frame1)

    frame2 = np.full((10, 10), 255, dtype=np.uint8)
    assert trigger.detect(frame2) is True


def test_tiny_change_does_not_trigger():
    trigger = FrameDiffTrigger(threshold=25, min_changed_ratio=0.5)
    frame1 = np.zeros((10, 10), dtype=np.uint8)
    trigger.detect(frame1)

    frame2 = np.zeros((10, 10), dtype=np.uint8)
    frame2[0, 0] = 255  # 1 van de 100 pixels = 1%
    assert trigger.detect(frame2) is False
```

- [ ] **Step 3: Run de tests, verwacht FAIL**

Run: `pytest tests/test_trigger.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'mirror_node.trigger'`

- [ ] **Step 4: Implementeer `mirror_node/trigger.py`**

```python
import numpy as np


class FrameDiffTrigger:
    """Detecteert beweging via frame-differencing op een grijswaarde-frame.

    Vervangbaar: een andere trigger-bron (PIR, detectiemodel) hoeft alleen
    dezelfde `.detect(frame_gray) -> bool`-interface te implementeren om
    deze klasse te vervangen, zonder de rest van de mirror-node aan te
    passen.
    """

    def __init__(self, threshold=25, min_changed_ratio=0.02):
        self._prev_gray = None
        self.threshold = threshold
        self.min_changed_ratio = min_changed_ratio

    def detect(self, frame_gray):
        if self._prev_gray is None:
            self._prev_gray = frame_gray
            return False

        diff = np.abs(frame_gray.astype(np.int16) - self._prev_gray.astype(np.int16))
        changed_ratio = np.mean(diff > self.threshold)
        self._prev_gray = frame_gray
        return bool(changed_ratio > self.min_changed_ratio)
```

- [ ] **Step 5: Run de tests, verwacht PASS**

Run: `pytest tests/test_trigger.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add mirror_node/__init__.py mirror_node/trigger.py tests/test_trigger.py
git commit -m "feat: frame-diff trigger-detectie voor mirror-node"
```

---

### Task 3: Mirror-node ghost-effect

**Files:**
- Create: `mirror_node/effect.py`
- Test: `tests/test_effect.py`

**Interfaces:**
- Produces: `mirror_node.effect.ghost_effect(frame_bgr: np.ndarray) -> np.ndarray`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_effect.py`:
```python
import numpy as np
from mirror_node.effect import ghost_effect


def test_output_shape_and_dtype_match_input():
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    result = ghost_effect(frame)
    assert result.shape == frame.shape
    assert result.dtype == np.uint8


def test_white_input_becomes_dark():
    frame = np.full((20, 20, 3), 255, dtype=np.uint8)
    result = ghost_effect(frame)
    assert result.mean() < frame.mean()
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_effect.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'mirror_node.effect'`

- [ ] **Step 3: Implementeer `mirror_node/effect.py`**

```python
import cv2


def ghost_effect(frame_bgr):
    """Startpunt-effect: grijswaarden + geïnverteerd + zachte blur, voor een
    x-ray/spookachtige look. Puur een `(frame_bgr) -> frame_bgr`-transform,
    dus tijdens het testen op locatie vrij te vervangen/aan te passen zonder
    de rest van de mirror-node te raken.
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    inverted = cv2.bitwise_not(gray)
    blurred = cv2.GaussianBlur(inverted, (9, 9), 0)
    return cv2.cvtColor(blurred, cv2.COLOR_GRAY2BGR)
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `pytest tests/test_effect.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add mirror_node/effect.py tests/test_effect.py
git commit -m "feat: ghost-effect transform voor mirror-node"
```

---

### Task 4: Mirror-node main loop + systemd-service

**Files:**
- Create: `mirror_node/main.py`
- Create: `mirror_node/requirements.txt`
- Create: `mirror_node/mirror-node.service`

**Interfaces:**
- Consumes:
  - `shared.mqtt_contract.TOPIC_MIRROR_TRIGGERED`, `TOPIC_SYSTEM_SLEEP`, `trigger_payload()` (Task 1)
  - `shared.logging_setup.setup_logging(node_name, log_dir, mqtt_client=None)` (Task 1)
  - `mirror_node.trigger.FrameDiffTrigger` (Task 2)
  - `mirror_node.effect.ghost_effect` (Task 3)
- Produces: draaiend `mirror_node/main.py`-script, `mirror-node.service` systemd-unit

Dit is glue-code die een echte camera en een echt scherm nodig heeft — geen
pytest hiervoor (conform de spec: geen geautomatiseerde tests voor fysieke
effecten). Verificatie gebeurt handmatig op de doelmachine (Step 5 hieronder).

- [ ] **Step 1: Implementeer `mirror_node/main.py`**

```python
import os
import time
import threading

import cv2
import paho.mqtt.client as mqtt

from shared.mqtt_contract import TOPIC_MIRROR_TRIGGERED, TOPIC_SYSTEM_SLEEP, trigger_payload
from shared.logging_setup import setup_logging
from mirror_node.trigger import FrameDiffTrigger
from mirror_node.effect import ghost_effect

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
CAMERA_INDEX = int(os.environ.get("MIRROR_CAMERA_INDEX", "0"))
ACTIVE_SECONDS = float(os.environ.get("MIRROR_ACTIVE_SECONDS", "6"))
LOG_DIR = os.environ.get("LOG_DIR", "/var/log/halloween")

sleeping = threading.Event()


def on_connect(client, userdata, flags, rc):
    client.subscribe(TOPIC_SYSTEM_SLEEP)


def on_message(client, userdata, msg):
    if msg.topic == TOPIC_SYSTEM_SLEEP:
        if msg.payload.decode() == "on":
            sleeping.set()
        else:
            sleeping.clear()


def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    client = mqtt.Client(client_id="mirror-node")
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # connect_async + loop_start: node blijft draaien en probeert op de
    # achtergrond te (her)verbinden, i.p.v. te crashen als HA nu niet
    # bereikbaar is (fail-safe eis uit de spec).
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    logger = setup_logging("mirror", LOG_DIR, mqtt_client=client)

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        logger.error("Kon camera index %s niet openen", CAMERA_INDEX)
        return

    trigger = FrameDiffTrigger()
    cv2.namedWindow("mirror", cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty("mirror", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    active_until = 0.0
    logger.info("mirror-node gestart")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                logger.warning("Kon geen frame lezen van camera")
                time.sleep(0.5)
                continue

            if sleeping.is_set():
                cv2.imshow("mirror", frame * 0)
                cv2.waitKey(1)
                time.sleep(0.2)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            now = time.time()

            if trigger.detect(gray) and now > active_until:
                active_until = now + ACTIVE_SECONDS
                client.publish(TOPIC_MIRROR_TRIGGERED, trigger_payload())
                logger.info("mirror triggered")

            cv2.imshow("mirror", ghost_effect(frame) if now < active_until else frame * 0)
            cv2.waitKey(1)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        client.loop_stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Voeg dependencies toe**

`mirror_node/requirements.txt`:
```
opencv-python
paho-mqtt
```

- [ ] **Step 3: Systemd-service**

`mirror_node/mirror-node.service`:
```ini
[Unit]
Description=Halloween mirror-node
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 -m mirror_node.main
WorkingDirectory=/opt/halloween
Environment=MQTT_HOST=homeassistant.local
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Installeer dependencies op de mirror-machine**

```bash
pip install -r mirror_node/requirements.txt
```

- [ ] **Step 5: Handmatige verificatie op locatie**

Run: `MQTT_HOST=<ha-host> python3 -m mirror_node.main`
Verwacht: camerabeeld-venster opent fullscreen, zwart in rust; bij beweging
voor de camera verschijnt het ghost-effect gedurende `MIRROR_ACTIVE_SECONDS`
en zie je op de HA MQTT-listener (`mosquitto_sub -t mirror/triggered`) een
bericht voorbijkomen.

- [ ] **Step 6: Commit**

```bash
git add mirror_node/main.py mirror_node/requirements.txt mirror_node/mirror-node.service
git commit -m "feat: mirror-node main loop en systemd-service"
```

---

### Task 5: Scare-node audioselectie

**Files:**
- Create: `scare_node/__init__.py`
- Create: `scare_node/playback.py`
- Test: `tests/test_playback.py`

**Interfaces:**
- Produces: `scare_node.playback.pick_audio_file(media_dir: str, rng=random) -> str`

- [ ] **Step 1: Maak de package-map**

```bash
mkdir -p scare_node
touch scare_node/__init__.py
```

- [ ] **Step 2: Schrijf de falende tests**

`tests/test_playback.py`:
```python
import pytest
from scare_node.playback import pick_audio_file


def test_picks_one_of_the_audio_files(tmp_path):
    (tmp_path / "scream1.wav").write_bytes(b"fake")
    (tmp_path / "scream2.wav").write_bytes(b"fake")
    (tmp_path / "notes.txt").write_bytes(b"ignore me")

    picked = pick_audio_file(str(tmp_path))

    assert picked in (str(tmp_path / "scream1.wav"), str(tmp_path / "scream2.wav"))


def test_raises_when_no_audio_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        pick_audio_file(str(tmp_path))
```

- [ ] **Step 3: Run de tests, verwacht FAIL**

Run: `pytest tests/test_playback.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'scare_node.playback'`

- [ ] **Step 4: Implementeer `scare_node/playback.py`**

```python
import os
import random

_AUDIO_EXTENSIONS = (".wav", ".mp3")


def pick_audio_file(media_dir, rng=random):
    files = [f for f in os.listdir(media_dir) if f.lower().endswith(_AUDIO_EXTENSIONS)]
    if not files:
        raise FileNotFoundError(f"Geen audiobestanden gevonden in {media_dir}")
    return os.path.join(media_dir, rng.choice(files))
```

- [ ] **Step 5: Run de tests, verwacht PASS**

Run: `pytest tests/test_playback.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add scare_node/__init__.py scare_node/playback.py tests/test_playback.py
git commit -m "feat: audioselectie voor scare-node"
```

---

### Task 6: Scare-node cooldown/debounce

**Files:**
- Create: `scare_node/debounce.py`
- Test: `tests/test_debounce.py`

**Interfaces:**
- Produces: `scare_node.debounce.Cooldown(seconds: float, clock=time.monotonic)` met methode `.ready() -> bool`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_debounce.py`:
```python
from scare_node.debounce import Cooldown


def test_first_call_is_always_ready():
    cooldown = Cooldown(10, clock=lambda: 0.0)
    assert cooldown.ready() is True


def test_second_call_too_soon_is_not_ready():
    times = iter([0.0, 1.0])
    cooldown = Cooldown(10, clock=lambda: next(times))
    assert cooldown.ready() is True
    assert cooldown.ready() is False


def test_call_after_cooldown_is_ready_again():
    times = iter([0.0, 15.0])
    cooldown = Cooldown(10, clock=lambda: next(times))
    assert cooldown.ready() is True
    assert cooldown.ready() is True
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_debounce.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'scare_node.debounce'`

- [ ] **Step 3: Implementeer `scare_node/debounce.py`**

```python
import time


class Cooldown:
    """Laat `.ready()` maar één keer per `seconds` True teruggeven, tegen
    PIR-vals-positieven (wind, dieren, koplampen) die anders continu
    zouden triggeren."""

    def __init__(self, seconds, clock=time.monotonic):
        self.seconds = seconds
        self._clock = clock
        self._last = None

    def ready(self):
        now = self._clock()
        if self._last is None or now - self._last >= self.seconds:
            self._last = now
            return True
        return False
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `pytest tests/test_debounce.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scare_node/debounce.py tests/test_debounce.py
git commit -m "feat: cooldown/debounce voor scare-node"
```

---

### Task 7: Scare-node main loop + systemd-service

**Files:**
- Create: `scare_node/main.py`
- Create: `scare_node/requirements.txt`
- Create: `scare_node/scare-node.service`

**Interfaces:**
- Consumes:
  - `shared.mqtt_contract.TOPIC_MIRROR_TRIGGERED`, `TOPIC_SYSTEM_SLEEP`, `scare_topic(zone)`, `trigger_payload()` (Task 1)
  - `shared.logging_setup.setup_logging(node_name, log_dir, mqtt_client=None)` (Task 1)
  - `scare_node.playback.pick_audio_file(media_dir)` (Task 5)
  - `scare_node.debounce.Cooldown(seconds)` (Task 6)
- Produces: draaiend `scare_node/main.py`-script, `scare-node.service` systemd-unit

Glue-code met echte PIR-hardware (`gpiozero`) en `aplay` — geen pytest
hiervoor, handmatige verificatie op de Pi (Step 5).

- [ ] **Step 1: Implementeer `scare_node/main.py`**

```python
import os
import random
import subprocess
import threading

import paho.mqtt.client as mqtt
from gpiozero import MotionSensor

from shared.mqtt_contract import (
    TOPIC_MIRROR_TRIGGERED,
    TOPIC_SYSTEM_SLEEP,
    scare_topic,
    trigger_payload,
)
from shared.logging_setup import setup_logging
from scare_node.playback import pick_audio_file
from scare_node.debounce import Cooldown

ZONE = os.environ.get("SCARE_ZONE", "zone-a")
MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MEDIA_DIR = os.environ.get("SCARE_MEDIA_DIR", "/opt/halloween/media")
PIR_PIN = int(os.environ.get("SCARE_PIR_PIN", "4"))
COOLDOWN_SECONDS = float(os.environ.get("SCARE_COOLDOWN_SECONDS", "12"))
LOG_DIR = os.environ.get("LOG_DIR", "/var/log/halloween")

sleeping = threading.Event()
cooldown = Cooldown(COOLDOWN_SECONDS)


def play_scare(logger):
    if not cooldown.ready():
        return
    try:
        audio_file = pick_audio_file(MEDIA_DIR)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return
    logger.info("speelt %s af", audio_file)
    subprocess.run(["aplay", audio_file], check=False)


def make_on_message(logger):
    def on_message(client, userdata, msg):
        if msg.topic == TOPIC_SYSTEM_SLEEP:
            if msg.payload.decode() == "on":
                sleeping.set()
            else:
                sleeping.clear()
            return
        if msg.topic == TOPIC_MIRROR_TRIGGERED and not sleeping.is_set():
            delay = random.uniform(0, 2)
            threading.Timer(delay, play_scare, args=(logger,)).start()
    return on_message


def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    def on_connect(client, userdata, flags, rc):
        client.subscribe(TOPIC_MIRROR_TRIGGERED)
        client.subscribe(TOPIC_SYSTEM_SLEEP)

    client = mqtt.Client(client_id=f"scare-node-{ZONE}")
    client.on_connect = on_connect
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # connect_async + loop_start: node blijft draaien en probeert op de
    # achtergrond te (her)verbinden, i.p.v. te crashen als HA nu niet
    # bereikbaar is (fail-safe eis uit de spec).
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    logger = setup_logging(f"scare-{ZONE}", LOG_DIR, mqtt_client=client)
    client.on_message = make_on_message(logger)

    pir = MotionSensor(PIR_PIN)

    def on_motion():
        if sleeping.is_set():
            return
        play_scare(logger)
        client.publish(scare_topic(ZONE), trigger_payload())

    pir.when_motion = on_motion

    logger.info("scare-node %s gestart op pin %s", ZONE, PIR_PIN)
    threading.Event().wait()  # blokkeert voor altijd


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Voeg dependencies toe**

`scare_node/requirements.txt`:
```
gpiozero
paho-mqtt
```

- [ ] **Step 3: Systemd-service**

`scare_node/scare-node.service`:
```ini
[Unit]
Description=Halloween scare-node
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 -m scare_node.main
WorkingDirectory=/opt/halloween
Environment=MQTT_HOST=homeassistant.local
Environment=SCARE_ZONE=zone-a
Environment=SCARE_PIR_PIN=4
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Installeer dependencies op de Pi**

```bash
pip install -r scare_node/requirements.txt
```

- [ ] **Step 5: Handmatige verificatie op de Pi**

Run: `MQTT_HOST=<ha-host> SCARE_ZONE=zone-a SCARE_PIR_PIN=4 python3 -m scare_node.main`
Verwacht: beweging voor de PIR speelt een willekeurig bestand uit
`SCARE_MEDIA_DIR` af en publiceert naar `scare/zone-a/triggered`; een
handmatig gepubliceerd bericht op `mirror/triggered`
(`mosquitto_pub -t mirror/triggered -m '{}'`) triggert ook een geluid, met
0-2s vertraging.

- [ ] **Step 6: Commit**

```bash
git add scare_node/main.py scare_node/requirements.txt scare_node/scare-node.service
git commit -m "feat: scare-node main loop en systemd-service"
```

---

### Task 8: Home Assistant — Mosquitto, tijdvenster, WLED-koppeling

**Files:**
- Create: `home_assistant/automations/time_window.yaml`
- Create: `home_assistant/automations/wled_trigger.yaml`
- Create: `home_assistant/README.md`

**Interfaces:**
- Consumes (topic-namen uit Task 1, hier als losse HA YAML-config, niet als Python-import): `system/sleep`, `mirror/triggered`

Dit is HA-configuratie, geen Python — verificatie gebeurt in de HA-UI
(Step 4), niet via pytest.

- [ ] **Step 1: Tijdvenster-automation**

`home_assistant/automations/time_window.yaml`:
```yaml
# Stuurt system/sleep "off" bij start van de avond en "on" aan het einde,
# zodat nodes buiten dit venster geen camera/PIR-verwerking doen.
# Topic-naam moet overeenkomen met shared/mqtt_contract.py: TOPIC_SYSTEM_SLEEP.

automation:
  - alias: "Halloween - nodes wakker"
    trigger:
      - platform: time
        at: "18:00:00"
    action:
      - service: mqtt.publish
        data:
          topic: system/sleep
          payload: "off"

  - alias: "Halloween - nodes slapen"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: mqtt.publish
        data:
          topic: system/sleep
          payload: "on"
```

- [ ] **Step 2: WLED-trigger-automation**

`home_assistant/automations/wled_trigger.yaml`:
```yaml
# Vereist dat de WLED-integratie al is toegevoegd in HA, met een
# lichtentiteit zoals light.wled_voortuin (pas aan naar je eigen entity_id).

automation:
  - alias: "Halloween - WLED flikker bij mirror-trigger"
    trigger:
      - platform: mqtt
        topic: mirror/triggered
    action:
      - service: light.turn_on
        target:
          entity_id: light.wled_voortuin
        data:
          effect: "Strobe"
          rgb_color: [255, 0, 0]
      - delay: "00:00:06"
      - service: light.turn_on
        target:
          entity_id: light.wled_voortuin
        data:
          effect: "Solid"
          rgb_color: [255, 140, 0]
```

- [ ] **Step 3: Setup-instructies**

`home_assistant/README.md`:
```markdown
# Home Assistant setup voor de Halloween-ervaring

1. Installeer/activeer de Mosquitto broker add-on (Settings > Add-ons >
   Mosquitto broker) als die nog niet draait.
2. Zorg dat de MQTT-integratie in HA naar die broker wijst (meestal
   automatisch gedetecteerd na installatie van de add-on).
3. Kopieer de inhoud van `automations/time_window.yaml` en
   `automations/wled_trigger.yaml` naar je HA-automations (via de
   Automations-UI "Edit in YAML", of in `automations.yaml` als je die
   beheert via bestanden).
4. Pas `entity_id: light.wled_voortuin` in `wled_trigger.yaml` aan naar de
   werkelijke entity-id van je WLED-controller (te vinden onder
   Settings > Devices & Services > WLED).
5. Voeg op het dashboard MQTT-sensoren toe voor node-status
   (last-will-topic `log/<node>` of een aparte `status/<node>`-topic, naar
   smaak) zodat je in één oogopslag ziet welke nodes online zijn.
```

- [ ] **Step 4: Handmatige verificatie in HA**

Verwacht: na het toevoegen van de automations en het instellen van de
juiste `entity_id`, triggert een handmatig gepubliceerd bericht
(`mosquitto_pub -t mirror/triggered -m '{}'`) het WLED-lichteffect, en
schakelt de tijdvenster-automation `system/sleep` op de ingestelde tijden.

- [ ] **Step 5: Commit**

```bash
git add home_assistant
git commit -m "feat: HA-automations voor tijdvenster en WLED-koppeling"
```

---

## Na dit plan

Alle testbare logica (MQTT-contract, logging, trigger-detectie, ghost-effect,
audioselectie, cooldown) heeft pytest-dekking en draait op elke
ontwikkelmachine zonder camera/PIR/WLED nodig te hebben. De fysieke
integratie (Tasks 4, 7, 8) wordt op de doelhardware handmatig geverifieerd,
conform de testaanpak uit de spec.
