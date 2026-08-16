import json
import re
import threading

_STATUS_RE = re.compile(r"^status/(.+)$")
_LOG_RE = re.compile(r"^log/(.+)$")


class NodeStatusTracker:
    """Houdt bij welke nodes online/offline zijn en hun recente logregels,
    puur op basis van binnenkomende MQTT-berichten. Geen eigen MQTT-verbinding
    — de MqttBridge (glue-laag) roept `handle_message` aan voor elk bericht."""

    def __init__(self, max_logs_per_node=200):
        self._nodes = {}
        self._logs = []
        self._max_logs_per_node = max_logs_per_node
        self._lock = threading.Lock()

    def handle_message(self, topic, payload):
        status_match = _STATUS_RE.match(topic)
        if status_match:
            node = status_match.group(1)
            with self._lock:
                self._nodes.setdefault(node, {})["status"] = payload
            return

        log_match = _LOG_RE.match(topic)
        if log_match:
            node = log_match.group(1)
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return
            if not isinstance(data, dict):
                return
            entry = {
                "node": node,
                "ts": data.get("ts"),
                "level": data.get("level"),
                "msg": data.get("msg"),
            }
            with self._lock:
                self._logs.append(entry)
                if len(self._logs) > self._max_logs_per_node * 20:
                    self._logs = self._logs[-(self._max_logs_per_node * 10):]
            return

    def get_nodes(self):
        with self._lock:
            return {k: dict(v) for k, v in self._nodes.items()}

    def get_recent_logs(self, node=None, limit=100):
        with self._lock:
            logs = self._logs if node is None else [l for l in self._logs if l["node"] == node]
            return logs[-limit:]
