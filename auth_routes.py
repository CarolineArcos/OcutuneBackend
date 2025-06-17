# routes/auth_routes.py

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
)
from config import Config
from datetime import datetime
from datetime import timedelta
from schemas.auth_schema import LoginSchema
from mysql_db import get_db_connection
from app import jwt, BLOCKLIST

from flask import Blueprint, request, jsonify
from sqlalchemy.exc import NoResultFound
from models import db
from models.clinician import Clinician
from models.patient   import Patient
from models.customer import Customer
from models.answer   import Answer
from models.choice   import Choice

auth_bp        = Blueprint("auth_bp", __name__)
clinician_bp = Blueprint("clinician", __name__)


@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    return jwt_payload["jti"] in BLOCKLIST

@jwt.revoked_token_loader
def revoked_token_callback(jwt_header, jwt_payload):
    return jsonify({"success":False, "msg":"Token revoked"}), 401

@auth_bp.route('/customer/login', methods=['POST'])
def customer_login():
    data     = request.get_json() or {}
    email    = data.get('email','').strip().lower()
    password = data.get('password','').strip()

    if not email or not password:
        return jsonify(success=False, message="E‐mail og adgangskode må ikke være tomme."), 400

    customer = Customer.query.filter_by(email=email).first()
    if not customer:
        return jsonify(success=False, message="Bruger ikke fundet."), 404
    if not customer.check_password(password):
        return jsonify(success=False, message="Forkert adgangskode."), 401

    # Én uges udløb:
    access_token = create_access_token(
        identity=str(customer.id),
        expires_delta=timedelta(weeks=1),
        additional_claims={"role": "customer"}
    )

    return jsonify({
        "success": True,
        "token": access_token,
        "user": {
            "id":    customer.id,
            "email": customer.email,
            "role":  "customer"
        }
    }), 200

@auth_bp.route('/registerCustomer', methods=['POST'])
def register_customer():
    data = request.get_json() or {}

    # ─── 1) Pull out fields ────────────────────────────────────────────────
    first_name      = (data.get('first_name')  or '').strip()
    last_name       = (data.get('last_name')   or '').strip()
    email           = (data.get('email')       or '').strip().lower()
    password        = (data.get('password')    or '').strip()
    birth_year      = data.get('birth_year')
    gender          = data.get('gender')
    chronotype_key  = data.get('chronotype')
    rmeq_score      = data.get('rmeq_score')
    meq_score       = data.get('meq_score')
    answers_list    = data.get('answers')          # maybe None or list
    question_scores = data.get('question_scores')  # maybe None or dict

    # ─── 2) Required‐field validation ───────────────────────────────────────
    if not all([first_name, last_name, email, password, chronotype_key]):
        return jsonify(success=False,
                       message="Fornavn, efternavn, e-mail, adgangskode og chronotype skal udfyldes."
                      ), 400

    # no duplicate email
    if Customer.query.filter_by(email=email).first():
        return jsonify(success=False,
                       message="En bruger med denne e-mail findes allerede."
                      ), 409

    # ─── 3) Normalize + cast helpers ───────────────────────────────────────
    def to_int(v):
        try: return int(v) if v is not None else None
        except: return None

    # map legacy 'owl' → 'nightowl'
    if chronotype_key == 'owl':
        chronotype_key = 'nightowl'

    # ─── 4) Create new customer (no commit yet) ────────────────────────────
    new_customer = Customer(
        first_name=first_name,
        last_name=last_name,
        email=email,
        password_plaintext=password,
        birth_year=to_int(birth_year),
        gender=gender,
        chronotype=chronotype_key,
        rmeq_score=to_int(rmeq_score),
        meq_score=to_int(meq_score),
    )
    db.session.add(new_customer)
    db.session.flush()  # now new_customer.id is available

    # ─── 5) Optionally persist RMEQ answers if we got exactly 5 answers+scores ──
    if (isinstance(answers_list, list) and len(answers_list) == 5
        and isinstance(question_scores, dict)
        and all(f"q{i}" in question_scores for i in range(1, 6))):

        # assume your RMEQ questions are question_id 1..5 in the DB
        for idx, answer_text in enumerate(answers_list, start=1):
            try:
                score      = int(question_scores[f"q{idx}"])
                choice_obj = Choice.query.filter_by(
                    question_id=idx,
                    score=score
                ).one()
            except (KeyError, ValueError, NoResultFound):
                db.session.rollback()
                return jsonify(success=False,
                               message=f"Fejl med score/choice for spørgsmål {idx}."
                              ), 400

            db.session.add(Answer(
                customer_id=new_customer.id,
                question_id=idx,
                choice_id=choice_obj.id,
                answer_text=answer_text,
                score=score
            ))

    # ─── 6) Commit everything ───────────────────────────────────────────────
    db.session.commit()

    # ─── 7) Issue JWTs (identity must be a string) ─────────────────────────
    access_token = create_access_token(
        identity=str(new_customer.id),
        expires_delta=timedelta(hours=1),
        additional_claims={"role": "customer"}
    )
    refresh_token = create_refresh_token(identity=str(new_customer.id))

    # ─── 8) Build response ─────────────────────────────────────────────────
    user_dict = new_customer.to_dict()
    user_dict['role'] = 'customer'

    return jsonify({
        "success":      True,
        "user":         user_dict,
        "access_token": access_token,
        "refresh_token": refresh_token
    }), 201

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    POST /auth/logout
    Ved JWT bruger vi som regel stateless token, så klienten sletter bare token lokalt.
    Her returnerer vi blot en success‐melding.
    """
    return jsonify({
        "success": True,
        "message": "Du er nu logget ud."
    }), 200


@auth_bp.route("/mitid/login", methods=["POST"])
def mitid_login():
    data = request.get_json() or {}

    # 1) Valider tilstedeværelse
    if "sim_userid" not in data or "sim_password" not in data:
        return jsonify({"error": "Manglende sim_userid eller sim_password"}), 400

    sim_userid_raw = data["sim_userid"]
    sim_password   = data["sim_password"]

    # 2) Konverter til int
    try:
        sim_userid = int(sim_userid_raw)
    except (ValueError, TypeError):
        return jsonify({"error": "Ugyldigt sim_userid (skal være et heltal)"}), 400

    # 3) Find enten clinician eller patient
    clinician = Clinician.query.filter_by(sim_userid=sim_userid).first()
    if clinician:
        if not clinician.check_password(sim_password):
            return jsonify({"error": "Ugyldigt login"}), 401
        role       = "clinician"
        user_id    = clinician.id
        first_name = clinician.first_name or ""
        last_name  = clinician.last_name  or ""
    else:
        patient = Patient.query.filter_by(sim_userid=sim_userid).first()
        if not patient or not patient.check_password(sim_password):
            return jsonify({"error": "Ugyldigt login"}), 401
        role       = "patient"
        user_id    = patient.id
        first_name = patient.first_name or ""
        last_name  = patient.last_name  or ""

    # 4) Udsted JWT — Config.JWT_ACCESS_TOKEN_EXPIRES er allerede en timedelta
    access_token = create_access_token(
        identity=str(user_id),
        expires_delta=Config.JWT_ACCESS_TOKEN_EXPIRES,
        additional_claims={"role": role}
    )

    return jsonify({
        "token":      access_token,
        "id":         str(user_id),
        "role":       role,
        "sim_userid": str(sim_userid),
        "first_name": first_name,
        "last_name":  last_name
    }), 200

@auth_bp.route("/sim-check-userid", methods=["POST"])
def sim_check_userid():
    """
    POST /api/auth/sim-check-userid
    Body: { "sim_userid": "<brugernavn>" }
    Returnerer 200 + { "exists": true, "role": "...", "id": ... } hvis brugeren findes, ellers 404.
    """
    data = request.get_json()
    sim_userid = data.get("sim_userid")
    if not sim_userid:
        return jsonify({"error": "Manglende sim_userid"}), 400

    from app import db
    from models.clinician import Clinician
    from models.patient   import Patient

    clinician = Clinician.query.filter_by(sim_userid=sim_userid).first()
    if clinician:
        return jsonify({"exists": True, "role": "clinician", "id": clinician.id}), 200

    patient = Patient.query.filter_by(sim_userid=sim_userid).first()
    if patient:
        return jsonify({"exists": True, "role": "patient", "id": patient.id}), 200

    return jsonify({"error": "Brugernavn ikke fundet"}), 404




@auth_bp.route("/check-email", methods=["POST"])
def check_email_availability():
    """
    POST /api/auth/check-email
    Tjekker om en email allerede findes i customers‐tabellen.
    Forventet JSON‐body: { "email": "<email>" }
    Returnerer { "available": true } eller { "available": false }.
    """
    data = request.get_json()
    if not data or "email" not in data:
        return jsonify({"error": "Manglende 'email' i body"}), 400

    email = data["email"].strip().lower()
    conn  = get_db_connection()
    cursor= conn.cursor()

    try:
        cursor.execute("SELECT 1 FROM customers WHERE email = %s", (email,))
        exists = cursor.fetchone() is not None
        conn.close()
        return jsonify({"available": not exists}), 200

    except Exception as e:
        conn.close()
        return jsonify({"error": f"Databasefejl: {str(e)}"}), 500




@clinician_bp.route("/api/clinician/patients/<int:patient_id>", methods=["GET"])
def get_patient_with_diagnoses(patient_id):
    patient = (
        Patient.query
        .options(joinedload(Patient.patient_diagnoses))
        .filter_by(id=patient_id)
        .first()
    )
    if not patient:
        return jsonify({"error": "Patient ikke fundet"}), 404

    data = patient.to_dict()
    data["diagnoses"] = [d.to_dict() for d in patient.patient_diagnoses]
    return jsonify(data), 200



# Route til status/health-check:
@auth_bp.route("/status", methods=["GET"])
def status():
    """
    Health-check for auth-routes. Returnerer 200 OK samt et JSON-objekt.
    URL: /api/auth/status
    """
    return jsonify({
        "status": "OK",
        "message": "Auth-routes kører fint",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }), 200






