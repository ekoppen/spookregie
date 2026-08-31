from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/node-config")
def get_node_config(request: Request):
    """Publiek endpoint (geen sessie nodig) waar mirror-node/scare-node bij
    het opstarten hun configuratie ophalen -- zie shared/topic_prefix.py.
    Geeft bewust alleen niet-gevoelige/expliciet-publiek-gemaakte velden
    terug: de topic-prefix en de camera-bron van de (voorlopig enige)
    output (beide besproken en geaccepteerd als niet-extra-beveiligd,
    vertrouwd LAN). Nooit MQTT-host/poort/credentials of het HA-token."""
    settings = request.app.state.runtime_settings
    db = request.app.state.db
    output = db.execute("SELECT camera_source FROM outputs ORDER BY id LIMIT 1").fetchone()
    return {
        "mqtt_topic_prefix": settings.mqtt_topic_prefix,
        "mirror_camera_source": output[0] if output else "",
    }
