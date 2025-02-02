FROM ghcr.io/home-assistant/aarch64-base-python:3.11
WORKDIR /app
COPY wiser_websocket.py /app/wiser_websocket.py
RUN pip install requests paho-mqtt websocket-client
CMD ["python3", "/app/wiser_websocket.py"]