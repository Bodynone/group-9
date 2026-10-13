"""OpenAI-compatible transport; credentials and reasoning stay server-side."""

import re

import httpx

from .config import Settings


class ModelError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ChatProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def redact(self, message: str) -> str:
        if self.settings.api_key:
            message = message.replace(self.settings.api_key, "[已隐藏]")
        return re.sub(r"(?i)bearer\s+\S+", "Bearer [已隐藏]", message)[:1000]

    async def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        if not self.settings.api_key or not self.settings.model or not self.settings.base_url:
            raise ModelError("model_not_configured", "模型尚未配置，请检查后端 OPENAI_API_KEY、OPENAI_BASE_URL 和 OPENAI_MODEL。")
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
                response = await client.post(
                    self.settings.base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + self.settings.api_key},
                    json={"model": self.settings.model, "messages": messages, "tools": tools,
                          "tool_choice": "auto", "stream": False, "max_tokens": 8192},
                )
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
                raise ModelError(f"model_http_{response.status_code}", self.redact(message))
            body = response.json()
            choice = body["choices"][0]
            if not isinstance(choice, dict):
                raise ValueError("invalid choice")
            if choice.get("finish_reason") == "length":
                raise ModelError("model_output_truncated", "模型输出达到长度上限，请重试或人工批改。")
            message = choice["message"]
            if not isinstance(message, dict):
                raise ValueError("invalid assistant message")
            return message
        except ModelError:
            raise
        except httpx.TimeoutException as exc:
            raise ModelError("model_timeout", "模型服务超时，请重试或人工批改。") from exc
        except httpx.RequestError as exc:
            raise ModelError("model_connection_error", "无法连接模型服务，请检查网络或模型地址。") from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError("model_invalid_response", "模型服务返回了无法解析的响应。") from exc
