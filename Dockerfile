# syntax=docker/dockerfile:1

# ---- Builder Stage ----
# Use slim image - full python:3.11 (~900MB) is unnecessary when --prefer-binary skips compilation
FROM python:3.11-slim-trixie AS builder

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app
COPY requirements.txt .

# BuildKit pip cache mount: downloaded wheels persist on host across builds
# --prefer-binary: downloads pre-built wheels, avoids C compilation
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --prefer-binary -r requirements.txt

# Download Chromium binary; layer cached until requirements.txt changes
RUN patchright install chromium


# ---- Final Stage ----
FROM python:3.11-slim-trixie

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

ENV PATH="/opt/venv/bin:$PATH"

# Switch to Aliyun mirror (http avoids ca-certificates dependency) and install Chromium runtime deps.
# apt-get update must run explicitly: the cache mount shadows /var/lib/apt/lists/, so it starts empty.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/sources.list.d/debian.sources && \
    echo "deb http://mirrors.aliyun.com/debian/ trixie main" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian/ trixie-updates main" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian-security trixie-security main" >> /etc/apt/sources.list && \
    apt-get update && \
    patchright install-deps chromium

# Copy application code last (most frequent change, least caching impact)
COPY . .
