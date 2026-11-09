"""Rocket.Chat gateway adapter for Hermes Agent (Atomic Group).

Transporte:
  * Entrada: WebSocket DDP do Rocket.Chat (``/websocket``), assinatura ``stream-room-messages``
    com ``__my_messages__`` — recebe as mensagens de todas as salas em que o bot está.
  * Saída: REST API v1 (``/api/v1``) autenticada com Personal Access Token (``X-User-Id`` +
    ``X-Auth-Token``).

Variáveis de ambiente:
    ROCKETCHAT_URL                  URL do servidor (ex.: https://chat.atomicgroup.com.br)
    ROCKETCHAT_USER_ID              ID do usuário-bot (aparece junto do Personal Access Token)
    ROCKETCHAT_TOKEN                Personal Access Token do usuário-bot
    ROCKETCHAT_ALLOWED_USERS        IDs de usuário autorizados (separados por vírgula)
    ROCKETCHAT_ALLOW_ALL_USERS      true = qualquer usuário do servidor pode falar com o bot
    ROCKETCHAT_HOME_CHANNEL         ID da sala que recebe os alertas/cron
    ROCKETCHAT_REPLY_MODE           thread | off (padrão: thread)
    ROCKETCHAT_REQUIRE_MENTION      exigir @bot em canais (padrão: true)
    ROCKETCHAT_FREE_RESPONSE_CHANNELS  IDs de salas onde não precisa de @menção
    ROCKETCHAT_ALLOWED_CHANNELS     se definido, o bot só responde nestas salas
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import mimetypes
import random
import re
from pathlib import Path
from typing import Any, Optional

from gateway.config import Platform, PlatformConfig
from gateway.platforms._shared import (
    apply_yaml_bridge as _apply_yaml_bridge,
    env_is_connected as _env_is_connected,
    extra_or_secret as _extra_or_secret,
    get_scoped_secret as _get_scoped_secret,
    seed_extra_from_env as _seed_extra_from_env,
    send_error,
)
from gateway.platforms.base import BasePlatformAdapter, SendResult, gateway_trust_env
from gateway.platforms.event import MessageEvent, MessageType
from gateway.platforms.helpers import MessageDeduplicator, cancel_task

logger = logging.getLogger(__name__)

PLATFORM_NAME = "rocketchat"
# Message_MaxAllowedSize padrão do Rocket.Chat é 5000; 4000 deixa folga para formatação.
MAX_MESSAGE_LENGTH = 4000

# t do room: d = DM, c = canal público, p = grupo privado, l = livechat/omnichannel
_ROOM_TYPE_MAP = {"d": "dm", "c": "channel", "p": "group", "l": "dm"}

_RECONNECT_BASE_DELAY, _RECONNECT_MAX_DELAY, _RECONNECT_JITTER = 2.0, 60.0, 0.2
_MEDIA_MSG_TYPES = (("image/", MessageType.PHOTO), ("audio/", MessageType.VOICE))
_TRUTHY = {"1", "true", "yes", "on", "sim"}


# --------------------------------------------------------------------------- helpers puros


def _csv_set(raw: Any) -> set[str]:
    items = raw if isinstance(raw, (list, tuple, set)) else str(raw or "").split(",")
    return {str(i).strip() for i in items if str(i).strip()}


def _credentials(config: Any) -> tuple[str, str, str]:
    """(url, user_id, token): ``config.extra``/``config.token`` primeiro, env como fallback."""
    extra = getattr(config, "extra", None) or {}
    url = extra.get("url") or _get_scoped_secret("ROCKETCHAT_URL", "") or ""
    user_id = extra.get("user_id") or _get_scoped_secret("ROCKETCHAT_USER_ID", "") or ""
    token = getattr(config, "token", None) or extra.get("token") or _get_scoped_secret("ROCKETCHAT_TOKEN", "") or ""
    return url.strip().rstrip("/"), user_id.strip(), token.strip()


def _ws_url(base_url: str) -> str:
    return re.sub(r"^http", "ws", base_url) + "/websocket"


def is_system_message(msg: dict[str, Any]) -> bool:
    """Mensagens com ``t`` (entrou na sala, mudou tópico, etc.) não são conversa."""
    return bool(msg.get("t"))


def is_edit(msg: dict[str, Any]) -> bool:
    """Edições e reações reenviam a mensagem inteira pelo stream; tratamos só a original."""
    return bool(msg.get("editedAt")) or ("reactions" in msg and not msg.get("msg") and not msg.get("file"))


def mentions_bot(msg: dict[str, Any], bot_id: str, bot_username: str) -> bool:
    for m in msg.get("mentions") or []:
        if m.get("_id") == bot_id or (bot_username and m.get("username") == bot_username):
            return True
    text = (msg.get("msg") or "").lower()
    return bool(bot_username) and f"@{bot_username.lower()}" in text


def strip_mention(text: str, bot_username: str) -> str:
    if not bot_username:
        return text.strip()
    return re.sub(rf"@{re.escape(bot_username)}\b[:,]?", "", text, flags=re.IGNORECASE).strip()


def classify(text: str, media_types: list[str]) -> MessageType:
    if text.startswith("/"):
        return MessageType.COMMAND
    if media_types:
        for prefix, mt in _MEDIA_MSG_TYPES:
            if any(m.startswith(prefix) for m in media_types):
                return mt
        return MessageType.DOCUMENT
    return MessageType.TEXT


def file_refs(msg: dict[str, Any]) -> list[tuple[str, str, str]]:
    """[(path, nome, mime)] dos anexos de uma mensagem (``files`` em 6.x+, ``file`` legado)."""
    refs: list[tuple[str, str, str]] = []
    files = msg.get("files") or ([msg["file"]] if msg.get("file") else [])
    for f in files:
        fid, name = f.get("_id"), f.get("name") or "arquivo"
        if fid:
            refs.append((f"/file-upload/{fid}/{name}", name, f.get("type") or "application/octet-stream"))
    return refs


def check_requirements() -> bool:
    try:
        import aiohttp  # noqa: F401
        return True
    except ImportError:
        logger.warning("Rocket.Chat: aiohttp não instalado")
        return False


def validate_config(config: PlatformConfig) -> bool:
    url, user_id, token = _credentials(config)
    missing = [n for n, v in (("ROCKETCHAT_URL", url), ("ROCKETCHAT_USER_ID", user_id), ("ROCKETCHAT_TOKEN", token)) if not v]
    if missing:
        logger.warning("Rocket.Chat: faltando %s", ", ".join(missing))
        return False
    return True


# --------------------------------------------------------------------------- adapter


class RocketChatAdapter(BasePlatformAdapter):
    """Adapter do gateway Hermes para Rocket.Chat (self-hosted)."""

    splits_long_messages = True
    serial_receive_loop = True

    def __init__(self, config: PlatformConfig):
        super().__init__(config=config, platform=Platform(PLATFORM_NAME))
        self._base_url, self._user_id, self._token = _credentials(config)
        self._bot_username = ""
        self._session: Any = None
        self._ws: Any = None
        self._ws_task: Optional[asyncio.Task] = None
        self._closing = False
        self._ddp_ids = itertools.count(1)
        self._dedup = MessageDeduplicator()
        self._reply_mode = str(_extra_or_secret(config.extra, "reply_mode", "ROCKETCHAT_REPLY_MODE", "thread")).lower()

    # ---- HTTP

    def _auth(self) -> dict[str, str]:
        return {"X-User-Id": self._user_id, "X-Auth-Token": self._token}

    async def _api(self, method: str, path: str, *, json_body: Any = None, params: Any = None,
                   data: Any = None) -> dict[str, Any]:
        import aiohttp
        if ".." in path:
            logger.error("Rocket.Chat: path traversal bloqueado: %s", path)
            return {}
        url = f"{self._base_url}/api/v1/{path.lstrip('/')}"
        try:
            async with self._session.request(method, url, headers=self._auth(), json=json_body, params=params,
                                             data=data, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.error("Rocket.Chat API %s %s → %s: %s", method, path, resp.status, body[:300])
                    return {}
                return await resp.json()
        except aiohttp.ClientError as exc:
            logger.error("Rocket.Chat API %s %s erro de rede: %s", method, path, exc)
            return {}

    # ---- ciclo de vida

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        import aiohttp
        if not (self._base_url and self._user_id and self._token):
            logger.error("Rocket.Chat: URL, USER_ID ou TOKEN não configurados")
            return False
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60), trust_env=gateway_trust_env())
        self._closing = False
        me = await self._api("GET", "me")
        if not me.get("_id"):
            logger.error("Rocket.Chat: falha de autenticação — confira ROCKETCHAT_USER_ID/ROCKETCHAT_TOKEN")
            await self._session.close()
            return False
        self._user_id, self._bot_username = me["_id"], me.get("username", "")
        logger.info("Rocket.Chat: autenticado como @%s em %s", self._bot_username, self._base_url)
        self._ws_task = asyncio.create_task(self._ws_loop())
        self._mark_connected()
        self._wire_plugin_handlers(None)
        return True

    async def disconnect(self) -> None:
        self._closing = True
        await cancel_task(self._ws_task)
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("Rocket.Chat: desconectado")

    # ---- envio

    def _thread_id(self, reply_to: Optional[str], metadata: Optional[dict]) -> Optional[str]:
        if self._reply_mode != "thread":
            return None
        if isinstance(metadata, dict) and (metadata.get("thread_id") or metadata.get("tmid")):
            return str(metadata.get("thread_id") or metadata.get("tmid"))
        return reply_to or None

    async def send(self, chat_id: str, content: str, reply_to: Optional[str] = None,
                   metadata: Optional[dict] = None) -> SendResult:
        if not content:
            return SendResult(success=True)
        tmid = self._thread_id(reply_to, metadata)
        result = SendResult(success=True)
        for chunk in self.truncate_message(self.format_message(content), MAX_MESSAGE_LENGTH):
            message: dict[str, Any] = {"rid": chat_id, "msg": chunk}
            if tmid:
                message["tmid"] = tmid
            data = await self._api("POST", "chat.sendMessage", json_body={"message": message})
            msg_id = (data.get("message") or {}).get("_id")
            result = SendResult(success=bool(msg_id), message_id=msg_id,
                                error=None if msg_id else "Falha ao enviar mensagem")
            if not result.success:
                break
        return result

    async def edit_message(self, chat_id: str, message_id: str, content: str, *, finalize: bool = False) -> SendResult:
        data = await self._api("POST", "chat.update",
                               json_body={"roomId": chat_id, "msgId": message_id, "text": self.format_message(content)})
        ok = bool(data.get("success"))
        return SendResult(success=ok, message_id=message_id if ok else None, error=None if ok else "Falha ao editar")

    async def send_typing(self, chat_id: str, metadata: Optional[dict] = None) -> None:
        await self._ddp_send({"msg": "method", "method": "stream-notify-room", "id": str(next(self._ddp_ids)),
                              "params": [f"{chat_id}/user-activity", self._bot_username, ["user-typing"], {}]})

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        room = (await self._api("GET", "rooms.info", params={"roomId": chat_id})).get("room") or {}
        return {"name": room.get("fname") or room.get("name") or chat_id,
                "type": _ROOM_TYPE_MAP.get(room.get("t", "c"), "channel"), "chat_id": chat_id}

    def format_message(self, content: str) -> str:
        # Rocket.Chat renderiza markdown; imagens ![alt](url) viram link (o preview é automático).
        return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\2", content)

    # ---- arquivos

    async def _upload(self, chat_id: str, data: bytes, filename: str, caption: Optional[str],
                      reply_to: Optional[str], metadata: Optional[dict]) -> SendResult:
        import aiohttp
        form = aiohttp.FormData()
        form.add_field("file", data, filename=filename,
                       content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream")
        up = await self._api("POST", f"rooms.media/{chat_id}", data=form)
        file_id = (up.get("file") or {}).get("_id")
        if not file_id:
            return SendResult(success=False, error="Falha no upload do arquivo")
        body: dict[str, Any] = {"msg": caption or ""}
        if tmid := self._thread_id(reply_to, metadata):
            body["tmid"] = tmid
        conf = await self._api("POST", f"rooms.mediaConfirm/{chat_id}/{file_id}", json_body=body)
        msg_id = (conf.get("message") or {}).get("_id")
        return SendResult(success=bool(msg_id), message_id=msg_id, error=None if msg_id else "Falha ao confirmar upload")

    async def _send_local_file(self, chat_id: str, path: str, caption: Optional[str] = None,
                               reply_to: Optional[str] = None, file_name: Optional[str] = None,
                               metadata: Optional[dict] = None) -> SendResult:
        p = Path(path)
        if not p.exists():
            logger.warning("Rocket.Chat: arquivo local não encontrado: %s", path)
            return SendResult(success=True)
        data = await asyncio.to_thread(p.read_bytes)
        return await self._upload(chat_id, data, file_name or p.name, caption, reply_to, metadata)

    async def send_image(self, chat_id: str, image_url: str, caption: Optional[str] = None,
                         reply_to: Optional[str] = None, metadata: Optional[dict] = None) -> SendResult:
        # O Rocket.Chat gera preview de URLs de imagem; evita baixar/reenviar e o risco de SSRF.
        return await self.send(chat_id, f"{caption or ''}\n{image_url}".strip(), reply_to, metadata)

    async def send_image_file(self, chat_id: str, image_path: str, caption: Optional[str] = None,
                              reply_to: Optional[str] = None, metadata: Optional[dict] = None) -> SendResult:
        return await self._send_local_file(chat_id, image_path, caption, reply_to, metadata=metadata)

    async def send_document(self, chat_id: str, file_path: str, caption: Optional[str] = None,
                            file_name: Optional[str] = None, reply_to: Optional[str] = None,
                            metadata: Optional[dict] = None) -> SendResult:
        return await self._send_local_file(chat_id, file_path, caption, reply_to, file_name, metadata)

    async def send_voice(self, chat_id: str, audio_path: str, caption: Optional[str] = None,
                         reply_to: Optional[str] = None, metadata: Optional[dict] = None, **_: Any) -> SendResult:
        return await self._send_local_file(chat_id, audio_path, caption, reply_to, metadata=metadata)

    async def send_video(self, chat_id: str, video_path: str, caption: Optional[str] = None,
                         reply_to: Optional[str] = None, metadata: Optional[dict] = None) -> SendResult:
        return await self._send_local_file(chat_id, video_path, caption, reply_to, metadata=metadata)

    async def _download_attachments(self, msg: dict[str, Any]) -> tuple[list[str], list[str]]:
        import aiohttp
        from gateway.platforms.base import (
            cache_audio_from_bytes_async, cache_document_from_bytes_async, cache_image_from_bytes_async)
        urls, types = [], []
        for path, name, mime in file_refs(msg):
            try:
                async with self._session.get(f"{self._base_url}{path}", headers=self._auth(),
                                             timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status >= 400:
                        logger.warning("Rocket.Chat: falha ao baixar anexo %s (HTTP %s)", name, resp.status)
                        continue
                    data = await resp.read()
                suffix = Path(name).suffix
                if mime.startswith("image/"):
                    urls.append(await cache_image_from_bytes_async(data, suffix or ".png"))
                elif mime.startswith("audio/"):
                    urls.append(await cache_audio_from_bytes_async(data, suffix or ".ogg"))
                else:
                    urls.append(await cache_document_from_bytes_async(data, name))
                types.append(mime)
            except Exception as exc:  # noqa: BLE001 — anexo com problema não derruba a mensagem
                logger.warning("Rocket.Chat: erro ao baixar anexo %s: %s", name, exc)
        return urls, types

    # ---- DDP / WebSocket

    async def _ddp_send(self, payload: dict[str, Any]) -> None:
        if self._ws is not None and not self._ws.closed:
            try:
                await self._ws.send_str(json.dumps(payload))
            except Exception as exc:  # noqa: BLE001
                logger.debug("Rocket.Chat: falha ao enviar frame DDP: %s", exc)

    async def _ws_loop(self) -> None:
        import aiohttp
        delay = _RECONNECT_BASE_DELAY
        while not self._closing:
            try:
                await self._ws_session()
                delay = _RECONNECT_BASE_DELAY
            except asyncio.CancelledError:
                return
            except PermissionError as exc:
                self._set_fatal_error("rocketchat_auth_error", str(exc), retryable=False)
                await self._notify_fatal_error()
                return
            except (aiohttp.ClientError, OSError, ValueError) as exc:
                logger.warning("Rocket.Chat WS erro: %s — reconectando em %.0fs", exc, delay)
            if self._closing:
                return
            await asyncio.sleep(delay + delay * _RECONNECT_JITTER * random.random())
            delay = min(delay * 2, _RECONNECT_MAX_DELAY)

    async def _ws_session(self) -> None:
        self._ws = await self._session.ws_connect(_ws_url(self._base_url), heartbeat=None)
        await self._ddp_send({"msg": "connect", "version": "1", "support": ["1"]})
        login_id, sub_id = str(next(self._ddp_ids)), str(next(self._ddp_ids))
        async for raw in self._ws:
            if self._closing:
                return
            if raw.type.name not in {"TEXT", "BINARY"}:
                logger.info("Rocket.Chat: WebSocket fechado (%s)", raw.type.name)
                return
            try:
                frame = json.loads(raw.data)
            except (TypeError, ValueError):
                continue
            kind = frame.get("msg")
            if kind == "ping":
                await self._ddp_send({"msg": "pong"})
            elif kind == "connected":
                await self._ddp_send({"msg": "method", "method": "login", "id": login_id,
                                      "params": [{"resume": self._token}]})
            elif kind == "result" and frame.get("id") == login_id:
                if frame.get("error"):
                    raise PermissionError(f"Rocket.Chat recusou o token no WebSocket: {frame['error']}")
                await self._ddp_send({"msg": "sub", "id": sub_id, "name": "stream-room-messages",
                                      "params": ["__my_messages__", {"useCollection": False, "args": []}]})
                logger.info("Rocket.Chat: WebSocket autenticado e inscrito em __my_messages__")
            elif kind == "changed" and frame.get("collection") == "stream-room-messages":
                args = (frame.get("fields") or {}).get("args") or []
                if args and isinstance(args[0], dict):
                    meta = args[1] if len(args) > 1 and isinstance(args[1], dict) else {}
                    await self._handle_message(args[0], meta)

    # ---- entrada

    def _gate_channel(self, rid: str, msg: dict[str, Any], text: str) -> Optional[str]:
        allowed = _csv_set(_extra_or_secret(self.config.extra, "allowed_channels", "ROCKETCHAT_ALLOWED_CHANNELS",
                                            blank_is_unset=False))
        if allowed and rid not in allowed:
            return None
        require = str(_extra_or_secret(self.config.extra, "require_mention", "ROCKETCHAT_REQUIRE_MENTION", "true",
                                       blank_is_unset=False)).lower() in _TRUTHY
        free = _csv_set(_extra_or_secret(self.config.extra, "free_response_channels",
                                         "ROCKETCHAT_FREE_RESPONSE_CHANNELS", blank_is_unset=False))
        mentioned = mentions_bot(msg, self._user_id, self._bot_username)
        if require and rid not in free and not mentioned:
            return None
        return strip_mention(text, self._bot_username) if mentioned else text

    async def _handle_message(self, msg: dict[str, Any], meta: dict[str, Any]) -> None:
        sender = msg.get("u") or {}
        msg_id, rid = msg.get("_id", ""), msg.get("rid", "")
        if (not msg_id or not rid or sender.get("_id") == self._user_id or is_system_message(msg)
                or is_edit(msg) or self._dedup.is_duplicate(msg_id)):
            return
        room_type = meta.get("roomType") or ("d" if rid and self._user_id in rid else "c")
        text = (msg.get("msg") or "").strip()
        if room_type not in {"d", "l"}:
            gated = self._gate_channel(rid, msg, text)
            if gated is None:
                return
            text = gated
        thread_id = msg.get("tmid") or (msg_id if self._reply_mode == "thread" and room_type not in {"d", "l"} else None)
        media_urls, media_types = await self._download_attachments(msg)
        source = self.build_source(
            chat_id=rid, chat_name=meta.get("roomName"), chat_type=_ROOM_TYPE_MAP.get(room_type, "channel"),
            user_id=sender.get("_id"), user_name=sender.get("username") or sender.get("name"),
            thread_id=thread_id, message_id=msg_id, is_bot=bool(msg.get("bot")))
        from gateway.platforms.base import resolve_channel_prompt
        await self.handle_message(MessageEvent(
            text=text, message_type=classify(text, media_types), source=source, raw_message=msg,
            message_id=msg_id, media_urls=media_urls, media_types=media_types,
            channel_prompt=resolve_channel_prompt(self.config.extra, rid, None)))


# --------------------------------------------------------------------------- envio fora do gateway (cron)


async def _standalone_send(pconfig, chat_id: str, message: str, *, thread_id: Optional[str] = None,
                           media_files: Optional[list] = None, force_document: bool = False,
                           **_: Any) -> dict[str, Any]:
    """Envio via REST sem adapter vivo — usado por jobs de cron (alertas da Nekt)."""
    try:
        import aiohttp
    except ImportError:
        return send_error("aiohttp não instalado")
    url, user_id, token = _credentials(pconfig)
    if not (url and user_id and token):
        return send_error("Rocket.Chat: defina ROCKETCHAT_URL, ROCKETCHAT_USER_ID e ROCKETCHAT_TOKEN")
    headers = {"X-User-Id": user_id, "X-Auth-Token": token}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
            last_id = None
            for media in media_files or []:
                path = media.get("path") if isinstance(media, dict) else media
                if not path or not Path(path).exists():
                    continue
                form = aiohttp.FormData()
                form.add_field("file", await asyncio.to_thread(Path(path).read_bytes), filename=Path(path).name)
                async with s.post(f"{url}/api/v1/rooms.media/{chat_id}", headers=headers, data=form) as r:
                    if r.status >= 400:
                        return send_error(f"Rocket.Chat upload falhou ({r.status}): {(await r.text())[:300]}")
                    fid = ((await r.json()).get("file") or {}).get("_id")
                body = {"msg": "", **({"tmid": thread_id} if thread_id else {})}
                async with s.post(f"{url}/api/v1/rooms.mediaConfirm/{chat_id}/{fid}", headers=headers, json=body) as r:
                    last_id = ((await r.json()).get("message") or {}).get("_id")
            if message:
                payload: dict[str, Any] = {"rid": chat_id, "msg": message}
                if thread_id:
                    payload["tmid"] = thread_id
                async with s.post(f"{url}/api/v1/chat.sendMessage", headers=headers,
                                  json={"message": payload}) as r:
                    if r.status >= 400:
                        return send_error(f"Rocket.Chat API erro ({r.status}): {(await r.text())[:300]}")
                    last_id = ((await r.json()).get("message") or {}).get("_id")
            return {"success": True, "platform": PLATFORM_NAME, "chat_id": chat_id, "message_id": last_id}
    except aiohttp.ClientError as exc:
        return send_error(f"Rocket.Chat envio falhou (rede): {exc}")


# --------------------------------------------------------------------------- registro do plugin


def _env_enablement() -> dict | None:
    url = (_get_scoped_secret("ROCKETCHAT_URL", "") or "").strip()
    token = (_get_scoped_secret("ROCKETCHAT_TOKEN", "") or "").strip()
    if not (url and token):
        return None
    seed = _seed_extra_from_env((
        ("ROCKETCHAT_USER_ID", "user_id", None),
        ("ROCKETCHAT_REPLY_MODE", "reply_mode", None),
    ), home_env="ROCKETCHAT_HOME_CHANNEL")
    return {"url": url.rstrip("/"), **seed}


_YAML_BRIDGE = (
    ("require_mention", "ROCKETCHAT_REQUIRE_MENTION", "lower"),
    ("free_response_channels", "ROCKETCHAT_FREE_RESPONSE_CHANNELS", "csv"),
    ("allowed_channels", "ROCKETCHAT_ALLOWED_CHANNELS", "csv"),
)


def _apply_yaml_config(yaml_cfg: dict, platform_cfg: dict) -> dict | None:
    return _apply_yaml_bridge(platform_cfg, _YAML_BRIDGE)


_PLATFORM_HINT = (
    "Você está no Atomic Chat (Rocket.Chat interno da Atomic Group). Responda em português do Brasil. "
    "O Rocket.Chat renderiza Markdown (negrito, itálico, listas, blocos de código e tabelas simples). "
    "Para enviar arquivos inclua MEDIA:/caminho/absoluto/do/arquivo na resposta. "
    "Em canais, seja objetivo; respostas longas vão em thread."
)


def register(ctx) -> None:
    ctx.register_platform(
        name=PLATFORM_NAME,
        label="Rocket.Chat",
        adapter_factory=RocketChatAdapter,
        dashboard_description="Conecta o Hermes às salas e DMs do Rocket.Chat (Atomic Chat).",
        docs_url="https://developer.rocket.chat/apidocs",
        dashboard_env_vars=("ROCKETCHAT_URL", "ROCKETCHAT_USER_ID", "ROCKETCHAT_TOKEN", "ROCKETCHAT_ALLOWED_USERS"),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=_env_is_connected("ROCKETCHAT_URL", "ROCKETCHAT_USER_ID", "ROCKETCHAT_TOKEN"),
        required_env=["ROCKETCHAT_URL", "ROCKETCHAT_USER_ID", "ROCKETCHAT_TOKEN"],
        install_hint="pip install aiohttp",
        env_enablement_fn=_env_enablement,
        apply_yaml_config_fn=_apply_yaml_config,
        cron_deliver_env_var="ROCKETCHAT_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        allowed_users_env="ROCKETCHAT_ALLOWED_USERS",
        allow_all_env="ROCKETCHAT_ALLOW_ALL_USERS",
        max_message_length=MAX_MESSAGE_LENGTH,
        emoji="🚀",
        allow_update_command=True,
        platform_hint=_PLATFORM_HINT,
    )
