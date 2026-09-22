#!/usr/bin/env bash
# Local equivalent of tests.yml job: container
#   docker build, the smoke the workflow ran against the image (health,
#   non-root user, one calculate, the metrics module present, the
#   HEALTHCHECK reaching healthy), then trivy when it is installed, the one
#   check whose absence is never a failure (the workflow runs the action).
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
# shellcheck source=ci/common.sh
source ci/common.sh

IMAGE="lol-calculator:ci"
NAME="lol-calculator-smoke"
PORT="${LCC_CI_SMOKE_PORT:-18000}"

ci_section "container: docker"
if ! require_tool docker "https://docs.docker.com/get-docker/"; then
  ci_summary
fi
if ! docker info >/dev/null 2>&1; then
  ci_skip "docker daemon not running: start Docker Desktop and rerun"
  ci_summary
fi

ci_section "container: build production image"
run_step "docker build --tag $IMAGE ." docker build --tag "$IMAGE" .

# shellcheck disable=SC2329  # invoked through run_step
smoke() {
  docker rm --force "$NAME" >/dev/null 2>&1 || true
  docker run --detach --name "$NAME" --publish "127.0.0.1:$PORT:8000" "$IMAGE" >/dev/null || return 1
  # A failing check dumps the container's own logs before cleanup, so a
  # gunicorn worker-boot death shows its traceback, not only `docker inspect`.
  # The status is captured here, not in a RETURN trap: `$?` inside a RETURN
  # trap reads 0, which made every failed smoke report success.
  local status=0
  smoke_checks || status=$?
  if [ "$status" -ne 0 ]; then docker logs "$NAME"; fi
  docker rm --force "$NAME" >/dev/null 2>&1
  return "$status"
}

smoke_checks() {
  local attempt
  for attempt in $(seq 1 45); do
    if curl --fail --silent "http://127.0.0.1:$PORT/healthz" >/dev/null; then
      break
    fi
    if [ "$attempt" = 45 ]; then
      return 1
    fi
    sleep 1
  done
  test "$(docker exec "$NAME" id -u)" != "0" || return 1
  curl --fail --silent --show-error \
    --header 'Content-Type: application/json' \
    --data '{"champion":"Aatrox"}' \
    "http://127.0.0.1:$PORT/api/calculate" | grep --quiet '"total_damage"' || return 1
  # Issue #144: the beta metrics scorecard must ship in the runtime package.
  local metrics
  metrics="$(curl --silent --show-error "http://127.0.0.1:$PORT/api/metrics")"
  if printf '%s' "$metrics" | grep --quiet 'Metrics module unavailable'; then
    echo "metrics module missing from the runtime package (issue #144)"
    return 1
  fi
  printf '%s' "$metrics" | grep --quiet '"gate"' \
    || printf '%s' "$metrics" | grep --quiet 'Database unavailable' || return 1
  for attempt in $(seq 1 45); do
    local health
    health="$(docker inspect --format '{{.State.Health.Status}}' "$NAME")"
    if [ "$health" = healthy ]; then
      return 0
    fi
    if [ "$health" = unhealthy ] || [ "$attempt" = 45 ]; then
      docker inspect "$NAME"
      return 1
    fi
    sleep 1
  done
}

ci_section "container: smoke production image"
run_step "smoke $IMAGE on 127.0.0.1:$PORT" smoke

ci_section "container: scan production image"
if command -v trivy >/dev/null 2>&1; then
  run_step "trivy image (HIGH,CRITICAL, unfixed ignored)" trivy image --exit-code 1 --ignore-unfixed --severity HIGH,CRITICAL --format table "$IMAGE"
else
  # The workflow scans with the trivy action, this job's next step, so the
  # binary is absent there by design: the one skip strict mode must allow.
  ci_skip_by_design "trivy not installed: install with: brew install trivy"
fi

ci_summary
