#!/bin/bash

python -m pip install "tomli >= 1.1.0 ; python_version < '3.11'"
python .circleci/scripts/get_test_env_deps.py | xargs -r python -m pip install

python -m pytest -c /dev/null --ignore tools --test-plugin-installation --continue-on-collection-errors -k test_with_examples
