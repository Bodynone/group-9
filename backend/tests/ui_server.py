"""Local end-to-end test server; never enable this provider in production.

Run from backend: UV_CACHE_DIR=/tmp/group9-uv-cache uv run --group dev python tests/ui_server.py
TEST_DB_PATH may select an isolated SQLite database. This code does not load .env
or make network model requests, and the fixture grades are test substitutions.
"""

import json
import os

import uvicorn

from backend.app import create_app
from backend.config import Settings
from backend.provider import ModelError
from backend.storage import Store

from scripted_provider import DIMENSIONS, ScriptedProvider, anchors


class UiTestProvider:
    def __init__(self):
        self.providers = {}
        self.failed_inputs = set()
        self.failed_tasks = set()

    async def complete(self, messages, tools):
        metadata = json.loads(messages[1]["content"])
        task_id = metadata["task_id"]
        text = metadata["assignment_text"]
        input_version = metadata["input_version"]
        if "\n[E2E_ALWAYS_FAIL]" in text:
            raise ModelError("test_tool_503", "受控测试：定位工具503")
        if "\n[E2E_TOOL_503_ONCE]" in text:
            if input_version not in self.failed_inputs:
                self.failed_inputs.add(input_version)
                self.failed_tasks.add(task_id)
            if task_id in self.failed_tasks:
                raise ModelError("test_tool_503", "受控测试：定位工具503")
        if task_id not in self.providers:
            task = {
                "id": task_id, "text": text, "input_version": input_version,
                "rubric_version": metadata["rubric_version"],
            }
            present = anchors(text)
            levels = {dimension: 100 if dimension in present else 0 for dimension in DIMENSIONS}
            self.providers[task_id] = ScriptedProvider(task, levels)
        return await self.providers[task_id].complete(messages, tools)


def create_ui_app():
    database = os.environ.get("TEST_DB_PATH", "/tmp/group9-ui-tests.sqlite3")
    settings = Settings(
        api_key="e2e-test-placeholder", base_url="https://never-call.invalid/v1",
        model="scripted-ui-test-provider", database_path=database,
    )
    return create_app(settings=settings, store=Store(database), provider=UiTestProvider())


if __name__ == "__main__":
    uvicorn.run(create_ui_app(), host="127.0.0.1", port=int(os.environ.get("E2E_PORT", "8001")), workers=1)
