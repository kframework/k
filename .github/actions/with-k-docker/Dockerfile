ARG BASE_DISTRO

# ECR Public mirror of the Docker official images, without Docker Hub's pull rate limit.
FROM public.ecr.aws/docker/library/ubuntu:${BASE_DISTRO}

ARG K_DEB_PATH
ARG INSTALL_BACKEND_DEBS
ARG LLVM_BACKEND_DEB_PATH
ARG HASKELL_BACKEND_DEB_PATH

COPY ${K_DEB_PATH} /kframework.deb
COPY ${LLVM_BACKEND_DEB_PATH} /llvm-backend.deb
COPY ${HASKELL_BACKEND_DEB_PATH} /haskell-backend.deb

RUN    apt-get -y update    \
    && apt-get -y install   \
         curl               \
         graphviz           \
         make               \
         python3.10-dev     \
         python3.10-venv    \
         /kframework.deb

RUN if [ "${INSTALL_BACKEND_DEBS}" = "true" ]; then \
      apt-get -y install /llvm-backend.deb /haskell-backend.deb; \
    fi

RUN apt-get -y clean

RUN rm /llvm-backend.deb
RUN rm /kframework.deb


ARG USER_ID=9876
ARG GROUP_ID=9876
RUN    groupadd -g ${GROUP_ID} user                     \
    && useradd -m -u ${USER_ID} -s /bin/sh -g user user

USER user
WORKDIR /home/user

ENV PATH=/home/user/.local/bin:${PATH}

ARG UV_VERSION
RUN    curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | sh \
    && uv --version

ENV PATH=/home/user/.elan/bin:${PATH}
RUN    curl -O https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    && sh elan-init.sh -y \
    && rm elan-init.sh
