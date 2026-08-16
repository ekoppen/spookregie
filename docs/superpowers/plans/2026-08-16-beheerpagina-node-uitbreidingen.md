# Beheerpagina — Node-uitbreidingen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maak mirror-node en scare-node live configureerbaar via MQTT (meerdere effecten + overlay-compositing + live-preview-kanaal voor mirror-node, een in-/uitschakelbare bestandenlijst voor scare-node), plus de gedeelde media-sync-laag die straks door de nog te bouwen backend gevoed wordt. Dit is plan 1 van 3 voor de beheerpagina (spec: zie hieronder) — de backend en frontend volgen als aparte plannen zodra hun exacte interfaces (MQTT-payloads, media-API) hier zijn vastgelegd in werkende code.

**Architecture:** Pure-logica-modules (effecten, overlay-wiskunde, preview/persistent-config state machine, media-hash-sync) krijgen volledige pytest-dekking, net als in het vorige plan. De uiteindelijke bekabeling in `mirror_node/main.py` en `scare_node/main.py` (MQTT-abonnementen, MJPEG-server, echte media-fetch) is glue-code zonder geautomatiseerde test — conform hoe deze twee bestanden al in het project werken; verificatie gebeurt handmatig op locatie zodra de backend (plan 2) een media-endpoint aanbiedt om tegen te testen.

**Tech Stack:** Python 3, bestaande dependencies (`opencv-python`, `paho-mqtt`, `numpy`) — geen nieuwe dependency. De MJPEG-server gebruikt stdlib `http.server`/`socketserver`, geen extra webframework op de nodes zelf.

**Spec:** `docs/superpowers/specs/2026-08-16-beheerpagina-design.md` (en de eerdere `docs/superpowers/specs/2026-08-15-voortuin-halloween-ervaring-design.md` voor de bestaande architectuur die dit plan uitbreidt).

## Global Constraints

- Nieuwe MQTT-topics komen alleen bij in `shared/mqtt_contract.py`, volgens hetzelfde patroon als de bestaande topic-helpers. `system/sleep` wordt hergebruikt voor noodstop/tijdvenster — geen nieuwe topic daarvoor in dit plan.
- Geen nieuwe pip-dependencies. De MJPEG-streamer gebruikt uitsluitend de standaardbibliotheek.
- Elk effect volgt exact het contract `(frame_bgr: np.ndarray, params: dict) -> np.ndarray`, geregistreerd in `mirror_node/effects/EFFECTS`.
- `scare_node/playback.py`'s `pick_audio_file` moet backward compatible blijven: een aanroep zonder `enabled`-argument (zoals de bestaande code in `scare_node/main.py` nu al doet) mag niet breken.
- Pure logica (effecten, overlay-compositing, preview/persistent state machine, media-hash-sync, MQTT-contract) krijgt volledige pytest-dekking. Glue-code (MQTT-bekabeling in `main.py`, de MJPEG-HTTP-server) krijgt geen geautomatiseerde test, conform de bestaande projectconventie — wel een expliciete handmatige-verificatiestap in de taak.

---

## File Structure

```
shared/
├── mqtt_contract.py       # uitgebreid: nieuwe topics/payload-helpers
└── media_sync.py           # nieuw: hash + fetch-en-cache, gedeeld door beide nodes
mirror_node/
├── effects/
│   ├── __init__.py          # EFFECTS-register + get_effect()
│   ├── xray.py               # bestaand ghost_effect, hernoemd/verplaatst
│   ├── thermal.py
│   ├── contour.py
│   └── posterize.py
├── overlay.py                # composite_overlay()
├── active_config.py           # ActiveMirrorConfig (preview/persistent state machine)
├── stream.py                   # MJPEGStreamer (stdlib http.server)
└── main.py                      # uitgebreid: MQTT-config-abonnement + streamer wiring
scare_node/
├── playback.py                 # uitgebreid: enabled-filter
└── main.py                      # uitgebreid: config/scare-abonnement + media-sync
tests/
├── test_mqtt_contract.py       # uitgebreid
├── test_media_sync.py           # nieuw
├── test_effects.py               # nieuw (alle 4 filters + registry)
├── test_overlay.py                # nieuw
├── test_active_config.py           # nieuw
└── test_playback.py                 # uitgebreid
```

---

### Task 1: MQTT-contract uitbreiding

**Files:**
- Modify: `shared/mqtt_contract.py`
- Test: `tests/test_mqtt_contract.py` (uitbreiden)

**Interfaces:**
- Produces:
  - `shared.mqtt_contract.TOPIC_CONFIG_MIRROR: str` = `"config/mirror"`
  - `shared.mqtt_contract.TOPIC_CONTROL_MIRROR_PREVIEW: str` = `"control/mirror/preview"`
  - `shared.mqtt_contract.TOPIC_CONTROL_MIRROR_TEST: str` = `"control/mirror/test-trigger"`
  - `shared.mqtt_contract.config_scare_topic(zone: str) -> str` → `"config/scare/{zone}"`
  - `shared.mqtt_contract.control_scare_test_topic(zone: str) -> str` → `"control/scare/{zone}/test-trigger"`

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_mqtt_contract.py` (bovenaan de imports uitbreiden met de nieuwe namen):
```python
from shared.mqtt_contract import (
    TOPIC_CONFIG_MIRROR,
    TOPIC_CONTROL_MIRROR_PREVIEW,
    TOPIC_CONTROL_MIRROR_TEST,
    config_scare_topic,
    control_scare_test_topic,
)


def test_new_topic_constants():
    assert TOPIC_CONFIG_MIRROR == "config/mirror"
    assert TOPIC_CONTROL_MIRROR_PREVIEW == "control/mirror/preview"
    assert TOPIC_CONTROL_MIRROR_TEST == "control/mirror/test-trigger"


def test_config_scare_topic_formats_zone():
    assert config_scare_topic("zone-a") == "config/scare/zone-a"


def test_control_scare_test_topic_formats_zone():
    assert control_scare_test_topic("zone-a") == "control/scare/zone-a/test-trigger"
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_mqtt_contract.py -v`
Expected: FAIL met `ImportError` voor de nieuwe namen.

- [ ] **Step 3: Implementeer de uitbreiding in `shared/mqtt_contract.py`**

Voeg toe (naast de bestaande constanten/templates, niets bestaands wijzigen):
```python
TOPIC_CONFIG_MIRROR = "config/mirror"
TOPIC_CONTROL_MIRROR_PREVIEW = "control/mirror/preview"
TOPIC_CONTROL_MIRROR_TEST = "control/mirror/test-trigger"

_CONFIG_SCARE_TEMPLATE = "config/scare/{zone}"
_CONTROL_SCARE_TEST_TEMPLATE = "control/scare/{zone}/test-trigger"


def config_scare_topic(zone):
    return _CONFIG_SCARE_TEMPLATE.format(zone=zone)


def control_scare_test_topic(zone):
    return _CONTROL_SCARE_TEST_TEMPLATE.format(zone=zone)
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `pytest tests/test_mqtt_contract.py -v`
Expected: PASS (alle tests, oud + nieuw)

- [ ] **Step 5: Commit**

```bash
git add shared/mqtt_contract.py tests/test_mqtt_contract.py
git commit -m "feat: MQTT-topics voor mirror-config/preview en scare-config/test-trigger"
```

---

### Task 2: Gedeelde media-sync (hash + fetch-en-cache)

**Files:**
- Create: `shared/media_sync.py`
- Test: `tests/test_media_sync.py`

**Interfaces:**
- Produces:
  - `shared.media_sync.content_hash(data: bytes) -> str`
  - `shared.media_sync.sync_media(base_url: str, cache_dir: str, wanted_hashes: list[str], fetch=None) -> dict[str, str]`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_media_sync.py`:
```python
from shared.media_sync import content_hash, sync_media


def test_content_hash_is_deterministic_and_hex():
    h1 = content_hash(b"hello")
    h2 = content_hash(b"hello")
    assert h1 == h2
    assert all(c in "0123456789abcdef" for c in h1)


def test_content_hash_differs_for_different_data():
    assert content_hash(b"a") != content_hash(b"b")


def test_sync_media_uses_cache_when_file_exists(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "abc123").write_bytes(b"cached")

    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"should not be called"

    result = sync_media("http://backend", str(cache_dir), ["abc123"], fetch=fake_fetch)

    assert result == {"abc123": str(cache_dir / "abc123")}
    assert calls == []


def test_sync_media_fetches_missing_file(tmp_path):
    cache_dir = tmp_path / "cache"
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"downloaded content"

    result = sync_media("http://backend", str(cache_dir), ["newhash"], fetch=fake_fetch)

    assert calls == ["http://backend/api/media/newhash"]
    assert result == {"newhash": str(cache_dir / "newhash")}
    assert (cache_dir / "newhash").read_bytes() == b"downloaded content"


def test_sync_media_skips_failed_fetch_without_crashing(tmp_path):
    cache_dir = tmp_path / "cache"

    def failing_fetch(url):
        raise OSError("netwerk weg")

    result = sync_media("http://backend", str(cache_dir), ["unreachable"], fetch=failing_fetch)

    assert result == {}
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_media_sync.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'shared.media_sync'`

- [ ] **Step 3: Implementeer `shared/media_sync.py`**

```python
import hashlib
import os
import urllib.request


def content_hash(data):
    return hashlib.sha256(data).hexdigest()


def sync_media(base_url, cache_dir, wanted_hashes, fetch=None):
    """Zorgt dat elk hash uit `wanted_hashes` lokaal in `cache_dir` staat
    (bestandsnaam = de hash). Haalt ontbrekende bestanden op via
    `GET {base_url}/api/media/<hash>`. `fetch` is injecteerbaar voor
    tests; standaard gebruikt het `urllib`. Hashes die niet opgehaald
    konden worden ontbreken in het resultaat — de aanroeper (main.py)
    logt dat apart en blijft op de vorige stand draaien."""
    if fetch is None:
        def fetch(url):
            with urllib.request.urlopen(url, timeout=10) as resp:
                return resp.read()

    os.makedirs(cache_dir, exist_ok=True)
    result = {}
    for h in wanted_hashes:
        local_path = os.path.join(cache_dir, h)
        if os.path.exists(local_path):
            result[h] = local_path
            continue
        try:
            data = fetch(f"{base_url}/api/media/{h}")
        except Exception:
            continue
        with open(local_path, "wb") as f:
            f.write(data)
        result[h] = local_path
    return result
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `pytest tests/test_media_sync.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add shared/media_sync.py tests/test_media_sync.py
git commit -m "feat: gedeelde media hash-sync voor mirror/scare-node"
```

---

### Task 3: Mirror-node effecten-register (xray, thermal, contour, posterize)

**Files:**
- Create: `mirror_node/effects/__init__.py`
- Create: `mirror_node/effects/xray.py`
- Create: `mirror_node/effects/thermal.py`
- Create: `mirror_node/effects/contour.py`
- Create: `mirror_node/effects/posterize.py`
- Test: `tests/test_effects.py`

Het oude `mirror_node/effect.py` (het enkele hardcoded ghost-effect) blijft
in deze taak bewust ongemoeid — `mirror_node/main.py` importeert het nog
en mag op geen enkel moment breken. Task 8 vervangt die import door het
nieuwe register én verwijdert dan pas `mirror_node/effect.py` en
`tests/test_effect.py`, op het moment dat de laatste referentie ernaar
verdwijnt.

**Interfaces:**
- Produces:
  - `mirror_node.effects.EFFECTS: dict[str, callable]`
  - `mirror_node.effects.get_effect(name: str) -> callable` (elk `(frame_bgr, params) -> frame_bgr`)

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_effects.py`:
```python
import numpy as np
from mirror_node.effects import EFFECTS, get_effect


def _sample_frame():
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    frame[5:15, 5:15] = (200, 100, 50)
    return frame


def test_registry_contains_all_four_effects():
    assert set(EFFECTS.keys()) == {"xray", "thermal", "contour", "posterize"}


def test_get_effect_returns_callable_for_known_name():
    fn = get_effect("xray")
    assert callable(fn)


def test_get_effect_raises_for_unknown_name():
    try:
        get_effect("nonexistent")
        assert False, "had een ValueError moeten geven"
    except ValueError:
        pass


def test_all_effects_preserve_shape_and_dtype():
    frame = _sample_frame()
    for name, fn in EFFECTS.items():
        result = fn(frame, {})
        assert result.shape == frame.shape, f"{name} veranderde de shape"
        assert result.dtype == np.uint8, f"{name} veranderde het dtype"


def test_xray_intensity_zero_differs_from_intensity_one():
    frame = _sample_frame()
    low = EFFECTS["xray"](frame, {"intensity": 0.0})
    high = EFFECTS["xray"](frame, {"intensity": 1.0})
    assert not np.array_equal(low, high)


def test_thermal_intensity_zero_differs_from_intensity_one():
    frame = _sample_frame()
    low = EFFECTS["thermal"](frame, {"intensity": 0.0})
    high = EFFECTS["thermal"](frame, {"intensity": 1.0})
    assert not np.array_equal(low, high)


def test_posterize_reduces_unique_values():
    frame = _sample_frame()
    result = EFFECTS["posterize"](frame, {"levels": 2})
    assert len(np.unique(result)) <= len(np.unique(frame))


def test_contour_output_is_edges_on_black():
    # Een egaal frame heeft geen randen -> praktisch zwart resultaat.
    flat_frame = np.full((20, 20, 3), 128, dtype=np.uint8)
    result = EFFECTS["contour"](flat_frame, {})
    assert result.mean() < 5
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_effects.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'mirror_node.effects'`

- [ ] **Step 3: Implementeer de effecten**

`mirror_node/effects/xray.py`:
```python
import cv2


def xray(frame_bgr, params):
    """params: {"intensity": float 0.0-1.0, standaard 1.0}."""
    intensity = float(params.get("intensity", 1.0))
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    inverted = cv2.bitwise_not(gray)
    blurred = cv2.GaussianBlur(inverted, (9, 9), 0)
    effect = cv2.cvtColor(blurred, cv2.COLOR_GRAY2BGR)
    if intensity >= 1.0:
        return effect
    base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return cv2.addWeighted(effect, intensity, base, 1 - intensity, 0)
```

`mirror_node/effects/thermal.py`:
```python
import cv2


def thermal(frame_bgr, params):
    """params: {"intensity": float 0.0-1.0, standaard 1.0}."""
    intensity = float(params.get("intensity", 1.0))
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    colored = cv2.applyColorMap(gray, cv2.COLORMAP_JET)
    if intensity >= 1.0:
        return colored
    base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return cv2.addWeighted(colored, intensity, base, 1 - intensity, 0)
```

`mirror_node/effects/contour.py`:
```python
import cv2


def contour(frame_bgr, params):
    """params: {"threshold1": int standaard 50, "threshold2": int standaard 150}."""
    threshold1 = int(params.get("threshold1", 50))
    threshold2 = int(params.get("threshold2", 150))
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, threshold1, threshold2)
    return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
```

`mirror_node/effects/posterize.py`:
```python
import numpy as np


def posterize(frame_bgr, params):
    """params: {"levels": int >= 2, standaard 4}."""
    levels = max(2, int(params.get("levels", 4)))
    step = 256 // levels
    return ((frame_bgr.astype(np.int32) // step) * step).astype(np.uint8)
```

`mirror_node/effects/__init__.py`:
```python
from .xray import xray
from .thermal import thermal
from .contour import contour
from .posterize import posterize

EFFECTS = {
    "xray": xray,
    "thermal": thermal,
    "contour": contour,
    "posterize": posterize,
}


def get_effect(name):
    try:
        return EFFECTS[name]
    except KeyError:
        raise ValueError(f"Onbekend effect: {name}") from None
```

- [ ] **Step 4: Run de volledige suite, verwacht PASS**

Run: `pytest tests/ -v`
Expected: PASS (`test_effects.py` (8 tests) slaagt erbij, `test_effect.py` blijft ook nog slagen — het oude bestand is nog niet verwijderd, zie de toelichting hierboven)

- [ ] **Step 5: Commit**

```bash
git add mirror_node/effects tests/test_effects.py
git commit -m "feat: effecten-register (xray, thermal, contour, posterize) ter vervanging van het enkele ghost_effect"
```

---

### Task 4: Overlay-compositing

**Files:**
- Create: `mirror_node/overlay.py`
- Test: `tests/test_overlay.py`

**Interfaces:**
- Produces: `mirror_node.overlay.composite_overlay(frame_bgr: np.ndarray, overlay_bgra: np.ndarray, scale: float = 1.0, position: tuple[float, float] = (0.5, 0.5)) -> np.ndarray`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_overlay.py`:
```python
import numpy as np
from mirror_node.overlay import composite_overlay


def test_fully_opaque_overlay_covers_center():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    overlay = np.zeros((20, 20, 4), dtype=np.uint8)
    overlay[:, :, :3] = (10, 20, 30)  # BGR
    overlay[:, :, 3] = 255  # volledig ondoorzichtig

    result = composite_overlay(frame, overlay, scale=1.0, position=(0.5, 0.5))

    center_pixel = result[50, 50]
    assert tuple(center_pixel) == (10, 20, 30)
    # buiten de overlay blijft het frame ongewijzigd
    assert tuple(result[0, 0]) == (0, 0, 0)


def test_fully_transparent_overlay_leaves_frame_unchanged():
    frame = np.full((50, 50, 3), 100, dtype=np.uint8)
    overlay = np.zeros((10, 10, 4), dtype=np.uint8)
    overlay[:, :, :3] = 255
    overlay[:, :, 3] = 0  # volledig doorzichtig

    result = composite_overlay(frame, overlay, scale=1.0, position=(0.5, 0.5))

    assert np.array_equal(result, frame)


def test_original_frame_is_not_mutated():
    frame = np.zeros((30, 30, 3), dtype=np.uint8)
    overlay = np.full((10, 10, 4), 255, dtype=np.uint8)

    composite_overlay(frame, overlay)

    assert np.array_equal(frame, np.zeros((30, 30, 3), dtype=np.uint8))


def test_overlay_partially_outside_frame_does_not_crash():
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    overlay = np.full((10, 10, 4), 255, dtype=np.uint8)

    result = composite_overlay(frame, overlay, scale=1.0, position=(0.0, 0.0))

    assert result.shape == frame.shape


def test_overlay_larger_than_frame_does_not_crash():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    overlay = np.full((50, 50, 4), 255, dtype=np.uint8)

    result = composite_overlay(frame, overlay, scale=1.0, position=(0.5, 0.5))

    assert result.shape == frame.shape
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_overlay.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'mirror_node.overlay'`

- [ ] **Step 3: Implementeer `mirror_node/overlay.py`**

```python
import cv2
import numpy as np


def composite_overlay(frame_bgr, overlay_bgra, scale=1.0, position=(0.5, 0.5)):
    """Legt `overlay_bgra` (met alphakanaal) over `frame_bgr` heen.
    `scale` schaalt de overlay t.o.v. zijn eigen afmetingen; `position`
    is het middelpunt van de overlay als fractie (x, y) van het frame
    (0.0-1.0). Geeft een nieuw frame terug, wijzigt de input niet."""
    frame_h, frame_w = frame_bgr.shape[:2]
    ov_h, ov_w = overlay_bgra.shape[:2]

    new_w = max(1, int(ov_w * scale))
    new_h = max(1, int(ov_h * scale))
    resized = cv2.resize(overlay_bgra, (new_w, new_h))

    center_x = int(position[0] * frame_w)
    center_y = int(position[1] * frame_h)
    x0 = center_x - new_w // 2
    y0 = center_y - new_h // 2

    result = frame_bgr.copy()

    src_x0, src_y0 = max(0, -x0), max(0, -y0)
    dst_x0, dst_y0 = max(0, x0), max(0, y0)
    dst_x1 = min(frame_w, x0 + new_w)
    dst_y1 = min(frame_h, y0 + new_h)
    if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
        return result  # overlay valt volledig buiten het frame

    src_x1 = src_x0 + (dst_x1 - dst_x0)
    src_y1 = src_y0 + (dst_y1 - dst_y0)

    overlay_region = resized[src_y0:src_y1, src_x0:src_x1]
    alpha = overlay_region[:, :, 3:4].astype(np.float32) / 255.0
    overlay_rgb = overlay_region[:, :, :3].astype(np.float32)

    dst_region = result[dst_y0:dst_y1, dst_x0:dst_x1].astype(np.float32)
    blended = overlay_rgb * alpha + dst_region * (1 - alpha)
    result[dst_y0:dst_y1, dst_x0:dst_x1] = blended.astype(np.uint8)

    return result
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `pytest tests/test_overlay.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mirror_node/overlay.py tests/test_overlay.py
git commit -m "feat: PNG-overlay-compositing met schaal en positie"
```

---

### Task 5: Preview/persistent config state machine

**Files:**
- Create: `mirror_node/active_config.py`
- Test: `tests/test_active_config.py`

**Interfaces:**
- Produces: `mirror_node.active_config.ActiveMirrorConfig(preview_timeout=30, clock=time.monotonic)` met methoden `.set_persistent(config: dict)`, `.set_preview(config: dict)`, `.get() -> dict`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_active_config.py`:
```python
from mirror_node.active_config import ActiveMirrorConfig


def test_get_returns_default_persistent_config_initially():
    cfg = ActiveMirrorConfig(clock=lambda: 0.0)
    result = cfg.get()
    assert result["effect"] == "xray"


def test_set_persistent_updates_get():
    cfg = ActiveMirrorConfig(clock=lambda: 0.0)
    cfg.set_persistent({"effect": "thermal", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    assert cfg.get()["effect"] == "thermal"


def test_preview_overrides_persistent_within_timeout():
    times = iter([0.0, 0.0, 5.0])  # set_persistent, set_preview, get
    cfg = ActiveMirrorConfig(preview_timeout=30, clock=lambda: next(times))
    cfg.set_persistent({"effect": "xray", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    cfg.set_preview({"effect": "contour", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    assert cfg.get()["effect"] == "contour"


def test_preview_expires_after_timeout():
    times = iter([0.0, 0.0, 40.0])  # set_persistent, set_preview, get (na timeout)
    cfg = ActiveMirrorConfig(preview_timeout=30, clock=lambda: next(times))
    cfg.set_persistent({"effect": "xray", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    cfg.set_preview({"effect": "contour", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    assert cfg.get()["effect"] == "xray"


def test_new_persistent_config_clears_active_preview():
    times = iter([0.0, 0.0, 0.0])
    cfg = ActiveMirrorConfig(preview_timeout=30, clock=lambda: next(times))
    cfg.set_preview({"effect": "contour", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    cfg.set_persistent({"effect": "thermal", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    assert cfg.get()["effect"] == "thermal"
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_active_config.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'mirror_node.active_config'`

- [ ] **Step 3: Implementeer `mirror_node/active_config.py`**

```python
import time


class ActiveMirrorConfig:
    """Houdt de actieve effect-config bij: een opgeslagen (persistente)
    config en een tijdelijke preview-config die na `preview_timeout`
    seconden zonder update automatisch vervalt. `.get()` geeft altijd de
    config die nu getoond moet worden, zodat een vergeten open
    beheerpagina-tab de projectie niet voor altijd in een proefstand
    laat hangen."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._persistent = {
            "effect": "xray",
            "params": {},
            "overlay_hash": None,
            "scale": 1.0,
            "position": [0.5, 0.5],
        }
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_persistent(self, config):
        self._persistent = config
        self._preview = None

    def set_preview(self, config):
        self._preview = config
        self._preview_set_at = self._clock()

    def get(self):
        if self._preview is not None:
            if self._clock() - self._preview_set_at <= self._preview_timeout:
                return self._preview
            self._preview = None
        return self._persistent
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `pytest tests/test_active_config.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mirror_node/active_config.py tests/test_active_config.py
git commit -m "feat: preview/persistent config state machine voor mirror-node"
```

---

### Task 6: Scare-node — inschakelbare bestandenlijst

**Files:**
- Modify: `scare_node/playback.py`
- Test: `tests/test_playback.py` (uitbreiden)

**Interfaces:**
- Produces (gewijzigde signatuur, backward compatible): `scare_node.playback.pick_audio_file(media_dir: str, rng=random, enabled: set[str] | None = None) -> str`

- [ ] **Step 1: Schrijf de falende test**

Voeg toe aan `tests/test_playback.py`:
```python
def test_enabled_filter_restricts_selection(tmp_path):
    (tmp_path / "scream1.wav").write_bytes(b"fake")
    (tmp_path / "scream2.wav").write_bytes(b"fake")

    picked = pick_audio_file(str(tmp_path), enabled={"scream1.wav"})

    assert picked == str(tmp_path / "scream1.wav")


def test_enabled_filter_empty_set_raises(tmp_path):
    (tmp_path / "scream1.wav").write_bytes(b"fake")

    with pytest.raises(FileNotFoundError):
        pick_audio_file(str(tmp_path), enabled=set())


def test_no_enabled_argument_still_considers_all_files(tmp_path):
    (tmp_path / "scream1.wav").write_bytes(b"fake")

    picked = pick_audio_file(str(tmp_path))

    assert picked == str(tmp_path / "scream1.wav")
```

Zorg dat `import pytest` bovenaan `tests/test_playback.py` staat (nodig voor `pytest.raises` — check of dat al zo is, anders toevoegen).

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_playback.py -v`
Expected: FAIL — `pick_audio_file()` accepteert `enabled` nog niet (TypeError), of de filtering ontbreekt.

- [ ] **Step 3: Pas `scare_node/playback.py` aan**

```python
import os
import random

_AUDIO_EXTENSIONS = (".wav",)


def pick_audio_file(media_dir, rng=random, enabled=None):
    files = [f for f in os.listdir(media_dir) if f.lower().endswith(_AUDIO_EXTENSIONS)]
    if enabled is not None:
        files = [f for f in files if f in enabled]
    if not files:
        raise FileNotFoundError(f"Geen (ingeschakelde) audiobestanden gevonden in {media_dir}")
    return os.path.join(media_dir, rng.choice(files))
```

(Dit bestand had in het vorige plan al `.wav`-only — als dat anders is, alleen de `enabled`-parameter toevoegen zonder de extensie-logica te wijzigen.)

- [ ] **Step 4: Run de volledige suite, verwacht PASS**

Run: `pytest tests/ -v`
Expected: PASS (alle bestaande + nieuwe tests)

- [ ] **Step 5: Commit**

```bash
git add scare_node/playback.py tests/test_playback.py
git commit -m "feat: inschakelbare-bestandenlijst voor scare-node audioselectie"
```

---

### Task 7: MJPEG-streamer voor mirror-node

**Files:**
- Create: `mirror_node/stream.py`

**Interfaces:**
- Consumes: niets uit eerdere taken (staat op zichzelf, wordt in Task 8 bekabeld)
- Produces: `mirror_node.stream.MJPEGStreamer(port: int)` met methoden `.publish_frame(frame_bgr: np.ndarray)`, `.start()`, `.stop()`

Glue/IO-code (een echte HTTP-server) — geen geautomatiseerde test, conform de bestaande projectconventie voor dit soort code. Verificatie gebeurt handmatig in Task 8's verificatiestap.

- [ ] **Step 1: Implementeer `mirror_node/stream.py`**

```python
import threading

import cv2
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from http.server import HTTPServer

_BOUNDARY = "frame"


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class MJPEGStreamer:
    """Serveert het laatst gepubliceerde frame als MJPEG over HTTP op
    `/stream`. `publish_frame()` wordt vanuit de hoofdloop aangeroepen;
    elke binnenkomende HTTP-verbinding krijgt zijn eigen thread die
    steeds het nieuwste frame stuurt (multipart/x-mixed-replace)."""

    def __init__(self, port):
        self._port = port
        self._frame_lock = threading.Lock()
        self._latest_jpeg = None
        self._server = None

    def publish_frame(self, frame_bgr):
        ok, encoded = cv2.imencode(".jpg", frame_bgr)
        if not ok:
            return
        with self._frame_lock:
            self._latest_jpeg = encoded.tobytes()

    def _get_latest_jpeg(self):
        with self._frame_lock:
            return self._latest_jpeg

    def start(self):
        streamer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_GET(self):
                if self.path != "/stream":
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
                )
                self.end_headers()
                try:
                    while True:
                        jpeg = streamer._get_latest_jpeg()
                        if jpeg is None:
                            continue
                        self.wfile.write(f"--{_BOUNDARY}\r\n".encode())
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self._server = _ThreadingHTTPServer(("0.0.0.0", self._port), Handler)
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
```

- [ ] **Step 2: Syntax-/importcontrole**

Run: `python3 -c "import ast; ast.parse(open('mirror_node/stream.py').read())"`
Expected: geen output (parseert schoon)

Run: `python3 -c "from mirror_node.stream import MJPEGStreamer"`
Expected: geen output (importeert schoon, alleen stdlib + al-geïnstalleerde `cv2`)

- [ ] **Step 3: Commit**

```bash
git add mirror_node/stream.py
git commit -m "feat: MJPEG-streamer voor live camera-preview op mirror-node"
```

---

### Task 8: Mirror-node main.py — bekabeling van effecten, overlay, config en streamer

**Files:**
- Modify: `mirror_node/main.py`

**Interfaces:**
- Consumes:
  - `shared.mqtt_contract.{TOPIC_CONFIG_MIRROR, TOPIC_CONTROL_MIRROR_PREVIEW}` (Task 1)
  - `shared.media_sync.sync_media(base_url, cache_dir, wanted_hashes)` (Task 2)
  - `mirror_node.effects.get_effect(name)` (Task 3)
  - `mirror_node.overlay.composite_overlay(frame, overlay, scale, position)` (Task 4)
  - `mirror_node.active_config.ActiveMirrorConfig` (Task 5)
  - `mirror_node.stream.MJPEGStreamer` (Task 7)
- Produces: bijgewerkt `mirror_node/main.py`

Glue-code, geen geautomatiseerde test — verificatie hieronder is handmatig
(vereist deels een draaiende backend uit plan 2 voor de media-fetch; het
MJPEG-deel en de effect/overlay-toepassing zijn zonder backend te
verifiëren).

- [ ] **Step 1: Vervang `mirror_node/main.py` volledig door onderstaande inhoud**

Dit is het huidige bestand (met `NODE_NAME`, `SLEEP_PAYLOAD_ON`,
`status_topic`, de `MQTT_USER`/`will_set`/`connect_async`-opzet en
`selfcheck()` zoals ze nu al bestaan) plus de nieuwe
config/preview/streamer-logica erin verweven — dit vervangt het hele
bestand, geen losse toevoeging:

```python
import json
import os
import sys
import tempfile
import time
import threading

import cv2
import paho.mqtt.client as mqtt

from shared.mqtt_contract import (
    SLEEP_PAYLOAD_ON,
    TOPIC_MIRROR_TRIGGERED,
    TOPIC_SYSTEM_SLEEP,
    TOPIC_CONFIG_MIRROR,
    TOPIC_CONTROL_MIRROR_PREVIEW,
    status_topic,
    trigger_payload,
)
from shared.logging_setup import setup_logging
from shared.media_sync import sync_media
from mirror_node.trigger import FrameDiffTrigger
from mirror_node.effects import get_effect
from mirror_node.overlay import composite_overlay
from mirror_node.active_config import ActiveMirrorConfig
from mirror_node.stream import MJPEGStreamer

NODE_NAME = "mirror"

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
# Optioneel: brokers zonder authenticatie laten MQTT_USER leeg.
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
CAMERA_INDEX = int(os.environ.get("MIRROR_CAMERA_INDEX", "0"))
ACTIVE_SECONDS = float(os.environ.get("MIRROR_ACTIVE_SECONDS", "6"))
# Default schrijfbaar voor een gewone gebruiker die het script direct start;
# systemd zet LOG_DIR expliciet op /var/log/halloween.
LOG_DIR = os.environ.get("LOG_DIR", "./logs")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
MEDIA_CACHE_DIR = os.environ.get("MIRROR_MEDIA_CACHE_DIR", "./media_cache")
STREAM_PORT = int(os.environ.get("MIRROR_STREAM_PORT", "8091"))

sleeping = threading.Event()
active_config = ActiveMirrorConfig()


def _apply_config_message(payload, is_preview, logger):
    try:
        config = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige config-JSON ontvangen, genegeerd")
        return
    if is_preview:
        active_config.set_preview(config)
        return
    active_config.set_persistent(config)
    overlay_hash = config.get("overlay_hash")
    if overlay_hash:
        sync_media(BACKEND_URL, MEDIA_CACHE_DIR, [overlay_hash])


def make_on_message(logger):
    def on_message(client, userdata, msg):
        if msg.topic == TOPIC_SYSTEM_SLEEP:
            if msg.payload.decode() == SLEEP_PAYLOAD_ON:
                sleeping.set()
            else:
                sleeping.clear()
            return
        if msg.topic == TOPIC_CONFIG_MIRROR:
            _apply_config_message(msg.payload.decode(), is_preview=False, logger=logger)
            return
        if msg.topic == TOPIC_CONTROL_MIRROR_PREVIEW:
            _apply_config_message(msg.payload.decode(), is_preview=True, logger=logger)
    return on_message


def _render(frame, logger):
    config = active_config.get()
    try:
        effect_fn = get_effect(config["effect"])
    except ValueError:
        logger.error("Onbekend effect in actieve config: %s", config.get("effect"))
        return frame

    result = effect_fn(frame, config.get("params", {}))

    overlay_hash = config.get("overlay_hash")
    if overlay_hash:
        overlay_path = os.path.join(MEDIA_CACHE_DIR, overlay_hash)
        if os.path.exists(overlay_path):
            overlay_img = cv2.imread(overlay_path, cv2.IMREAD_UNCHANGED)
            if overlay_img is not None and overlay_img.shape[2] == 4:
                result = composite_overlay(
                    result,
                    overlay_img,
                    scale=config.get("scale", 1.0),
                    position=tuple(config.get("position", [0.5, 0.5])),
                )
    return result


def selfcheck():
    """Pakt één frame, draait het door het standaard xray-effect en
    laat/bewaart het resultaat. Heeft geen MQTT nodig."""
    cap = cv2.VideoCapture(CAMERA_INDEX)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print(f"selfcheck MISLUKT: geen frame van camera index {CAMERA_INDEX}")
        sys.exit(1)

    ghost = get_effect("xray")(frame, {})
    path = os.path.join(tempfile.gettempdir(), "mirror-selfcheck.png")
    cv2.imwrite(path, ghost)
    print(f"selfcheck OK: xray-frame opgeslagen als {path}")

    try:
        cv2.imshow("mirror-selfcheck", ghost)
        cv2.waitKey(2000)
        cv2.destroyAllWindows()
    except cv2.error as exc:
        print(f"(geen display beschikbaar: {exc})")


def main():
    if "--selfcheck" in sys.argv:
        selfcheck()
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)

    client = mqtt.Client(client_id="mirror-node")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    # setup_logging vóór de callbacks: die loggen naar het lokale bestand,
    # wat ook werkt als de broker onbereikbaar is.
    logger = setup_logging(NODE_NAME, LOG_DIR, mqtt_client=client)

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT verbonden met %s:%s", MQTT_HOST, MQTT_PORT)
        else:
            logger.error("MQTT verbinden mislukt (rc=%s)", rc)
            return
        client.publish(status_topic(NODE_NAME), "online", retain=True)
        client.subscribe(TOPIC_SYSTEM_SLEEP)
        client.subscribe(TOPIC_CONFIG_MIRROR)
        client.subscribe(TOPIC_CONTROL_MIRROR_PREVIEW)

    def on_disconnect(client, userdata, rc):
        logger.warning("MQTT verbinding verbroken (rc=%s)", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = make_on_message(logger)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # Last-will: broker publiceert "offline" als deze node wegvalt.
    client.will_set(status_topic(NODE_NAME), payload="offline", retain=True)
    # connect_async + loop_start: node blijft draaien en probeert op de
    # achtergrond te (her)verbinden, i.p.v. te crashen als HA nu niet
    # bereikbaar is (fail-safe eis uit de spec).
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    streamer = MJPEGStreamer(STREAM_PORT)
    streamer.start()
    logger.info("MJPEG-stream op poort %s (/stream)", STREAM_PORT)

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

            rendered = _render(frame, logger) if now < active_until else frame * 0
            streamer.publish_frame(rendered)
            cv2.imshow("mirror", rendered)
            cv2.waitKey(1)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        streamer.stop()
        client.loop_stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verwijder het nu ongebruikte oude effect-bestand**

`mirror_node/effect.py` en zijn test worden nergens meer geïmporteerd
zodra Step 1 is doorgevoerd — dit is het moment om ze te verwijderen:

```bash
git rm mirror_node/effect.py tests/test_effect.py
```

- [ ] **Step 3: Syntax-/importcontrole**

Run: `python3 -c "import ast; ast.parse(open('mirror_node/main.py').read())"`
Expected: geen output

Run: `python3 -c "import mirror_node.main"`
Expected: geen output (importeert schoon met de geïnstalleerde dependencies)

- [ ] **Step 4: Run de volledige pytest-suite, verwacht PASS**

Run: `pytest tests/ -v`
Expected: PASS — `test_effect.py` is weg (bewust, Step 2), alle overige tests (incl. `test_effects.py` uit Task 3) slagen nog steeds.

- [ ] **Step 5: Handmatige verificatie (deels, zonder backend)**

Run: `MQTT_HOST=<ha-host> python3 -m mirror_node.main`
Verwacht: camerabeeld-venster opent zoals voorheen; `curl
http://localhost:8091/stream` (of een browser) toont een live MJPEG-stream
van het verwerkte beeld. Config-berichten publiceren
(`mosquitto_pub -t config/mirror -m '{"effect":"thermal","params":{"intensity":0.7},"overlay_hash":null,"scale":1.0,"position":[0.5,0.5]}'`)
en controleren dat het effect in de stream direct wisselt. Media-fetch
(overlay ophalen bij de backend) kan pas volledig getest worden zodra plan
2 (backend) draait — noteer dat als openstaand punt, geen blokkade voor
deze taak.

- [ ] **Step 6: Commit**

```bash
git add mirror_node/main.py
git commit -m "feat: mirror-node bekabeld met effecten, overlay, live-config en MJPEG-preview"
```

---

### Task 9: Scare-node main.py — bekabeling van config en test-trigger

**Files:**
- Modify: `scare_node/main.py`

**Interfaces:**
- Consumes:
  - `shared.mqtt_contract.{config_scare_topic, control_scare_test_topic}` (Task 1)
  - `shared.media_sync.sync_media(base_url, cache_dir, wanted_hashes)` (Task 2)
  - `scare_node.playback.pick_audio_file(media_dir, enabled=...)` (Task 6)
- Produces: bijgewerkt `scare_node/main.py`

Glue-code, geen geautomatiseerde test — verificatie hieronder is handmatig.

- [ ] **Step 1: Vervang `scare_node/main.py` volledig door onderstaande inhoud**

Dit is het huidige bestand (met `NODE_NAME`, `SLEEP_PAYLOAD_ON`,
`status_topic`, `trigger_scare`, `selfcheck()` en de bestaande
opstart-mediavalidatie zoals ze nu al bestaan) plus de nieuwe
config/test-trigger-logica erin verweven — dit vervangt het hele bestand:

```python
import json
import os
import random
import subprocess
import sys
import threading
import time

import paho.mqtt.client as mqtt

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
from scare_node.playback import pick_audio_file
from scare_node.debounce import Cooldown

ZONE = os.environ.get("SCARE_ZONE", "zone-a")
NODE_NAME = f"scare-{ZONE}"

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
# Optioneel: brokers zonder authenticatie laten MQTT_USER leeg.
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MEDIA_DIR = os.environ.get("SCARE_MEDIA_DIR", "/opt/halloween/media")
PIR_PIN = int(os.environ.get("SCARE_PIR_PIN", "4"))
COOLDOWN_SECONDS = float(os.environ.get("SCARE_COOLDOWN_SECONDS", "12"))
# Default schrijfbaar voor een gewone gebruiker die het script direct start;
# systemd zet LOG_DIR expliciet op /var/log/halloween.
LOG_DIR = os.environ.get("LOG_DIR", "./logs")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
MEDIA_CACHE_DIR = os.environ.get("SCARE_MEDIA_CACHE_DIR", "./media_cache")

sleeping = threading.Event()
cooldown = Cooldown(COOLDOWN_SECONDS)
enabled_files = None  # None = alles toegestaan (backward compatible, Task 6)


def _apply_scare_config(payload, logger):
    global enabled_files
    try:
        config = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige scare-config-JSON ontvangen, genegeerd")
        return
    hashes = config.get("enabled_hashes", [])
    sync_media(BACKEND_URL, MEDIA_CACHE_DIR, hashes)
    enabled_files = set(config.get("enabled_filenames", []))


def play_scare(logger):
    """Speelt één willekeurig fragment af uit de ingeschakelde set (of alle
    bestanden als er nog geen config binnen is). Doet zelf geen
    cooldown-check."""
    try:
        audio_file = pick_audio_file(MEDIA_DIR, enabled=enabled_files)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return
    logger.info("speelt %s af", audio_file)
    result = subprocess.run(["aplay", audio_file], check=False)
    if result.returncode != 0:
        logger.error("aplay faalde (returncode=%s) op %s", result.returncode, audio_file)


def trigger_scare(client, logger):
    """Enige plek waar een scare start: cooldown-check, dan meteen het
    scare-topic publiceren (zodat HA/WLED niet op het geluid hoeft te
    wachten) en pas daarna afspelen."""
    if not cooldown.ready():
        return
    client.publish(scare_topic(ZONE), trigger_payload())
    play_scare(logger)


def make_on_message(logger):
    def on_message(client, userdata, msg):
        if msg.topic == TOPIC_SYSTEM_SLEEP:
            if msg.payload.decode() == SLEEP_PAYLOAD_ON:
                sleeping.set()
            else:
                sleeping.clear()
            return
        if msg.topic == config_scare_topic(ZONE):
            _apply_scare_config(msg.payload.decode(), logger)
            return
        if msg.topic == control_scare_test_topic(ZONE):
            trigger_scare(client, logger)
            return
        if msg.topic == TOPIC_MIRROR_TRIGGERED and not sleeping.is_set():
            delay = random.uniform(0, 2)
            threading.Timer(delay, trigger_scare, args=(client, logger)).start()
    return on_message


def selfcheck():
    """Speelt één fragment af en publiceert (best-effort) één testbericht.
    Heeft geen PIR-sensor en geen bereikbare broker nodig."""
    print(f"selfcheck scare-node {ZONE}")
    try:
        audio_file = pick_audio_file(MEDIA_DIR)
    except FileNotFoundError as exc:
        print(f"selfcheck MISLUKT: {exc}")
        sys.exit(1)

    print(f"speelt {audio_file} af")
    try:
        result = subprocess.run(["aplay", audio_file], check=False)
    except FileNotFoundError:
        print("selfcheck MISLUKT: `aplay` niet gevonden (alsa-utils installeren)")
        sys.exit(1)
    if result.returncode != 0:
        print(f"selfcheck MISLUKT: aplay returncode={result.returncode}")
        sys.exit(1)

    client = mqtt.Client(client_id=f"scare-selfcheck-{ZONE}")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
        client.loop_start()
        client.publish(scare_topic(ZONE), trigger_payload())
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()
        print(f"MQTT OK: {scare_topic(ZONE)} gepubliceerd")
    except OSError as exc:
        print(f"MQTT niet bereikbaar ({exc}) — audio werkte wel")

    print("selfcheck OK")


def main():
    if "--selfcheck" in sys.argv:
        selfcheck()
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)

    client = mqtt.Client(client_id=f"scare-node-{ZONE}")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    logger = setup_logging(NODE_NAME, LOG_DIR, mqtt_client=client)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            logger.error("MQTT verbinden mislukt (rc=%s)", rc)
            return
        logger.info("MQTT verbonden met %s:%s", MQTT_HOST, MQTT_PORT)
        client.publish(status_topic(NODE_NAME), "online", retain=True)
        client.subscribe(TOPIC_MIRROR_TRIGGERED)
        client.subscribe(TOPIC_SYSTEM_SLEEP)
        client.subscribe(config_scare_topic(ZONE))
        client.subscribe(control_scare_test_topic(ZONE))

    def on_disconnect(client, userdata, rc):
        logger.warning("MQTT verbinding verbroken (rc=%s)", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = make_on_message(logger)

    # Mediamap bij opstarten valideren (spec-eis), niet pas midden in een
    # scare-moment. De uitkomst zelf wordt niet hergebruikt: elke scare kiest
    # opnieuw willekeurig.
    try:
        logger.info("mediamap %s OK (bijv. %s)", MEDIA_DIR, pick_audio_file(MEDIA_DIR))
    except FileNotFoundError as exc:
        logger.error("Mediamap onbruikbaar, node stopt: %s", exc)
        return

    # Last-will: broker publiceert "offline" als deze node wegvalt.
    client.will_set(status_topic(NODE_NAME), payload="offline", retain=True)
    # connect_async + loop_start: node blijft draaien en probeert op de
    # achtergrond te (her)verbinden, i.p.v. te crashen als HA nu niet
    # bereikbaar is (fail-safe eis uit de spec). on_message staat hierboven
    # al vast, zodat het achtergrondthread geen berichten kan missen terwijl
    # de main thread nog met de rest van de setup bezig is.
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    from gpiozero import MotionSensor  # pas hier nodig: selfcheck werkt zonder GPIO

    pir = MotionSensor(PIR_PIN)

    def on_motion():
        if sleeping.is_set():
            return
        trigger_scare(client, logger)

    pir.when_motion = on_motion

    logger.info("scare-node %s gestart op pin %s", ZONE, PIR_PIN)
    threading.Event().wait()  # blokkeert voor altijd


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax-/importcontrole**

Run: `python3 -c "import ast; ast.parse(open('scare_node/main.py').read())"`
Expected: geen output

- [ ] **Step 3: Run de volledige pytest-suite, verwacht PASS**

Run: `pytest tests/ -v`
Expected: PASS — regressiecontrole, deze taak voegt geen tests toe.

- [ ] **Step 4: Handmatige verificatie (deels, zonder backend)**

Publiceer handmatig een config-bericht
(`mosquitto_pub -t config/scare/zone-a -m '{"enabled_hashes":[],"enabled_filenames":["scream1.wav"]}'`)
en controleer dat een volgende PIR-trigger/test-trigger alleen dat bestand
kan kiezen. Test-trigger:
`mosquitto_pub -t control/scare/zone-a/test-trigger -m '{}'` moet
onmiddellijk (met de bestaande 0-2s-vertragingslogica alleen van
toepassing op de mirror-reactie-pad, niet hier) een geluid afspelen en
`cooldown` respecteren zoals voorheen.

- [ ] **Step 5: Commit**

```bash
git add scare_node/main.py
git commit -m "feat: scare-node bekabeld met live audio-config en test-trigger"
```

---

## Na dit plan

Alle pure logica (MQTT-contract, media-sync, effecten, overlay-compositing,
preview/persistent state machine, audioselectie) heeft volledige
pytest-dekking. De twee `main.py`-bestanden zijn uitgebreid maar nog niet
volledig end-to-end te verifiëren zonder de backend (plan 2) — dat is een
bekend, geaccepteerd tussenpunt, geen fout. Plan 2 (backend) kan nu de
exacte MQTT-payload-vormen en het `GET /api/media/<hash>`-contract
overnemen zoals hier in code vastgelegd.
