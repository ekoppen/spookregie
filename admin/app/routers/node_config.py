from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/node-config")
def get_node_config(request: Request):
    """Publiek endpoint (geen sessie nodig) waar mirror-node/scare-node bij
    het opstarten de actuele topic-prefix ophalen -- zie shared/topic_prefix.py.
    Geeft bewust alleen de prefix terug, nooit MQTT-host/poort/credentials."""
    return {"mqtt_topic_prefix": request.app.state.runtime_settings.mqtt_topic_prefix}
