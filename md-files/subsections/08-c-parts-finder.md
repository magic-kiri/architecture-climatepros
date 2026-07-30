<!--
  §8 · Use Case C subsection — SOURCE OF TRUTH. Content from sample-unified.docx.
  Replaces "C Technician Parts Finder — API Reference" only.
-->

# C Technician Parts Finder — API Reference

The FastAPI AI Server exposes a deliberately small HTTP surface, reached by FJX 2.2 through the `.NET` Microservices API's AI proxy route — the mobile app never calls the AI layer directly, and the proxy forwards exactly the two control endpoints (`/parts/predict`, `/parts/source`).

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness / deploy probe (load-balancer + Container Apps health checks; not proxied to clients). |
| `POST /parts/predict` | RAG-predicted parts for a dispatch — via the AI proxy route. |
| `POST /parts/source` | All sources per part — via the AI proxy route. |

Both endpoints return a simple list of parts: `predict` returns the suggested parts for a dispatch, and `source` returns, for each part, the places it can be collected. Everything else — dispatch details, manual add, catalogue search — stays in the existing `.NET` APIs, unchanged. If prediction is unavailable the app simply falls back to manual add.
