import asyncio
import pytest
from admin.app.websocket_hub import WebSocketHub


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def test_register_and_broadcast_sends_to_all():
    hub = WebSocketHub()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    hub.register(ws1)
    hub.register(ws2)

    asyncio.run(hub.broadcast({"type": "status", "node": "mirror"}))

    assert ws1.sent == [{"type": "status", "node": "mirror"}]
    assert ws2.sent == [{"type": "status", "node": "mirror"}]


def test_unregister_stops_delivery():
    hub = WebSocketHub()
    ws = FakeWebSocket()
    hub.register(ws)
    hub.unregister(ws)

    asyncio.run(hub.broadcast({"type": "status"}))

    assert ws.sent == []


def test_broadcast_to_failing_client_does_not_break_others():
    hub = WebSocketHub()

    class FailingWebSocket:
        async def send_json(self, data):
            raise ConnectionError("weg")

    ok_ws = FakeWebSocket()
    hub.register(FailingWebSocket())
    hub.register(ok_ws)

    asyncio.run(hub.broadcast({"type": "status"}))

    assert ok_ws.sent == [{"type": "status"}]
