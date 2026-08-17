class WebSocketHub:
    """Houdt actieve browser-WebSockets bij en zendt berichten naar allemaal.
    Eén trage/kapotte client mag de andere niet raken."""

    def __init__(self):
        self._clients = set()

    def register(self, ws):
        self._clients.add(ws)

    def unregister(self, ws):
        self._clients.discard(ws)

    async def broadcast(self, message):
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:
                self._clients.discard(ws)
