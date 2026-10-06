# CloudLabs student terminal: AWS CLI v2 + ttyd, non-root "student". Nothing lab-specific is baked in.
# Pinned and checksum-verified downloads: changing a version means updating its sha256 below (ttyd hashes are
# the release's SHA256SUMS; AWS publishes no checksums, so the AWS CLI hashes were taken from the pinned zips).
FROM debian:bookworm-slim
ARG TARGETARCH
ARG AWSCLI_VERSION=2.37.1
ARG AWSCLI_SHA256_AMD64=61a79950dfb436985611a258d3a8f85a47e13498fcc72c7d8d0597f5c9fde133
ARG AWSCLI_SHA256_ARM64=30642dc4840012614229feb68314637d024500f565d92f513a422bdd55844a90
ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256_AMD64=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
ARG TTYD_SHA256_ARM64=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
      amd64) ARCH=x86_64;  AWS_SHA="$AWSCLI_SHA256_AMD64"; TTYD_SHA="$TTYD_SHA256_AMD64" ;; \
      arm64) ARCH=aarch64; AWS_SHA="$AWSCLI_SHA256_ARM64"; TTYD_SHA="$TTYD_SHA256_ARM64" ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip jq less groff-base bash-completion python3 zip nano vim-tiny procps \
 && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}-${AWSCLI_VERSION}.zip" -o /tmp/awscli.zip \
 && echo "${AWS_SHA}  /tmp/awscli.zip" | sha256sum -c - \
 && unzip -q /tmp/awscli.zip -d /tmp && /tmp/aws/install && rm -rf /tmp/aws /tmp/awscli.zip \
 && curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${ARCH}" -o /usr/local/bin/ttyd \
 && echo "${TTYD_SHA}  /usr/local/bin/ttyd" | sha256sum -c - \
 && chmod 0755 /usr/local/bin/ttyd \
 && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10002 --create-home --shell /bin/bash student \
 && mkdir -p /work && chown student:student /work
COPY bashrc /etc/cloudlabs.bashrc
COPY entrypoint.sh /usr/local/bin/cloudlabs-terminal
RUN chmod 0755 /usr/local/bin/cloudlabs-terminal && echo 'source /etc/cloudlabs.bashrc' >> /etc/bash.bashrc
USER 10002
WORKDIR /home/student
EXPOSE 7681
ENTRYPOINT ["/usr/local/bin/cloudlabs-terminal"]
LABEL cloudlabs.image=terminal cloudlabs.awscli_version=${AWSCLI_VERSION} cloudlabs.ttyd_version=${TTYD_VERSION}
