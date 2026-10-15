# The organisation's runner image (ghcr.io/diluxone/runner). Every job on the
# organisation's VM runs in a fresh container of it and the container is
# discarded when the job ends (scripts/runner-vm/dx-runner-slot.sh), so no job
# sees what another installed. It carries what every stack needs and nothing a
# job should install itself: jobs still pick their PHP, Node or Python with the
# setup-* actions, as on GitHub's runners; for PHP the image carries only the
# shared libraries setup-php's prebuilt builds expect from GitHub's image.
# Rebuilt every week and promoted to :stable only after a smoke test
# (.github/workflows/runner-image.yml), which sets PHP up with setup-php.
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55

# Filled by runner-image.yml with the latest release of actions/runner and the
# SHA-256 GitHub publishes for it, and the latest Node.js LTS line.
ARG RUNNER_VERSION
ARG RUNNER_SHA256
ARG NODE_MAJOR=22

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    ImageOS=ubuntu24

# Base tools, and sudo: setup-php and Playwright install with apt, as they do
# on GitHub's runners.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git gnupg jq lsb-release openssh-client rsync \
      software-properties-common sudo tzdata unzip xz-utils zip build-essential \
 && rm -rf /var/lib/apt/lists/*

# Docker CLI and Compose: the jobs drive the VM's own Docker (wp-env) through
# its socket, mounted by the slot.
RUN install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL --retry 5 --retry-all-errors https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/*

# What the organisation's workflows call that GitHub's runners carry: the
# GitHub CLI, Python with PyYAML (scripts/*.py), gettext (msgfmt),
# shellcheck, and mikefarah's yq (not Ubuntu's yq, a different tool), checked
# against its published SHA-256.
RUN curl -fsSL --retry 5 --retry-all-errors https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli.gpg \
 && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends gh python3 python3-yaml python3-venv python3-pip gettext shellcheck \
 && rm -rf /var/lib/apt/lists/*
RUN set -eu; base=https://github.com/mikefarah/yq/releases/latest/download; \
    curl -fsSL --retry 5 --retry-all-errors -o /usr/local/bin/yq "$base/yq_linux_amd64"; \
    i=$(curl -fsSL --retry 5 --retry-all-errors "$base/checksums_hashes_order" | grep -n '^SHA-256$' | cut -d: -f1); \
    sum=$(curl -fsSL --retry 5 --retry-all-errors "$base/checksums" | awk -v c=$((i + 1)) '$1 == "yq_linux_amd64" {print $c}'); \
    echo "$sum  /usr/local/bin/yq" | sha256sum -c -; chmod 755 /usr/local/bin/yq; yq --version

# Node.js LTS from nodejs.org, checked against its published SHA-256.
RUN set -eu; base="https://nodejs.org/dist/latest-v${NODE_MAJOR}.x"; \
    file=$(curl -fsSL --retry 5 --retry-all-errors "$base/SHASUMS256.txt" | awk '/linux-x64\.tar\.xz$/ {print $2}'); \
    sum=$(curl -fsSL --retry 5 --retry-all-errors "$base/SHASUMS256.txt" | awk '/linux-x64\.tar\.xz$/ {print $1}'); \
    curl -fsSL --retry 5 --retry-all-errors -o /tmp/node.tar.xz "$base/$file"; \
    echo "$sum  /tmp/node.tar.xz" | sha256sum -c -; \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1; rm /tmp/node.tar.xz; \
    node --version

# Chromium's system libraries, so a job installs only the browser
# (plugin-tests-wp.yml drops --with-deps on self-hosted runners).
RUN npx --yes playwright@latest install-deps chromium && rm -rf /var/lib/apt/lists/* /root/.npm

# The shared libraries setup-php's prebuilt PHP links against (#145). On a
# self-hosted runner setup-php installs PHP 8.3 and up from php-builder's
# builds, extracted straight onto the system, while an apt-get of their
# libraries runs beside it; when that apt-get fails the build is extracted
# anyway, and php does not start (libsodium) or loses the extensions it
# enables by default. These are the libraries `ldd` finds missing in the
# image for php and those extensions (8.3 to 8.5); PHP itself stays out.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libsodium23 \
      libaspell15 libenchant-2-2 libfbclient2 libgd3 liblmdb0 \
      libmagickwand-6.q16-7t64 libmemcached11t64 libodbc2 libodbcinst2 \
      libpq5 libqdbm14 librabbitmq4 libsnmp40t64 libsybdb5 libtidy5deb1 \
      libxslt1.1 libzip4t64 libzmq5 \
 && rm -rf /var/lib/apt/lists/*

# The runner, as the user `runner`, with password-less sudo like GitHub's.
RUN useradd -m -s /bin/bash runner \
 && echo 'runner ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/runner \
 && chmod 0440 /etc/sudoers.d/runner
WORKDIR /home/runner/actions-runner
RUN test -n "$RUNNER_VERSION" && test -n "$RUNNER_SHA256" \
 && curl -fsSL --retry 5 --retry-all-errors -o /tmp/runner.tgz "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
 && echo "${RUNNER_SHA256}  /tmp/runner.tgz" | sha256sum -c - \
 && tar -xzf /tmp/runner.tgz && rm /tmp/runner.tgz \
 && ./bin/installdependencies.sh && rm -rf /var/lib/apt/lists/* \
 && chown -R runner:runner /home/runner

COPY --chmod=755 entrypoint.sh /usr/local/bin/dx-runner-entrypoint
USER runner
ENTRYPOINT ["/usr/local/bin/dx-runner-entrypoint"]
