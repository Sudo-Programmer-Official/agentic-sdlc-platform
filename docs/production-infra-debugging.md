Love this move. 🔥
If you don’t document infra incidents, you debug the same thing 6 months later at 2AM.

Let’s create a clean, reusable infra runbook for Prompt2PR.

You can drop this straight into Notion / README / /docs/infra/alb-setup.md.

⸻

📘 Prompt2PR – API HTTPS + ALB Setup Documentation

🎯 Goal

Expose FastAPI backend securely at:

https://api.prompt2pr.com

Architecture:

Browser
   ↓
Cloudflare (DNS only for API)
   ↓
AWS ALB (HTTPS:443, ACM cert)
   ↓
Target Group
   ↓
FastAPI (Uvicorn)


⸻

🏗 Final Working Architecture

Domain
	•	www.prompt2pr.com → frontend
	•	api.prompt2pr.com → backend API

DNS

Cloudflare:

Type: CNAME
Name: api
Target: agentic-api-alb-457386848.us-east-1.elb.amazonaws.com
Proxy: DNS only (grey cloud)


⸻

🔐 SSL Setup

ACM Certificate

Issued for:
	•	api.prompt2pr.com
	•	prompt2pr.com
	•	*.prompt2pr.com

Region:

us-east-1

Status:

Issued


⸻

⚙️ ALB Configuration

Load Balancer

Name:

agentic-api-alb

Type:

Application Load Balancer

Scheme:

Internet-facing


⸻

🎧 Listeners

HTTP:80
	•	Forward → agentic-api-tg

HTTPS:443
	•	Certificate: api.prompt2pr.com
	•	Forward → agentic-api-tg
	•	Security policy: TLS 1.2+ / 1.3

⸻

🎯 Target Group

Name:

agentic-api-tg

Health check path:

/health

Health check must return:

{"status":"ok"}


⸻

🔥 Critical Issue We Debugged

❌ Root Cause

ALB was attached to wrong security group.

It was using:

default (sg-0861a5408da128071)

But we opened port 443 on:

agentic-alb (sg-09b741bfd9da5fa9b)

Result:
	•	DNS resolved
	•	HTTPS listener existed
	•	Certificate valid
	•	But port 443 blocked
	•	Curl hung at TCP layer

Symptom:

Trying 44.x.x.x:443...
(then nothing)


⸻

✅ Final Fix

Either:

Option A (Clean)

Attach correct SG to ALB.

OR

Option B (Quick Fix)

Open port 443 on the SG actually attached to ALB.

Inbound rule required:

Type: HTTPS
Port: 443
Source: 0.0.0.0/0


⸻

🧪 Verification Commands

DNS Check

dig api.prompt2pr.com +short

HTTPS Check

curl -v https://api.prompt2pr.com/health

Expected:

HTTP/2 200
{"status":"ok"}

CORS Preflight Check

curl -i -X OPTIONS https://api.prompt2pr.com/api/v1/projects \
  -H "Origin: https://www.prompt2pr.com" \
  -H "Access-Control-Request-Method: POST"

Expected:

HTTP/2 200
access-control-allow-origin: https://www.prompt2pr.com


⸻

🧠 Debugging Decision Tree (Future Reference)

If HTTPS hangs:
	1.	Check DNS
	2.	Check ALB security group
	3.	Confirm 443 open
	4.	Confirm ALB attached to correct SG
	5.	Confirm HTTPS listener exists
	6.	Confirm certificate attached
	7.	Confirm target group healthy

If 405:
	•	Check wrong ALB
	•	Check nginx upstream
	•	Check listener forwarding

If CORS fails:
	•	Check OPTIONS response
	•	Check FastAPI CORSMiddleware
	•	Check access-control-allow-origin

⸻

🌐 Cloudflare Settings

For API:

Proxy: DNS only (recommended)

SSL Mode:

Full (Strict)

Never use:

Flexible


⸻

🧩 Lessons Learned
	1.	Always verify which security group ALB is actually using.
	2.	HTTPS hang = network-level block.
	3.	If TLS handshake never completes → check SG first.
	4.	Do not mix multiple ALBs for same domain unless intentional.
	5.	Always test ALB directly before testing domain.

⸻

🚀 Current Production State

Fully functional:

https://api.prompt2pr.com

Working:
	•	HTTPS
	•	TLS 1.3
	•	HTTP/2
	•	CORS
	•	Preflight
	•	Health checks

⸻

If you want, I can now:
	•	Convert this into a clean infra.md
	•	Create a diagram (architecture visual)
	•	Generate a production hardening checklist
	•	Or create a “New API Domain Setup SOP” template for future projects

This was a solid infrastructure debugging session.
Now you have a clean edge stack. 💪