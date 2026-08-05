import os

import redis.asyncio as redis
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="dispatch-worker")

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_TLS = os.environ.get("REDIS_TLS", "false").lower() == "true"
REDIS_AUTH_TOKEN = os.environ.get("REDIS_AUTH_TOKEN")

_redis_client = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_AUTH_TOKEN,
            ssl=REDIS_TLS,
            decode_responses=True,
        )
    return _redis_client


@app.get("/")
def root():
    return {"service": "dispatch-worker", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


class KeyValue(BaseModel):
    key: str
    value: str


@app.post("/test/write")
async def test_write(item: KeyValue):
    client = get_redis()
    await client.set(item.key, item.value)
    return {"key": item.key, "value": item.value, "status": "written"}


@app.get("/test/read")
async def test_read():
    client = get_redis()
    data = {}
    async for key in client.scan_iter("*"):
        if await client.type(key) == "string":
            data[key] = await client.get(key)
        else:
            data[key] = f"<unsupported type: {await client.type(key)}>"
    return {"count": len(data), "data": data}
