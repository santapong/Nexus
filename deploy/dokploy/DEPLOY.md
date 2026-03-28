# NEXUS — Dokploy Multi-Platform Deployment Guide

Deploy NEXUS on **AWS**, **GCP**, or **Raspberry Pi** using [Dokploy](https://dokploy.com) — an open-source, self-hosted PaaS alternative to Vercel/Netlify.

---

## Architecture Overview

```
                    ┌──────────────────────┐
                    │   Dokploy Dashboard   │
                    │   (manages deploys)   │
                    └──────────┬───────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                     │
    ┌─────▼─────┐       ┌─────▼─────┐       ┌──────▼──────┐
    │  AWS EC2   │       │  GCP VM   │       │ Raspberry Pi │
    │  (amd64)   │       │  (amd64)  │       │   (arm64)    │
    └─────┬─────┘       └─────┬─────┘       └──────┬──────┘
          │                    │                     │
    docker-compose.dokploy.yml (same file, different .env)
```

All platforms use the **same compose file** (`docker-compose.dokploy.yml`). Platform differences are handled through environment variables and resource limits.

---

## Quick Start

### 1. Install Dokploy on your server

```bash
# On your target server (AWS, GCP, or Pi):
curl -sSL https://dokploy.com/install.sh | sh
```

### 2. Run the setup script

```bash
# Clone the repo
git clone https://github.com/santapong/nexus.git
cd nexus

# Run platform-specific setup
bash deploy/dokploy/setup.sh aws          # For AWS
bash deploy/dokploy/setup.sh gcp          # For GCP
bash deploy/dokploy/setup.sh raspberrypi  # For Raspberry Pi
```

### 3. Edit your .env

```bash
# Add your LLM API keys
nano .env
```

### 4. Deploy via Dokploy

1. Open Dokploy dashboard (https://your-server:3000)
2. Create a new **Compose** project
3. Set the compose file path to `docker-compose.dokploy.yml`
4. Copy your `.env` variables into Dokploy's Environment tab
5. Click **Deploy**

---

## Platform-Specific Details

### AWS EC2

| Setting | Recommendation |
|---------|---------------|
| Instance type | `t3.medium` (2 vCPU, 4GB) minimum |
| Storage | 30GB+ EBS gp3 |
| Security group | Open ports 80, 443, 3000 (Dokploy) |
| OS | Ubuntu 22.04 LTS or Amazon Linux 2023 |

**Tips:**
- Use an Elastic IP for a stable address
- Set up an Application Load Balancer for SSL termination
- For production, consider RDS for PostgreSQL and ElastiCache for Redis

### GCP Compute Engine

| Setting | Recommendation |
|---------|---------------|
| Machine type | `e2-medium` (2 vCPU, 4GB) minimum |
| Storage | 30GB+ Balanced PD |
| Firewall | Allow HTTP (80), HTTPS (443), Dokploy (3000) |
| OS | Ubuntu 22.04 LTS |

**Tips:**
- Reserve a static external IP
- Use Cloud SQL for managed PostgreSQL in production
- Use Memorystore for managed Redis

### Raspberry Pi

| Setting | Recommendation |
|---------|---------------|
| Model | Pi 4 (4GB+) or Pi 5 |
| Storage | 64GB+ high-endurance microSD or USB SSD |
| OS | Raspberry Pi OS 64-bit (Bookworm) |
| Cooling | Active cooling recommended under load |

**Tips:**
- Use a USB SSD instead of microSD for better I/O and longevity
- Default config uses lighter models (Haiku/Flash) to reduce API costs
- Temporal is disabled by default — enable only on 8GB+ Pi
- Add 2GB+ swap for stability (setup script checks this)
- Consider running Ollama locally for fully offline operation

---

## Manual Deploy (without Dokploy)

```bash
# Start all services
docker compose -f docker-compose.dokploy.yml up -d

# With Temporal (optional)
docker compose -f docker-compose.dokploy.yml --profile temporal up -d

# Run database migrations
docker compose -f docker-compose.dokploy.yml exec backend alembic upgrade head

# Seed initial data
docker compose -f docker-compose.dokploy.yml exec backend python -m nexus.db.seed

# Check health
curl http://localhost:8000/health

# View logs
docker compose -f docker-compose.dokploy.yml logs -f
```

---

## Environment Variables Reference

### Required

| Variable | Description |
|----------|-------------|
| `POSTGRES_PASSWORD` | Database password |
| `JWT_SECRET_KEY` | JWT signing secret (generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`) |

### LLM Keys (at least one required)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | For Claude models |
| `GOOGLE_API_KEY` | For Gemini models |
| `OPENAI_API_KEY` | For OpenAI models |
| `OLLAMA_BASE_URL` | For local Ollama (e.g., `http://host.docker.internal:11434/v1`) |

### Resource Limits

| Variable | Default | Pi Default | Description |
|----------|---------|------------|-------------|
| `POSTGRES_MEMORY_LIMIT` | 1g | 512m | PostgreSQL memory limit |
| `REDIS_MEMORY_LIMIT` | 512m | 256m | Redis container limit |
| `KAFKA_MEMORY_LIMIT` | 1g | 512m | Kafka container limit |
| `KAFKA_HEAP_OPTS` | -Xmx512m | -Xmx256m | Kafka JVM heap |
| `BACKEND_MEMORY_LIMIT` | 1g | 512m | Backend memory limit |
| `FRONTEND_MEMORY_LIMIT` | 256m | 128m | Frontend (nginx) limit |

---

## Updating

### Via Dokploy
Click **Redeploy** in the Dokploy dashboard. It will pull the latest images.

### Manually
```bash
docker compose -f docker-compose.dokploy.yml pull
docker compose -f docker-compose.dokploy.yml up -d
docker compose -f docker-compose.dokploy.yml exec backend alembic upgrade head
```

---

## Troubleshooting

### Kafka fails to start on Raspberry Pi
Kafka needs `vm.max_map_count >= 262144`:
```bash
sudo sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf
```

### Out of memory on Raspberry Pi
- Reduce `KAFKA_HEAP_OPTS` to `-Xmx128m -Xms64m`
- Add swap: `sudo fallocate -l 2G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`
- Disable Temporal (don't use `--profile temporal`)

### Health check failing
```bash
# Check backend logs
docker compose -f docker-compose.dokploy.yml logs backend

# Check if services are healthy
docker compose -f docker-compose.dokploy.yml ps
```

### SSL/HTTPS
Dokploy handles SSL via its built-in Traefik proxy. Configure your domain in the Dokploy dashboard and it will auto-provision Let's Encrypt certificates.
