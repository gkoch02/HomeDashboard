.PHONY: dry test deploy setup install check previews version \
        pi-install pi-enable pi-status pi-logs configure

VENV = venv/bin/python

_check-venv:
	@test -f $(VENV) || { echo "ERROR: venv not found. Run 'make setup' first."; exit 1; }

version: _check-venv
	@$(VENV) -m src.main --version

dry: _check-venv
	$(VENV) -m src.main --dry-run --dummy

previews: _check-venv
	@for theme in air_quality default diags fantasy fuzzyclock fuzzyclock_invert minimalist old_fashioned qotd qotd_invert terminal today weather; do \
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
PI_HOST ?= dashboard
PI_DIR  ?= /home/$(PI_USER)/home-dashboard

deploy:
	rsync -avz --exclude='venv' --exclude='output/*.png' \
		--exclude='__pycache__' --exclude='.git' \
		--exclude='credentials/' --exclude='config/config.yaml' \
		. $(PI_USER)@$(PI_HOST):$(PI_DIR)/

install:
	@echo "Copying systemd units to Pi..."
	scp deploy/dashboard.service deploy/dashboard.timer $(PI_USER)@$(PI_HOST):/tmp/
	ssh $(PI_USER)@$(PI_HOST) " \
		sudo systemctl stop dashboard.timer 2>/dev/null || true; \
		REMOTE_DIR='$(PI_DIR)'; \
		sed -e \"s|__INSTALL_DIR__|\$$REMOTE_DIR|g\" \
		    -e \"s|__USER__|$(PI_USER)|g\" \
		    /tmp/dashboard.service | sudo tee /etc/systemd/system/dashboard.service > /dev/null && \
		sudo cp /tmp/dashboard.timer /etc/systemd/system/ && \
		sudo systemctl daemon-reload && \
		sudo systemctl reset-failed dashboard.service dashboard.timer 2>/dev/null || true; \
		sudo systemctl enable dashboard.timer && \
		sudo systemctl restart dashboard.timer && \
		echo 'Timer enabled. Status:' && \
		sudo systemctl status dashboard.timer --no-pager"

pi-install:
	@echo "==> Installing system dependencies..."
	@if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then \
		echo "WARNING: This does not appear to be a Raspberry Pi. Continuing anyway."; \
	fi
	sudo apt-get update -qq
	@TIFF_PKG="$$(apt-cache show libtiff5 >/dev/null 2>&1 && echo libtiff5 || echo libtiff6)"; \
	sudo apt-get install -y python3-dev python3-venv libopenjp2-7 $$TIFF_PKG git swig liblgpio-dev
	@echo ""
	@echo "==> Enabling SPI interface..."
	sudo raspi-config nonint do_spi 0
	@echo ""
	@echo "==> Creating Python virtual environment..."
	python3 -m venv venv
	venv/bin/pip install --quiet --upgrade pip
	venv/bin/pip install -r requirements.txt -r requirements-pi.txt
	@echo ""
	@echo "==> Installing Waveshare EPD library..."
	rm -rf /tmp/waveshare-epd
	git clone --depth=1 --filter=blob:none --sparse https://github.com/waveshare/e-Paper /tmp/waveshare-epd
	git -C /tmp/waveshare-epd sparse-checkout set RaspberryPi_JetsonNano/python
	venv/bin/pip install --quiet /tmp/waveshare-epd/RaspberryPi_JetsonNano/python/
	rm -rf /tmp/waveshare-epd
	venv/bin/python -c "import waveshare_epd; print('  Waveshare EPD: OK')"
	@echo ""
	@mkdir -p credentials output
	@if [ ! -f config/config.yaml ]; then \
		cp config/config.example.yaml config/config.yaml; \
	fi
	@echo "============================================"
	@echo "  pi-install complete!"
	@echo ""
	@echo "  NOTE: If SPI was just enabled for the first"
	@echo "  time, reboot before running on real hardware:"
	@echo "    sudo reboot"
	@echo ""
	@echo "  Next steps:"
	@echo "    make configure   -- fill in your API keys"
	@echo "    make dry         -- preview with dummy data"
	@echo "    make pi-enable   -- start the refresh timer"
	@echo "============================================"

pi-enable:
	@echo "==> Installing systemd units with current paths..."
	@INSTALL_DIR="$$(pwd)"; USER_NAME="$$(whoami)"; \
	sed -e "s|__INSTALL_DIR__|$$INSTALL_DIR|g" \
	    -e "s|__USER__|$$USER_NAME|g" \
	    deploy/dashboard.service | sudo tee /etc/systemd/system/dashboard.service > /dev/null; \
	sudo cp deploy/dashboard.timer /etc/systemd/system/dashboard.timer; \
	sudo systemctl daemon-reload; \
	sudo systemctl enable --now dashboard.timer
	@echo ""
	@$(MAKE) pi-status

pi-status:
	@echo "=== Timer ==="
	@sudo systemctl status dashboard.timer --no-pager || true
	@echo ""
	@echo "=== Last service run ==="
	@sudo systemctl status dashboard.service --no-pager || true
	@if [ -f output/dashboard.log ]; then \
		echo ""; \
		echo "=== Recent log (last 20 lines) ==="; \
		tail -20 output/dashboard.log; \
	fi

pi-logs:
	tail -f output/dashboard.log

configure:
	@deploy/configure.sh

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
