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
