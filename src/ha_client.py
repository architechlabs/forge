import asyncio
import json
import ssl
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import websockets


class HomeAssistantError(RuntimeError):
    pass


class HomeAssistantClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        verify_ssl: bool = True,
        current_instance: bool = False,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.verify_ssl = verify_ssl
        self.current_instance = current_instance
        self.timeout = timeout

    @classmethod
    def current(cls, supervisor_token: str) -> "HomeAssistantClient":
        return cls(
            "http://supervisor/core/api",
            supervisor_token,
            verify_ssl=False,
            current_instance=True,
        )

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def api_url(self, path: str) -> str:
        if path.startswith("/"):
            path = path[1:]
        if self.current_instance:
            return f"{self.base_url}/{path}"
        return f"{self.base_url}/api/{path}"

    def websocket_url(self) -> str:
        if self.current_instance:
            return "ws://supervisor/core/websocket"
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((scheme, parsed.netloc, "/api/websocket", "", "", ""))

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=self.timeout) as client:
            response = await client.request(
                method,
                self.api_url(path),
                headers=self.headers,
                **kwargs,
            )
        if response.status_code >= 400:
            text = response.text[:300]
            raise HomeAssistantError(f"{method} {path} failed with {response.status_code}: {text}")
        if response.text:
            return response.json()
        return None

    async def get_config(self) -> dict[str, Any]:
        return await self.request("GET", "config")

    async def get_states(self) -> list[dict[str, Any]]:
        return await self.request("GET", "states")

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
    ) -> Any:
        return await self.request("POST", f"services/{domain}/{service}", json=data or {})

    async def websocket_command(self, command_type: str, payload: dict[str, Any] | None = None) -> Any:
        uri = self.websocket_url()
        kwargs: dict[str, Any] = {"open_timeout": self.timeout}
        if uri.startswith("wss://") and not self.verify_ssl:
            kwargs["ssl"] = ssl._create_unverified_context()
        async with websockets.connect(uri, **kwargs) as websocket:
            greeting = json.loads(await asyncio.wait_for(websocket.recv(), timeout=self.timeout))
            if greeting.get("type") != "auth_required":
                raise HomeAssistantError("WebSocket did not request authentication")
            await websocket.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth = json.loads(await asyncio.wait_for(websocket.recv(), timeout=self.timeout))
            if auth.get("type") != "auth_ok":
                raise HomeAssistantError(auth.get("message", "WebSocket authentication failed"))
            message_id = 1
            data = {"id": message_id, "type": command_type}
            if payload:
                data.update(payload)
            await websocket.send(json.dumps(data))
            while True:
                message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=self.timeout))
                if message.get("id") == message_id:
                    if not message.get("success", False):
                        error = message.get("error", {})
                        raise HomeAssistantError(error.get("message", f"{command_type} failed"))
                    return message.get("result")
