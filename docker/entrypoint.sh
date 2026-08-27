#!/bin/sh
set -eu

case "${1:-web}" in
  web)
    shift
    exec sci-search --corpus "${SCI_SEARCH_CORPUS:-/srv/sci-search/corpus}" serve \
      --host 0.0.0.0 --port "${SCI_SEARCH_PORT:-8000}" "$@"
    ;;
  worker)
    shift
    exec dramatiq sci_search.worker_runtime --processes 1 --threads 2 "$@"
    ;;
  migrate)
    shift
    exec python -m scripts.migrate "$@"
    ;;
  backup)
    shift
    exec python -m scripts.backup "$@"
    ;;
  restore)
    shift
    exec python -m scripts.restore "$@"
    ;;
  verify-restore)
    shift
    exec python -m scripts.verify_restore "$@"
    ;;
  storage-gc)
    shift
    exec python -m scripts.storage_gc "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
