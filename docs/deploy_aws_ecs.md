# Deploy to AWS ECS (Fargate)

This guide packages the monorepo into two images (`agentic-sdlc-api`, `agentic-sdlc-web`) and runs them on ECS with an ALB health check hitting `/health`.

## 1) Prereqs
- AWS CLI v2 installed and configured (`aws configure`)
- ECR + ECS permissions (or use an admin IAM user while testing)
- Docker logged in locally

## 2) Create ECR Repositories
```bash
aws ecr create-repository --repository-name agentic-sdlc-api --image-scanning-configuration scanOnPush=true
aws ecr create-repository --repository-name agentic-sdlc-web --image-scanning-configuration scanOnPush=true
```

## 3) Build, Tag, Push Images
Set these once:
```bash
AWS_REGION=us-east-1            # adjust as needed
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_API=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/agentic-sdlc-api
ECR_WEB=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/agentic-sdlc-web
GIT_SHA=$(git rev-parse --short HEAD)
```

Authenticate Docker to ECR:
```bash
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

Build & tag:
```bash
# API (context: repo root)
docker build -f apps/api/Dockerfile -t $ECR_API:latest -t $ECR_API:v1 -t $ECR_API:$GIT_SHA .

# Web (context: apps/web to keep build small; set API base URL for deployed API/ALB)
docker build -f Dockerfile --build-arg VITE_API_BASE=https://your-api-domain/api/v1 \
  -t $ECR_WEB:latest -t $ECR_WEB:v1 -t $ECR_WEB:$GIT_SHA \
  apps/web
```

Push:
```bash
docker push $ECR_API:latest && docker push $ECR_API:v1 && docker push $ECR_API:$GIT_SHA
docker push $ECR_WEB:latest && docker push $ECR_WEB:v1 && docker push $ECR_WEB:$GIT_SHA
```

## 4) ECS (Fargate) Outline
- Create a Fargate cluster (e.g., `agentic-sdlc-cluster`).
- Define task definitions:
  - **API task**: container `agentic-sdlc-api`, image `$ECR_API:<tag>`, port 8000, CPU/Memory per your load, health check path `/health`.
  - **Web task**: container `agentic-sdlc-web`, image `$ECR_WEB:<tag>`, port 80.
- Set environment variables via task definition or SSM:
  - API runtime: `DATABASE_URL`, `OPENAI_API_KEY`, `ENV=production`, `RUN_MIGRATIONS_ON_STARTUP=1` as needed for your rollout strategy.
  - GitHub integration: `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_ALLOWED_ORG`.
  - Web build only: `VITE_API_BASE` (only used at build time; not required at runtime for the static web).
  - Prefer AWS Secrets Manager or SSM Parameter Store for secrets such as `OPENAI_API_KEY` and database credentials instead of baking them into images or committing `.env` files.
- Create an Application Load Balancer:
  - Target group for API (HTTP 8000) with health check path `/health`, matcher 200.
  - (Optional) Target group for Web if you want to front it with ALB instead of CloudFront/S3.
- Attach security groups allowing 80/443 inbound from the internet and 8000 only from the ALB.
- Place tasks in private subnets with NAT or public subnets as needed.

## 5) Runtime Health
- API exposes `/health` (FastAPI) returning `{"status": "ok"}`.
- Web container also responds at `/health` via Nginx for container-level checks.

## 6) Local Smoke Test
```bash
docker compose up --build
# Web: http://localhost:5173
# API: http://localhost:8000/health
```

## 7) Troubleshooting
- A local `.env` file is not shipped to ECS automatically. Set runtime secrets on the ECS task definition or inject them from Secrets Manager/SSM.
- `POST /api/v1/store/projects` is database-backed. A `500` on that route usually points to DB connectivity, migrations, or task env configuration, not to a missing `OPENAI_API_KEY`.
- Use `GET /api/v1/health/detail` to confirm whether the running task can reach the database before debugging OpenAI-related flows.

## 8) Image Tagging Strategy
- `:latest` — mutable dev/staging tag
- `:v1` — stable major line for pinned ECS services
- `:<git-sha>` — immutable for rollbacks/audits
