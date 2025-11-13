from flask import Flask, render_template, request, redirect, session
import math
import requests  # Para hacer la petición al Jetson

app = Flask(__name__)

app.secret_key = "super-secret-key"  # Requerido para usar session

JETSON_URL = "http://*.*.*.*:6000/predict"  # IP y puerto del Nano
DITTO_URL = "http://*.*.*.*:8080/api/2/things/org.acme:my-dev/attributes/reactorState"

# 🔹 Función para consultar estado en Ditto
def get_reactor_state():
    try:
        ditto_response = requests.get(
            DITTO_URL,
            auth=("ditto", "ditto"),
            timeout=5
        )
        if ditto_response.status_code == 200:
            return ditto_response.json()
        else:
            return "unknown"
    except Exception as e:
        print(f"Error consultando Ditto: {e}")
        return "unknown"

@app.route('/')
def index():
    reactor_state = get_reactor_state()
    return render_template('index.html', reactor_state=reactor_state)

@app.route('/predict', methods=['POST'])
def predict():
    try:
        variedad = int(request.form['variedad'])
        categoria_puntaje = int(request.form['categoria_puntaje'])
        altura = float(request.form['altura'])
        cantidad = float(request.form['cantidad'])
        ph = float(request.form['ph'])
        temperatura = float(request.form['temperatura'])

        payload = {
            "Variedad": variedad,
            "Altura": altura,
            "Cantidad (L)": cantidad,
            "pH": ph,
            "Temperatura": temperatura,
            "Categoria_Puntaje": categoria_puntaje
        }

        # Petición al Jetson
        response = requests.post(JETSON_URL, json=payload)
        result = response.json()

        if "prediccion" in result:
            prediccion = result["prediccion"]

            tiempo_segundos = int(prediccion * 3600)
            session["last_payload"] = {**payload, "tiempo_predicho_horas": round(prediccion, 2), "tiempo_predicho_segundos": tiempo_segundos}

            # Convertir la predicción a formato hh:mm
            horas = math.trunc(prediccion)
            minutos = int((prediccion - horas) * 60)

            # Formatear la cadena para que tenga dos dígitos
            prediccion_formateada = f'{horas:02d}:{minutos:02d}'

            return render_template('index.html', prediccion=prediccion_formateada, reactor_state=get_reactor_state())
        else:
            return f"Error en la predicción: {result.get('error', 'desconocido')}", 500

    except Exception as e:
        return f"Error en los datos de entrada: {e}", 400

@app.route('/start_fermentacion')
def start_fermentacion():
    try:
        # Recuperar los últimos datos ingresados por el usuario.
        payload = session.get("last_payload")  # payload guardado en predict()
        print (payload)

        if not payload:
            return "No hay datos de predicción disponibles", 400

        # Disparar flujo en Kestra
        KESTRA_URL = "http://KESTRA_IP:KESTRA_PORT/api/v1/main/executions/cafe/fermentacion-proceso"
        kestra_payload = {
        "Altura": str(payload.get("Altura")),
        "Cantidad_L": str(payload.get("Cantidad (L)")),
        "Categoria_Puntaje": str(payload.get("Categoria_Puntaje")),
        "Temperatura": str(payload.get("Temperatura")),
        "Variedad": str(payload.get("Variedad")),
        "pH": str(payload.get("pH")),
        "tiempo_predicho_horas": str(payload.get("tiempo_predicho_horas")),
        "tiempo_predicho_segundos": str(payload.get("tiempo_predicho_segundos"))
    }

        username="KESTRA_USER"
        password="KESTRA_PASSWORD"
        kestra_response = requests.post(KESTRA_URL, files=kestra_payload, auth=(username, password))

        if kestra_response.status_code not in (200, 201):
            return f"Error al disparar flujo en Kestra: {kestra_response.text}", 500

        # Redirigir a Grafana
        return redirect("http://192.168.1.43:3000")

    except Exception as e:
        return f"Error al iniciar fermentación: {e}", 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)  # Tu PC abre el puerto
