.PHONY: dry test deploy setup install check previews version

VENV = venv/bin/python

_check-venv:
	@test -f $(VENV) || { echo "ERROR: venv not found. Run 'make setup' first."; exit 1; }

version: _check-venv
	@$(VENV) -m src.main --version

dry: _check-venv
	$(VENV) -m src.main --dry-run --dummy

previews: _check-venv
	@for theme in default fantasy fuzzyclock minimalist old_fashioned qotd terminal today weather; do \
		echo "Generating preview for theme: $$theme"; \
		$(VENV) -m src.main --dry-run --dummy --theme $$theme; \
		cp output/latest.png output/theme_$$theme.png; \
	done
	@echo "All theme previews saved to output/theme_*.png"

test: _check-venv
	$(VENV) -m pytest tests/ -v

check: _check-venv
	$(VENV) -m src.main --check-config

PI_USER ?= pi
PI_HOST ?= raspberrypi.local
PI_DIR  ?= ~/home-dashboard

deploy:
	rsync -avz --exclude='venv' --exclude='output/*.png' \
		--exclude='__pycache__' --exclude='.git' \
		--exclude='credentials/' --exclude='config/config.yaml' \
		. $(PI_USER)@$(PI_HOST):$(PI_DIR)/

install:
	@echo "Copying systemd units to Pi..."
	scp deploy/dashboard.service deploy/dashboard.timer $(PI_USER)@$(PI_HOST):/tmp/
	ssh $(PI_USER)@$(PI_HOST) " \
		sudo cp /tmp/dashboard.service /etc/systemd/system/ && \
		sudo cp /tmp/dashboard.timer /etc/systemd/system/ && \
		sudo systemctl daemon-reload && \
		sudo systemctl enable --now dashboard.timer && \
		echo 'Timer enabled. Status:' && \
		sudo systemctl status dashboard.timer --no-pager"

setup:
	python3 -m venv venv
	venv/bin/pip install -r requirements.txt
	@if [ -f /proc/device-tree/model ] && grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then \
		echo "Raspberry Pi detected — installing Pi-specific dependencies..."; \
		venv/bin/pip install -r requirements-pi.txt; \
	fi
	@mkdir -p credentials output
	@if [ ! -f config/config.yaml ]; then \
		cp config/config.example.yaml config/config.yaml; \
		echo ""; \
		echo "Created config/config.yaml from template."; \
		echo "Edit it with your API keys and settings before running."; \
		echo ""; \
		echo "Next steps:"; \
		echo "  1. Edit config/config.yaml with your settings"; \
		echo "  2. Place your Google service account JSON in credentials/"; \
		echo "  3. Run 'make check' to validate your configuration"; \
		echo "  4. Run 'make dry' to preview the dashboard with dummy data"; \
		echo ""; \
	else \
		echo "config/config.yaml already exists — not overwriting."; \
	fi
