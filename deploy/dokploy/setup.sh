#!/usr/bin/env bash
# NEXUS — Dokploy Setup Helper
# Run this on your target server BEFORE deploying with Dokploy
#
# Usage: bash setup.sh [aws|gcp|raspberrypi]

set -euo pipefail

PLATFORM="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[NEXUS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# ── Check prerequisites ──
check_prereqs() {
    log "Checking prerequisites..."

    if ! command -v docker &>/dev/null; then
        err "Docker is not installed. Install it first:"
        echo "  curl -fsSL https://get.docker.com | sh"
        exit 1
    fi

    if ! docker compose version &>/dev/null; then
        err "Docker Compose V2 is not available."
        echo "  Update Docker or install docker-compose-plugin"
        exit 1
    fi

    log "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"
    log "Docker Compose $(docker compose version --short)"

    # Check architecture
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64|amd64) log "Architecture: amd64" ;;
        aarch64|arm64) log "Architecture: arm64" ;;
        armv7l) warn "armv7l detected — some images may not be available. Use arm64 (64-bit OS) if possible." ;;
        *) warn "Unknown architecture: $ARCH" ;;
    esac

    # Check available memory
    TOTAL_MEM_MB=$(free -m | awk '/^Mem:/{print $2}')
    log "Total RAM: ${TOTAL_MEM_MB}MB"
    if [ "$TOTAL_MEM_MB" -lt 3500 ]; then
        warn "Less than 4GB RAM detected. Use Raspberry Pi config with reduced limits."
        warn "Temporal will be disabled. Kafka heap reduced."
    fi
}

# ── Generate .env from platform template ──
generate_env() {
    local template="$SCRIPT_DIR/.env.${PLATFORM}"

    if [ ! -f "$template" ]; then
        err "Unknown platform: $PLATFORM"
        echo "Available: aws, gcp, raspberrypi"
        exit 1
    fi

    if [ -f "$PROJECT_ROOT/.env" ]; then
        warn ".env already exists. Backing up to .env.backup"
        cp "$PROJECT_ROOT/.env" "$PROJECT_ROOT/.env.backup"
    fi

    cp "$template" "$PROJECT_ROOT/.env"

    # Generate JWT secret
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32)
    sed -i "s|JWT_SECRET_KEY=CHANGE_ME_generate_a_strong_secret|JWT_SECRET_KEY=$JWT_SECRET|" "$PROJECT_ROOT/.env"

    # Generate DB password
    DB_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))" 2>/dev/null || openssl rand -base64 24)
    sed -i "s|POSTGRES_PASSWORD=CHANGE_ME_use_a_strong_password|POSTGRES_PASSWORD=$DB_PASS|" "$PROJECT_ROOT/.env"

    # Generate Redis password
    REDIS_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))" 2>/dev/null || openssl rand -base64 16)
    sed -i "s|REDIS_PASSWORD=CHANGE_ME_redis_password|REDIS_PASSWORD=$REDIS_PASS|" "$PROJECT_ROOT/.env"

    log "Generated .env from $PLATFORM template"
    warn "Edit .env to add your LLM API keys before deploying!"
}

# ── Platform-specific setup ──
setup_aws() {
    log "AWS-specific setup..."

    # Increase vm.max_map_count for Kafka
    if [ "$(cat /proc/sys/vm/max_map_count)" -lt 262144 ]; then
        warn "Increasing vm.max_map_count for Kafka (requires sudo)"
        sudo sysctl -w vm.max_map_count=262144
        echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf >/dev/null
    fi

    log "AWS setup complete."
}

setup_gcp() {
    log "GCP-specific setup..."

    # Same Kafka requirement
    if [ "$(cat /proc/sys/vm/max_map_count)" -lt 262144 ]; then
        warn "Increasing vm.max_map_count for Kafka (requires sudo)"
        sudo sysctl -w vm.max_map_count=262144
        echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf >/dev/null
    fi

    log "GCP setup complete."
}

setup_raspberrypi() {
    log "Raspberry Pi setup..."

    # Enable cgroups (required for Docker resource limits on Pi)
    if ! grep -q "cgroup_enable=memory" /boot/firmware/cmdline.txt 2>/dev/null && \
       ! grep -q "cgroup_enable=memory" /boot/cmdline.txt 2>/dev/null; then
        warn "Docker resource limits may not work without cgroup_memory=1"
        warn "Add to /boot/firmware/cmdline.txt or /boot/cmdline.txt:"
        echo "  cgroup_enable=cpuset cgroup_enable=memory cgroup_memory=1"
        echo "Then reboot."
    fi

    # Increase vm.max_map_count for Kafka
    if [ "$(cat /proc/sys/vm/max_map_count)" -lt 262144 ]; then
        warn "Increasing vm.max_map_count for Kafka (requires sudo)"
        sudo sysctl -w vm.max_map_count=262144
        echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf >/dev/null
    fi

    # Swap recommendation
    SWAP_MB=$(free -m | awk '/^Swap:/{print $2}')
    if [ "$SWAP_MB" -lt 2000 ]; then
        warn "Swap is ${SWAP_MB}MB — recommend at least 2GB for stability"
        echo "  sudo fallocate -l 2G /swapfile"
        echo "  sudo chmod 600 /swapfile"
        echo "  sudo mkswap /swapfile"
        echo "  sudo swapon /swapfile"
        echo "  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab"
    fi

    log "Raspberry Pi setup complete."
}

# ── Validate deployment ──
validate() {
    log "Validating docker-compose.dokploy.yml..."
    cd "$PROJECT_ROOT"
    docker compose -f docker-compose.dokploy.yml config --quiet 2>/dev/null && \
        log "Compose file is valid." || \
        err "Compose file has errors!"
}

# ── Main ──
main() {
    echo ""
    echo "╔══════════════════════════════════════════╗"
    echo "║    NEXUS — Dokploy Deployment Setup      ║"
    echo "╚══════════════════════════════════════════╝"
    echo ""

    check_prereqs

    if [ -z "$PLATFORM" ]; then
        echo ""
        echo "Usage: bash setup.sh [aws|gcp|raspberrypi]"
        echo ""
        echo "This script will:"
        echo "  1. Check prerequisites (Docker, RAM, architecture)"
        echo "  2. Generate .env from platform template"
        echo "  3. Apply platform-specific OS tuning"
        echo "  4. Validate the compose file"
        echo ""
        exit 0
    fi

    generate_env

    case "$PLATFORM" in
        aws)         setup_aws ;;
        gcp)         setup_gcp ;;
        raspberrypi) setup_raspberrypi ;;
        *)           err "Unknown platform: $PLATFORM"; exit 1 ;;
    esac

    validate

    echo ""
    log "Setup complete! Next steps:"
    echo ""
    echo "  1. Edit .env to add your LLM API keys"
    echo "  2. Deploy with Dokploy:"
    echo "     - Create a 'Compose' project in Dokploy dashboard"
    echo "     - Set compose path: docker-compose.dokploy.yml"
    echo "     - Paste your .env variables in Dokploy environment tab"
    echo "     - Click Deploy"
    echo ""
    echo "  Or deploy manually:"
    echo "     docker compose -f docker-compose.dokploy.yml up -d"
    echo ""
    echo "  Enable Temporal (optional):"
    echo "     docker compose -f docker-compose.dokploy.yml --profile temporal up -d"
    echo ""
    echo "  Run database migrations:"
    echo "     docker compose -f docker-compose.dokploy.yml exec backend alembic upgrade head"
    echo ""
}

main "$@"
