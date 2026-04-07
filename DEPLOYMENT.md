# Flax Assistant — Deployment Guide

Deploy the backend to AWS ECS Fargate and distribute the Electron desktop app to teammates.

## Architecture

```
GitHub (main branch)
   │
   └── backend/** → GitHub Actions → ECR → ECS Service (flax-assistant-service)
                                              │
                                    Application Load Balancer
                                    └── api.flax-assistant.com → Backend (port 8747)

Teammates install the macOS DMG (built via GitHub Actions) pointing at the deployed backend.
```

**Components:**
- **1 ECR repository** — Docker image storage
- **1 ECS Cluster** (Fargate) — runs the backend
- **1 ECS Task Definition** — container spec
- **1 ECS Service** — manages rolling deploys
- **1 Application Load Balancer** — HTTPS termination
- **Supabase** (PostgreSQL) — managed database, no infra to run
- **1 AWS Secrets Manager secret** — runtime env vars
- **GitHub Actions** — auto-deploy backend on push to main; build desktop DMG on tag

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create IAM User for GitHub Actions](#2-create-iam-user-for-github-actions)
3. [Create ECR Repository](#3-create-ecr-repository)
4. [Push Initial Docker Image](#4-push-initial-docker-image)
5. [Store Secrets in AWS Secrets Manager](#5-store-secrets-in-aws-secrets-manager)
6. [Create IAM Roles for ECS](#6-create-iam-roles-for-ecs)
7. [Create Supabase Project](#7-create-supabase-project)
8. [Create CloudWatch Log Group](#8-create-cloudwatch-log-group)
9. [Create ECS Cluster](#9-create-ecs-cluster)
10. [Register Task Definition](#10-register-task-definition)
11. [Create Application Load Balancer](#11-create-application-load-balancer)
12. [Create ECS Service](#12-create-ecs-service)
13. [Connect Domain & SSL](#13-connect-domain--ssl)
14. [Configure HTTPS on Load Balancer](#14-configure-https-on-load-balancer)
15. [Set Up GitHub Actions Secrets](#15-set-up-github-actions-secrets)
16. [Trigger First Deployment](#16-trigger-first-deployment)
17. [Build & Distribute Desktop App](#17-build--distribute-desktop-app)

---

## 1. Prerequisites

- AWS account with billing enabled
- AWS CLI installed and configured: `brew install awscli && aws configure`
- Docker installed and running
- Domain name (optional but recommended for HTTPS)

---

## 2. Create IAM User for GitHub Actions

1. **IAM → Users → Create user**, name: `flax-assistant-github-actions`
2. Attach policies:
   - `AmazonEC2ContainerRegistryFullAccess`
   - `AmazonECS_FullAccess`
3. **Security credentials → Create access key → Application running outside AWS**
4. Save `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` for Step 15

---

## 3. Create ECR Repository

1. **ECR → Repositories → Create repository**
2. Name: `flax-assistant`
3. Note your **AWS Account ID** and **region** (e.g., `us-east-1`)

---

## 4. Push Initial Docker Image

```bash
export AWS_ACCOUNT_ID=123456789012
export AWS_REGION=us-east-1

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build and push
docker build -t $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/flax-assistant:latest ./backend
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/flax-assistant:latest
```

---

## 5. Store Secrets in AWS Secrets Manager

1. **Secrets Manager → Store a new secret → Other type of secret**
2. Add these key-value pairs:

| Key | Value |
|-----|-------|
| `DATABASE_URL` | Supabase connection string — see Step 7 |
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `GEMINI_API_KEY` | `AIza...` |
| `CORS_ORIGINS` | `*` (or lock down to specific origins later) |
| `GOOGLE_CLIENT_ID` | `....apps.googleusercontent.com` (if using Calendar) |
| `GOOGLE_CLIENT_SECRET` | `...` |
| `SENTRY_DSN` | `https://...` (optional) |
| `LANGFUSE_PUBLIC_KEY` | `pk-lf-...` (optional) |
| `LANGFUSE_SECRET_KEY` | `sk-lf-...` (optional) |

3. Secret name: `flax-assistant/api`
4. Copy the full secret ARN for Step 10

---

## 6. Create IAM Roles for ECS

### Task Execution Role

If `ecsTaskExecutionRole` doesn't exist:
1. **IAM → Roles → Create role → AWS service → ECS Task**
2. Attach: `AmazonECSTaskExecutionRolePolicy`
3. Name: `ecsTaskExecutionRole`

Add secrets access:
1. Find `ecsTaskExecutionRole` → **Add permissions → Create inline policy**
2. JSON:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:<REGION>:<ACCOUNT_ID>:secret:flax-assistant/*"
    }
  ]
}
```
3. Name: `flax-assistant-secrets-access`

---

## 7. Create Supabase Project

Supabase is a managed PostgreSQL service — no servers to run.

1. Go to [supabase.com](https://supabase.com) → **New project**
2. Name: `flax-assistant`, choose a region close to your AWS region
3. Set a strong database password — save it
4. Wait ~1 min for provisioning

### Get the connection string

1. **Project Settings → Database → Connection string**
2. Select the **Session mode** tab (not Transaction mode — needed for SQLAlchemy)
3. Copy the URI, it looks like:
   ```
   postgresql://postgres.[project]:[password]@aws-0-us-east-1.pooler.supabase.com:5432/postgres
   ```
4. Change the scheme to `postgresql+asyncpg://` for async SQLAlchemy:
   ```
   postgresql+asyncpg://postgres.[project]:[password]@aws-0-us-east-1.pooler.supabase.com:5432/postgres
   ```
5. Paste this as the `DATABASE_URL` value in Secrets Manager (Step 5)

> The schema (tables) is created automatically on first backend startup via SQLAlchemy `create_all`.

---

## 8. Create CloudWatch Log Group

```bash
aws logs create-log-group --log-group-name /ecs/flax-assistant --region $AWS_REGION
```

---

## 9. Create ECS Cluster

1. **ECS → Clusters → Create cluster**
2. Name: `flax-assistant-cluster`
3. Infrastructure: **AWS Fargate (serverless)**
4. Click **Create**

---

## 10. Register Task Definition

Edit `infrastructure/ecs/assistant-task-definition.json` — replace all placeholders:

```bash
# Replace placeholders in the task definition
sed -i '' \
  -e 's/<YOUR_ACCOUNT_ID>/'"$AWS_ACCOUNT_ID"'/g' \
  -e 's/<YOUR_REGION>/'"$AWS_REGION"'/g' \
  -e 's/<YOUR_EFS_ID>/fs-0abc12345/g' \
  infrastructure/ecs/assistant-task-definition.json

# Also update the Secrets Manager ARN suffix to match yours exactly
# (the ARN has a random 6-char suffix, e.g. :secret:flax-assistant/api-AbCdEf)
```

Then register:

```bash
aws ecs register-task-definition \
  --cli-input-json file://infrastructure/ecs/assistant-task-definition.json \
  --region $AWS_REGION
```

---

## 11. Create Application Load Balancer

### Create ALB

1. **EC2 → Load Balancers → Create → Application Load Balancer**
2. Name: `flax-assistant-alb`
3. Scheme: **Internet-facing**, IPv4
4. VPC: default, select **at least 2 AZs**
5. Security group — create new `flax-alb-sg`:
   - Inbound: HTTP 80 and HTTPS 443 from `0.0.0.0/0`
6. Listener: HTTP:80, default action: fixed 503
7. Click **Create**

### Create Target Group

1. **EC2 → Target Groups → Create target group**
2. Type: **IP addresses**
3. Name: `flax-assistant-tg`
4. Protocol: HTTP, Port: **8747**
5. Health check path: `/health`
6. Thresholds: interval 30s, healthy threshold 2
7. Click **Create**

---

## 12. Create ECS Service

### Create Security Group for ECS Tasks

1. **EC2 → Security Groups → Create**
2. Name: `flax-ecs-sg`
3. Inbound: TCP 8747 from `flax-alb-sg`
4. Outbound: all traffic (for ECR pulls and Supabase)

### Create the Service

1. **ECS → flax-assistant-cluster → Services → Create**
2. Launch type: **Fargate**
3. Task definition: `flax-assistant-task` (latest)
4. Service name: `flax-assistant-service`
5. Desired tasks: **1** (scale up later if needed)
6. Networking:
   - VPC: default, all subnets
   - Security group: `flax-ecs-sg`
   - Public IP: **Enabled**
7. Load balancing:
   - ALB: `flax-assistant-alb`
   - Container: `flax-assistant:8747`
   - Target group: `flax-assistant-tg`
8. Click **Create**

### Add ALB Routing Rule

1. **EC2 → Load Balancers → flax-assistant-alb → Listeners → HTTP:80 → Manage rules**
2. Edit default rule: forward to `flax-assistant-tg`

---

## 13. Connect Domain & SSL

Get the ALB DNS name from **EC2 → Load Balancers → flax-assistant-alb → DNS name**.

Add a DNS record at your provider:

| Type | Name | Value |
|------|------|-------|
| CNAME | `api` | `flax-assistant-alb-xxxx.us-east-1.elb.amazonaws.com` |

Test: `curl http://api.flax-assistant.com/health` → `{"status":"ok",...}`

### Get SSL Certificate (AWS ACM)

1. **Certificate Manager → Request certificate → Public**
2. Domain: `api.flax-assistant.com`
3. Validation: DNS → add the CNAME to your DNS
4. Wait ~2min for status **Issued**

---

## 14. Configure HTTPS on Load Balancer

1. **EC2 → Load Balancers → flax-assistant-alb → Listeners → Add listener**
2. Protocol: **HTTPS**, Port: **443**
3. Default action: forward to `flax-assistant-tg`
4. SSL cert: select your ACM cert
5. Click **Add**

Redirect HTTP → HTTPS:
1. **Listeners → HTTP:80 → Edit default rule**
2. Action: **Redirect to HTTPS**, status 301

---

## 15. Set Up GitHub Actions Secrets

**Settings → Secrets and variables → Actions → New repository secret:**

| Secret | Value |
|--------|-------|
| `AWS_ACCESS_KEY_ID` | From Step 2 |
| `AWS_SECRET_ACCESS_KEY` | From Step 2 |
| `AWS_REGION` | e.g., `us-east-1` |
| `ECR_REPOSITORY` | `flax-assistant` |
| `ECS_CLUSTER` | `flax-assistant-cluster` |
| `ECS_SERVICE` | `flax-assistant-service` |
| `BACKEND_URL` | `https://api.flax-assistant.com` |
| `WS_URL` | `wss://api.flax-assistant.com/ws/mascot` |
| `SUPABASE_URL` | `https://your-project.supabase.co` (same as backend) |
| `SUPABASE_ANON_KEY` | Project Settings → API → anon/public key |

---

## 16. Trigger First Deployment

Push to main to trigger the backend deploy workflow:

```bash
git add .
git commit -m "add deployment configuration"
git push origin main
```

Watch: **GitHub → Actions → Deploy Backend**

The workflow builds the Docker image, pushes to ECR, and does a rolling ECS deploy.

---

## 17. Build & Distribute Desktop App

### Option A — Manual dispatch (quickest for team testing)

1. **GitHub → Actions → Build Desktop App → Run workflow**
2. Enter the backend URL: `https://api.flax-assistant.com`
3. Wait ~5 min — the DMG appears in **Artifacts**
4. Share the download link with your team

### Option B — Tag-based release (recommended once stable)

```bash
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions builds the DMG and attaches it to the GitHub Release automatically. Teammates download from **Releases**.

### Installing the DMG

1. Download `Flax Assistant-*.dmg`
2. Open it, drag **Flax Assistant** to Applications
3. Launch — the app connects to the deployed backend automatically

> **Note:** macOS may show "unidentified developer" for unsigned builds. To open: right-click → Open → Open anyway. For wider distribution, code-signing via Apple Developer account is needed.

---

## Verification Checklist

```
[ ] https://api.flax-assistant.com/health returns {"status":"ok","service":"flax-assistant","env":"production"}
[ ] ECS task is RUNNING in flax-assistant-cluster
[ ] CloudWatch logs appear in /ecs/flax-assistant
[ ] GitHub Actions deploys automatically on push to main
[ ] Desktop DMG builds and opens successfully
[ ] Desktop app connects to backend (chat responds)
```

---

## Cost Estimate (approximate, us-east-1)

| Resource | Spec | Monthly |
|----------|------|---------|
| ECS Fargate | 0.5 vCPU, 1GB × 1 task | ~$15 |
| Application Load Balancer | 1 ALB | ~$18 |
| ECR storage | ~0.5GB | ~$0.50 |
| CloudWatch Logs | ~1GB/month | ~$0.50 |
| Secrets Manager | 1 secret | ~$0.40 |
| Supabase | Free tier (500MB, 2 cores) | $0 |
| **Total** | | **~$34/month** |

---

## Common Issues

**ECS task keeps restarting:**
- Check CloudWatch logs: `/ecs/flax-assistant`
- Verify Secrets Manager ARN in task definition has the exact random suffix

**ECS task can't connect to Supabase:**
- Confirm `DATABASE_URL` in Secrets Manager uses `postgresql+asyncpg://` scheme
- Use the **Session mode** pooler URL (not the direct host — direct requires IPv6 from Fargate)
- Check CloudWatch logs for `asyncpg` connection errors

**Desktop shows "connection refused":**
- Verify `BACKEND_URL` secret is set correctly before building the DMG
- Check that port 8747 on the ALB target group is routing correctly
