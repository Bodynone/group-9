"""OpenAI-compatible transport; credentials and reasoning stay server-side."""

import asyncio
import math
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import httpx

from .config import Settings

def usage_cost(usage: dict, *, prompt_price=None, completion_price=None) -> float | None:
    """Estimate CNY only with explicit per-million prices; unknown pricing is not zero."""
    counts = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
    if any(type(count) is not int or count < 0 for count in counts):
        return None
    if prompt_price is None or completion_price is None:
        return None
    try:
        prices = [Decimal(str(prompt_price)), Decimal(str(completion_price))]
        if any(not price.is_finite() or price < 0 for price in prices):
            return None
        amount = sum(Decimal(count) * price for count, price in zip(counts, prices)) / Decimal(1_000_000)
        return float(amount.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, OverflowError):
        return None


class ModelError(Exception):
    def __init__(self, code: str, message: str, transport=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.transport = transport


class ChatProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.semaphore = asyncio.Semaphore(3)
        if type(settings.max_output_tokens) is not int or not 512 <= settings.max_output_tokens <= 32768:
            raise ValueError("MODEL_MAX_OUTPUT_TOKENS须为512至32768的整数")
        if not math.isfinite(settings.min_request_interval) or not 0 <= settings.min_request_interval <= 60:
            raise ValueError("MODEL_MIN_REQUEST_INTERVAL_SECONDS须为0至60")
        self.pace_lock = asyncio.Lock()
        self.last_request_at = None

    async def pace(self):
        if self.settings.min_request_interval == 0:
            return
        async with self.pace_lock:
            clock = asyncio.get_running_loop().time
            if self.last_request_at is not None:
                await asyncio.sleep(max(0, self.settings.min_request_interval - (clock() - self.last_request_at)))
            self.last_request_at = clock()

    def redact(self, message: str) -> str:
        if self.settings.api_key:
            message = message.replace(self.settings.api_key, "[已隐藏]")
        return re.sub(r"(?i)bearer\s+\S+", "Bearer [已隐藏]", message)[:1000]

    async def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        if not self.settings.api_key or not self.settings.model or not self.settings.base_url:
            raise ModelError("model_not_configured", "模型尚未配置，请检查后端 OPENAI_API_KEY、OPENAI_BASE_URL 和 OPENAI_MODEL。")
        endpoint = self.settings.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        for attempt in range(5):
            try:
                async with self.semaphore, httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
                    await self.pace()
                    response = await client.post(
                        endpoint,
                        headers={"Authorization": "Bearer " + self.settings.api_key},
                        json={"model": self.settings.model, "messages": messages,
                              **({"tools": tools, "tool_choice": "auto"} if tools else {}), "stream": False, "max_tokens": self.settings.max_output_tokens},
                    )
                if response.status_code == 429 and attempt < 4:
                    await asyncio.sleep(6 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    message = "模型服务请求失败"
                    try:
                        body = response.json()
                        error = body.get("error", {}) if isinstance(body, dict) else {}
                        if isinstance(error, dict) and isinstance(error.get("message"), str):
                            message = error["message"]
                    except (ValueError, TypeError):
                        pass
                    if response.status_code == 403 and "email verification" in message.lower():
                        message = "魔搭账号尚未完成邮箱验证，请在 https://modelscope.cn/my/settings/account 完成验证后重试。"
                    transport = {"attempts": attempt + 1, "rate_limits": attempt + int(response.status_code == 429)} if attempt or response.status_code == 429 else None
                    raise ModelError(f"model_http_{response.status_code}", self.redact(message), transport)
                body = response.json()
                choice = body["choices"][0]
                if not isinstance(choice, dict):
                    raise ValueError("invalid choice")
                if choice.get("finish_reason") == "length":
                    raise ModelError("model_output_truncated", "模型输出达到长度上限，请重试或人工批改。")
                message = choice["message"]
                if not isinstance(message, dict):
                    raise ValueError("invalid assistant message")
                usage = body.get("usage")
                if isinstance(usage, dict):
                    message["usage"] = usage
                if attempt:
                    message["_transport"] = {"attempts": attempt + 1, "rate_limits": attempt}
                return message
            except ModelError:
                raise
            except httpx.TimeoutException as exc:
                raise ModelError("model_timeout", "模型服务超时，请重试或人工批改。") from exc
            except httpx.RequestError as exc:
                raise ModelError("model_connection_error", "无法连接模型服务，请检查网络或模型地址。") from exc
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ModelError("model_invalid_response", "模型服务返回了无法解析的响应。") from exc
