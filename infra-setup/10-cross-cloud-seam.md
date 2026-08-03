# 10 · Cross-cloud seam — AWS → Azure AI server (AWS side only)

**Status:** NEW · **Cloud:** AWS side of the seam · **Used by:** UC-B, UC-C

Stream 1's **only** cross-cloud hop: the .NET AI-proxy route on AWS EC2 calling the FastAPI AI server on
Azure Container Apps, carrying job context in the request payload.

What this means for AWS provisioning:

| | |
|---|---|
| **Auto-Dispatch (A)** | never crosses clouds. Nothing in this file affects it. |
| **AWS-side work** | outbound HTTPS from one EC2 host, one secret, egress accounting |
| **Not here** | Azure Container Apps, Cosmos DB, the vector store, the on-prem model link — all Azure/on-prem provisioning |

Two invariants from §4, worth checking against any implementation:

- The AI server **never** holds a connection to AWS SQL Server. Context travels in the payload.
- Technician phones **never** reach the AI server directly. Only the .NET proxy does.

---

## Prereqs

`04` — the `cp/$ENV/ai-server` secret. The Azure side must exist and expose an HTTPS endpoint.

---

## Steps

### 1. Confirm the direction of travel

**Outbound only.** AWS initiates; Azure never calls into AWS. So there is **no inbound rule to add, no
load balancer, no public listener** on the AWS side. If someone asks you to open an inbound port for the
AI server, the design has been misread.

### 2. Egress from the EC2 host

The .NET host already reaches the internet (it serves the mobile app). Confirm the SG allows outbound 443:

```bash
aws ec2 describe-security-groups --group-ids $EC2_SG_ID \
  --query 'SecurityGroups[0].IpPermissionsEgress' --output json
```

To tighten it — replace allow-all egress with the Azure endpoint only — resolve the Container Apps
hostname and pin its IPs, or use an AWS Network Firewall FQDN rule. Container Apps IPs are not static, so
prefer the firewall/FQDN route over hard-coded CIDRs.

### 3. Give Azure a stable source IP to allow-list

Until VPN/peering exists, the interim posture in §4 is *public HTTPS endpoint locked down by IP
allow-listing / mTLS*. Azure needs to know which IP is us — the NAT gateway's Elastic IP, or the EC2
host's own EIP:

```bash
aws ec2 describe-nat-gateways --filter Name=state,Values=available \
  --query 'NatGateways[].NatGatewayAddresses[].PublicIp' --output text

aws ec2 describe-addresses --query 'Addresses[].{Ip:PublicIp,Instance:InstanceId}' --output table
```

Hand that IP to whoever configures the Container Apps ingress restriction. If it is not a *fixed* EIP,
fix it first — an allow-list against a rotating IP breaks silently on the next reboot.

### 4. Endpoint + credential in one place

Already created in `04`. The .NET proxy reads it at start-up:

```bash
aws secretsmanager get-secret-value --secret-id cp/$ENV/ai-server \
  --query 'SecretString' --output text
```

The EC2 instance role needs `secretsmanager:GetSecretValue` on that ARN — same shape as the policy in
`03`, added to `$EC2_ROLE_NAME`.

### 5. Target state — site-to-site VPN (leads only, later)

§4's target is a site-to-site VPN or VPC-to-VNet peering. Shape of the AWS half, for planning; do not run
this during initial bring-up:

```bash
aws ec2 create-vpn-gateway --type ipsec.1 --amazon-side-asn 64512
aws ec2 attach-vpn-gateway --vpn-gateway-id <vgw-...> --vpc-id $VPC_ID
aws ec2 create-customer-gateway --type ipsec.1 --public-ip <azure-vpn-gateway-ip> --bgp-asn 65000
aws ec2 create-vpn-connection --type ipsec.1 --vpn-gateway-id <vgw-...> --customer-gateway-id <cgw-...>
```

Then the Azure-side Virtual Network Gateway with the matching PSK, and routes on both sides. Coordinated
work across two clouds — assign to Kiriti / Althaf per
[`../md-files/cloud-access-request.md`](../md-files/cloud-access-request.md). Cost: VPN connection
≈ $36/mo per tunnel, plus data transfer.

---

## Verify

From the EC2 host (SSM session), not your laptop:

```bash
curl -sS -o /dev/null -w '%{http_code} %{time_total}s\n' https://<ai-server-host>/health
```

Expect `200` and a round-trip time you can budget against the §9 P95 targets. Then confirm the negative
cases:

```bash
# from anywhere outside AWS - must NOT succeed if the allow-list is right
curl -sS -m 5 https://<ai-server-host>/health
```

And confirm the invariants hold:

```bash
# the Fargate worker must have no route to the AI server (A never crosses clouds)
aws ecs describe-task-definition --task-definition cp-$ENV-dispatch-worker \
  --query 'taskDefinition.containerDefinitions[0].{env:environment,secrets:secrets[].name}' --output json
# no ai-server URL, no ai-server secret
```

---

## Talks to

| From | To | Protocol | Auth | Notes |
|---|---|---|---|---|
| .NET AI proxy (EC2) | FastAPI AI server (Azure Container Apps) | 443 out | API key / mTLS | **the only cross-cloud hop** |
| Azure AI server | AWS | — | — | never initiates |
| Azure AI server | AWS SQL Server | — | — | **forbidden by design** |
| ECS dispatch worker | Azure | — | — | never — A stays in AWS |

Downstream of the AI server (Azure → on-prem LiteLLM over VPN, Azure → Gemini over HTTPS) is Azure-side
configuration.

---

## Cost

AWS bills **egress** on the proxy's outbound call: ~$0.09/GB after the free tier. One request/response
pair per summarisation (B) or parts search (C) — not per SQL row. §10 records this line as **TBD** because
no source figure exists; measure it in Staging before quoting a number.

Adding the VPN later replaces per-GB internet egress with a fixed ~$36/mo tunnel plus lower-rate transfer.

---

## Gotchas

- **If the link goes down:** B and C fall back to their existing manual path (forms without AI assist, no
  parts search). Auto-Dispatch (A) is completely unaffected. Set the HTTP client timeout to fail fast — a
  hung AI call must never block a technician's Save.
- Don't let the fallback posture become permanent. A public endpoint + IP allow-list is the interim; VPN is
  the target.
- One trace across two clouds needs OTel context propagated in the request headers, with CloudWatch
  holding the AWS spans and Azure Monitor the Azure ones. Neither side sees the whole trace by default.
- Never solve latency by caching AI responses in Redis — that cache is the dispatch queue, and mixing
  concerns in a `noeviction` store is how the queue fills up.

**Next:** [`11-service-communication.md`](11-service-communication.md)
