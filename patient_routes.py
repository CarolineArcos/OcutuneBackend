# routes/patient_routes.py

import re
import traceback
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from mysql_db import get_db_connection
from models.light_data import LightData
from datetime import datetime, timedelta, timezone
import pytz
import json

patient_bp = Blueprint("patient_bp", __name__)


def _extract_user_and_role():
    """
    Håndterer både ældre tokens (identity=str) og nye tokens (identity=dict):
    - Hvis identity er dict, trækkes “id” og “role” derfra.
    - Hvis identity er str, bruges den som user_id, og role hentes fra claims.
    """
    identity = get_jwt_identity()
    claims = get_jwt()

    if isinstance(identity, dict):
        user_id = identity.get("id")
        role = identity.get("role")
    else:
        user_id = identity
        role = claims.get("role")

    return user_id, role


def fetch_all_dict(cursor):
    """
    Hjælpefunktion der konverterer alle rækker fra en cursor til en liste af dict’er.
    """
    cols = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    return [dict(zip(cols, row)) for row in rows]


@patient_bp.route("/", methods=["GET"])
@jwt_required()
def get_patients():
    """
    GET /api/patients/
    Returnerer en liste af patienter (id, first_name, last_name, cpr),
    som den loggede kliniker har adgang til.
    """
    try:
        user_id, role = _extract_user_and_role()
        if role != "clinician":
            return jsonify({"error": "Kun klinikere kan hente patient‐listen"}), 403

        clinician_id = user_id

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
        current_app.logger.error(f"get_patients fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved hentning af patienter"}), 500


@patient_bp.route("/search", methods=["GET"])
@jwt_required()
def search_patients():
    """
    GET /api/patients/search?q=<tekst>
    Søger i klinikerens patienter efter fornavn, efternavn eller CPR.
    """
    try:
        user_id, role = _extract_user_and_role()
        if role != "clinician":
            return jsonify({"error": "Kun klinikere kan søge i patienter"}), 403

        clinician_id = user_id

        raw_q = request.args.get("q", "")         # Læs q fra ?q=<tekst>
        query = raw_q.strip().lower()
        if not query:
            return jsonify([]), 200             # Returnér tom liste, hvis brugeren ikke skrev noget

        like_pattern = f"%{query}%"

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT p.id,
                   p.first_name,
                   p.last_name,
                   p.sim_userid,
                   p.cpr,
                   p.email
            FROM patients AS p
            JOIN clinician_patients AS cp
              ON p.id = cp.patient_id
            WHERE cp.clinician_id = %s
              AND (
                    LOWER(p.first_name) LIKE %s
                 OR LOWER(p.last_name)  LIKE %s
                 OR p.cpr               LIKE %s
              )
            ORDER BY p.last_name, p.first_name
            LIMIT 50
            """,
            (
                clinician_id,
                like_pattern,
                like_pattern,
                like_pattern,
            ),
        )
        rows = cursor.fetchall()
        conn.close()

        result = [
            {
                "id":         row["id"],
                "first_name": row["first_name"],
                "last_name":  row["last_name"],
                "sim_userid": row["sim_userid"],
                "cpr":        row["cpr"],
                "email":      row["email"],
            }
            for row in rows
        ]
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"search_patients fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved søgning af patienter"}), 500


@patient_bp.route("/<patient_id>", methods=["GET"])
@jwt_required()
def get_patient(patient_id):
    """
    GET /api/patients/<patient_id>
    Returnerer alle detaljer om én patient (inkl. rmeq_score, meq_score osv.),
    men kun hvis den loggede kliniker har adgang til netop denne patient.
    """
    try:
        user_id, role = _extract_user_and_role()
        if role != "clinician":
            return jsonify({"error": "Kun klinikere kan hente patientens detaljer"}), 403

        clinician_id = user_id

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT 1
            FROM clinician_patients
            WHERE clinician_id = %s AND patient_id = %s
        """, (clinician_id, patient_id))
        if cursor.fetchone() is None:
            conn.close()
            return jsonify({"error": "Ingen adgang til patient"}), 403

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
        current_app.logger.error(f"get_patient fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved hentning af patient"}), 500


@patient_bp.route("/<patient_id>/diagnoses", methods=["GET"])
@jwt_required()
def get_diagnoses(patient_id):
    """
    GET /api/patients/<patient_id>/diagnoses
    Returnerer en liste af diagnoser fra 'patient_diagnoses' for netop denne patient.
    """
    try:
        user_id, role = _extract_user_and_role()
        if role != "clinician":
            return jsonify({"error": "Kun klinikere kan hente diagnoser"}), 403

        clinician_id = user_id

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT 1
            FROM clinician_patients
            WHERE clinician_id = %s AND patient_id = %s
        """, (clinician_id, patient_id))
        if cursor.fetchone() is None:
            conn.close()
            return jsonify({"error": "Ingen adgang til patientens diagnoser"}), 403

        cursor.execute("""
            SELECT *
            FROM patient_diagnoses
            WHERE patient_id = %s
        """, (patient_id,))
        diagnoses = cursor.fetchall()
        conn.close()

        return jsonify(diagnoses), 200

    except Exception as e:
        current_app.logger.error(f"get_diagnoses fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved hentning af diagnoser"}), 500


@patient_bp.route("/<patient_id>/lightdata", methods=["GET"])
@jwt_required()
def get_light_data(patient_id):
    """
    GET /api/patients/<patient_id>/lightdata
    Hvis der medsendes ?from=<ISO8601>&to=<ISO8601>, filtreres data på interval.
    Ellers returnerer vi de seneste 7 dage (UTC).
    (Ingen rolle‐og adgangstjek – enhver gyldig JWT kan hente.)
    """
    try:
        # 1) Parse “from” og “to” fra query‐parametre
        from_param = request.args.get("from")
        to_param   = request.args.get("to")

        if from_param and to_param:
            try:
                # Fjern evt. “Z” bagerst, så datetime.fromisoformat kan parse
                if from_param.endswith("Z"):
                    from_param = from_param[:-1]
                if to_param.endswith("Z"):
                    to_param = to_param[:-1]
                from_dt = datetime.fromisoformat(from_param)
                to_dt   = datetime.fromisoformat(to_param)
            except ValueError:
                return (
                    jsonify({"error": 'Parametrene "from" og "to" skal være i ISO8601-format'}),
                    400,
                )
        else:
            nu_utc  = datetime.utcnow()
            to_dt   = nu_utc
            from_dt = nu_utc - timedelta(days=7)

        # 2) Hent data mellem from_dt og to_dt
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
              captured_at,
              melanopic_edi,
              illuminance,
              light_type,
              exposure_score,
              action_required
            FROM patient_light_sensor_data
            WHERE patient_id   = %s
              AND captured_at >= %s
              AND captured_at <= %s
            ORDER BY captured_at ASC
        """, (patient_id, from_dt, to_dt))
        rows = cursor.fetchall()
        conn.close()

        # 3) Hvis ingen data, returnér 404
        if not rows:
            return jsonify({"error": "Ingen lysdata fundet i det ønskede interval"}), 404

        # 4) Konverter hver række til JSON‐venlig dict
        result = []
        for row in rows:
            result.append({
                "captured_at":    row["captured_at"].isoformat(),
                "melanopic_edi":  float(row["melanopic_edi"]) if row["melanopic_edi"] is not None else None,
                "illuminance":    float(row["illuminance"])   if row["illuminance"]   is not None else None,
                "light_type":     row["light_type"],
                "exposure_score": float(row["exposure_score"]) if row["exposure_score"] is not None else None,
                "action_required": bool(row["action_required"])  if row["action_required"] is not None else False,
            })
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"get_light_data fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved hentning af lyssensor‐data"}), 500


@patient_bp.route("/<patient_id>/lightdata/all", methods=["GET"])
@jwt_required()
def get_all_light_data(patient_id):
    """
    GET /api/patients/<patient_id>/lightdata/all
    Returnerer samtlige lysmålinger for patienten sorteret stigende på captured_at.
    (Ingen rolle‐og adgangstjek – enhver gyldig JWT kan hente.)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
              captured_at,
              melanopic_edi,
              illuminance,
              light_type,
              exposure_score,
              action_required
            FROM patient_light_sensor_data
            WHERE patient_id = %s
            ORDER BY captured_at ASC
        """, (patient_id,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return jsonify({"error": "Ingen lysdata fundet"}), 404

        result = []
        for row in rows:
            result.append({
                "captured_at":    row["captured_at"].isoformat(),
                "melanopic_edi":  float(row["melanopic_edi"]) if row["melanopic_edi"] is not None else None,
                "illuminance":    float(row["illuminance"])   if row["illuminance"]   is not None else None,
                "light_type":     row["light_type"],
                "exposure_score": float(row["exposure_score"]) if row["exposure_score"] is not None else None,
                "action_required": bool(row["action_required"])  if row["action_required"] is not None else False,
            })
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"get_all_light_data fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved hentning af lyssensor‐data"}), 500


@patient_bp.route("/<patient_id>/lightdata/daily", methods=["GET"])
@jwt_required()
def get_light_data_daily(patient_id):
    """
    GET /api/patients/<patient_id>/lightdata/daily
    Returnerer alle lysmålinger fra UTC‐midnat til næste UTC‐midnat.
    (Fjernet rolle‐og permissions‐tjek – enhver gyldig JWT får adgang.)
    Bemærk: patient_id kan indeholde bogstaver, f.eks. "P3".
    """
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", patient_id):
            return jsonify({"error": "Ugyldigt patient_id"}), 400

        now_utc = datetime.utcnow()
        start_date = now_utc.date()
        start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
        end_dt = start_dt + timedelta(days=1)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT
              captured_at,
              melanopic_edi,
              illuminance,
              light_type,
              exposure_score,
              action_required
            FROM patient_light_sensor_data
            WHERE patient_id = %s
              AND captured_at >= %s
              AND captured_at <  %s
            ORDER BY captured_at ASC
        """
        cursor.execute(query, (patient_id, start_dt, end_dt))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return jsonify({"error": "Ingen lysdata fundet for i dag"}), 404

        result = []
        for row in rows:
            result.append({
                "captured_at":     row["captured_at"].isoformat(),
                "melanopic_edi":   float(row["melanopic_edi"]),
                "illuminance":     float(row["illuminance"]),
                "light_type":      row["light_type"],
                "exposure_score":  float(row["exposure_score"]),
                "action_required": bool(row["action_required"]),
            })
        return jsonify(result), 200

    except mysql_errors.OperationalError as db_err:
        current_app.logger.error(f"Databasefejl i get_light_data_daily: {db_err}", exc_info=True)
        return jsonify({"error": "Databaseforbindelse fejlede"}), 500

    except Exception as e:
        current_app.logger.error(f"get_light_data_daily fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved hentning af daglige lysdata"}), 500


@patient_bp.route("/<patient_id>/lightdata/weekly", methods=["GET"])
@jwt_required()
def get_light_data_weekly(patient_id):
    """
    GET /api/patients/<patient_id>/lightdata/weekly
    Returnerer 7 aggregerede datapunkter, ét for hver dag i sidste uge (man–søn),
    hvor hver dags værdier er baseret på ALLE råmålinger for den dag.
    """
    try:
        # 1) Valider patient_id som alfanumerisk
        if not re.fullmatch(r"[A-Za-z0-9_-]+", patient_id):
            return jsonify({"error": "Ugyldigt patient_id"}), 400

        # 2) Beregn dato‐interval: sidste mandag 00:00 UTC → næste mandag 00:00 UTC
        now_utc = datetime.utcnow()
        today = now_utc.date()
        # Find mandag i indeværende uge:
        current_monday = today - timedelta(days=today.weekday())

        # Hvis i fx vil vise “sidste mandag→seneste søndag”, kan du i stedet
        # trække en uge fra current_monday. Men antager vi “nod’: current_monday er forrige mandag.
        # Hvis i vil have uge som "2. juni–8. juni 2025":
        start_dt = datetime(
            year=current_monday.year,
            month=current_monday.month,
            day=current_monday.day,
            hour=0, minute=0, second=0
        )
        end_dt = start_dt + timedelta(days=7)

        # 3) Kør SQL til at aggregere pr. dag:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT
              DATE(captured_at) AS day_utc,
              SUM(CASE WHEN illuminance >= 1000 THEN 1 ELSE 0 END) AS count_high_light,
              SUM(CASE WHEN illuminance  <  1000 THEN 1 ELSE 0 END) AS count_low_light,
              COUNT(*)                                        AS total_measurements
            FROM patient_light_sensor_data
            WHERE patient_id = %s
              AND captured_at >= %s
              AND captured_at <  %s
            GROUP BY day_utc
            ORDER BY day_utc ASC;
        """
        cursor.execute(query, (patient_id, start_dt, end_dt))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # 4) Hvis ingen data for hele ugen, returnér 404
        if not rows:
            return jsonify({"error": "Ingen lysdata fundet for denne uge"}), 404

        # 5) Byg en dict day→data for hurtig opslag
        agg_dict = { row["day_utc"]: row for row in rows }

        # 6) Iterér netop 7 dage (mandag→søndag) og tilsæt “0”‐dage, hvis mangler
        result = []
        for i in range(7):
            d = start_dt.date() + timedelta(days=i)  # d er f.eks. 2025-06-02, 2025-06-03, …
            if d in agg_dict:
                r = agg_dict[d]
                result.append({
                    "day":                 d.isoformat(),               # "2025-06-02"
                    "count_high_light":    int(r["count_high_light"]),  # f.eks. 4800
                    "count_low_light":     int(r["count_low_light"]),   # f.eks. 1200
                    "total_measurements":  int(r["total_measurements"])
                })
            else:
                result.append({
                    "day":                 d.isoformat(),
                    "count_high_light":    0,
                    "count_low_light":     0,
                    "total_measurements":  0
                })

        return jsonify(result), 200

    except mysql_errors.OperationalError as db_err:
        current_app.logger.error(f"Databasefejl i get_light_data_weekly: {db_err}", exc_info=True)
        return jsonify({"error": "Databaseforbindelse fejlede"}), 500

    except Exception as e:
        current_app.logger.error(f"get_light_data_weekly fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved hentning af ugentlige lysdata"}), 500



@patient_bp.route("/<patient_id>/lightdata/monthly", methods=["GET"])
@jwt_required()
def get_light_data_monthly(patient_id):
    """
    GET /api/patients/<patient_id>/lightdata/monthly
    Returnerer én opsummering pr. dag for alle dage i denne måned (samme format som weekly).
    """
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", patient_id):
            return jsonify({"error": "Ugyldigt patient_id"}), 400

        now_utc = datetime.utcnow()
        year = now_utc.year
        month = now_utc.month

        # Start/slut for denne måned
        start_dt = datetime(year, month, 1, 0, 0, 0)
        # Find første dag i næste måned
        if month == 12:
            next_year = year + 1
            next_month = 1
        else:
            next_year = year
            next_month = month + 1
        end_dt = datetime(next_year, next_month, 1, 0, 0, 0)

        # Antal dage i denne måned
        days_in_month = (end_dt - start_dt).days

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT
                DATE(captured_at) AS day_utc,
                SUM(CASE WHEN illuminance >= 1000 THEN 1 ELSE 0 END) AS count_high_light,
                SUM(CASE WHEN illuminance  <  1000 THEN 1 ELSE 0 END) AS count_low_light,
                COUNT(*) AS total_measurements
            FROM patient_light_sensor_data
            WHERE patient_id = %s
              AND captured_at >= %s
              AND captured_at <  %s
            GROUP BY day_utc
            ORDER BY day_utc ASC;
        """
        cursor.execute(query, (patient_id, start_dt, end_dt))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Byg dict for hurtig opslag
        agg_dict = { str(row["day_utc"]): row for row in rows }  # brug altid str()

        # Returnér alle dage, også dem uden målinger (giver 0’er)
        result = []
        for i in range(days_in_month):
            d = (start_dt.date() + timedelta(days=i))           # fx 2025-06-01
            d_str = d.isoformat()                               # fx "2025-06-01"
            if d_str in agg_dict:
                r = agg_dict[d_str]
                result.append({
                    "day": d_str,
                    "count_high_light": int(r["count_high_light"]),
                    "count_low_light": int(r["count_low_light"]),
                    "total_measurements": int(r["total_measurements"])
                })
            else:
                result.append({
                    "day": d_str,                    # <-- ALTID en string, aldrig null!
                    "count_high_light": 0,
                    "count_low_light": 0,
                    "total_measurements": 0
                })

        # Debug: se første 3 rækker (kan slettes i produktion)
        print("MONTHLY RESULT SAMPLE:", result[:3])

        return jsonify(result), 200

    except mysql_errors.OperationalError as db_err:
        current_app.logger.error(f"Databasefejl i get_light_data_monthly: {db_err}", exc_info=True)
        return jsonify({"error": "Databaseforbindelse fejlede"}), 500

    except Exception as e:
        current_app.logger.error(f"get_light_data_monthly fejl: {e}", exc_info=True)
        return jsonify({"error": "Serverfejl ved hentning af månedlige lysdata"}), 500
