from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/node-config")
def get_node_config(request: Request):
    """Publiek endpoint (geen sessie nodig) waar mirror-node/scare-node bij
    het opstarten hun configuratie ophalen -- zie shared/topic_prefix.py.
    Geeft bewust alleen niet-gevoelige/expliciet-publiek-gemaakte velden
    terug: de topic-prefix en een startup-camera-bron (de root player's
    source, of anders de eerste/enige source) -- beide besproken en
    geaccepteerd als niet-extra-beveiligd, vertrouwd LAN. Nooit
    MQTT-host/poort/credentials of het HA-token. Dit is alleen de
    STARTUP-bron, vóórdat de eerste graaf-config binnenkomt -- de
    daadwerkelijk actieve source per player wisselt daarna dynamisch,
    zie mirror_node/main.py's _ensure_source."""
    settings = request.app.state.runtime_settings
    db = request.app.state.db
    root_source = db.execute(
        "SELECT s.value FROM players p JOIN sources s ON s.id = p.source_id "
        "WHERE p.is_root = 1 AND s.kind = 'camera_stream' LIMIT 1"
    ).fetchone()
    if root_source is None:
        root_source = db.execute(
            "SELECT value FROM sources WHERE kind = 'camera_stream' ORDER BY id LIMIT 1"
        ).fetchone()
    return {
        "mqtt_topic_prefix": settings.mqtt_topic_prefix,
        "mirror_camera_source": root_source[0] if root_source else "",
    }
