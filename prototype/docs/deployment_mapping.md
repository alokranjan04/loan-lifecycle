# Deployment mapping

How each prototype component maps to a production service. Azure is shown as primary because many banks already run on it; the design does not depend on it, and the cloud is a discovery-week decision (ADR 0004).

| Component (prototype file) | Azure (primary) | AWS (alternative) | GCP (alternative) | Why |
|---|---|---|---|---|
| Case state machine and human tasks (`orchestrator.py`) | Durable Functions (or Logic Apps Standard) | Step Functions with task tokens | Workflows + Cloud Tasks | A case waits days on a human without a running process; every transition is replayable |
| Agents (`agents.py`) | Container Apps or Functions, one managed identity per agent | ECS Fargate or Lambda, one IAM role per agent | Cloud Run, one service account per agent | Least privilege per agent; scale to zero at ~10 cases a day |
| Model access (`llm.py`) | Claude via Microsoft Foundry, behind API Management as the LLM gateway | Claude via Amazon Bedrock or Claude Platform on AWS, behind API Gateway | Claude via Vertex AI, behind Apigee | In-region endpoint, no training on bank data; gateway handles redaction, rate limits and cost per case |
| Document ingestion and OCR | Blob Storage + Azure AI Document Intelligence (layout) | S3 + Textract | Cloud Storage + Document AI | Line and page coordinates for citations; raw, masked and extracted copies kept |
| PII token vault (`security.py`) | Key Vault + a tokenisation table in Azure SQL (Always Encrypted) | KMS + DynamoDB, or Macie for discovery | Cloud KMS + Sensitive Data Protection | Identifiers never reach the model |
| Policy registry and retrieval (`knowledge.py`, `registry.json`) | Azure SQL for versions; Azure AI Search when the corpus grows (ADR 0003) | Aurora / RDS; OpenSearch | Cloud SQL; Vertex AI Search | Clause ID + effective date are exact keys; hybrid search added later |
| Case store and decision records (`report.py`) | Azure SQL or Cosmos DB | Aurora or DynamoDB | Cloud SQL or Firestore | Queryable for MI and replay |
| Audit log (`audit.py`) | Immutable Blob Storage (WORM, time-based retention) | S3 Object Lock (compliance mode) | Cloud Storage bucket lock | Hash chain plus storage-level immutability |
| Reviewer workbench (`workbench/`) | Panel in the LOS UI, or App Service with Entra ID SSO | Panel in the LOS, or App Runner with IAM Identity Center | Panel in the LOS, or Cloud Run with IAP | Reviewers stay in their system of record (ADR 0004) |
| Evals and release gate (`evals/`, `tests/`) | Azure DevOps / GitHub Actions pipeline; results to Blob | CodePipeline / GitHub Actions; results to S3 | Cloud Build / GitHub Actions; results to GCS | Golden set runs on every model, prompt or policy change |
| Observability (`trace.jsonl`) | Application Insights (OpenTelemetry) | CloudWatch + X-Ray | Cloud Trace + Cloud Logging | Latency, tokens, cost and errors per case and step |
| Integration with LOS, KYC, core banking | API Management + Service Bus; MCP servers as typed tools | API Gateway + EventBridge | Apigee + Pub/Sub | One tool contract per system, scoped credentials |
| Identity | Entra ID (SSO, RBAC, managed identities) | IAM Identity Center + IAM | Cloud Identity + IAM | Named humans at the gates; agents have their own identities |

## How the human gates map

The prototype's `ApprovalWorkflowAgent` produces a list of gates (compliance, then credit at the required authority). In production each gate becomes a human task in the workflow engine (a Durable Functions external event, a Step Functions task token, or a Workflows callback). The workbench or LOS submits the decision; the same `validate_human_action` controls run server-side before the workflow continues; blocked attempts are written to the audit log exactly as they are today.

## Sizing note

The stated volume is about 2,000 applications a year, roughly 8 a working day. Serverless, scale-to-zero services fit that volume; nothing in this design needs a cluster or a streaming platform for the POC.
