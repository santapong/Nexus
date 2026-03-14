.PHONY: setup up down logs migrate seed test-unit test-behavior test-e2e test-e2e-phase2 stress-test-phase2 test-all kafka-test kafka-topics shell-db shell-redis lint typecheck build-prod up-prod

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

test-all: test-unit test-behavior test-e2e

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

build-prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml build

up-prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
