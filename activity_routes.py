# routes/activity_routes.py

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from datetime import datetime
from models.activity import Activity
import traceback

activity_bp = Blueprint("activity_bp", __name__)

# ------------------------------------------------------------
# routes/activity_routes.py
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required
from datetime import datetime
from app import db
from models.activity import Activity

activity_bp = Blueprint("activity_bp", __name__)

# ──────────────────────────────────────────────────────────────────────────────────────
# GET  /api/activity-labels/activity-labels?patient_id=<id>
#  Returnerer en liste af strenge: 
#     – Seneste 5 “event_type” fra patient_events (hvis ønsket), 
#     – Alle brugeroprettede labels fra activity_labels, 
#     – Og til sidst default_labels fra DB.
#  Her kombinerer vi dem uden dubletter.
# ──────────────────────────────────────────────────────────────────────────────────────
from flask_jwt_extended import jwt_required, get_jwt_identity

@activity_bp.route("/", methods=["GET"], strict_slashes=False)
@jwt_required()
def get_activity_labels():

    user_id = get_jwt_identity()
    if not user_id:
        return jsonify({'error': 'Bruger-ID ikke fundet'}), 403

    try:
        # Hent seneste brugerdefinerede labels for netop denne patient
        labels_query = (
            db.session
            .query(Activity.label)
            .filter(Activity.patient_id == user_id)
            .order_by(Activity.created_at.desc())
            .all()
        )
        final_labels = [row[0] for row in labels_query]
        return jsonify(final_labels), 200

    except Exception as e:
        db.session.rollback()
        print("❌ Fejl i get_activity_labels:", e)
        return jsonify({'error': 'Serverfejl ved hentning af labels'}), 500


# ──────────────────────────────────────────────────────────────────────────────────────
# POST /api/activity-labels/activity-labels
#  Kroppen: { "patient_id": "<id>", "label": "<tekst>" }
#  Gemmer i activity_labels-tabellen.
# ──────────────────────────────────────────────────────────────────────────────────────

@activity_bp.route("/", methods=["POST"], strict_slashes=False)
@jwt_required()
def post_activity_label():
    print("🔥 post_activity_label CALLED!")
    data = request.get_json() or {}
    patient_id = data.get("patient_id", "").strip()
    label_text = data.get("label", "").strip()

    if not patient_id or not label_text:
        print("🚫 Manglende patient_id eller label")
        return jsonify({"error": "Manglende patient_id eller label"}), 400

    try:
        new_label = Activity(
            patient_id=patient_id,
            label=label_text
        )
        db.session.add(new_label)
        db.session.commit()
        print(f"✅ Label oprettet: {new_label.label} for patient {new_label.patient_id}")
        return jsonify({"status": "ok", "id": new_label.id}), 201

    except Exception as e:
        db.session.rollback()
        print("❌ DB-fejl i post_activity_label:", e)
        traceback.print_exc()
        return jsonify({"error": "DB-error", "details": str(e)}), 500
