Let’s go 🔥
You just deployed your first full ECS + ALB production stack.

Below is a clean, future-dev-ready documentation of everything you did — structured, reusable, and production-grade.

You can copy this into your repo as:

/docs/deployment/aws-ecs-fargate.md


⸻

🚀 Agentic SDLC – AWS ECS Fargate Deployment Guide

🎯 Goal

Deploy the agentic-sdlc-web frontend container to AWS using:
	•	Amazon ECR (container registry)
	•	Amazon ECS (Fargate)
	•	Application Load Balancer (ALB)
	•	Target Group
	•	IAM Roles
	•	VPC networking

Final Result:
App accessible via ALB public DNS.

⸻

🧱 Phase 1 – Container Preparation

1️⃣ Problem: ARM vs AMD64 Mismatch

Error encountered:

CannotPullContainerError:
image Manifest does not contain descriptor matching platform 'linux/amd64'

Cause
	•	Built Docker image on Apple Silicon (ARM64)
	•	ECS Fargate default runtime = linux/amd64

Fix

Rebuild image for amd64:

docker buildx build \
  --platform linux/amd64 \
  --load \
  -t agentic-sdlc-web:latest \
  -f apps/web/Dockerfile \
  --build-arg VITE_API_BASE="/api/v1" \
  apps/web

Then push to ECR:

docker tag agentic-sdlc-web:latest \
495849799931.dkr.ecr.us-east-1.amazonaws.com/agentic-sdlc-web:latest

docker push \
495849799931.dkr.ecr.us-east-1.amazonaws.com/agentic-sdlc-web:latest


⸻

🧱 Phase 2 – ECR Setup
	•	Created ECR repository:

agentic-sdlc-web


	•	Pushed latest image tag

⸻

🧱 Phase 3 – IAM Setup

🚨 First Issue

Error:

ECS was unable to assume role ecsTaskExecutionRole

Cause

Wrong IAM role type selected:
	•	❌ Elastic Container Service
	•	❌ EC2 Container Service Role

Correct Role Type

Create role using:

Task Execution Role for Elastic Container Service

Attach policy:

AmazonECSTaskExecutionRolePolicy

Trust relationship must be:

{
  "Effect": "Allow",
  "Principal": {
    "Service": "ecs-tasks.amazonaws.com"
  },
  "Action": "sts:AssumeRole"
}

Role name:

ecsTaskExecutionRole


⸻

🧱 Phase 4 – Task Definition

Created Task Definition:

agentic-web-task

Settings
	•	Launch type: Fargate
	•	OS/Arch: Linux / X86_64
	•	CPU: 0.25 vCPU
	•	Memory: 0.5 GB
	•	Execution role: ecsTaskExecutionRole

Container Config

Name:

web

Image:

495849799931.dkr.ecr.us-east-1.amazonaws.com/agentic-sdlc-web:latest

Port:

80

Important:
App must listen on:

0.0.0.0

Not localhost.

⸻

🧱 Phase 5 – VPC & Security Groups

Security Groups

ALB Security Group

Inbound:

HTTP 80 → 0.0.0.0/0

ECS Service Security Group

Inbound:

HTTP 80 → Source = ALB Security Group

Outbound:

All traffic → 0.0.0.0/0


⸻

🧱 Phase 6 – Application Load Balancer

Created:

agentic-sdlc-alb

Type:

Internet-facing

Listener:

HTTP : 80


⸻

🧱 Phase 7 – Target Group

Created:

tg-agentic-web

Type:

IP

Port:

80

Health check path:

/


⸻

🧱 Phase 8 – ECS Service

Created service:

agentic-web-service

Launch type:

Fargate

Desired tasks:

1

Load balancer:
	•	Existing ALB
	•	Listener: 80
	•	Target group: tg-agentic-web

⸻

🧱 Phase 9 – Debugging Timeline

❌ IAM Assume Role Error

Fixed by:
	•	Creating correct ECS Task Execution role

⸻

❌ Image Platform Error

Fixed by:
	•	Rebuilding Docker image with –platform linux/amd64

⸻

❌ No Targets in Target Group

Cause:
	•	Task failing before registering

Fixed automatically after above issues resolved.

⸻

✅ Final State

ECS Service:

1 Running

Target Group:

Healthy

Application accessible at:

http://agentic-sdlc-alb-xxxx.us-east-1.elb.amazonaws.com


⸻

🧠 Architecture Summary

Internet
   ↓
Application Load Balancer (Public)
   ↓
Target Group (IP mode)
   ↓
ECS Fargate Task
   ↓
Docker Container


⸻

🧠 Production Best Practices (Next Steps)

1️⃣ Add HTTPS
	•	Create ACM certificate
	•	Add HTTPS listener (443)
	•	Redirect 80 → 443

2️⃣ Add Auto Scaling

Service Auto Scaling:
	•	CPU based scaling
	•	Min: 1
	•	Max: 3

3️⃣ Add Health Endpoint

Instead of /, use:

/health

4️⃣ Add CI/CD

Future:
	•	GitHub Actions
	•	Auto build + push
	•	Auto deploy ECS

⸻

🏆 What Was Achieved

You:
	•	Fixed IAM trust relationships
	•	Fixed container architecture mismatch
	•	Debugged ECS deployment loops
	•	Properly configured ALB + Target Group
	•	Successfully deployed production container infra

This is real DevOps.

⸻

If you want, next we can:
	•	Turn this into Terraform
	•	Convert to CloudFormation
	•	Or create a reusable ECS deployment template

You just leveled up hard today 🔥