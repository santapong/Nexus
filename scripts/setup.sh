#!/usr/bin/env bash
set -euo pipefail

# NEXUS — Full Setup & Start Script
# Usage: bash scripts/setup.sh
# Idempotent — safe to run multiple times.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

# ── Step 1: Check prerequisites ──────────────────────────────────────────────

info "Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    fail "Docker is not installed. Install it from https://docs.docker.com/get-docker/"
fi

if ! docker compose version &>/dev/null; then
    fail "Docker Compose (v2) is not available. Update Docker or install the compose plugin."
fi

if ! docker info &>/dev/null 2>&1; then
    fail "Docker daemon is not running. Start Docker and try again."
fi

ok "Docker and Docker Compose are available."

# ── Step 2: Create .env if missing ───────────────────────────────────────────

if [ ! -f .env ]; then
    info "Creating .env from .env.example..."
    cp .env.example .env
    warn ".env created. Edit it to add your API keys:"
    warn "  ANTHROPIC_API_KEY=sk-ant-..."
    warn "  GOOGLE_API_KEY=..."
    echo ""
else
    ok ".env already exists — skipping."
fi

# ── Step 3: Build containers ─────────────────────────────────────────────────

info "Building Docker containers..."
docker compose build --quiet
ok "Containers built."

# ── Step 4: Start services ───────────────────────────────────────────────────

info "Starting services (postgres, redis, kafka, backend, frontend)..."
docker compose up -d
ok "Services starting."

# ── Step 5: Wait for health checks ──────────────────────────────────────────

wait_for_service() {
    local service="$1"
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        status=$(docker compose ps --format json "$service" 2>/dev/null | grep -o '"Health":"[^"]*"' | head -1 || true)
        if echo "$status" | grep -q "healthy"; then
            ok "$service is healthy."
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    fail "$service did not become healthy after $((max_attempts * 2))s. Check: docker compose logs $service"
}

info "Waiting for services to be healthy..."
wait_for_service "postgres"
wait_for_service "redis"
wait_for_service "kafka"

# Give backend a moment to start after dependencies are healthy
info "Waiting for backend to initialize..."
sleep 5

# Check if backend is responding
backend_attempts=0
while [ $backend_attempts -lt 15 ]; do
    if docker compose exec -T backend curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        ok "Backend is responding."
        break
    fi
    backend_attempts=$((backend_attempts + 1))
    sleep 2
done

if [ $backend_attempts -ge 15 ]; then
    warn "Backend health check not reachable (may still be starting). Continuing..."
fi

# ── Step 6: Run database migrations ──────────────────────────────────────────

info "Running database migrations..."
docker compose exec -T backend alembic upgrade head
ok "Migrations applied."

# ── Step 7: Seed database ────────────────────────────────────────────────────

info "Seeding database..."
if docker compose exec -T backend python -m nexus.db.seed 2>/dev/null; then
    ok "Database seeded."
else
    warn "Seed script failed or not yet implemented — skipping."
fi

# ── Step 8: Print status ─────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  NEXUS is running!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  API:       ${CYAN}http://localhost:8000${NC}"
echo -e "  Health:    ${CYAN}http://localhost:8000/health${NC}"
echo -e "  Frontend:  ${CYAN}http://localhost:5173${NC}"
echo ""
echo -e "  Useful commands:"
echo -e "    make logs         — Stream all service logs"
echo -e "    make down         — Stop all services"
echo -e "    make test-unit    — Run unit tests"
echo -e "    make shell-db     — PostgreSQL shell"
echo -e "    make shell-redis  — Redis shell"
echo -e "    make kafka-topics — List Kafka topics"
echo ""
