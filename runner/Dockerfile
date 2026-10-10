# The organisation's runner image (ghcr.io/diluxone/runner). Every job on the
# organisation's VM runs in a fresh container of it and the container is
# discarded when the job ends (scripts/runner-vm/dx-runner-slot.sh), so no job
# sees what another installed. It carries what every stack needs and nothing a
# job should install itself: jobs still pick their PHP, Node or Python with the
# setup-* actions, as on GitHub's runners. Rebuilt every week and promoted to
# :stable only after a smoke test (.github/workflows/runner-image.yml).
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
 && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/*

# Node.js LTS from nodejs.org, checked against its published SHA-256.
RUN set -eu; base="https://nodejs.org/dist/latest-v${NODE_MAJOR}.x"; \
    file=$(curl -fsSL "$base/SHASUMS256.txt" | awk '/linux-x64\.tar\.xz$/ {print $2}'); \
    sum=$(curl -fsSL "$base/SHASUMS256.txt" | awk '/linux-x64\.tar\.xz$/ {print $1}'); \
    curl -fsSL -o /tmp/node.tar.xz "$base/$file"; \
    echo "$sum  /tmp/node.tar.xz" | sha256sum -c -; \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1; rm /tmp/node.tar.xz; \
    node --version

# Chromium's system libraries, so a job installs only the browser
# (plugin-tests-wp.yml drops --with-deps on self-hosted runners).
RUN npx --yes playwright@latest install-deps chromium && rm -rf /var/lib/apt/lists/* /root/.npm

# The runner, as the user `runner`, with password-less sudo like GitHub's.
RUN useradd -m -s /bin/bash runner \
 && echo 'runner ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/runner \
 && chmod 0440 /etc/sudoers.d/runner
WORKDIR /home/runner/actions-runner
RUN test -n "$RUNNER_VERSION" && test -n "$RUNNER_SHA256" \
 && curl -fsSL -o /tmp/runner.tgz "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
 && echo "${RUNNER_SHA256}  /tmp/runner.tgz" | sha256sum -c - \
 && tar -xzf /tmp/runner.tgz && rm /tmp/runner.tgz \
 && ./bin/installdependencies.sh && rm -rf /var/lib/apt/lists/* \
 && chown -R runner:runner /home/runner

COPY entrypoint.sh /usr/local/bin/dx-runner-entrypoint
USER runner
ENTRYPOINT ["/usr/local/bin/dx-runner-entrypoint"]
