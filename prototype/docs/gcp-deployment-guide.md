# GCP Deployment Guide — Loan Lifecycle API

**Project:** `nth-infusion-490008-h8`
**Region:** `asia-south1` (Mumbai)
**Service:** `loan-lifecycle-api`
**Registry:** `asia-south1-docker.pkg.dev/nth-infusion-490008-h8/loan-lifecycle`

---

## Deployment Architecture

![GCP Deployment Pipeline](.archify/../../../.archify/workflow-gcp-deploy-20261020-120000/gcp-deploy.html)

Three parallel deployment paths all converge on Cloud Run:

| Path | Trigger | Entry point |
|---|---|---|
| Manual | Developer runs script locally | `deploy_gcp.sh` |
| Cloud Build | `gcloud builds submit` | `cloudbuild.yaml` |
| GitHub Actions | Push to `main` branch | `.github/workflows/deploy.yml` |

---

## 0. Prerequisites

```bash
# Verify gcloud is installed
gcloud version

# Verify Docker is installed and running
docker version

# Log in to GCP
gcloud auth login

# Set default project
gcloud config set project nth-infusion-490008-h8
```

---

## 1. One-Time Setup (run once per project)

### 1.1 Enable Required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  --project=nth-infusion-490008-h8 \
  --quiet
```

### 1.2 Create Artifact Registry Repository

```bash
gcloud artifacts repositories create loan-lifecycle \
  --repository-format=docker \
  --location=asia-south1 \
  --project=nth-infusion-490008-h8 \
  --quiet
```

### 1.3 Configure Docker to Authenticate with Artifact Registry

```bash
gcloud auth configure-docker asia-south1-docker.pkg.dev --quiet
```

---

## 2. IAM Permissions

### 2.1 Roles Required on the Deploying Identity

Grant these roles to the identity running deployments (user account, service account, or Cloud Build SA):

```bash
# Replace MEMBER with the principal, e.g.:
#   user:alok@example.com
#   serviceAccount:github-sa@nth-infusion-490008-h8.iam.gserviceaccount.com
#   serviceAccount:123456789@cloudbuild.gserviceaccount.com

PROJECT=nth-infusion-490008-h8
MEMBER="serviceAccount:github-sa@${PROJECT}.iam.gserviceaccount.com"

# Deploy and manage Cloud Run services
gcloud projects add-iam-policy-binding $PROJECT \
  --member="$MEMBER" \
  --role="roles/run.admin"

# Push images to Artifact Registry
gcloud projects add-iam-policy-binding $PROJECT \
  --member="$MEMBER" \
  --role="roles/artifactregistry.writer"

# Read secrets from Secret Manager at deploy time
gcloud projects add-iam-policy-binding $PROJECT \
  --member="$MEMBER" \
  --role="roles/secretmanager.secretAccessor"

# Submit Cloud Build jobs
gcloud projects add-iam-policy-binding $PROJECT \
  --member="$MEMBER" \
  --role="roles/cloudbuild.builds.editor"

# Act as the Cloud Run runtime service account
gcloud projects add-iam-policy-binding $PROJECT \
  --member="$MEMBER" \
  --role="roles/iam.serviceAccountUser"
```

### 2.2 Cloud Build Default Service Account (for `cloudbuild.yaml` path)

```bash
# Get the Cloud Build SA email
CB_SA=$(gcloud projects describe nth-infusion-490008-h8 \
  --format="value(projectNumber)")@cloudbuild.gserviceaccount.com

# Cloud Build SA needs to deploy to Cloud Run and read secrets
gcloud projects add-iam-policy-binding nth-infusion-490008-h8 \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding nth-infusion-490008-h8 \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/secretmanager.secretAccessor"

gcloud projects add-iam-policy-binding nth-infusion-490008-h8 \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/iam.serviceAccountUser"
```

### 2.3 Cloud Run Runtime Service Account

Cloud Run needs permission to access secrets at startup:

```bash
# Cloud Run uses the Compute Engine default SA by default
CR_SA=$(gcloud projects describe nth-infusion-490008-h8 \
  --format="value(projectNumber)")-compute@developer.gserviceaccount.com

gcloud projects add-iam-policy-binding nth-infusion-490008-h8 \
  --member="serviceAccount:${CR_SA}" \
  --role="roles/secretmanager.secretAccessor"
```

---

## 3. Store Secrets in Secret Manager

```bash
# OPENROUTER_API_KEY
printf 'sk-or-v1-YOUR_KEY_HERE' | gcloud secrets create OPENROUTER_API_KEY \
  --data-file=- \
  --project=nth-infusion-490008-h8

# QDRANT_URL
printf 'https://YOUR-CLUSTER.aws.cloud.qdrant.io:6333' | gcloud secrets create QDRANT_URL \
  --data-file=- \
  --project=nth-infusion-490008-h8

# QDRANT_API_KEY
printf 'YOUR_QDRANT_JWT_TOKEN' | gcloud secrets create QDRANT_API_KEY \
  --data-file=- \
  --project=nth-infusion-490008-h8

# To update an existing secret (add a new version):
printf 'NEW_VALUE' | gcloud secrets versions add OPENROUTER_API_KEY \
  --data-file=- \
  --project=nth-infusion-490008-h8
```

Verify secrets exist:

```bash
gcloud secrets list --project=nth-infusion-490008-h8
```

---

## 4. Path A — Manual Deploy (`deploy_gcp.sh`)

Run this for the very first deployment or when you need full control.

```bash
# From repo root
cd /path/to/loan-lifecycle

# Edit the variables at the top of deploy_gcp.sh, then:
chmod +x deploy_gcp.sh
./deploy_gcp.sh
```

What the script does step by step:

```bash
# Step 1: Set project
gcloud config set project nth-infusion-490008-h8

# Step 2: Enable APIs (idempotent)
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  --quiet

# Step 3: Create Artifact Registry repo (idempotent, errors suppressed)
gcloud artifacts repositories create loan-lifecycle \
  --repository-format=docker \
  --location=asia-south1 \
  --quiet

# Step 4: Store secrets
printf 'sk-or-v1-...' | gcloud secrets create OPENROUTER_API_KEY --data-file=- --quiet
printf 'https://...'   | gcloud secrets create QDRANT_URL          --data-file=- --quiet
printf 'eyJ...'        | gcloud secrets create QDRANT_API_KEY       --data-file=- --quiet

# Step 5: Authenticate Docker
gcloud auth configure-docker asia-south1-docker.pkg.dev --quiet

# Step 6: Build image
docker build -t asia-south1-docker.pkg.dev/nth-infusion-490008-h8/loan-lifecycle/loan-lifecycle-api:latest .

# Step 7: Push image
docker push asia-south1-docker.pkg.dev/nth-infusion-490008-h8/loan-lifecycle/loan-lifecycle-api:latest

# Step 8: Deploy to Cloud Run
gcloud run deploy loan-lifecycle-api \
  --image=asia-south1-docker.pkg.dev/nth-infusion-490008-h8/loan-lifecycle/loan-lifecycle-api:latest \
  --region=asia-south1 \
  --platform=managed \
  --allow-unauthenticated \
  --cpu=2 \
  --memory=2Gi \
  --min-instances=1 \
  --max-instances=5 \
  --concurrency=10 \
  --timeout=3600 \
  --no-cpu-throttling \
  --set-secrets="OPENROUTER_API_KEY=OPENROUTER_API_KEY:latest,QDRANT_URL=QDRANT_URL:latest,QDRANT_API_KEY=QDRANT_API_KEY:latest" \
  --set-env-vars="PYTHONUNBUFFERED=1,PYTHONPATH=/app/prototype,LOAN_AGENT_MODEL=anthropic/claude-sonnet-4-5" \
  --quiet

# Step 9: Get the live URL
gcloud run services describe loan-lifecycle-api \
  --region=asia-south1 \
  --format="value(status.url)"
```

---

## 5. Path B — Cloud Build (`cloudbuild.yaml`)

Trigger a build and deploy directly from the `cloudbuild.yaml` config:

```bash
# From repo root — submits source code to Cloud Build and runs the 3-step pipeline
gcloud builds submit \
  --config=cloudbuild.yaml \
  --project=nth-infusion-490008-h8

# Watch logs in real time (get BUILD_ID from the output above)
gcloud builds log BUILD_ID --stream --project=nth-infusion-490008-h8
```

`cloudbuild.yaml` pipeline (3 steps):

```
Step 1 — docker build  →  tags :SHORT_SHA and :latest
Step 2 — docker push   →  --all-tags to asia-south1-docker.pkg.dev
Step 3 — gcloud run deploy  →  uses :SHORT_SHA image, same Cloud Run config as manual path
```

Default substitution values (override with `--substitutions` flag if needed):

```bash
_REGION=asia-south1
_REPO=loan-lifecycle
_SERVICE=loan-lifecycle-api
```

---

## 6. Path C — GitHub Actions CI/CD (auto-deploy on push)

This path runs automatically on every push to `main` via `.github/workflows/deploy.yml`.

### 6.1 Create a GCP Service Account for GitHub

```bash
# Create the SA
gcloud iam service-accounts create github-sa \
  --display-name="GitHub Actions Deploy SA" \
  --project=nth-infusion-490008-h8

# Grant the required roles (same as section 2.1 above, targeting this SA)
PROJECT=nth-infusion-490008-h8
SA_EMAIL="github-sa@${PROJECT}.iam.gserviceaccount.com"

for ROLE in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/secretmanager.secretAccessor \
  roles/cloudbuild.builds.editor \
  roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$ROLE"
done

# Generate and download the JSON key
gcloud iam service-accounts keys create github-sa-key.json \
  --iam-account="${SA_EMAIL}" \
  --project=nth-infusion-490008-h8

echo "Key saved to github-sa-key.json — add its contents to GitHub secrets as GCP_SA_KEY"
```

**IMPORTANT:** `github-sa-key.json` is in `.gitignore`. Never commit it.

### 6.2 Add GitHub Repository Secrets

In GitHub → Settings → Environments → `GCP_Account_Setup`, add:

| Secret name | Value |
|---|---|
| `GCP_SA_KEY` | Full contents of `github-sa-key.json` |
| `GCP_PROJECT_ID` | `nth-infusion-490008-h8` |

### 6.3 Trigger the Workflow

```bash
# Option 1: push to main (automatic)
git push origin main

# Option 2: manual trigger from GitHub CLI
gh workflow run deploy.yml --repo YOUR_ORG/loan-lifecycle

# Watch the run
gh run watch --repo YOUR_ORG/loan-lifecycle
```

The workflow steps:
```
1. Checkout code
2. google-github-actions/auth@v2  (authenticates using GCP_SA_KEY)
3. google-github-actions/setup-gcloud@v2
4. gcloud auth configure-docker asia-south1-docker.pkg.dev
5. Create Artifact Registry repo (idempotent)
6. docker build  →  :${{ github.sha }} + :latest
7. docker push --all-tags
8. google-github-actions/deploy-cloudrun@v2  (same Cloud Run config)
9. Print live URL
```

---

## 7. Verify the Deployment

```bash
# Get service URL
gcloud run services describe loan-lifecycle-api \
  --region=asia-south1 \
  --format="value(status.url)"

# Check service status
gcloud run services describe loan-lifecycle-api \
  --region=asia-south1

# List recent revisions
gcloud run revisions list \
  --service=loan-lifecycle-api \
  --region=asia-south1 \
  --limit=5

# Stream logs
gcloud run services logs tail loan-lifecycle-api \
  --region=asia-south1

# Health check (replace URL)
curl -s https://loan-lifecycle-api-HASH-el.a.run.app/health | jq .

# List images in Artifact Registry
gcloud artifacts docker images list \
  asia-south1-docker.pkg.dev/nth-infusion-490008-h8/loan-lifecycle/loan-lifecycle-api \
  --include-tags
```

---

## 8. Subsequent Deploys

| Scenario | Command |
|---|---|
| Full redeploy (new code) | `git push origin main` → GitHub Actions fires automatically |
| Redeploy specific image | `gcloud run deploy loan-lifecycle-api --image=IMAGE_URL --region=asia-south1` |
| Update env vars only | `gcloud run services update loan-lifecycle-api --set-env-vars="KEY=VAL" --region=asia-south1` |
| Update a secret value | `printf 'NEW_VAL' \| gcloud secrets versions add SECRET_NAME --data-file=-` |
| Roll back to previous revision | `gcloud run services update-traffic loan-lifecycle-api --to-revisions=REVISION_NAME=100 --region=asia-south1` |
| Force Cloud Build run | `gcloud builds submit --config=cloudbuild.yaml` |

---

## 9. Summary of All IAM Roles Provisioned

| Role | Why |
|---|---|
| `roles/run.admin` | Create/update/delete Cloud Run services |
| `roles/artifactregistry.writer` | Push Docker images to Artifact Registry |
| `roles/secretmanager.secretAccessor` | Read secret values (deploy SA + Cloud Run runtime SA) |
| `roles/cloudbuild.builds.editor` | Submit and manage Cloud Build jobs |
| `roles/iam.serviceAccountUser` | Act as the Cloud Run runtime service account |

---

## 10. Useful One-Liners

```bash
# Print the live service URL
gcloud run services describe loan-lifecycle-api --region=asia-south1 --format="value(status.url)"

# Force traffic to 100% on the latest revision
gcloud run services update-traffic loan-lifecycle-api \
  --to-latest --region=asia-south1

# Delete old revisions (keeps last 5)
gcloud run revisions list --service=loan-lifecycle-api --region=asia-south1 \
  --format="value(name)" | tail -n +6 | xargs -I {} gcloud run revisions delete {} --region=asia-south1 --quiet

# Describe all secrets
gcloud secrets list --project=nth-infusion-490008-h8

# View Cloud Build history
gcloud builds list --project=nth-infusion-490008-h8 --limit=10
```
