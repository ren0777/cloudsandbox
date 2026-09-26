# CloudLabs AWS emulator engine: MiniStack (MIT), pinned. Used ONLY for labs that pin
# runtime.emulator: ministack because they must execute Lambda code: MiniStack runs functions in-process,
# so no Docker socket is needed (EMULATOR-EVALUATION.md, Lambda decision). Non-root, read-only rootfs;
# state lives in the runner-mounted tmpfs /tmp.
FROM ministackorg/ministack:1.5.16
ENV S3_PERSIST=0 LOG_LEVEL=WARNING
USER 10001
HEALTHCHECK --interval=1s --timeout=3s --retries=60 CMD ["python", "-c", "import urllib.request as r; r.urlopen('http://127.0.0.1:4566/_ministack/health')"]
EXPOSE 4566
LABEL cloudlabs.image=emulator cloudlabs.engine=ministack cloudlabs.ministack_version=1.5.16
