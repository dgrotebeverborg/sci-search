FROM python:3.11-slim@sha256:be1575ed968de893bd54f4c56315ff7c4736ce522c1bca08fd521731aafc0d76 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY sci_search ./sci_search
RUN python -m pip install --no-cache-dir setuptools==84.0.0 wheel==0.46.3 \
    && python -m pip wheel --wheel-dir /wheels .

FROM python:3.11-slim@sha256:be1575ed968de893bd54f4c56315ff7c4736ce522c1bca08fd521731aafc0d76 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/sci-search/bin:$PATH \
    TMPDIR=/tmp/sci-search
RUN groupadd --gid 10001 sci-search \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent sci-search \
    && apt-get update \
    && apt-get upgrade --yes \
    && apt-get install --yes --no-install-recommends age postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/sci-search \
    && mkdir -p /tmp/sci-search \
    && chown 10001:10001 /tmp/sci-search
COPY --from=builder /wheels /wheels
RUN /opt/sci-search/bin/pip install --no-cache-dir --no-index --find-links=/wheels \
        /wheels/sci_search-*.whl \
    && /opt/sci-search/bin/pip uninstall --yes setuptools wheel \
    && /usr/local/bin/python -m pip uninstall --yes setuptools wheel \
    && rm -rf /wheels
COPY --chmod=0555 docker/entrypoint.sh /usr/local/bin/sci-search-entrypoint
COPY --chmod=0555 scripts /app/scripts
WORKDIR /app
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/sci-search-entrypoint"]
CMD ["web"]
