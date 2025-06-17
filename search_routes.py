# routes/search_routes.py

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

search_bp = Blueprint("search_bp", __name__)

@search_bp.route("/", methods=["GET"])
@jwt_required()
def search_patients():
    # Forsink importen af db og modeller
    from app import db
    from models.patient import Patient
    from models.clinician import Clinician

    current = get_jwt_identity()
    clinician_id = current.get("id") if current.get("role") == "clinician" else None
    if not clinician_id:
        return jsonify({"error": "Kun klinikere kan søge patienter"}), 403

    query_text = request.args.get("q", "").strip().lower()
    if not query_text:
        return jsonify([]), 200

    rows = db.session.execute(
        """
        SELECT 
          p.id,
          p.first_name,
          p.last_name,
          p.sim_userid,
          p.cpr,
          p.email
        FROM patients p
        JOIN clinician_patients cp 
          ON p.id = cp.patient_id
        WHERE cp.clinician_id = :clin_id
          AND (
            LOWER(p.first_name) LIKE :q
            OR LOWER(p.last_name)  LIKE :q
            OR p.cpr              LIKE :raw_q
          )
        ORDER BY p.last_name, p.first_name
        LIMIT 50
        """,
        {
          "clin_id": clinician_id,
          "q":       f"%{query_text}%",
          "raw_q":   f"%{query_text}%"
        }
    ).fetchall()

    result = []
    for row in rows:
        result.append({
            "id":         row.id,
            "first_name": row.first_name,
            "last_name":  row.last_name,
            "sim_userid": row.sim_userid,
            "cpr":        row.cpr,
            "email":      row.email,
        })
    return jsonify(result), 200
