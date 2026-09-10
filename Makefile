# Local CI runner for the calculator.
#
# Mirrors .github/workflows/tests.yml job for job so a change is proven on
# this machine before it is pushed, and the repo does not depend on GitHub
# Actions to know its own state. See docs/ci-local.md for the mapping from
# each workflow job and step to the target below.
#
# Usage:
#   make ci-fast             # pre-push loop: UI gates, black, golden compares
#   make ci-full             # every job tests.yml runs, all failures reported
#   make ci-shared-ui        # tests.yml: shared-ui
#   make ci-test             # tests.yml: test (pytest, goldens, matrices)
#   make ci-static           # tests.yml: static (black, pylint, pip-audit, bandit)
#   make ci-coverage-census  # tests.yml: coverage-census (LCC_CI_CENSUS_SHARD=K/N for one cut)
#   make ci-container        # tests.yml: container (docker build, smoke, trivy)
#   make hooks               # install the pre-push hook that runs ci-fast
#
# Each target is a thin wrapper around a script in ci/. Scripts print a
# PASS/FAIL/SKIP line per check and a summary; they exit non-zero on any
# real failure and exit 0 when everything passed or was cleanly skipped.

.PHONY: ci-fast ci-full ci-shared-ui ci-test ci-static ci-coverage-census ci-container hooks

ci-fast:
	bash ci/fast.sh

# Run every job and report ALL failures, the way hosted CI did. Depending
# on the targets would stop at the first failure and hide the rest.
ci-full:
	@failed=""; \
	for job in shared_ui static test coverage_census container; do \
	  echo ""; echo "########## ci-$$job ##########"; \
	  bash ci/$$job.sh || failed="$$failed $$job"; \
	done; \
	echo ""; echo "================ CI-FULL SUMMARY ================"; \
	if [ -n "$$failed" ]; then \
	  echo "FAILED JOBS:$$failed"; echo "================================================"; exit 1; \
	else \
	  echo "all jobs passed"; echo "================================================"; \
	fi

ci-shared-ui:
	bash ci/shared_ui.sh

ci-test:
	bash ci/test.sh

ci-static:
	bash ci/static.sh

ci-coverage-census:
	bash ci/coverage_census.sh

ci-container:
	bash ci/container.sh

hooks:
	bash ci/install-hooks.sh
