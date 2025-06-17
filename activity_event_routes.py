# routes/activity_event_routes.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from models.activity_event import ActivityEvent
from datetime import datetime

activity_event_bp = Blueprint("activity_event_bp", __name__)

# ──────────────────────────────────────────────────────────────────────────────────────
# GET  /api/activities/activities?patient_id=<id>
#  Returnerer alle patient_events for en given patient i JSON-format.
# ──────────────────────────────────────────────────────────────────────────────────────
@activity_event_bp.route("/activities", methods=["GET"], strict_slashes=False)
@jwt_required()
def get_activities():
    patient_id = request.args.get("patient_id", None)
    # Du kan også hente patient_id fra token: patient_id = get_jwt_identity()

    try:
        if patient_id:
            events = (
                db.session.query(ActivityEvent)
                .filter(ActivityEvent.patient_id == patient_id)
                .order_by(ActivityEvent.start_time.desc())
                .all()
            )
        else:
            # Hvis ingen patient_id er angivet, returnér tom liste eller alle med NULL,
            # alt efter business logic. Her vælger vi at returnere en tom liste.
            events = []

        result = [evt.to_dict() for evt in events]
        return jsonify(result), 200

    except Exception as e:
        db.session.rollback()
        print("❌ Fejl i get_activities:", e)
        return jsonify({"error": "Serverfejl ved hentning af aktiviteter"}), 500


# ──────────────────────────────────────────────────────────────────────────────────────
# POST /api/activities/activities
#  Kroppen (JSON): 
#     { 
#       "patient_id": "<id>", 
#       "event_type": "<label>", 
#       "note": "<tekst>", 
#       "start_time": "<ISO8601-streng>", 
#       "end_time": "<ISO8601-streng>", 
#       "duration_minutes": <int> 
#     }
#  Opretter en ny ActivityEvent i patient_events-tabellen.
# ──────────────────────────────────────────────────────────────────────────────────────
@activity_event_bp.route("/activities", methods=["POST"], strict_slashes=False)
@jwt_required()
def post_activity():
    data = request.get_json() or {}
    required = ["patient_id", "event_type", "start_time", "end_time", "duration_minutes"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Følgende felter mangler: {missing}"}), 400

    try:
        # Pars ISO8601-strenge til datetime-objekter
        start_dt = datetime.fromisoformat(data["start_time"])
        end_dt   = datetime.fromisoformat(data["end_time"])
        duration = int(data["duration_minutes"])

        new_event = ActivityEvent(
            patient_id       = data["patient_id"],
            event_type       = data["event_type"],
            note             = data.get("note", ""),
            start_time       = start_dt,
            end_time         = end_dt,
            duration_minutes = duration
        )
        db.session.add(new_event)
        db.session.commit()

        return jsonify(new_event.to_dict()), 201

    except Exception as e:
        db.session.rollback()
        print("❌ Fejl i post_activity:", e)
        return jsonify({"error": "DB-fejl ved oprettelse af aktivitet", "details": str(e)}), 500



# ──────────────────────────────────────────────────────────────────────────────────────
# DELETE /api/activities/activities/<activity_id>
#  Sletter ét event, men kan også logføre det i “deleted_events”-tabel.
# ──────────────────────────────────────────────────────────────────────────────────────
@activity_event_bp.route("/activities/<int:activity_id>", methods=["DELETE"], strict_slashes=False)
@jwt_required()
def delete_activity(activity_id):
    # Du kan enten tage patient_id/user_id fra querystring: request.args.get("user_id")
    # Eller du kan få brugerens id fra token med get_jwt_identity()
    user_id = request.args.get("user_id", None)
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400

    try:
        evt = db.session.query(ActivityEvent).get(activity_id)
        if not evt:
            return jsonify({"error": "Aktivitet findes ikke"}), 404

        # Eksempel: Log sletning i en “deleted_events” tabel, hvis du har sådan en:
        # deleted = DeletedEvent(
        #     event_id         = evt.id,
        #     user_id          = user_id,
        #     deleted_at       = datetime.utcnow(),
        #     event_type       = evt.event_type,
        #     duration_minutes = evt.duration_minutes,
        #     note             = evt.note
        # )
        # db.session.add(deleted)

        db.session.delete(evt)
        db.session.commit()
        return jsonify({"status": "deleted"}), 200

    except Exception as e:
        db.session.rollback()
        print("❌ Fejl i delete_activity:", e)
        return jsonify({"error": "Serverfejl ved sletning af aktivitet", "details": str(e)}), 500
