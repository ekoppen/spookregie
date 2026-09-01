import os
import uuid

DEFAULT_PATH = os.path.expanduser("~/.spookregie/device-id")


def get_or_create_device_uuid(path=None):
    """Geeft de lokaal opgeslagen device-uuid terug -- genereert er één en
    schrijft 'm weg als het bestand nog niet bestaat. Gedeeld tussen
    mirror_node/main.py en mirror_node/agent.py zodat beide processen op
    hetzelfde apparaat exact dezelfde identiteit gebruiken."""
    path = path or DEFAULT_PATH
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    device_uuid = str(uuid.uuid4())
    with open(path, "w") as f:
        f.write(device_uuid)
    return device_uuid
