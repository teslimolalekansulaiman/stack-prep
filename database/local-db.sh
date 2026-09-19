#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The cluster belongs to the checkout, not to a working copy of it. A git worktree gets its
# own copy of this script, so taking the script's own location would put a second data
# directory inside the worktree — and initdb it, and then fail to start it, because the
# cluster already running holds the port. --git-common-dir names the main checkout's .git
# from anywhere in the repository, including from a worktree; its parent is the checkout
# the cluster lives in. The path it prints is relative to the working directory when it is
# not a worktree, so it is resolved by cd rather than by string surgery.
if common_dir="$(cd "$script_dir" && git rev-parse --git-common-dir 2>/dev/null)"; then
  repo_root="$(cd "$script_dir" && cd "$common_dir/.." && pwd)"
else
  # Not a git checkout at all: an unpacked tarball still has a database/ beside a root.
  repo_root="$(cd "$script_dir/.." && pwd)"
fi
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
