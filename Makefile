PYTHON ?= python3
VENV_PYTHON := .venv/bin/python
.PHONY: set-up test run staff-setup

set-up:
	$(PYTHON) -m venv .venv
	$(VENV_PYTHON) tools/install_dependencies.py
	$(VENV_PYTHON) tools/install_gitleaks.py --hooks

test:
	$(VENV_PYTHON) -m unittest discover -s tests -p "test_*.py" -v

run:
	$(VENV_PYTHON) -m flask --app app run --port 5050

staff-setup:
	$(VENV_PYTHON) -m flask --app app staff-setup

.PHONY: mail-setup sms-setup
mail-setup:
	$(VENV_PYTHON) tools/configure_staff_mail.py
sms-setup:
	$(VENV_PYTHON) tools/configure_sms.py

.PHONY: release-check
release-check:
	$(VENV_PYTHON) tools/verify_final_release.py --browsers

.PHONY: security-setup secrets-check
security-setup:
	$(PYTHON) tools/install_gitleaks.py --hooks

secrets-check:
	$(PYTHON) tools/check_secrets.py --staged
	$(PYTHON) tools/check_secrets.py --history
