# Stream 1 — Cloud Access Request List

Source: `stream1-unified-architecture-doc.html` §3 Technology Stack, §4 Infrastructure.

Team: Pavithra, Saravana, Karthik, Kanish, Ajay. Lead: Kiriti, Althaf.

---

| Service | Cloud | Purpose | Who needs access |
|---|---|---|---|
| AWS EC2 | AWS | Host for .NET Legacy API + .NET Microservices API | Pavithra, Saravana, Karthik, Kanish, Ajay, Kiriti, Althaf |
| AWS SQL Server (RDS) | AWS | System of record — dispatch & assignment tables | Pavithra, Saravana, Kiriti, Althaf |
| Amazon ElastiCache for Redis | AWS | Durable dispatch queue — Redis Streams, division locks, per-tech reply BLPOP | Pavithra, Saravana, Kiriti, Althaf |
| AWS ECS Fargate | AWS | Async worker pool (scale 0–1), consumes queued dispatches | Pavithra, Saravana, Kiriti, Althaf |
| Amazon SNS | AWS | Outbound push (APNs/FCM) to technician phones | Pavithra, Saravana, Kiriti, Althaf |
| AWS Load Balancer / API Gateway (WAF, TLS) | AWS | Public entry point for all API traffic | Kiriti, Althaf |
| Azure Container Apps | Azure | FastAPI AI Server — single entry point, only path to models | Karthik, Kanish, Saravana, Ajay, Kiriti, Althaf |
| Azure Cosmos DB (vCore, MongoDB API) | Azure | AI-owned datastore — summaries, part results, llm_calls, evals | Karthik, Kanish, Saravana, Ajay, Kiriti, Althaf |
| Vector store (Azure AI Search / Pinecone) | Azure | Embedded similarity search over historical dispatch/parts data | Karthik, Kanish, Saravana, Ajay, Kiriti, Althaf |
| Azure VNet (private endpoints, VPN/peering to AWS VPC) | Azure | Network boundary for AI stack + cross-cloud hop | Kiriti, Althaf |
| LiteLLM Gateway + self-hosted qwen3-vl-moe (vLLM) + bge-m3 embedding | On-prem | Primary generation/embedding models, client hardware | Karthik, Kanish, Saravana, Ajay |
| Google Gemini API | External | Managed fallback model only | Karthik, Kanish, Saravana, Ajay |
| CloudWatch | AWS | Observability/tracing — AWS-side services | Pavithra, Saravana, Karthik, Kanish, Ajay, Kiriti, Althaf |
| Azure Monitor | Azure | Observability/tracing — AI stack | Pavithra, Saravana, Karthik, Kanish, Ajay, Kiriti, Althaf |

---

## Notes for client

- One cross-cloud hop: AWS `.NET AI-proxy` → Azure AI Server. VPN/peering setup between clouds is Lead-only (Kiriti, Althaf).
- On-prem model hardware access is client-managed; devs need credentials/network path to it, not cloud console access.
- Observability (CloudWatch + Azure Monitor) needed by everyone — full team touches traces/logs across both clouds.
