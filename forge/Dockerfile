ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.name="Forge" \
    io.hass.description="Multi-instance Home Assistant entity bridge and importer" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN apk add --no-cache python3 py3-pip

COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY ui /app/ui
COPY run.sh /run.sh

RUN chmod a+x /run.sh

EXPOSE 8099

CMD ["/run.sh"]
