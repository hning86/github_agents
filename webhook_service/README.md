# ADK GitHub PR Reviewer Webhook Service

A lightweight FastAPI service designed to listen for GitHub webhooks (`pull_request` events) and autonomously invoke the **ADK GitHub Agent** (Gemini 2.5 Flash + remote GitHub MCP server) to perform code reviews and post comments on Pull Requests.

---

## 📁 Folder Structure

```
webhook_service/
├── __init__.py
├── main.py        # FastAPI webhook server & agent background task runner
├── Dockerfile     # Cloud Run multi-stage Dockerfile
└── README.md      # Deployment & running instructions
```

---

## 🚀 Running Locally (with ngrok)

1. **Ensure environment variables are configured** in `.env`:
   ```ini
   GCP_PROJECT_ID=ninghai-srtt
   GCP_REGION=us-central1
   GOOGLE_GENAI_USE_VERTEXAI=1
   GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_...
   GITHUB_WEBHOOK_SECRET=your_secret_passphrase
   ```

2. **Start the local FastAPI webhook server**:
   ```bash
   uv run python -m webhook_service.main
   ```
   *Server will listen on `http://localhost:8080`.*

3. **Expose localhost to GitHub using ngrok**:
   ```bash
   ngrok http 8080
   ```
   *Copy your forwarding URL (e.g., `https://abcdef123456.ngrok-free.app`).*

4. **Configure GitHub Webhook**:
   - Go to repo **Settings** → **Webhooks** → **Add webhook**
   - **Payload URL**: `https://<your-ngrok-domain>/webhook/github`
   - **Content type**: `application/json`
   - **Secret**: Your value from `GITHUB_WEBHOOK_SECRET`
   - **Events**: Select **Pull requests**

---

## ☁️ Deploying to Google Cloud Run

To deploy this service as a scalable, serverless app on Google Cloud Run:

1. **Submit Build & Deploy directly via gcloud** (from the repository root directory):
   ```bash
   gcloud run deploy github-pr-reviewer \
     --source . \
     --project ninghai-srtt \
     --region us-central1 \
     --allow-unauthenticated \
     --set-env-vars="GCP_PROJECT_ID=ninghai-srtt,GCP_REGION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=1,GITHUB_WEBHOOK_SECRET=your_secret_passphrase" \
     --set-secrets="GITHUB_PERSONAL_ACCESS_TOKEN=GITHUB_PAT_SECRET:latest"
   ```
   *(Or pass `GITHUB_PERSONAL_ACCESS_TOKEN` directly via `--set-env-vars` for testing).*

2. **Update your GitHub Webhook**:
   Replace the ngrok URL in GitHub with the assigned Cloud Run HTTPS Service URL (e.g., `https://github-pr-reviewer-abc123xyz-uc.a.run.app/webhook/github`).
