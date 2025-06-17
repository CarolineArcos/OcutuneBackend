# routes/clinician_routes.py

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from mysql_db import get_db_connection

# Blueprint‐definition
clinician_bp = Blueprint("clinician_bp", __name__)

@clinician_bp.route("/patients", methods=["GET"])
@jwt_required()
def get_clinician_patients():
    """
    GET /api/clinician/patients
    Returnerer en liste af patienter (id, first_name, last_name, cpr),
    som den loggede kliniker har adgang til.
    """
    try:
        # 1) Hent identity‐payload
        current = get_jwt_identity()
        # Hvis current er en str (f.eks. et gammelt token), tolkes det som bruger‐ID
        if isinstance(current, str):
            clinician_id = current
            # Prøv at hente rolle som custom‐claim (hvis token var oprettet med additional_claims)
            role = get_jwt().get("role", None)
        else:
            # Hvis current er dict, hentes begge felter herfra
            clinician_id = current.get("id")
            role = current.get("role")

        # 2) Tjek rolle
        if role != "clinician" or not clinician_id:
            return jsonify({"error": "Kun klinikere kan hente patienter"}), 403

        # 3) SQL‐opslag
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT p.id, p.first_name, p.last_name, p.cpr
            FROM patients AS p
            JOIN clinician_patients AS cp
              ON p.id = cp.patient_id
            WHERE cp.clinician_id = %s
            ORDER BY p.last_name, p.first_name
        """, (clinician_id,))
        rows = cursor.fetchall()
        conn.close()

        # 4) Byg resultatliste
        result = []
        for row in rows:
            result.append({
                "id":         row["id"],
                "first_name": row["first_name"],
                "last_name":  row["last_name"],
                "cpr":        row["cpr"]
            })
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"get_clinician_patients fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved hentning af kliniker‐patienter"}), 500


@clinician_bp.route("/patients/<int:patient_id>", methods=["GET"])
@jwt_required()
def get_patient_detail_for_clinician(patient_id):
    """
    GET /api/clinician/patients/<patient_id>
    Returnerer detaljer om én patient, hvis klinikeren har adgang.
    """
    try:
        current = get_jwt_identity()
        if isinstance(current, str):
            clinician_id = current
            role = get_jwt().get("role", None)
        else:
            clinician_id = current.get("id")
            role = current.get("role")

        if role != "clinician" or not clinician_id:
            return jsonify({"error": "Ikke autoriseret"}), 403

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1) Tjek adgang
        cursor.execute("""
            SELECT 1
            FROM clinician_patients
            WHERE clinician_id = %s AND patient_id = %s
        """, (clinician_id, patient_id))
        if cursor.fetchone() is None:
            conn.close()
            return jsonify({"error": "Ingen adgang til patient"}), 403

        # 2) Hent patientdetaljer
        cursor.execute("""
            SELECT
                p.id,
                p.first_name,
                p.last_name,
                p.cpr,
                p.street,
                p.zip_code,
                p.city,
                p.phone,
                p.email,
                p.uuid,
                p.sim_userid,
                p.sim_password,
                p.created_at,
                p.rmeq_score,
                p.meq_score
            FROM patients AS p
            WHERE p.id = %s
        """, (patient_id,))
        patient_row = cursor.fetchone()
        conn.close()

        if not patient_row:
            return jsonify({"error": "Patient ikke fundet"}), 404

        return jsonify(patient_row), 200

    except Exception as e:
        current_app.logger.error(f"get_patient_detail_for_clinician fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved hentning af patient‐detaljer"}), 500

