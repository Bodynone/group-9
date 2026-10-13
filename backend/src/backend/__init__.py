def main() -> None:
    import uvicorn

    uvicorn.run("backend.app:create_app", factory=True, host="127.0.0.1", port=8000, workers=1)
