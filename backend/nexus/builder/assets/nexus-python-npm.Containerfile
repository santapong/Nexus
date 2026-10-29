# SOURCE TEMPLATE ONLY: no base/image/test-dependency/cold-cache qualification exists here.
# Root must supply a validated platform leaf digest and matching fully frozen offline context.
# No mutable tag/default, downloader, package manager network, or host cache fallback.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG MANIFEST_SHA256
COPY tools/uv /opt/uv/uv
COPY tools/node/ /opt/node/
COPY python-build/ /opt/nexus-build-venv/
COPY python-test/ /opt/nexus-test-venv/
COPY node_modules/ /opt/nexus-node-modules/
COPY recipe/ /opt/nexus-recipe/
# Fixed .vite-temp symlink is part of the frozen node tree; its only target is scratch.
# check.py, manifest.json, Containerfile, build requirements and both npmrc files are pinned.
RUN /usr/local/bin/python3.12 /opt/nexus-recipe/check.py image-check --manifest-sha256 "$MANIFEST_SHA256"
ENV PATH=/opt/node/bin:/usr/local/bin:/usr/bin:/bin
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
