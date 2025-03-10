# several pytest settings
DURATION ?= all  # pytest duration, one of short, long or all
WORLD_SIZE ?= 1  # world size for launcher tests
MASTER_PORT ?= 26000 # port for distributed tests
PYTHON ?= python3  # Python command
PYTEST ?= pytest  # Pytest command
PYRIGHT ?= pyright  # Pyright command. Pyright must be installed seperately -- e.g. `node install -g pyright`
EXTRA_ARGS ?=  # extra arguments for pytest
EXTRA_LAUNCHER_ARGS ?= # extra arguments for the composer cli launcher

# Force append the duration flag to extra args
override EXTRA_ARGS += --duration $(DURATION)

test:
	$(PYTHON) -m $(PYTEST) $(EXTRA_ARGS)

test-gpu:
	$(PYTHON) -m $(PYTEST) -m gpu $(EXTRA_ARGS)

# runs tests with the launcher
test-dist:
	$(PYTHON) -m composer.cli.launcher -n $(WORLD_SIZE) --master_port $(MASTER_PORT) $(EXTRA_LAUNCHER_ARGS) -m $(PYTEST) $(EXTRA_ARGS)

test-dist-gpu:
	$(PYTHON) -m composer.cli.launcher -n $(WORLD_SIZE) --master_port $(MASTER_PORT) $(EXTRA_LAUNCHER_ARGS) -m $(PYTEST) -m gpu $(EXTRA_ARGS)

clean-notebooks:
	$(PYTHON) scripts/clean_notebooks.py -i notebooks/*.ipynb

.PHONY: test test-gpu test-dist test-dist-gpu clean-notebooks
