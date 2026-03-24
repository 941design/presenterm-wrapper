# syntax=docker/dockerfile:1
FROM node:20-bookworm-slim

ARG PRESENTERM_VERSION=0.15.1
ARG PANDOC_VERSION=3.2.1
ARG TYPST_VERSION=0.13.1

USER root

# Install runtime dependencies, including system Chromium for Mermaid CLI.
RUN set -eux; \
  apt-get update; \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 \
    curl \
    tar \
    xz-utils \
    ca-certificates \
    chromium \
    chromium-sandbox \
    fonts-noto-color-emoji \
    fonts-noto-core; \
  rm -rf /var/lib/apt/lists/*

# Install a recent Pandoc with Typst support.
RUN set -eux; \
  case "${TARGETARCH:-amd64}" in \
    amd64)  PD_ARCH="amd64" ;; \
    arm64)  PD_ARCH="arm64" ;; \
    *) echo "Unsupported TARGETARCH for pandoc: ${TARGETARCH}"; exit 1 ;; \
  esac; \
  PD_URL="https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-${PD_ARCH}.tar.gz"; \
  mkdir -p /tmp/pandoc; \
  curl -fsSL "$PD_URL" -o /tmp/pandoc.tgz; \
  tar -xzf /tmp/pandoc.tgz -C /tmp/pandoc; \
  install -m 0755 "/tmp/pandoc/pandoc-${PANDOC_VERSION}/bin/pandoc" /usr/local/bin/pandoc; \
  rm -rf /tmp/pandoc /tmp/pandoc.tgz; \
  pandoc --version

# Install Typst binary required by Pandoc's typst output pipeline.
RUN set -eux; \
  case "${TARGETARCH:-amd64}" in \
    amd64)  TY_ARCH="x86_64-unknown-linux-musl" ;; \
    arm64)  TY_ARCH="aarch64-unknown-linux-musl" ;; \
    *) echo "Unsupported TARGETARCH for typst: ${TARGETARCH}"; exit 1 ;; \
  esac; \
  TY_URL="https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${TY_ARCH}.tar.xz"; \
  mkdir -p /tmp/typst; \
  curl -fsSL "$TY_URL" -o /tmp/typst.tar.xz; \
  tar -xJf /tmp/typst.tar.xz -C /tmp/typst; \
  install -m 0755 /tmp/typst/typst-${TY_ARCH}/typst /usr/local/bin/typst; \
  rm -rf /tmp/typst /tmp/typst.tar.xz; \
  typst --version

# Install Mermaid CLI without downloading bundled Chromium.
ENV PUPPETEER_SKIP_DOWNLOAD=true
RUN set -eux; \
  npm install -g @mermaid-js/mermaid-cli; \
  command -v mmdc; \
  mmdc --version

# Force Puppeteer to use distro Chromium (multi-arch compatible).
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Ensure mmdc launches Chromium with container-safe sandbox flags.
RUN set -eux; \
  mkdir -p /etc/mermaid; \
  printf '%s\n' \
    '{' \
    '  "args": ["--no-sandbox", "--disable-setuid-sandbox"]' \
    '}' \
    > /etc/mermaid/puppeteer-config.json
RUN set -eux; \
  mv /usr/local/bin/mmdc /usr/local/bin/mmdc-bin; \
  printf '%s\n' \
    '#!/bin/sh' \
    'set -eu' \
    'exec /usr/local/bin/mmdc-bin --puppeteerConfigFile /etc/mermaid/puppeteer-config.json "$@"' \
    > /usr/local/bin/mmdc
RUN chmod +x /usr/local/bin/mmdc

# Install presenterm (built from source submodule)
COPY build/presenterm-${TARGETARCH} /usr/local/bin/presenterm
RUN chmod +x /usr/local/bin/presenterm && presenterm --version

COPY presenterm-config.yaml /etc/presenterm/config.yaml
ENV PRESENTERM_CONFIG_FILE=/etc/presenterm/config.yaml

# Copy preprocessor entrypoint
COPY auto_presenterm_slides.py /usr/local/bin/auto_presenterm_slides.py
RUN chmod +x /usr/local/bin/auto_presenterm_slides.py

WORKDIR /data

# Run as non-root user.
RUN set -eux; \
  groupadd -r mermaidcli; \
  useradd -r -g mermaidcli -m -d /home/mermaidcli mermaidcli
USER mermaidcli

ENTRYPOINT ["/usr/local/bin/auto_presenterm_slides.py"]
