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

    def __init__(self, settings, tracker, ws_hub=None, loop=None, logger=None, on_connect_extra=None):
        self._settings = settings
        self._tracker = tracker
        self._ws_hub = ws_hub
        self._loop = loop
        self._logger = logger
        # Aangeroepen (zonder argumenten) nadat _on_connect klaar is met
        # subscriben -- laat create_app() retained config (scenes,
        # scare-video) opnieuw publiceren bij elke (her)verbinding, zonder
        # dat MqttBridge zelf iets van de DB hoeft te weten. Zie
        # `_republish_retained_config` in main.py.
        self._on_connect_extra = on_connect_extra
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
        if self._on_connect_extra is not None:
            # Republiceert retained config (scenes, scare-video) bij elke
            # (her)verbinding -- zonder dit blijft een net herstarte
            # mirror-node zwart tot iemand handmatig een scene opslaat.
            try:
                self._on_connect_extra()
            except Exception:
                self._log("error", "republiceren van config na MQTT-connect mislukt")

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

    def publish_mirror_graph(self, graph):
        self._client.publish(self._topics.config_mirror_graph, json.dumps(graph), retain=True)

    def publish_mirror_scene_preview(self, scene):
        self._client.publish(self._topics.control_mirror_scene_preview, json.dumps(scene))

    def publish_mirror_test(self):
        self._client.publish(self._topics.control_mirror_test, "{}")

    def publish_mirror_scare_video_config(self, enabled_hashes):
        self._client.publish(
            self._topics.config_mirror_scare_video,
            json.dumps({"enabled_hashes": enabled_hashes}),
            retain=True,
        )

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
