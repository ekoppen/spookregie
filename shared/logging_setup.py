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
