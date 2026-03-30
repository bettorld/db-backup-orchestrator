# DB Backup Orchestrator — Makefile
# GNU Special-Targets: https://www.gnu.org/software/make/manual/html_node/Special-Targets.html#Special-Targets

.POSIX:
.SILENT: help print_box clean build build-dev build-test build-multi bake test test-unit test-integration lint format
.PHONY: help print_box clean build build-dev build-test build-multi bake test test-unit test-integration lint format
.DEFAULT_GOAL := help

-include .env

PUSH = false
CLEAN = false

DOCKER_REGISTRY ?= docker.io
IMAGE_NAME = db-backup-orchestrator
IMAGE_TAG = production
IMAGE = $(DOCKER_REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)
TEST_IMAGE = $(DOCKER_REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)-test

PLATFORM = linux/amd64
PLATFORMS = linux/amd64,linux/arm64
BUILDER_NAME = dbo-builder

# ─── Help ─────────────────────────────────────────────────────────────────────

help:
	printf "Usage: make [target] [VARS]\n\n"
	printf "Targets:\n"
	printf "  build            Build container image\n"
	printf "  build-dev        Build with no cache\n"
	printf "  build-test       Build test container (pytest + ruff)\n"
	printf "  build-multi      Build multi-platform (amd64 + arm64)\n"
	printf "  bake             Build using docker-bake.hcl\n"
	printf "  test             Run all tests (unit + integration)\n"
	printf "  test-unit        Run unit tests inside container\n"
	printf "  test-integration Run integration tests inside container\n"
	printf "  lint             Lint inside container\n"
	printf "  format           Auto-format code (runs locally)\n"
	printf "  clean            Remove images, containers, and caches\n"
	printf "  help             Show this help\n\n"
	printf "Variables:\n"
	printf "  IMAGE_TAG   Image tag (default: production)\n"
	printf "  PUSH        Push after build (default: false)\n"
	printf "  CLEAN       Remove local image after build (default: false)\n"
	printf "  PLATFORM    Build platform (default: linux/amd64)\n"
	printf "  PLATFORMS   Multi-platform list (default: linux/amd64,linux/arm64)\n"

# ─── Utilities ────────────────────────────────────────────────────────────────

# Prints a message inside a dynamic-width # border
# Usage: $(MAKE) print_box MSG="Your message here"
print_box:
	msg="### $(MSG) ###"; \
	border=$$(printf '%*s' "$${#msg}" '' | tr ' ' '#'); \
	printf "\n%s\n%s\n%s\n\n" "$$border" "$$msg" "$$border"

# ─── Build ────────────────────────────────────────────────────────────────────

# Usage: make build IMAGE_TAG=production PUSH=true
build:
	$(MAKE) print_box MSG="Building image: $(IMAGE)"
	docker build --platform $(PLATFORM) -t $(IMAGE) .
	if [ "$(PUSH)" = "true" ]; then \
		$(MAKE) print_box MSG="Pushing image: $(IMAGE)"; \
		docker image push $(IMAGE); \
	else \
		$(MAKE) print_box MSG="Push skipped"; \
	fi
	if [ "$(CLEAN)" = "true" ]; then \
		$(MAKE) clean; \
	fi

# Usage: make build-dev PUSH=false
build-dev:
	$(MAKE) print_box MSG="Building image (no cache): $(DOCKER_REGISTRY)/$(IMAGE_NAME):dev"
	docker build --no-cache --platform $(PLATFORM) -t $(DOCKER_REGISTRY)/$(IMAGE_NAME):dev .
	if [ "$(PUSH)" = "true" ]; then \
		$(MAKE) print_box MSG="Pushing image: $(DOCKER_REGISTRY)/$(IMAGE_NAME):dev"; \
		docker image push $(DOCKER_REGISTRY)/$(IMAGE_NAME):dev; \
	else \
		$(MAKE) print_box MSG="Push skipped"; \
	fi

# Usage: make build-test
build-test:
	$(MAKE) build IMAGE_TAG=$(IMAGE_TAG) PUSH=false CLEAN=false
	$(MAKE) print_box MSG="Building test image: $(TEST_IMAGE)"
	docker build --platform $(PLATFORM) --build-arg DOCKER_REGISTRY=$(DOCKER_REGISTRY) -f Dockerfile.test -t $(TEST_IMAGE) .

# Usage: make build-multi PUSH=true
build-multi:
	$(MAKE) print_box MSG="Building multi-platform: $(IMAGE)"
	docker buildx inspect $(BUILDER_NAME) > /dev/null 2>&1 || docker buildx create --name $(BUILDER_NAME) --use
	docker buildx build \
		--builder $(BUILDER_NAME) \
		--platform $(PLATFORMS) \
		--tag $(IMAGE) \
		.
	if [ "$(PUSH)" = "true" ]; then \
		$(MAKE) print_box MSG="Pushing multi-platform: $(IMAGE)"; \
		docker buildx build \
			--builder $(BUILDER_NAME) \
			--platform $(PLATFORMS) \
			--tag $(IMAGE) \
			--tag $(DOCKER_REGISTRY)/$(IMAGE_NAME):production \
			--push .; \
	else \
		$(MAKE) print_box MSG="Push skipped"; \
	fi

# Usage: make bake IMAGE_TAG=production PUSH=true
bake:
	$(MAKE) print_box MSG="Baking image: $(IMAGE)"
	IMAGE_TAG=$(IMAGE_TAG) docker buildx bake
	if [ "$(PUSH)" = "true" ]; then \
		$(MAKE) print_box MSG="Pushing image: $(IMAGE)"; \
		docker image push $(IMAGE); \
	else \
		$(MAKE) print_box MSG="Push skipped"; \
	fi
	if [ "$(CLEAN)" = "true" ]; then \
		$(MAKE) clean; \
	fi

# ─── Test (all tests run inside containers — no local dependencies needed) ────

test: test-coverage test-integration

test-unit: build-test
	$(MAKE) print_box MSG="Running unit tests"
	docker run --rm --platform $(PLATFORM) $(TEST_IMAGE) tests/unit/ -v --timeout=30

test-coverage: build-test
	$(MAKE) print_box MSG="Running unit tests with coverage"
	docker run --rm --platform $(PLATFORM) $(TEST_IMAGE) tests/unit/ --cov=db_backup_orchestrator --cov-report=term-missing --timeout=30

test-integration: build-test
	$(MAKE) print_box MSG="Running integration tests"
	docker run --rm --platform $(PLATFORM) \
		-v /var/run/docker.sock:/var/run/docker.sock \
		$(TEST_IMAGE) tests/integration/ -v --timeout=120

# ─── Lint ─────────────────────────────────────────────────────────────────────

lint: build-test
	$(MAKE) print_box MSG="Linting code"
	docker run --rm --platform $(PLATFORM) --entrypoint ruff $(TEST_IMAGE) check db_backup_orchestrator/ tests/
	docker run --rm --platform $(PLATFORM) --entrypoint ruff $(TEST_IMAGE) format --check db_backup_orchestrator/ tests/

format:
	$(MAKE) print_box MSG="Formatting code"
	ruff format db_backup_orchestrator/ tests/

# ─── Clean ────────────────────────────────────────────────────────────────────

clean:
	$(MAKE) print_box MSG="Cleaning up"
	-docker ps -a --filter "name=dbo-test-" -q | xargs -r docker rm -f 2>/dev/null
	-docker rmi $(IMAGE) 2>/dev/null
	-docker rmi $(TEST_IMAGE) 2>/dev/null
	rm -rf test-backups/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null
