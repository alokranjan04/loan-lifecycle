#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy_gcp.sh — one-shot GCP deploy for loan-lifecycle
# Run once to set up; subsequent deploys go through Cloud Build / GitHub trigger
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── EDIT THESE ────────────────────────────────────────────────────────────────
PROJECT_ID="nth-infusion-490008-h8"
REGION="asia-south1"
SERVICE="loan-lifecycle-api"
REPO="loan-lifecycle"
OPENROUTER_KEY="sk-or-..."                # your OpenRouter API key
QDRANT_URL=""        # set via Secret Manager — see README / env.example
QDRANT_API_KEY=""    # set via Secret Manager — see README / env.example
# ─────────────────────────────────────────────────────────────────────────────

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}"

echo "▶ Setting project to ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

echo "▶ Enabling required APIs"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  --quiet

echo "▶ Creating Artifact Registry repository (skip if exists)"
gcloud artifacts repositories create "${REPO}" \
  --repository-format=docker \
  --location="${REGION}" \
  --quiet 2>/dev/null || true

echo "▶ Storing secrets in Secret Manager (skipped if value is empty)"
for SECRET_NAME in OPENROUTER_API_KEY QDRANT_URL QDRANT_API_KEY; do
  case $SECRET_NAME in
    OPENROUTER_API_KEY) VAL="${OPENROUTER_KEY}" ;;
    QDRANT_URL)         VAL="${QDRANT_URL}" ;;
    QDRANT_API_KEY)     VAL="${QDRANT_API_KEY}" ;;
  esac
  if [ -z "${VAL}" ]; then
    echo "  skipping ${SECRET_NAME} (already set via Secret Manager)"
    continue
  fi
  printf '%s' "${VAL}" | gcloud secrets create "${SECRET_NAME}" \
    --data-file=- --quiet 2>/dev/null || \
  printf '%s' "${VAL}" | gcloud secrets versions add "${SECRET_NAME}" \
    --data-file=- --quiet
done

echo "▶ Configuring Docker auth for Artifact Registry"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "▶ Building Docker image"
docker build -t "${IMAGE}:latest" .

echo "▶ Pushing image"
docker push "${IMAGE}:latest"

echo "▶ Deploying to Cloud Run"
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}:latest" \
  --region="${REGION}" \
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

echo ""
echo "✅ Deployed! Service URL:"
gcloud run services describe "${SERVICE}" --region="${REGION}" \
  --format="value(status.url)"
