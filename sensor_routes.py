# routes/sensor_routes.py

from flask import Blueprint, request, jsonify
from mysql_db import get_db_connection
import json
from datetime import datetime

sensor_bp = Blueprint("sensor_bp", __name__)

@sensor_bp.route('/log', methods=['POST'])
def log_sensor_event():
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.callproc('log_sensor_event', [
            data['sensor_id'],
            data['patient_id'],
            data['event_type']
        ])
        conn.commit()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@sensor_bp.route("/patient-battery-status", methods=["POST"])
def battery_status():
    """
    POST /api/sensor/patient-battery-status
    Indsætter patient_id, sensor_id og battery_level i patient_battery_status.
    Logger til terminal, når opslaget lykkes.
    """
    data = request.get_json()
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        patient_id = data["patient_id"]
        sensor_id  = data.get("sensor_id")       # Kan være None
        battery_lvl = data["battery_level"]

        # Eksekver INSERT
        cursor.execute(
            """
            INSERT INTO patient_battery_status (patient_id, sensor_id, battery_level)
            VALUES (%s, %s, %s)
            """,
            (patient_id, sensor_id, battery_lvl),
        )
        conn.commit()

        # --- Printe til terminalen:
        print(f"[{__name__}] Ny batteri‐status modtaget: "
              f"patient_id={patient_id}, sensor_id={sensor_id}, battery_level={battery_lvl}")

        return jsonify({"success": True, "sensor_id": sensor_id}), 200

    except Exception as e:
        print(f"[{__name__}] Fejl ved indsættelse i DB: {e}")
        return jsonify({"success": False, "error": str(e)}), 400

    finally:
        cursor.close()
        conn.close()


@sensor_bp.route("/patient-light-data", methods=["POST"])
def light_data():
    """
    POST /api/sensor/patient-light-data
    Indsætter et datapunkt i patient_light_sensor_data med alle nødvendige felter.
    Logger til terminalen, når indsættelsen lykkes.
    """
    data = request.get_json()
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # ────────────────────────────────────────────────────────────
        # 1) Udpak alle felter fra JSON til lokale Python‐variabler:
        patient_id    = data["patient_id"]
        sensor_id     = data.get("sensor_id")
        lux_level     = data.get("lux_level")
        # Her læser vi "timestamp" i stedet for "captured_at":
        raw_ts        = data.get("timestamp")
        melanopic_edi = data.get("melanopic_edi")
        der           = data.get("der")
        illuminance   = data.get("illuminance")
        light_type    = data.get("light_type")
        exposure_score   = data.get("exposure_score")
        action_required  = data.get("action_required", 0)

        # Hvis klienten ikke har sendt "timestamp", kan vi stadig falde tilbage på server‐tid:
        if raw_ts is None:
            captured_at = datetime.now()
        else:
            # Bruger Python 3.7+'s fromisoformat til at parse ISO‐strengen:
            captured_at = datetime.fromisoformat(raw_ts)

        # ────────────────────────────────────────────────────────────
        # 2) Udfør INSERT i patient_light_sensor_data‐tabellen:
        cursor.execute(
            """
            INSERT INTO patient_light_sensor_data (
                patient_id,
                sensor_id,
                lux_level,
                captured_at,
                melanopic_edi,
                der,
                illuminance,
                light_type,
                exposure_score,
                action_required
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                patient_id,
                sensor_id,
                lux_level,
                captured_at,                 # nu det faktiske tidspunkt fra Flutter
                melanopic_edi,
                der,
                illuminance,
                light_type,
                exposure_score,
                action_required
            ),
        )

        # ────────────────────────────────────────────────────────────
        # 3) Commit for at gemme i databasen:
        conn.commit()

        # ────────────────────────────────────────────────────────────
        # 4) Print en bekræftende loglinje med præcis de værdier, der blev sendt:
        print(
            f"[{__name__}] Ny lysdata modtaget: "
            f"patient_id={patient_id}, sensor_id={sensor_id}, lux={lux_level}, "
            f"melanopic={melanopic_edi:.2f}, der={der:.2f}, illum={illuminance:.2f}, "
            f"light_type={light_type}, exposure_score={exposure_score}, action_required={action_required}, "
            f"captured_at={captured_at.isoformat()}"
        )

        return jsonify({"success": True}), 200

    except Exception as e:
        print(f"[{__name__}] Fejl ved indsættelse af lysdata i DB: {e}")
        return jsonify({"success": False, "error": str(e)}), 400

    finally:
        cursor.close()
        conn.close()


@sensor_bp.route('/register-sensor-use', methods=['POST'])
def register_sensor_use():
    conn = None
    cursor = None
    try:
        data = request.get_json()
        patient_id = data["patient_id"]
        device_serial = data["device_serial"]
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Start transaction
        conn.start_transaction()
        
        # 1) Find eller opret sensor
        cursor.execute(
            "SELECT id FROM patient_sensors WHERE patient_id = %s",
            (patient_id,)
        )
        row = cursor.fetchone()
        
        if row:
            sensor_id = row["id"]
        else:
            cursor.execute("""
                INSERT INTO patient_sensors (patient_id, device_serial, sensor_type)
                VALUES (%s, %s, 'light')
            """, (patient_id, device_serial))
            sensor_id = cursor.lastrowid
        
        # 2) Afslut eventuelle aktive sessioner
        cursor.execute("""
            UPDATE patient_sensor_log
            SET ended_at = NOW(),
                status = 'auto_closed'
            WHERE patient_id = %s
              AND sensor_id = %s
              AND ended_at IS NULL
        """, (patient_id, sensor_id))
        
        # 3) Opret ny session
        cursor.execute("""
            INSERT INTO patient_sensor_log (
                sensor_id, patient_id, started_at, status
            ) VALUES (%s, %s, NOW(), 'active')
        """, (sensor_id, patient_id))
        
        conn.commit()
        return jsonify({
            "success": True,
            "sensor_id": sensor_id
        }), 200
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@sensor_bp.route("/end-sensor-use", methods=["POST"])
def end_sensor_use():
    """
    POST /api/sensor/end-sensor-use
    Lukker seneste åbne sensor‐log for en given sensor_id og patient_id, sætter ended_at og status.
    """
    try:
        data = request.get_json()
        patient_id = data["patient_id"]
        sensor_id = data["sensor_id"]
        status = data.get("status", "manual")

        conn = get_db_connection()
        cursor = conn.cursor()

        # Find seneste uafsluttede log
        cursor.execute("""
            SELECT id FROM patient_sensor_log
            WHERE patient_id = %s AND sensor_id = %s AND ended_at IS NULL
            ORDER BY started_at DESC LIMIT 1
        """, (patient_id, sensor_id))
        row = cursor.fetchone()

        if row:
            log_id = row[0]
            cursor.execute("""
                UPDATE patient_sensor_log
                SET ended_at = NOW(), status = %s
                WHERE id = %s
            """, (status, log_id))
            conn.commit()

        cursor.close()
        conn.close()
        return jsonify({"message": "Sensor log afsluttet"}), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@sensor_bp.route("/get-sensor-id", methods=["GET"])
def get_sensor_id():
    """
    GET /api/sensor/get-sensor-id?device_serial=<serial>
    Returnerer {"sensor_id": <id>} hvis der findes en sensor med det givne device_serial,
    ellers 404.
    """
    try:
        serial = request.args.get("device_serial")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM patient_sensors WHERE device_serial = %s",
            (serial,)
        )
        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if row:
            return jsonify({"sensor_id": row["id"]}), 200

        return jsonify({"error": "Not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500
