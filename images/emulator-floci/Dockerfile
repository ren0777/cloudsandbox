# CloudLabs AWS emulator engine: Floci (MIT), pinned. Runs non-root with a read-only rootfs; the runner
# mounts tmpfs at /tmp and /app/data (see runner EmulatorSpec). No Docker socket is ever mounted, so
# Docker-backed Floci features (Lambda invoke, real EC2) are unavailable by design.
FROM floci/floci:2.1.0
ENV FLOCI_STORAGE_MODE=memory
USER 10001
# The base entrypoint only fixes Docker-socket groups when started as root; run the binary directly.
ENTRYPOINT []
CMD ["/app/application", "-Dquarkus.http.host=0.0.0.0"]
HEALTHCHECK --interval=1s --timeout=2s --retries=60 CMD ["/usr/local/bin/healthcheck.sh"]
EXPOSE 4566
LABEL cloudlabs.image=emulator cloudlabs.engine=floci cloudlabs.floci_version=2.1.0
