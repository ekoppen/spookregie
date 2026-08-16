import asyncio
import json

import paho.mqtt.client as mqtt

from shared.mqtt_contract import (
    SLEEP_PAYLOAD_ON,
    SLEEP_PAYLOAD_OFF,
    TOPIC_SYSTEM_SLEEP,
    TOPIC_CONFIG_MIRROR,
    TOPIC_CONTROL_MIRROR_PREVIEW,
    TOPIC_CONTROL_MIRROR_TEST,
    TOPIC_MIRROR_TRIGGERED,
    scare_topic,
    config_scare_topic,
    control_scare_test_topic,
)

_STATUS_WILDCARD = "status/+"
_LOG_WILDCARD = "log/+"
_SCARE_TRIGGERED_WILDCARD = "scare/+/triggered"


class MqttBridge:
    """Verbindt de backend met dezelfde broker als de nodes. Leest
    status/log/trigger-topics door naar de NodeStatusTracker (en, als
    `ws_hub`/`loop` zijn ingesteld, ook live naar verbonden browsers via
    WebSocket — zie Task 12); publiceert config/control-berichten wanneer
    de beheerpagina iets wijzigt."""

    def __init__(self, settings, tracker, ws_hub=None, loop=None):
        self._settings = settings
        self._tracker = tracker
        self._ws_hub = ws_hub
        self._loop = loop
        self._client = mqtt.Client(client_id="beheerpagina-backend")
        if settings.mqtt_user:
            self._client.username_pw_set(settings.mqtt_user, settings.mqtt_pass)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            return
        client.subscribe(_STATUS_WILDCARD)
        client.subscribe(_LOG_WILDCARD)
        client.subscribe(TOPIC_MIRROR_TRIGGERED)
        client.subscribe(_SCARE_TRIGGERED_WILDCARD)

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode()
            self._tracker.handle_message(msg.topic, payload)
            self._broadcast_to_websockets(msg.topic, payload)
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

    def publish_mirror_config(self, config):
        self._client.publish(TOPIC_CONFIG_MIRROR, json.dumps(config), retain=True)

    def publish_mirror_preview(self, config):
        self._client.publish(TOPIC_CONTROL_MIRROR_PREVIEW, json.dumps(config))

    def publish_mirror_test(self):
        self._client.publish(TOPIC_CONTROL_MIRROR_TEST, "{}")

    def publish_scare_config(self, zone, enabled_hashes):
        self._client.publish(
            config_scare_topic(zone),
            json.dumps({"enabled_hashes": enabled_hashes}),
            retain=True,
        )

    def publish_scare_test(self, zone):
        self._client.publish(control_scare_test_topic(zone), "{}")

    def publish_sleep(self, is_sleeping):
        payload = SLEEP_PAYLOAD_ON if is_sleeping else SLEEP_PAYLOAD_OFF
        self._client.publish(TOPIC_SYSTEM_SLEEP, payload, retain=True)
