#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
local_root="$repo_root/.local"
data_dir="$local_root/postgres"
socket_dir="$local_root/run"
log_file="$local_root/postgres.log"
port=55439

case "${1:-}" in
  start)
    mkdir -p "$local_root" "$socket_dir"
    chmod 700 "$socket_dir"
    if [[ ! -f "$data_dir/PG_VERSION" ]]; then
      initdb -D "$data_dir" -A trust --no-instructions >/dev/null
      {
        printf "\nlisten_addresses = '127.0.0.1'\n"
        printf "unix_socket_directories = '%s'\n" "$socket_dir"
        printf 'port = %s\n' "$port"
      } >> "$data_dir/postgresql.conf"
    fi
    if ! pg_ctl -D "$data_dir" status >/dev/null 2>&1; then
      pg_ctl -D "$data_dir" -l "$log_file" start
    fi
    if [[ "$(psql -X -h "$socket_dir" -p "$port" -d postgres -tAqc "SELECT 1 FROM pg_database WHERE datname = 'scorepilot'")" != '1' ]]; then
      createdb -h "$socket_dir" -p "$port" scorepilot
    fi
    echo "Local database ready: scorepilot (Unix socket $socket_dir, port $port)"
    ;;
  stop)
    if [[ -f "$data_dir/PG_VERSION" ]]; then
      pg_ctl -D "$data_dir" stop -m fast
    fi
    ;;
  status)
    if [[ -f "$data_dir/PG_VERSION" ]]; then
      pg_ctl -D "$data_dir" status
    else
      echo 'Local database has not been initialised.'
      exit 1
    fi
    ;;
  *)
    echo 'Usage: bash database/local-db.sh {start|stop|status}' >&2
    exit 2
    ;;
esac
