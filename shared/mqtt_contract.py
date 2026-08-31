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
    def config_mirror_graph(self) -> str:
        return self._p("config/mirror/graph")

    @property
    def control_mirror_scene_preview(self) -> str:
        return self._p("control/mirror/scene-preview")

    @property
    def control_mirror_test(self) -> str:
        return self._p("control/mirror/test-trigger")

    @property
    def control_mirror_ha_trigger(self) -> str:
        return self._p("control/mirror/ha-trigger")

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

    @property
    def config_mirror_scare_video(self) -> str:
        return self._p("config/mirror/scare-video")

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
