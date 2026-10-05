# Deploying FinSight

FinSight runs three ways. Pick one:

| Way | Command | Use it for |
|---|---|---|
| **Local dev (Windows)** | `powershell -ExecutionPolicy Bypass -File .\start_app.ps1` | Day-to-day coding, hot reload |
| **Local dev (Docker)** | `docker compose up` | Same, everything in containers |
| **Production** | `docker compose -f docker-compose.prod.yml up -d --build` | AWS server - or a production-like test on your laptop |

The production stack is 6 containers on one machine:

```
Internet ──► web (Caddy: HTTPS + login + React app) ──/api/*──► backend (FastAPI)
                                                                   │
                         celery_worker, celery_beat ──► redis, db (Postgres/TimescaleDB)
```

Only `web` is reachable from outside (ports 80/443). Postgres, Redis and the API are
on Docker's private network.

Files: `docker-compose.prod.yml`, `deploy/` (Dockerfiles, Caddyfile, password helper),
`.env.production.example`.

---

## Try production locally first (optional, 10 min)

On your laptop with Docker Desktop running, from the repo root:

```powershell
copy .env .env.backup                          # keep your dev .env safe
# add these lines to .env:
#   POSTGRES_PASSWORD=localtest123
#   AUTH=off
docker compose -f docker-compose.prod.yml up -d --build
```

Open http://localhost. Stop with `docker compose -f docker-compose.prod.yml down`.
(Stop the dev stack first if it is using port 80/5432 - the prod stack doesn't publish 5432, so usually no clash.)

---

## Deploy to AWS EC2 (first time, ~1-2 hours)

### 1. AWS account
1. Sign up at https://aws.amazon.com - choose the **Free plan** (not Paid). On the Free plan
   you **cannot be charged**; usage stops when the credits ($100 + up to $100 more) or the
   6 months run out.
2. Top-right region selector -> **Asia Pacific (Mumbai) ap-south-1**.

### 2. Launch the server
EC2 -> **Launch instance**:

| Setting | Value |
|---|---|
| Name | `finsight` |
| OS image | **Ubuntu Server 24.04 LTS** (x86_64) |
| Instance type | **m7i-flex.large** (2 vCPU, 8 GB) - free-plan eligible, paid from credits. `c7i-flex.large` (4 GB) is a bit cheaper and should also work. |
| Key pair | Create new -> name `finsight`, type RSA, format **.pem** -> it downloads. Keep it safe. |
| Network | Allow **SSH** from **My IP**; tick **Allow HTTPS** and **Allow HTTP** from the internet |
| Storage | **30 GB gp3** (the backend image is ~4.5 GB) |

Launch, then copy the instance's **Public IPv4 address** (e.g. `13.233.10.20`).

> Tip: EC2 -> Elastic IPs -> Allocate -> Associate with `finsight`. Then the IP (and your
> URL) stays the same when you stop/start the server.

### 3. Connect from your laptop (PowerShell)
```powershell
# one time: let only you read the key (ssh refuses keys others can read)
icacls $HOME\Downloads\finsight.pem /inheritance:r /grant:r "$($env:USERNAME):R"

ssh -i $HOME\Downloads\finsight.pem ubuntu@13.233.10.20
```
Type `yes` the first time. You are now on the server (prompt `ubuntu@ip-...`).

### 4. Prepare the server (copy-paste, on the server)
```bash
# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu

# 4 GB swap = safety net if memory spikes
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

exit   # log out and ssh back in so the docker group applies
```

### 5. Get the code onto the server
Commit and push your branch from your laptop first. Then on the server:
```bash
git clone -b finsight-v2 https://github.com/harshmasalge/finance_agent.git
cd finance_agent
```
(Private repo? Use a GitHub Personal Access Token as the password: GitHub -> Settings ->
Developer settings -> Fine-grained tokens -> read-only access to this repo.)

### 6. Copy the knowledge-base data (from your laptop, PowerShell)
`data/` is not in git (~220 MB: Chroma index + corpus).
```powershell
cd C:\Users\harsh\Projects\finance_agent
scp -i $HOME\Downloads\finsight.pem -r data ubuntu@13.233.10.20:~/finance_agent/
```

### 7. Configure (on the server)
```bash
cd ~/finance_agent
cp .env.production.example .env
openssl rand -hex 24                     # -> use as POSTGRES_PASSWORD
openssl rand -hex 32                     # -> use as SESSION_SECRET
sh deploy/make-password.sh 'pick-a-login-password'   # prints BASIC_AUTH_HASH='...'
nano .env
```
Fill in:
- `SITE_ADDRESS=13.233.10.20.sslip.io` (your IP + `.sslip.io` - a free domain that points to
  your IP, so Caddy can get a real HTTPS certificate)
- `BASIC_AUTH_HASH='...'` (paste the whole line from the helper, **with** the single quotes)
- `POSTGRES_PASSWORD`, `SESSION_SECRET`
- Your LLM keys (`GROQ_API_KEYS`, etc.) and `NEWSAPI_KEYS` - same values as your local `.env`

Save: `Ctrl+O`, `Enter`, `Ctrl+X`.

### 8. Start
```bash
docker compose -f docker-compose.prod.yml up -d --build    # first build ~10 min
docker compose -f docker-compose.prod.yml ps               # all "Up", backend "healthy"
```
Open **https://13.233.10.20.sslip.io**, log in as `finsight` + your password. Done!

---

## Everyday operations (on the server, in ~/finance_agent)

| Task | Command |
|---|---|
| Deploy new code | `git pull && docker compose -f docker-compose.prod.yml up -d --build` |
| Logs (all / one) | `docker compose -f docker-compose.prod.yml logs -f --tail 100` / `... logs -f backend` |
| Restart | `docker compose -f docker-compose.prod.yml restart` |
| Stop / start app | `docker compose -f docker-compose.prod.yml down` / `... up -d` (data is kept in volumes) |
| Disk / memory | `df -h`, `free -h`, `docker stats` |
| DB shell | `docker compose -f docker-compose.prod.yml exec db psql -U finsight -d finsight` |

**Save credits:** stop the EC2 instance in the AWS console when you're not demoing - you
pay only for storage while it's stopped. Everything starts again on boot
(`restart: unless-stopped`). Without an Elastic IP the IP changes: update `SITE_ADDRESS`
and run `up -d`.

Check credits: AWS console -> Billing and Cost Management -> Credits.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Browser can't connect | EC2 security group must allow 80 and 443 from `0.0.0.0/0` |
| HTTPS certificate error | `logs web`. Port 80 must be open and `SITE_ADDRESS` must match the IP exactly |
| Login keeps failing | Re-run `make-password.sh`; keep the single quotes around the hash in `.env`; `up -d` |
| `web` restarting, "illegal base64" | `BASIC_AUTH_HASH` empty -> set it, or `AUTH=off` |
| Backend restarting | `logs backend` - usually a missing/wrong value in `.env` |
| Answers fail with 401/402/429 | LLM key invalid / out of credits / rate limited - check provider keys |
| Server very slow / killed processes | `free -h`; lower `CELERY_CONCURRENCY=1`, or a bigger instance |
