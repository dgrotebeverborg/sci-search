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
    exec python -m sci_search.worker "$@"
    ;;
  migrate)
    shift
    exec alembic -c /app/alembic.ini upgrade head "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
