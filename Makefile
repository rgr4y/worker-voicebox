# Voicebox Makefile — Python backend setup
# Unix-only (macOS/Linux). Windows users should use WSL.

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND_DIR := backend
PYTHON := $(shell command -v python3.12 2>/dev/null || command -v python3.13 2>/dev/null || echo python3)
VENV := $(CURDIR)/.venv
VENV_BIN := $(VENV)/bin
PIP := $(VENV_BIN)/pip
PYTHON_VENV := $(VENV_BIN)/python

BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m

.PHONY: help
help: ## Show this help message
	@echo -e "$(BLUE)Voicebox$(NC) - Development Commands"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

# =============================================================================
# SETUP
# =============================================================================

.PHONY: setup setup-python setup-python-linux-cuda

setup: setup-python ## Full project setup
	@echo -e "$(GREEN)✓ Setup complete!$(NC)"

setup-python: $(VENV)/bin/activate ## Set up Python venv and dependencies
	@echo -e "$(BLUE)Installing Python dependencies...$(NC)"
	$(PIP) install --upgrade pip
	@if [ "$$(uname -m)" = "arm64" ] && [ "$$(uname)" = "Darwin" ]; then \
		echo -e "$(BLUE)Detected Apple Silicon — using MLX-compatible dependency resolution...$(NC)"; \
		$(PIP) install -r $(BACKEND_DIR)/requirements-mlx.txt; \
		grep -v -E "^transformers" $(BACKEND_DIR)/requirements.txt > /tmp/voicebox-requirements-filtered.txt; \
		$(PIP) install -r /tmp/voicebox-requirements-filtered.txt; \
		rm /tmp/voicebox-requirements-filtered.txt; \
		$(PIP) install --no-deps git+https://github.com/QwenLM/Qwen3-TTS.git; \
		echo -e "$(GREEN)✓ MLX backend enabled (native Metal acceleration)$(NC)"; \
		echo -e "$(YELLOW)Note: Using transformers 5.0.0rc3 (required by MLX)$(NC)"; \
	else \
		$(PIP) install -r $(BACKEND_DIR)/requirements.txt; \
		$(PIP) install git+https://github.com/QwenLM/Qwen3-TTS.git; \
	fi
	@echo -e "$(GREEN)✓ Python environment ready$(NC)"

setup-python-linux-cuda: $(VENV)/bin/activate ## Set up Python venv for Linux + CUDA (matches Docker image)
	@echo -e "$(BLUE)Installing Python dependencies for Linux/CUDA (mirrors Dockerfile)...$(NC)"
	$(PIP) install --upgrade pip
	$(PIP) install torch torchvision --index-url https://download.pytorch.org/whl/cu124
	$(PIP) install -r $(BACKEND_DIR)/requirements-linux.txt --extra-index-url https://download.pytorch.org/whl/cu124
	@echo -e "$(GREEN)✓ Python environment ready (Linux/CUDA)$(NC)"

$(VENV)/bin/activate:
	@echo -e "$(BLUE)Creating Python virtual environment...$(NC)"
	@if [ "$$(uname)" = "Linux" ]; then \
		PYENV_PY=$$(echo $$HOME/.pyenv/versions/3.12.*/bin/python3.12 | tr ' ' '\n' | sort -V | tail -1); \
		if [ -x "$$PYENV_PY" ]; then \
			echo -e "$(BLUE)Using pyenv Python 3.12 with --copies (Docker-compatible)...$(NC)"; \
			$$PYENV_PY -m venv --copies $(VENV); \
		elif command -v python3.12 >/dev/null 2>&1; then \
			echo -e "$(BLUE)Using system python3.12 with --copies...$(NC)"; \
			python3.12 -m venv --copies $(VENV); \
		else \
			echo -e "$(YELLOW)Warning: Python 3.12 not found, using default $(PYTHON)$(NC)"; \
			$(PYTHON) -m venv --copies $(VENV); \
		fi; \
	else \
		PY_MINOR=$$($(PYTHON) -c "import sys; print(sys.version_info[1])"); \
		if [ "$$PY_MINOR" -gt 13 ]; then \
			echo -e "$(YELLOW)Warning: Python 3.$$PY_MINOR detected. ML packages may not be compatible.$(NC)"; \
			echo -e "$(YELLOW)Recommended: Use Python 3.12 or 3.13 (brew install python@3.12)$(NC)"; \
		fi; \
		$(PYTHON) -m venv $(VENV); \
	fi

# =============================================================================
# DEVELOPMENT
# =============================================================================

.PHONY: docker-cuda docker-cpu docker-runpod dev build

docker-cuda: ## Build Docker image (GPU/CUDA)
	DOCKER_BUILDKIT=1 docker build -t voicebox .

docker-cpu: ## Build Docker image (CPU-only)
	DOCKER_BUILDKIT=1 docker build --build-arg CUDA=0 -t voicebox-cpu .

docker-runpod: ## Build Docker image (RunPod serverless)
	DOCKER_BUILDKIT=1 docker build --build-arg SERVERLESS=1 -t voicebox-serverless .

dev: ## Start FastAPI backend server (auto-reload)
	@echo -e "$(BLUE)Starting backend server on http://localhost:17493$(NC)"
	$(PYTHON_VENV) -m backend.main --host 0.0.0.0 --port 17493

build: ## Build Python server binary (PyInstaller)
	@echo -e "$(BLUE)Building server binary...$(NC)"
	PATH="$(VENV_BIN):$$PATH" ./scripts/build-server.sh

# =============================================================================
# CLEAN
# =============================================================================

.PHONY: clean

clean: ## Clean Python venv and cache
	@echo -e "$(BLUE)Cleaning Python files...$(NC)"
	rm -rf $(VENV)
	find $(BACKEND_DIR) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find $(BACKEND_DIR) -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo -e "$(GREEN)✓ Cleaned$(NC)"
