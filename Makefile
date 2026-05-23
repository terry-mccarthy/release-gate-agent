.PHONY: stack-up stack-down test-unit test-eval test-integration test install

install:
	pip install -e packages/harness-gateway -e packages/harness-validator \
	    jsonschema pyyaml pytest pytest-asyncio

test-unit:
	pytest tests/unit/ -v

test-eval:
	pytest tests/eval/ -v -m eval

test-integration:
	pytest tests/integration/ -v -m integration

test: test-unit test-eval

stack-up:
	docker compose up -d --build
	@echo "Waiting for stack to be healthy..."
	@sleep 5
	@docker compose ps

stack-down:
	docker compose down -v

logs:
	docker compose logs -f
