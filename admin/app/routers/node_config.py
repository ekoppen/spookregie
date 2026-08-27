from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/node-config")
def get_node_config(request: Request):
    """Publiek endpoint (geen sessie nodig) waar mirror-node/scare-node bij
    het opstarten hun configuratie ophalen -- zie shared/topic_prefix.py.
    Geeft bewust alleen niet-gevoelige/expliciet-publiek-gemaakte velden
    terug: de topic-prefix en de mirror-camera-bron (beide besproken en
    geaccepteerd als niet-extra-beveiligd, vertrouwd LAN). Nooit MQTT-host/
    poort/credentials of het HA-token."""
    settings = request.app.state.runtime_settings
    return {
        "mqtt_topic_prefix": settings.mqtt_topic_prefix,
        "mirror_camera_source": settings.mirror_camera_source,
    }
