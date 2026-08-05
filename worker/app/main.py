from fastapi import FastAPI

app = FastAPI(title="dispatch-worker")


@app.get("/")
def root():
    return {"service": "dispatch-worker", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}
