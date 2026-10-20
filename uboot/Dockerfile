FROM ubuntu:24.04
RUN apt-get update -qq \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
      build-essential bison flex bc libssl-dev libgnutls28-dev uuid-dev \
      python3 python3-dev python3-setuptools python3-pyelftools swig \
      device-tree-compiler git ca-certificates \
      e2fsprogs mtools xz-utils gzip \
 && if [ "$(dpkg --print-architecture)" != arm64 ]; then \
      DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends gcc-aarch64-linux-gnu; \
    fi \
 && rm -rf /var/lib/apt/lists/*
