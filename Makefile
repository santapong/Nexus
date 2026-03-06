.PHONY: up down logs migrate seed test-unit test-behavior test-e2e test-all kafka-test kafka-topics shell-db shell-redis lint typecheck

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
