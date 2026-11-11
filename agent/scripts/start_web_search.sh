#!/usr/bin/env bash
# Start the two keyless web search backends used by web_search, if they are not already running:
#   open-websearch daemon on 127.0.0.1:3210  (npm install -g open-websearch)
#   SearXNG on 127.0.0.1:8889                (venv + settings.yml under $SEARXNG_HOME)
# Then set OPEN_WEBSEARCH_URL, WEB_SEARCH_BASE_URL and WEB_SEARCH_BACKENDS=openwebsearch,searxng.
set -euo pipefail

SEARXNG_HOME="${SEARXNG_HOME:-$HOME/.cache/searxng}"
OWS_HOME="${OWS_HOME:-$HOME/.cache/open-websearch}"
OWS_PORT="${OWS_PORT:-3210}"
SEARXNG_PORT="${SEARXNG_PORT:-8889}"
export PATH="$HOME/.cache/toolchains/node/bin:$PATH"

up() { curl -s -o /dev/null -m 3 -w "%{http_code}" "$1" | grep -q 200; }

wait_up() {
    for _ in $(seq 1 20); do
        if up "$2"; then echo "$1 up: $2"; return 0; fi
        sleep 1
    done
    echo "$1 did not come up; see its log" >&2
    return 1
}

if up "http://127.0.0.1:$OWS_PORT/health"; then
    echo "open-websearch already running"
else
    mkdir -p "$OWS_HOME"
    (cd "$OWS_HOME" && nohup open-websearch serve --host 127.0.0.1 --port "$OWS_PORT" > daemon.log 2>&1 &)
    wait_up open-websearch "http://127.0.0.1:$OWS_PORT/health"
fi

if up "http://127.0.0.1:$SEARXNG_PORT/healthz"; then
    echo "SearXNG already running"
else
    (cd "$SEARXNG_HOME" && SEARXNG_SETTINGS_PATH="$SEARXNG_HOME/settings.yml" \
        nohup venv/bin/python -m searx.webapp > searxng.log 2>&1 &)
    wait_up SearXNG "http://127.0.0.1:$SEARXNG_PORT/healthz"
fi
