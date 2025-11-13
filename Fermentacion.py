from flask import Flask, request, jsonify
import onnxruntime as ort
import numpy as np
import pandas as pd
import pickle
import serial
import subprocess
import json
import time
import threading
import requests
from influxdb_client import InfluxDBClient
import usbrelay_py

app = Flask(__name__)

#####Modelo Time
# Proveedores de ejecución
providers = ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']

# Cargar modelo
modelo = ort.InferenceSession("modelo_TimeFx.onnx", providers=providers)

# Cargar columnas
with open("columnas_Xx.pkl", "rb") as f:
    columnas = pickle.load(f)

#####Data Gathering & Sensor State
# Configuración del puerto serial
SERIAL_PORT = '/dev/ttyUSB0'
BAUD_RATE = 115200

# Configuración Ditto
DITTO_IP = "http://localhost"
DITTO_PORT = "8080"
THING_ID = "org.acme:my-dev"
USERNAME = "ditto"
PASSWORD = "ditto"

publishing = False
state_publishing = False
serial_conn = None
thread = None
state_thread = None
last_data = {}         # Últimos datos recibidos
last_update_time = {}  # Última vez que se actualizó cada sensor

# Función para actualizar propiedad en Ditto
def update_features(values: dict):
    url = f"{DITTO_IP}:{DITTO_PORT}/api/2/things/{THING_ID}/features"
    payload = {}
    for key, val in values.items():
        payload[key] = {"properties": {"value": val}}

    try:
        r = requests.put(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            auth=(USERNAME, PASSWORD),
            timeout=5
        )
    except Exception as e:
        print(f"[ERROR] No se pudo enviar PUT: {e}")

# Función de lectura y publicación
last_valid_json = None  # Último JSON válido almacenado

def read_and_publish():
    global publishing, serial_conn, last_data, last_update_time, last_valid_json
    while publishing:
        try:
            line = serial_conn.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

            try:
                data = json.loads(line)  # Intento de parseo del JSON recibido
                last_valid_json = data  # Actualizar respaldo
            except json.JSONDecodeError:
                print(f"[{timestamp_str}][WARN] Datos inválidos recibidos (no es JSON)")
                # Usar último JSON válido si existe
                if last_valid_json is not None:
                    data = last_valid_json.copy()
                    print(f"[{timestamp_str}][INFO] Usando último JSON válido como respaldo")
                else:
                    # No hay respaldo disponible aún
                    time.sleep(10)
                    continue

            # Filtrar null/NaN
            clean_data = {
                k: v
                for k, v in data.items()
                if v is not None and not (isinstance(v, float) and (v != v))
            }

            timestamp = time.time()

            # Publicar cada sensor
            sensors_to_send = {}
            for key in ["temperature", "ph", "alcohol", "brix", "pressure"]:
                if key in clean_data:
                    sensors_to_send[key] = clean_data[key]
                    last_data[key] = clean_data[key]
                    last_update_time[key] = timestamp

            if sensors_to_send:
                update_features(sensors_to_send)

        except Exception as e:
            print(f"[{timestamp_str}][ERROR] {e}")

        time.sleep(10)

# Función para actualizar estados
# ==============================
def update_states():
    global state_publishing, last_data, last_update_time
    while state_publishing:
        now = time.time()

        # Definir rangos razonables
        ranges = {
            "temperature": (-50, 120),
            "ph": (0, 14),
            "alcohol": (0, 7),
            "brix": (0, 15),
            "pressure": (0, 150),
        }

        states_to_send = {}
        for sensor, (low, high) in ranges.items():
            state_feature = f"{sensor}State"

            if sensor not in last_data:
                states_to_send[state_feature] = 0  # Inactivo
                continue

            value = last_data[sensor]
            last_time = last_update_time.get(sensor, 0)

            if now - last_time > 25:  # No se recibe dato en 25s
                states_to_send[state_feature] = 2  # Falla
            elif value is None or not (low <= value <= high):
                states_to_send[state_feature] = 2  # Falla
            else:
                states_to_send[state_feature] = 1  # Operando

        if states_to_send:
            update_features(states_to_send)

        time.sleep(10)

#####Modelo Temperatura
INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "Ow3PqYUGHxJ2OK7Tnsaqc9Vtl4OT9SITySvA3Nog_qV70j4GVwE3tgCvL8KPZZjV2xsNMH13XwpOPuyDUVt3_w=="
INFLUX_ORG = "cafe"
INFLUX_BUCKET = "biorreactor"

influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api = influx_client.query_api()

ONNX_MODEL_PATH = "modelo_Temp1m.onnx"

HIST_MINUTES = 10
FREQ_MINUTES = 1

variables = ["Temperatura", "pH", "Presión", "Altura", "Cantidad (L)", "Variedad"]

# CARGAR MODELO ONNX
providers = ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
session = ort.InferenceSession(ONNX_MODEL_PATH, providers=providers)
input_name = session.get_inputs()[0].name
output_name = session.get_outputs()[0].name

#####Relay control
board_count = usbrelay_py.board_count()
if board_count == 0:
    raise RuntimeError("No se detectaron relés USB")

boards = usbrelay_py.board_details()
board_id = boards[0][0]  # Tomamos el primer board detectado
print(f"Usando board: {board_id}")

@app.route('/predict', methods=['POST'])
def predict():
    data = request.get_json()  # Espera un JSON
    try:
        input_df = pd.DataFrame([data])
        input_df = pd.get_dummies(input_df)
        input_df = input_df.reindex(columns=columnas, fill_value=0)

        inputs = {modelo.get_inputs()[0].name: input_df.astype(np.float32).values}
        pred = modelo.run(None, inputs)[0]
        prediccion = float(pred[0][0])

        return jsonify({"prediccion": prediccion})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/start_sensors", methods=["POST"])
def control():
    global publishing, thread, serial_conn

    content = request.get_json()
    if not content or "publish" not in content:
        return jsonify({"error": "Falta parámetro 'publish'"}), 400

    if content["publish"] and not publishing:
        # Activar publicación
        try:
            serial_conn = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            serial_conn.reset_input_buffer()
            while True:
                line = serial_conn.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    json.loads(line)  # Intento de parseo
                    break  # Si es JSON válido, salimos del bucle
                except json.JSONDecodeError:
                    print("[INIT] Descartando línea inicial inválida:", line)
                    continue
            publishing = True
            thread = threading.Thread(target=read_and_publish, daemon=True)
            thread.start()
            return jsonify({"status": "publicación iniciada"}), 200
        except Exception as e:
            return jsonify({"error": f"No se pudo abrir el puerto serial: {e}"}), 500

    elif not content["publish"] and publishing:
        # Detener publicación
        publishing = False
        if serial_conn:
            serial_conn.close()
        return jsonify({"status": "publicación detenida"}), 200

    else:
        return jsonify({"status": "sin cambios"}), 200

@app.route("/state_control", methods=["POST"])
def state_control():
    global state_publishing, state_thread
    content = request.get_json()
    if not content or "publish" not in content:
        return jsonify({"error": "Falta parámetro 'publish'"}), 400

    if content["publish"] and not state_publishing:
        state_publishing = True
        state_thread = threading.Thread(target=update_states, daemon=True)
        state_thread.start()
        return jsonify({"status": "estado iniciado"}), 200

    elif not content["publish"] and state_publishing:
        state_publishing = False
        # Forzar a inactivo (0) todos los sensores
        states_off = {f"{sensor}State": 0 for sensor in ["temperature", "ph", "alcohol", "brix", "pressure"]}
        update_features(states_off)

        return jsonify({"status": "estado detenido"}), 200

    else:
        return jsonify({"status": "sin cambios"}), 200

@app.route("/predict_temp", methods=["POST"])
def predict_temp():
    try:
        data = request.get_json()
        if not all(k in data for k in ["variedad", "cantidad", "altura"]):
            return jsonify({"error": "Faltan parámetros: variedad, cantidad, altura"}), 400

        variedad = float(data["variedad"])
        cantidad = float(data["cantidad"])
        altura = float(data["altura"])

        # -------------------
        # Consultar InfluxDB
        # -------------------

        query = f'''
        import "timezone"
        import "strings"
        option location = timezone.location(name: "America/Bogota")

        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -{HIST_MINUTES}m)
          |> filter(fn: (r) => r["_field"] == "temperature" or r["_field"] == "ph" or r["_field"] == "pressure")
          |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
          |> keep(columns: ["_time", "temperature", "ph", "pressure"])
          |> map(fn: (r) =>  ({{ r with _time: strings.substring(v: string(v: r._time), start: 0, end: 19)}}))
          |> sort(columns: ["_time"], desc: false)
        '''
        df = query_api.query_data_frame(query)

        # query_data_frame puede devolver lista de DF -> concatenamos
        if isinstance(df, list):
            df = pd.concat(df)

        if df.empty:
            return jsonify({"error": "No hay datos en InfluxDB"}), 400

        # Nos quedamos solo con columnas necesarias
        df = df[["_time", "temperature", "ph", "pressure"]].copy()

        # Asegurar tipos correctos
        df["_time"] = pd.to_datetime(df["_time"])
        df = df.set_index("_time")

        numeric_columns = ["temperature", "ph", "pressure"]
        for col in numeric_columns:
            df[col] = df[col].astype("float32")

        step = f"{int(FREQ_MINUTES*60)}s"  # ej: "6s" o "10s"
        df_resampled = df.resample(step).mean().dropna()

        pasos_historial = int(HIST_MINUTES / FREQ_MINUTES)
        if len(df_resampled) < pasos_historial:
            return jsonify({"error": "No hay suficientes datos en InfluxDB"}), 400

        df_resampled = df_resampled.tail(pasos_historial)

        # Renombrar
        df_resampled = df_resampled.rename(columns={
            "temperature": "Temperatura",
            "ph": "pH",
            "pressure": "Presión"
        })

        df_resampled = df_resampled.reset_index(drop=True)

        # -------------------
        # Construir vector de entrada
        # -------------------
        X_input = []
        for var in variables:
            if var == "Altura":
                X_input.extend([altura] * pasos_historial)
            elif var == "Cantidad (L)":
                X_input.extend([cantidad] * pasos_historial)
            elif var == "Variedad":
                X_input.extend([variedad] * pasos_historial)
            else:
                X_input.extend(df_resampled[var].values.tolist())

        X_input = np.array(X_input, dtype=np.float32).reshape(1, -1)

        # -------------------
        # Predicción
        # -------------------
        pred = session.run([output_name], {input_name: X_input})[0]
        prediccion = float(pred[0])

        update_features({"tempPrediction": prediccion})

        return jsonify(
            prediccion
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/cooling", methods=["POST"])
def control_relay():
    data = request.get_json()

    if "cooling" not in data:
        return jsonify({"error": "Falta la llave 'cooling'"}), 400

    state = data["cooling"]

    if state is True:
        result = usbrelay_py.board_control(board_id, 1, 1)  # ON
        ditto_ok = update_features({"cooling": 1})
        return jsonify({"relay": "cooling", "state": "on", "result": result, "ditto_updated": ditto_ok})
    elif state is False:
        result = usbrelay_py.board_control(board_id, 1, 0)  # OFF
        ditto_ok = update_features({"cooling": 0})
        return jsonify({"relay": "cooling", "state": "off", "result": result, "ditto_updated": ditto_ok})
    else:
        return jsonify({"error": "El valor de 'cooling' debe ser true o false"}), 400

@app.route('/stop_fermentacion', methods=["POST"])
def stop_fermentacion():
    global publishing, state_publishing, serial_conn

    # Detener hilos de publicación
    publishing = False
    state_publishing = False

    if serial_conn:
        try:
            serial_conn.close()
        except:
            pass

    # Desactivar enfriamiento por seguridad
    requests.post("http://localhost:6000/cooling", json={"cooling": False})

    # Enviar estado a Ditto
    update_attributes({
        "reactorState": "inactive",
        "variedad": "-",
        "cantidad": "-",
        "altura": "-"
    })

    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6000, debug=False, threaded=True)  # expone el puerto 6000