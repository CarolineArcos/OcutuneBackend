from flask import Blueprint, request, jsonify
from mysql_db import get_db_connection
import json
sensor_bp = Blueprint("sensor_bp", __name__)

# … eksisterende ruter som /patient-battery-status og /patient-light-data …

@sensor_bp.route("/error-logs", methods=["POST"])
def log_error():
    """
    POST /api/error-logs
    Modtager en JSON med information om en mislykket synkronisering eller anden fejl,
    og gemmer den i tabellen 'error_logs'.
    Eksempel på payload fra klienten:
      {
        "endpoint": "/api/sensor/patient-light-data",
        "payload": { … den JSON, der blev forsøgt sendt … },
        "error_message": "400 – {\"error\":\"name 'sensor_id' is not defined\",\"success\":false}"
      }
    """
    data = request.get_json()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        endpoint = data.get("endpoint", "")            # F.eks. "/api/sensor/patient-light-data"
        payload_json = json.dumps(data.get("payload", {}))  # Gemmer selve JSON‐objektet som streng
        error_msg = data.get("error_message", "")

        cursor.execute(
            """
            INSERT INTO error_logs (endpoint, payload, error_message)
            VALUES (%s, %s, %s)
            """,
            (endpoint, payload_json, error_msg),
        )
        conn.commit()

        print(f"[{__name__}] Fejllog gemt: endpoint='{endpoint}', error_message='{error_msg[:50]}…'")
        return jsonify({"success": True}), 200

    except Exception as e:
        # Hvis selve indsættelsen i error_logs fejler, returner 500 eller 400
        print(f"[{__name__}] FEJL i log_error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
