#!/bin/bash
set -e

# The dashboard is NOT started here. Since the s6-overlay switch the image
# ships its own supervised dashboard service (docker/s6-rc.d/dashboard),
# gated on HERMES_DASHBOARD and bound via HERMES_DASHBOARD_HOST/_PORT.
# Running it from CMD as well would just fight it for the port.
#
# Note it needs an auth provider: since the June 2026 hardening the gate
# engages on every non-loopback bind and --insecure / HERMES_DASHBOARD_INSECURE
# are accepted but ignored. Set HERMES_DASHBOARD_BASIC_AUTH_USERNAME plus
# _PASSWORD (bundled dashboard_auth/basic plugin) or the dashboard fails closed
# and takes the container down with it.

# Establish the default gateway profile's durable "running" intent. This only
# does real work on the first boot of a fresh volume: cont-init's profile
# reconciler auto-starts profiles whose last desired_state was "running", but a
# never-started profile is only registered, so without this the gateway would
# stay down forever. Returns immediately - the gateway runs under s6.
hermes gateway run

# Keep TD Automate isolated from the existing default profile. The public web
# app talks only to this profile's separately keyed API on port 8650; the
# default profile and its messaging adapters remain untouched.
TD_AUTOMATE_HOME="/opt/data/agent/tdautomate"
TD_AUTOMATE_ENV_FILE="${TD_AUTOMATE_HOME}/.env"

upsert_td_automate_env() {
  key="$1"
  value="$2"
  temporary_file="${TD_AUTOMATE_ENV_FILE}.tmp"

  awk -v key="$key" -v value="$value" '
    BEGIN { replaced = 0 }
    $0 ~ ("^" key "=") {
      if (!replaced) {
        print key "=" value
        replaced = 1
      }
      next
    }
    { print }
    END {
      if (!replaced) print key "=" value
    }
  ' "$TD_AUTOMATE_ENV_FILE" > "$temporary_file"
  mv "$temporary_file" "$TD_AUTOMATE_ENV_FILE"
}

if [ -d "$TD_AUTOMATE_HOME" ] && [ -n "${TD_AUTOMATE_API_SERVER_KEY:-}" ]; then
  # A TD-specific configuration failure must not make the existing default
  # gateway restart. The subshell keeps its environment scoped as well.
  if ! (
    umask 077
    touch "$TD_AUTOMATE_ENV_FILE"
    upsert_td_automate_env "API_SERVER_ENABLED" "true"
    upsert_td_automate_env "API_SERVER_HOST" "0.0.0.0"
    upsert_td_automate_env "API_SERVER_PORT" "8650"
    upsert_td_automate_env "API_SERVER_KEY" "$TD_AUTOMATE_API_SERVER_KEY"
    upsert_td_automate_env "API_SERVER_MODEL_NAME" "tdautomate"

    # This is a public website assistant, not a general-purpose operator. Use
    # Hermes' own config writer to disable every side-effecting or data-bearing
    # toolset for this profile before it accepts API traffic.
    HERMES_HOME="$TD_AUTOMATE_HOME" hermes config set agent.disabled_toolsets '["browser", "clarify", "code_execution", "cronjob", "delegation", "file", "image_gen", "memory", "other", "session_search", "skills", "terminal", "tts", "vision", "web"]'
    HERMES_HOME="$TD_AUTOMATE_HOME" hermes config set approvals.mode manual

    # `HERMES_HOME` intentionally applies only to this command. It starts the
    # requested profile through the image's supervisor without retargeting the
    # running default profile.
    HERMES_HOME="$TD_AUTOMATE_HOME" hermes gateway run
  ); then
    echo "TD Automate gateway profile could not be registered; preserving the default gateway."
  fi
else
  echo "TD Automate profile or API key unavailable; preserving the default gateway."
fi

# CMD is /init's main program: when it exits the whole supervision tree comes
# down. Nothing left to do in the foreground, so just stay alive.
exec sleep infinity
