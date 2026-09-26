# CloudLabs student terminal: AWS CLI v2 + ttyd, non-root "student". Nothing lab-specific is baked in.
FROM debian:bookworm-slim
ARG TTYD_VERSION=1.7.7
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip jq less groff-base bash-completion python3 zip nano vim-tiny procps \
 && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscli.zip \
 && unzip -q /tmp/awscli.zip -d /tmp && /tmp/aws/install && rm -rf /tmp/aws /tmp/awscli.zip \
 && curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64" -o /usr/local/bin/ttyd \
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
LABEL cloudlabs.image=terminal
