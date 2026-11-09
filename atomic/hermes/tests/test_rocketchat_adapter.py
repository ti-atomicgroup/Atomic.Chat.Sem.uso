"""Testes do adapter Rocket.Chat contra um servidor Rocket.Chat simulado (REST + DDP).

Rodar a partir de um checkout do hermes-agent:
    PYTHONPATH=<repo>/atomic/hermes/plugins pytest <repo>/atomic/hermes/tests -q
"""

import asyncio
import json

import pytest
from aiohttp import WSMsgType, web

from gateway.config import PlatformConfig
from gateway.platforms.event import MessageType
from rocketchat import adapter as rc

BOT_ID, BOT_USER, TOKEN = "bot123", "hermes", "tok-abc"


class FakeRocketChat:
    def __init__(self):
        self.sent: list[dict] = []
        self.ws_logins: list[dict] = []
        self.subscribed = asyncio.Event()
        self.ws: web.WebSocketResponse | None = None

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/api/v1/me", self.me)
        app.router.add_post("/api/v1/chat.sendMessage", self.send_message)
        app.router.add_get("/websocket", self.websocket)
        return app

    def _authed(self, req) -> bool:
        return req.headers.get("X-User-Id") == BOT_ID and req.headers.get("X-Auth-Token") == TOKEN

    async def me(self, req):
        if not self._authed(req):
            return web.json_response({"success": False}, status=401)
        return web.json_response({"_id": BOT_ID, "username": BOT_USER, "success": True})

    async def send_message(self, req):
        assert self._authed(req)
        body = await req.json()
        self.sent.append(body["message"])
        return web.json_response({"success": True, "message": {"_id": f"m{len(self.sent)}", **body["message"]}})

    async def websocket(self, req):
        ws = web.WebSocketResponse()
        await ws.prepare(req)
        self.ws = ws
        async for raw in ws:
            if raw.type != WSMsgType.TEXT:
                break
            frame = json.loads(raw.data)
            if frame.get("msg") == "connect":
                await ws.send_json({"msg": "connected", "session": "s1"})
            elif frame.get("method") == "login":
                self.ws_logins.append(frame["params"][0])
                await ws.send_json({"msg": "result", "id": frame["id"], "result": {"id": BOT_ID}})
            elif frame.get("msg") == "sub":
                assert frame["params"][0] == "__my_messages__"
                await ws.send_json({"msg": "ready", "subs": [frame["id"]]})
                self.subscribed.set()
        return ws

    async def push(self, message: dict, room_type: str = "c"):
        await self.ws.send_json({"msg": "changed", "collection": "stream-room-messages", "id": "id",
                                 "fields": {"eventName": message["rid"],
                                            "args": [message, {"roomType": room_type, "roomName": "geral"}]}})


@pytest.fixture
async def env(aiohttp_server, monkeypatch):
    fake = FakeRocketChat()
    server = await aiohttp_server(fake.app())
    url = str(server.make_url("")).rstrip("/")
    monkeypatch.setenv("ROCKETCHAT_URL", url)
    monkeypatch.setenv("ROCKETCHAT_USER_ID", BOT_ID)
    monkeypatch.setenv("ROCKETCHAT_TOKEN", TOKEN)
    adapter = rc.RocketChatAdapter(PlatformConfig(enabled=True, extra={}))
    received = []

    async def capture(event):
        received.append(event)

    adapter.handle_message = capture
    assert await adapter.connect()
    await asyncio.wait_for(fake.subscribed.wait(), 5)
    yield fake, adapter, received
    await adapter.disconnect()


async def _settle():
    await asyncio.sleep(0.2)


async def test_login_usa_token_no_ddp(env):
    fake, adapter, _ = env
    assert fake.ws_logins == [{"resume": TOKEN}]
    assert adapter._bot_username == BOT_USER


async def test_dm_chega_sem_mencao(env):
    fake, _, received = env
    await fake.push({"_id": "a1", "rid": f"user1{BOT_ID}", "msg": "quanto vendemos?", "u": {"_id": "user1", "username": "ana"}}, "d")
    await _settle()
    assert len(received) == 1
    ev = received[0]
    assert ev.text == "quanto vendemos?" and ev.source.chat_type == "dm" and ev.source.thread_id is None


async def test_canal_exige_mencao_e_remove_o_arroba(env):
    fake, _, received = env
    await fake.push({"_id": "b1", "rid": "GERAL", "msg": "bom dia a todos", "u": {"_id": "u2", "username": "joao"}})
    await fake.push({"_id": "b2", "rid": "GERAL", "msg": "@hermes faturamento de outubro",
                     "mentions": [{"_id": BOT_ID, "username": BOT_USER}], "u": {"_id": "u2", "username": "joao"}})
    await _settle()
    assert [e.text for e in received] == ["faturamento de outubro"]
    assert received[0].source.thread_id == "b2"  # modo thread: responde na thread da pergunta


async def test_ignora_proprio_bot_sistema_edicao_e_duplicata(env):
    fake, _, received = env
    base = {"rid": "DM", "u": {"_id": "u3", "username": "bia"}}
    await fake.push({"_id": "c1", **base, "msg": "eco", "u": {"_id": BOT_ID, "username": BOT_USER}}, "d")
    await fake.push({"_id": "c2", **base, "msg": "", "t": "uj"}, "d")
    await fake.push({"_id": "c3", **base, "msg": "editada", "editedAt": {"$date": 1}}, "d")
    await fake.push({"_id": "c4", **base, "msg": "/nekt status"}, "d")
    await fake.push({"_id": "c4", **base, "msg": "/nekt status"}, "d")
    await _settle()
    assert [e.text for e in received] == ["/nekt status"]
    assert received[0].message_type == MessageType.COMMAND


async def test_send_quebra_mensagem_longa_e_usa_thread(env):
    fake, adapter, _ = env
    result = await adapter.send("GERAL", "x" * 9000, reply_to="b2")
    assert result.success
    assert len(fake.sent) >= 3
    assert all(m["rid"] == "GERAL" and m["tmid"] == "b2" for m in fake.sent)


async def test_standalone_send_para_alertas(env, monkeypatch):
    fake, _, _ = env
    out = await rc._standalone_send(PlatformConfig(enabled=True, extra={}), "ALERTAS", "🚨 Meta diária atingida")
    assert out["success"] and fake.sent[-1] == {"rid": "ALERTAS", "msg": "🚨 Meta diária atingida"}


def test_helpers_puros():
    assert rc.strip_mention("@Hermes: oi", "hermes") == "oi"
    assert rc.file_refs({"files": [{"_id": "f1", "name": "a.pdf", "type": "application/pdf"}]}) == [
        ("/file-upload/f1/a.pdf", "a.pdf", "application/pdf")]
    assert rc._ws_url("https://chat.x.com") == "wss://chat.x.com/websocket"
