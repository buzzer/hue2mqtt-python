FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

COPY . /hue2mqtt-python

WORKDIR /hue2mqtt-python

RUN pip install --no-cache-dir -c constraints.txt . \
    && useradd --system --no-create-home hue2mqtt

USER hue2mqtt

# The config file is expected at /hue2mqtt-python/hue2mqtt.toml
CMD ["hue2mqtt"]
