import websocket
import json
import paho.mqtt.client as mqtt
import requests
import time

# --------------------------
# 🔹 Wiser & MQTT Konfiguration
# --------------------------
WS_URL = "ws://192.168.1.109/api"
AUTH_TOKEN = "Bearer c2ce9b6a-fd7c-4f14-a313-a3db811f55e5"

MQTT_BROKER = "192.168.1.144"
MQTT_PORT = 1883
MQTT_USERNAME = "mqtt_user"
MQTT_PASSWORD = "Loris2013"

MQTT_TOPIC_SHUTTERS = "wiser/shutters"
MQTT_TOPIC_LIGHTS = "wiser/lights"

WISER_MAX_LEVEL = 10000  # Wiser gibt Level von 0 bis 10000 aus
LAST_MQTT_COMMANDS = {}
LAST_WISER_STATES = {}

# --------------------------
# 🔹 MQTT-Client einrichten
# --------------------------
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

def on_mqtt_message(client, userdata, msg):
    """Empfängt MQTT-Befehle und sendet API-Befehle an Wiser."""
    try:
        payload = json.loads(msg.payload.decode())
        device_id = payload["id"]

        # 🔹 **Lichtsteuerung**
        if msg.topic.startswith(MQTT_TOPIC_LIGHTS):
            state = payload.get("state", None)
            brightness = payload.get("bri", 1000 if state else 0)  # Standard auf 1000 setzen

            print(f"📩 MQTT-Befehl für Licht: {msg.topic} → {payload}")
            set_wiser_light(device_id, state, brightness)
            return

        # 🔹 **Rolladensteuerung**
        button = payload.get("button", None)  # up, down, stop, toggle
        if not button:
            return

        # `toggle`-Logik: Entscheidet zwischen `up` oder `down`
        if button == "toggle":
            current_level = LAST_WISER_STATES.get(device_id, 50)  # Standardwert: 50%
            button = "up" if current_level < 50 else "down"
            print(f"🔄 Toggle-Befehl erkannt: Setze auf `{button}`")

        # Verhindere doppelte Befehle
        if LAST_MQTT_COMMANDS.get(device_id) == button:
            print(f"⚠ Befehl ignoriert: Raffstore {device_id} ist bereits auf `{button}`.")
            return

        send_wiser_shutter(device_id, button)
        LAST_MQTT_COMMANDS[device_id] = button

    except Exception as e:
        print(f"⚠ Fehler beim Verarbeiten der MQTT-Nachricht: {e}")

mqtt_client.on_message = on_mqtt_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.subscribe(f"{MQTT_TOPIC_SHUTTERS}/+")
mqtt_client.subscribe(f"{MQTT_TOPIC_LIGHTS}/+")
mqtt_client.loop_start()

# --------------------------
# 🔹 Wiser API: Raffstore steuern
# --------------------------
def send_wiser_shutter(device_id, button):
    """Sendet einen Steuerbefehl an Wiser für Raffstores."""
    url = f"http://192.168.1.109/api/loads/{device_id}/ctrl"
    headers = {"Authorization": AUTH_TOKEN, "Content-Type": "application/json"}

    event = "press" if button in ["up", "down"] else "click"  # Lange oder kurze Taste
    data = json.dumps({"button": button, "event": event})

    try:
        response = requests.put(url, headers=headers, data=data, timeout=5)
        if response.status_code == 200:
            print(f"✅ Raffstore {device_id} → {button} ({event}) ausgelöst!")
        else:
            print(f"❌ Fehler beim Bewegen von {device_id}: {response.status_code} - {response.text}")
    except requests.RequestException as e:
        print(f"⚠ API-Fehler für Raffstore {device_id}: {e}")

# --------------------------
# 🔹 Wiser API: Licht steuern
# --------------------------
def set_wiser_light(device_id, state, brightness):
    """Schaltet eine Wiser Lampe ein/aus und setzt die Helligkeit."""
    url = f"http://192.168.1.109/api/loads/{device_id}/target_state"
    headers = {"Authorization": AUTH_TOKEN, "Content-Type": "application/json"}
    data = json.dumps({"state": "on" if state else "off", "bri": brightness})

    try:
        response = requests.put(url, headers=headers, data=data, timeout=5)
        if response.status_code == 200:
            print(f"✅ Licht {device_id} → {'on' if state else 'off'} mit Helligkeit {brightness} gesetzt!")
        else:
            print(f"❌ Fehler beim Schalten von Licht {device_id}: {response.status_code} - {response.text}")
    except requests.RequestException as e:
        print(f"⚠ API-Fehler für Licht {device_id}: {e}")

# --------------------------
# 🔹 WebSocket empfängt Statusänderungen von Wiser
# --------------------------
def on_websocket_message(ws, message):
    """Empfängt Statusänderungen von Wiser & sendet den Level-Wert über MQTT."""
    print(f"📩 Wiser Nachricht erhalten: {message}")
    data = json.loads(message)

    if "load" in data:
        device_id = data["load"]["id"]
        state_data = data["load"]["state"]

        # Rolladen-Level auslesen und senden
        if "level" in state_data:
            level = state_data["level"]
            moving = state_data.get("moving", "stop")
            print(f"📤 MQTT gesendet: wiser/shutters/{device_id}/status → Level: {level}%, Bewegung: {moving}")
            mqtt_payload = json.dumps({"id": device_id, "level": level, "moving": moving})
            mqtt_client.publish(f"wiser/shutters/{device_id}/status", mqtt_payload, retain=True)

        # Lichtstatus auslesen und senden
        if "bri" in state_data:
            brightness = state_data["bri"]
            state = brightness > 0  # Licht ist an, wenn Helligkeit > 0
            print(f"📤 MQTT gesendet: wiser/lights/{device_id}/status → State: {state}, Brightness: {brightness}")
            mqtt_payload = json.dumps({"id": device_id, "state": state, "bri": brightness})
            mqtt_client.publish(f"wiser/lights/{device_id}/status", mqtt_payload, retain=True)

# --------------------------
# 🔹 WebSocket starten
# --------------------------
HEADERS = [
    f"Authorization: {AUTH_TOKEN}",
    "Sec-WebSocket-Version: 13",
    "Upgrade: websocket",
    "Connection: Upgrade"
]

ws = websocket.WebSocketApp(
    WS_URL,
    header=HEADERS,
    on_message=on_websocket_message,
    on_error=lambda ws, err: print(f"❌ WebSocket-Fehler: {err}"),
    on_close=lambda ws, status, msg: print("🔌 WebSocket Verbindung geschlossen")
)

# WebSocket mit Auto-Reconnect starten
while True:
    try:
        print("🔗 WebSocket wird gestartet...")
        ws.run_forever()
    except Exception as e:
        print(f"⚠ WebSocket-Fehler: {e}, Neustart in 5 Sekunden...")
        time.sleep(5)
