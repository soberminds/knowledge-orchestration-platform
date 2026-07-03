FROM python:3.11-slim-bookworm

WORKDIR /app

ARG APT_MIRROR=http://mirrors.aliyun.com/debian
ARG APT_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=
ARG TORCH_VERSION=2.3.1+cpu
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    TZ=Asia/Shanghai \
    SOFFICE_BIN=/usr/bin/soffice

RUN set -eux; \
    sed -i \
      -e "s|http://deb.debian.org/debian|${APT_MIRROR}|g" \
      -e "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
      /etc/apt/sources.list.d/debian.sources; \
    apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=120 -o Acquire::https::Timeout=120 update; \
    apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=120 -o Acquire::https::Timeout=120 install -y --no-install-recommends \
        tzdata \
        libreoffice-writer-nogui \
        libreoffice-calc-nogui \
        libreoffice-impress-nogui \
        fonts-noto-cjk \
        fontconfig; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN set -eux; \
    trusted_args=""; \
    if [ -n "$PIP_TRUSTED_HOST" ]; then trusted_args="--trusted-host $PIP_TRUSTED_HOST"; fi; \
    printf 'torch==%s\n' "$TORCH_VERSION" > /tmp/torch-cpu-constraints.txt; \
    python -m pip install --upgrade pip setuptools wheel; \
    pip install --retries 10 --timeout 120 -i "$PIP_INDEX_URL" --extra-index-url "$TORCH_INDEX_URL" $trusted_args \
        -c /tmp/torch-cpu-constraints.txt "torch==$TORCH_VERSION"; \
    pip install --retries 10 --timeout 120 -i "$PIP_INDEX_URL" --extra-index-url "$TORCH_INDEX_URL" $trusted_args \
        -c /tmp/torch-cpu-constraints.txt -r requirements.txt; \
    rm -f /tmp/torch-cpu-constraints.txt

COPY app ./app
RUN mkdir -p ./data/user_docs ./data/chroma_db ./data/preview_pdf

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
