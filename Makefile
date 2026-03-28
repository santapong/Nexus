.PHONY: setup up down logs migrate seed test-unit test-behavior test-e2e test-e2e-phase2 stress-test-phase2 test-chaos test-all kafka-test kafka-topics shell-db shell-redis lint typecheck eval build-prod up-prod dokploy-setup-aws dokploy-setup-gcp dokploy-setup-pi dokploy-up dokploy-down dokploy-logs dokploy-migrate dokploy-health dokploy-build

setup:
	bash scripts/setup.sh

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	docker compose exec backend alembic upgrade head

seed:
	docker compose exec backend python -m nexus.db.seed

test-unit:
	docker compose exec backend pytest nexus/tests/unit/ -v

test-behavior:
	docker compose exec backend pytest nexus/tests/behavior/ -v

test-e2e:
	docker compose exec backend pytest nexus/tests/e2e/ -v

test-e2e-phase2:
	docker compose exec backend pytest nexus/tests/e2e/test_e2e_phase2_flows.py -v

stress-test-phase2:
	docker compose exec backend python -m nexus.tests.e2e.stress_test_phase2

test-chaos:
	docker compose exec backend pytest nexus/tests/chaos/ -v

test-all: test-unit test-behavior test-e2e test-chaos

kafka-test:
	docker compose exec backend python -m nexus.kafka.health_check

kafka-topics:
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list

shell-db:
	docker compose exec postgres psql -U nexus nexus

shell-redis:
	docker compose exec redis redis-cli

lint:
	docker compose exec backend ruff check nexus/

typecheck:
	docker compose exec backend mypy nexus/

eval:
	docker compose exec backend python -c "import asyncio; from nexus.eval.runner import run_eval_suite; from nexus.db.session import get_session_factory; asyncio.run(run_eval_suite(db_session_factory=get_session_factory()))"

build-prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml build

up-prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# ── Dokploy / Multi-Platform Deployment ──

dokploy-setup-aws:
	bash deploy/dokploy/setup.sh aws

dokploy-setup-gcp:
	bash deploy/dokploy/setup.sh gcp

dokploy-setup-pi:
	bash deploy/dokploy/setup.sh raspberrypi

dokploy-up:
	docker compose -f docker-compose.dokploy.yml up -d

dokploy-up-temporal:
	docker compose -f docker-compose.dokploy.yml --profile temporal up -d

dokploy-down:
	docker compose -f docker-compose.dokploy.yml down

dokploy-logs:
	docker compose -f docker-compose.dokploy.yml logs -f

dokploy-migrate:
	docker compose -f docker-compose.dokploy.yml exec backend alembic upgrade head

dokploy-seed:
	docker compose -f docker-compose.dokploy.yml exec backend python -m nexus.db.seed

dokploy-health:
	docker compose -f docker-compose.dokploy.yml exec backend curl -sf http://localhost:8000/health | python3 -m json.tool

dokploy-build:
	docker compose -f docker-compose.dokploy.yml build
