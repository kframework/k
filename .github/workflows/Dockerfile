ARG BASE_IMAGE
ARG BASE_DISTRO
ARG K_VERSION

FROM stack:${BASE_DISTRO}-${K_VERSION} AS stack-deps

FROM maven:${BASE_DISTRO}-${K_VERSION} AS maven-cache

FROM ${BASE_IMAGE}

ENV TZ America/Chicago
ENV DEBIAN_FRONTEND=noninteractive

ARG LLVM_VERSION
ARG JDK_VERSION

RUN    apt-get update              \
    && apt-get install --yes       \
        bison                      \
        build-essential            \
        clang-${LLVM_VERSION}      \
        cmake                      \
        curl                       \
        debhelper                  \
        flex                       \
        gcc                        \
        git                        \
        libboost-test-dev          \
        libbz2-dev                 \
        libffi-dev                 \
        libfmt-dev                 \
        libgdbm-dev                \
        libgmp-dev                 \
        libjemalloc-dev            \
        libmpfr-dev                \
        libncurses5-dev            \
        libnss3-dev                \
        libreadline-dev            \
        libsecp256k1-dev           \
        libsqlite3-dev             \
        libssl-dev                 \
        libunwind-dev              \
        libyaml-dev                \
        libz3-dev                  \
        lld-${LLVM_VERSION}        \
        llvm-${LLVM_VERSION}-tools \
        locales                    \
        lsof                       \
        maven                      \
        openjdk-${JDK_VERSION}-jdk \
        parallel                   \
        pkg-config                 \
        python3                    \
        python3-dev                \
        python3-pip                \
        unzip                      \
        xxd                        \
        zlib1g-dev

# Install the upstream Z3 release binary rather than pulling a prebuilt image from Docker Hub.
# The checksum is for the zip of Z3_VERSION (deps/z3): when bumping it, update Z3_SHA256, and
# Z3_ZIP if the asset name changed.
ARG Z3_VERSION
ARG Z3_SHA256=93f91f9c6f4a00a041c19fc7a74adc1f441c8244ce70d486e19abcd89c6a014b
ARG Z3_ZIP=z3-${Z3_VERSION}-x64-glibc-2.35
RUN    curl --fail --silent --show-error --location --output /tmp/z3.zip                             \
         "https://github.com/Z3Prover/z3/releases/download/z3-${Z3_VERSION}/${Z3_ZIP}.zip" \
    && echo "${Z3_SHA256}  /tmp/z3.zip" | sha256sum --check --strict                              \
    && unzip -j /tmp/z3.zip "${Z3_ZIP}/bin/z3" -d /usr/bin                                         \
    && rm /tmp/z3.zip

COPY --from=stack-deps /usr/local/bin/stack /usr/local/bin/stack

RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8

# The image is built specifically for an environment with this user/group
ARG USER=github-user
ARG GROUP=$USER
ARG USER_ID=1000
ARG GROUP_ID=$USER_ID
RUN groupadd -g $GROUP_ID $GROUP && useradd -m -u $USER_ID -s /bin/sh -g $GROUP $USER

USER $USER:$GROUP
# The sources are copied in here, see .github/actions/with-docker.
RUN mkdir /home/$USER/workspace
WORKDIR /home/$USER/workspace

COPY --from=stack-deps --chown=$USER:$GROUP /home/$USER/.stack /home/$USER/.stack
COPY --from=maven-cache --chown=$USER:$GROUP /home/$USER/.m2 /home/$USER/.m2
