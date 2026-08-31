import json

from fastapi.testclient import TestClient

import admin.app.mqtt_bridge as mqtt_bridge_module
from admin.app.config import Settings
from admin.app.main import create_app
from admin.app.mqtt_bridge import MqttBridge
from admin.app.runtime_settings import RuntimeSettings


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


def _settings(**overrides):
    base = dict(
        mqtt_host="broker-a", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="", mirror_stream_url="",
    )
    base.update(overrides)
    return RuntimeSettings(**base)


def test_start_connects_with_configured_host_and_port(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_host="broker-a", mqtt_port=1883), tracker=object())
    bridge.start()

    assert bridge._client.connected_to == ("broker-a", 1883)


def test_reconfigure_disconnects_old_client_and_connects_new_one(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(), tracker=object())
    bridge.start()
    old_client = bridge._client

    bridge.reconfigure(_settings(mqtt_host="broker-b", mqtt_port=1884, mqtt_user="op", mqtt_pass="geheim"))

    assert old_client.loop_stopped is True
    assert old_client.disconnected is True
    new_client = bridge._client
    assert new_client is not old_client
    assert new_client.connected_to == ("broker-b", 1884)
    assert new_client.username == "op"
    assert new_client.password == "geheim"


def test_start_subscribes_with_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())
    bridge.start()
    bridge._on_connect(bridge._client, None, None, 0)

    assert bridge._client.subscribed == [
        "test/status/+", "test/log/+", "test/mirror/triggered", "test/scare/+/triggered"
    ]


def test_publish_mirror_graph_uses_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())

    bridge.publish_mirror_graph({"scenes": [{"id": 1}], "edges": [], "root_scene_id": 1})

    topic, payload, retain = bridge._client.published[-1]
    assert topic == "test/config/mirror/graph"
    assert json.loads(payload) == {"scenes": [{"id": 1}], "edges": [], "root_scene_id": 1}
    assert retain is True


def test_publish_mirror_scene_preview_is_not_retained(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())

    bridge.publish_mirror_scene_preview({"id": 1, "effect": "xray"})

    topic, payload, retain = bridge._client.published[-1]
    assert topic == "test/control/mirror/scene-preview"
    assert json.loads(payload) == {"id": 1, "effect": "xray"}
    assert retain is False


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


def test_on_connect_calls_on_connect_extra_hook(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)
    calls = []

    bridge = MqttBridge(
        _settings(mqtt_topic_prefix="test"), tracker=object(),
        on_connect_extra=lambda: calls.append("republished"),
    )
    bridge._on_connect(bridge._client, None, None, 0)

    assert calls == ["republished"]


def test_on_connect_extra_failure_does_not_crash_on_connect(monkeypatch):
    """Zonder deze bescherming zou een DB-foutje tijdens republiceren de
    hele MQTT-netwerkthread (en dus status/log-verwerking) laten crashen."""
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    def _boom():
        raise RuntimeError("db weg")

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object(), on_connect_extra=_boom)

    bridge._on_connect(bridge._client, None, None, 0)  # mag niet raisen

    assert bridge._client.subscribed  # subscribes zijn nog steeds gebeurd


def test_reconnect_republishes_retained_scenes_and_scare_video_config(tmp_path, monkeypatch):
    """Simuleert een broker-(her)verbinding via _on_connect en verifieert dat
    de retained config/mirror/scenes en config/mirror/scare-video topics
    opnieuw gepubliceerd worden vanuit de echte DB-inhoud -- dit is de fix
    voor een mirror-node die na een herstart zwart blijft omdat er nooit een
    retained bericht op die topics heeft gestaan."""
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})

    scene_payload = {
        "name": "Basis", "enabled": True, "source_mode": "camera", "effect": "xray",
        "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
        "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
        "trigger_type": "always", "trigger_from": None, "trigger_until": None,
    }
    created = client.post("/api/scenes", json=scene_payload).json()
    client.put("/api/mirror/scare-video-config", json={"enabled_hashes": ["a" * 64]})

    # Wis wat de CRUD-routes hierboven al publiceerden -- we willen alleen
    # zien wat een verse (her)verbinding publiceert, zonder enige handmatige
    # actie op de beheerpagina.
    app.state.bridge._client.published.clear()

    app.state.bridge._on_connect(app.state.bridge._client, None, None, 0)

    published = {
        topic: (json.loads(payload), retain)
        for topic, payload, retain in app.state.bridge._client.published
    }
    assert published["config/mirror/scenes"] == ([created], True)
    assert published["config/mirror/scare-video"] == ({"enabled_hashes": ["a" * 64]}, True)


def test_publish_mirror_scare_video_config_uses_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())

    bridge.publish_mirror_scare_video_config(["a" * 64])

    topic, payload, retain = bridge._client.published[-1]
    assert topic == "test/config/mirror/scare-video"
    assert json.loads(payload) == {"enabled_hashes": ["a" * 64]}
    assert retain is True
