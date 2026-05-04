ARG BUILD_VERSION=0.1.0
ARG BUILD_ARCH=amd64
ARG BUILD_FROM=ghcr.io/home-assistant/base:latest

FROM $BUILD_FROM

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache python3 py3-pip

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir --break-system-packages -r /app/requirements.txt

COPY src /app/src
COPY ui /app/ui
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
