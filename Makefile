.PHONY: stack-up stack-down test-unit test-eval test-integration test install

install:
	uv sync --all-packages

test-unit:
	uv run pytest tests/unit/ -v

test-eval:
	uv run pytest tests/eval/ -v -m eval

test-integration:
	uv run pytest tests/integration/ -v -m integration

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
