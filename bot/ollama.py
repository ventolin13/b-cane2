"""HTTP-клиент локальной Ollama."""

from __future__ import annotations

from typing import Any

import httpx

SHORT_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
CHAT_TIMEOUT = httpx.Timeout(180.0, connect=5.0)


class OllamaDown(Exception):
    """Процесс Ollama недоступен."""


class OllamaTimeout(Exception):
    """Ollama не ответила в отведённое время."""


class OllamaModelNotFound(Exception):
    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(model)


class OllamaError(Exception):
    """Прочий ответ Ollama, который нельзя показать как успешный чат."""


class OllamaClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> bool:
        try:
            response = await self._client.get("/", timeout=SHORT_TIMEOUT)
        except (httpx.TimeoutException, httpx.TransportError):
            return False
        return 200 <= response.status_code < 300

    async def list_models(self) -> list[str]:
        payload = await self._request("GET", "/api/tags", timeout=SHORT_TIMEOUT)
        names: list[str] = []
        for item in payload.get("models") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("model")
            if isinstance(name, str) and name:
                names.append(name)
        return names

    async def chat(self, model: str, messages: list[dict[str, str]]) -> str:
        payload = await self._request(
            "POST",
            "/api/chat",
            timeout=CHAT_TIMEOUT,
            json={"model": model, "messages": messages, "stream": False},
            model=model,
        )
        message = payload.get("message")
        if not isinstance(message, dict):
            raise OllamaError("в ответе нет message")
        content = message.get("content")
        if not isinstance(content, str):
            raise OllamaError("в ответе нет content")
        return content

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: httpx.Timeout,
        json: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method, path, json=json, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            raise OllamaTimeout from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise OllamaDown from exc

        if response.status_code >= 400:
            body = response.text
            if model is not None and _is_unknown_model(response.status_code, body):
                raise OllamaModelNotFound(model)
            detail = body.strip().replace("\n", " ")
            if len(detail) > 180:
                detail = detail[:180] + "…"
            raise OllamaError(detail or f"HTTP {response.status_code}")

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaError("Ollama вернула не JSON") from exc
        if not isinstance(data, dict):
            raise OllamaError("Ollama вернула не объект")
        return data


def _is_unknown_model(status_code: int, body: str) -> bool:
    if status_code == 404:
        return True
    lowered = body.lower()
    return "not found" in lowered or "unknown model" in lowered
