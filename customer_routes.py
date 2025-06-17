# routes/customer_routes.py
from models.deleted_customer import DeletedCustomer

from flask import Blueprint, jsonify
from flask import request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from sqlalchemy import func
from models import db
from models.light_data import LightData
from models import Customer
from models.chronotype import Chronotype
from werkzeug.security import generate_password_hash
import logging
from flask import current_app


from models import Customer, Chronotype
from models import DeletedCustomer


customer_bp = Blueprint('customer_bp', __name__, url_prefix='/api/customer')

@customer_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_customer_profile():
    print(">>> REQUEST KOM IND I get_customer_profile()")
    identity = get_jwt_identity()
    claims   = get_jwt()
    print("DEBUG: get_jwt_identity() =", identity)
    print("DEBUG: get_jwt claims:", claims)

    if identity is None:
        return jsonify({
            "success": False,
            "message": "Mangler gyldig identitet i token"
        }), 422

    try:
        customer_id = int(identity)
    except ValueError:
        return jsonify({
            "success": False,
            "message": "Token.identity kan ikke konverteres til tal"
        }), 422

    # Hent kunden
    customer = Customer.query.get(customer_id)
    if not customer:
        return jsonify({
            "success": False,
            "message": "Kunden blev ikke fundet."
        }), 404

    # Opslag i chronotypes‐tabellen for at få detaljer
    chrono_key = customer.chronotype 
    chrono = Chronotype.query.filter_by(type_key=chrono_key).first()
    if chrono:
        chrono_data = {
            "id":                chrono.id,
            "type_key":          chrono.type_key,
            "title":             chrono.title,
            "short_description": chrono.short_description,
            "long_description":  chrono.long_description,
            "facts":             chrono.facts,
            "image_url":         chrono.image_url,
            "icon_url":          chrono.icon_url,
            "language":          chrono.language,
            "min_score":         chrono.min_score,
            "max_score":         chrono.max_score,
            "summary_text":      chrono.summary_text,
        }
    else:
        chrono_data = None

    # Byg data‐objektet inkl. de nye felter
    data = {
        "id":                 customer.id,
        "first_name":         customer.first_name,
        "last_name":          customer.last_name,
        "email":              customer.email,
        "birth_year":         customer.birth_year,                   # ← NYT
        "gender":             customer.gender,                       # ← NYT
        "registration_date":  customer.registration_date.isoformat(),# ← NYT
        "chronotype":         customer.chronotype,
        "rmeq_score":         customer.rmeq_score,
        "meq_score":          customer.meq_score,
        "chronotype_details": chrono_data
    }

    return jsonify({"success": True, "data": data}), 200

@customer_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout_customer():
    jti = get_jwt()["jti"]
    BLOCKLIST.add(jti)
    return jsonify({
        "success": True,
        "message": "Logout lykkedes."
    }), 200



@customer_bp.route('/profile/changepassword', methods=['PUT'])
@jwt_required()
def change_password():
    # Debug: log entry into route and payload
    current_app.logger.debug(
        f"🔑 change_password called for user {get_jwt_identity()} with payload {request.get_json()}"
    )

    try:
        data = request.get_json(force=True) or {}
        old_pw = data.get('oldPassword', '').strip()
        new_pw = data.get('newPassword', '').strip()

        if not old_pw or not new_pw:
            return jsonify(success=False, message="Du skal angive både gammel og ny adgangskode."), 400

        user_id = get_jwt_identity()
        customer = Customer.query.get(user_id)
        if not customer:
            return jsonify(success=False, message="Bruger ikke fundet."), 404

        if not customer.check_password(old_pw):
            return jsonify(success=False, message="Forkert adgangskode."), 401

        customer.password_hash = generate_password_hash(new_pw)
        db.session.commit()
        current_app.logger.debug(f"✅ Password for user {user_id} updated successfully")

        return jsonify(success=True, message="Adgangskode opdateret."), 200

    except Exception as e:
        current_app.logger.exception("❌ Uventet fejl i change_password")
        return jsonify(success=False, message="Internt serverproblem. Prøv igen om lidt."), 500


@customer_bp.route('/delete/<int:customer_id>', methods=['DELETE'])
@jwt_required()
def delete_customer(customer_id):
    current_app.logger.debug(f"-- DELETE route hit for id={customer_id}")

    try:
        raw_id = get_jwt_identity()
        current_app.logger.debug(f"  -> raw JWT identity: {raw_id!r} ({type(raw_id)})")
        current_id = int(raw_id)
    except (TypeError, ValueError) as ex:
        current_app.logger.warning("  -> invalid token: %s", ex)
        return jsonify({"success": False, "message": "Ugyldigt token"}), 401

    current_app.logger.debug("  -> current_id from JWT: %d", current_id)
    if current_id != customer_id:
        current_app.logger.warning("  -> forbidden: mismatch id")
        return jsonify({"success": False, "message": "Ikke tilladt"}), 403

    customer = Customer.query.get(customer_id)
    current_app.logger.debug("  -> fetched customer: %r", customer)
    if not customer:
        current_app.logger.debug("  -> customer not found")
        return jsonify({"success": False, "message": "Bruger ikke fundet"}), 404

    current_app.logger.debug("  -> archiving before delete")
    archived = DeletedCustomer(customer)
    db.session.add(archived)

    current_app.logger.debug("  -> deleting original and committing")
    db.session.delete(customer)
    db.session.commit()

    current_app.logger.info("  -> delete+archive succeeded for id=%d", customer_id)
    return jsonify({"success": True, "message": "Bruger slettet og anonymiseret"}), 200

@customer_bp.route('/lightdata/daily', methods=['GET'])
@jwt_required()
def get_customer_daily_lightdata():
    """
    GET /api/customer/lightdata/daily
    Returnerer P3’s dagsdata, aggregeret pr. time, for alle kunder.
    Brugeren skal blot have en valid kunde‐JWT.
    """

    # 1) Hent den indloggede bruger‐id (kunde‐id) – vi bruger det til at sikre,
    #    at der er en token, men vi gør ikke yderligere ID‐checks, fordi vi mocker P3 for alle.
    customer_id = get_jwt_identity()
    if customer_id is None:
        return jsonify({
            "success": False,
            "message": "Ugyldig token eller tomt identity."
        }), 401

    # 2) Hent aggregeret dagsdata for P3 (hardkodet patient_id= 'P3')
    #    Vi antager, at P3’s patient_id i tabellen er strengen 'P3'.
    try:
        rows = (
            db.session.query(
                func.hour(LightSensorData.captured_at).label('hour_utc'),
                func.avg(LightSensorData.melanopic_edi).label('avg_edi'),
                func.avg(LightSensorData.lux_level).label('avg_lux'),
                func.avg(LightSensorData.exposure_score).label('avg_exposure'),
                func.sum(LightSensorData.action_required).label('actions')
            )
            .filter(LightSensorData.patient_id == 'P3')
            .group_by(func.hour(LightSensorData.captured_at))
            .order_by(func.hour(LightSensorData.captured_at))
            .all()
        )
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Fejl ved hentning af dagsdata: {str(e)}"
        }), 500

    daily_list = []
    for row in rows:
        daily_list.append({
            "hour": row.hour_utc,
            "average_melanopic_edi": float(row.avg_edi or 0.0),
            "average_lux": float(row.avg_lux or 0.0),
            "average_exposure_score": float(row.avg_exposure or 0.0),
            "action_required_count": int(row.actions or 0),
        })

    return jsonify({
        "success": True,
        "data": daily_list
    }), 200



@customer_bp.route('/lightdata/weekly', methods=['GET'])
@jwt_required()
def get_customer_weekly_lightdata():
    """
    GET /api/customer/lightdata/weekly
    Returnerer P3’s ugentlige data, aggregeret pr. ugedag (0=mandag..6=søndag), for alle kunder.
    """

    customer_id = get_jwt_identity()
    if customer_id is None:
        return jsonify({
            "success": False,
            "message": "Ugyldig token eller tomt identity."
        }), 401

    try:
        rows = (
            db.session.query(
                (func.dayofweek(LightSensorData.captured_at) - 1).label('weekday'),
                func.avg(LightSensorData.melanopic_edi).label('avg_edi'),
                func.avg(LightSensorData.lux_level).label('avg_lux'),
                func.avg(LightSensorData.exposure_score).label('avg_exposure'),
                func.sum(LightSensorData.action_required).label('actions')
            )
            .filter(LightSensorData.patient_id == 'P3')
            .group_by((func.dayofweek(LightSensorData.captured_at) - 1))
            .order_by((func.dayofweek(LightSensorData.captured_at) - 1))
            .all()
        )
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Fejl ved hentning af ugentlige data: {str(e)}"
        }), 500

    weekly_list = []
    for row in rows:
        weekly_list.append({
            "weekday_index": row.weekday,
            "average_melanopic_edi": float(row.avg_edi or 0.0),
            "average_lux": float(row.avg_lux or 0.0),
            "average_exposure_score": float(row.avg_exposure or 0.0),
            "action_required_count": int(row.actions or 0),
        })

    return jsonify({
        "success": True,
        "data": weekly_list
    }), 200



@customer_bp.route('/lightdata/monthly', methods=['GET'])
@jwt_required()
def get_customer_monthly_lightdata():
    """
    GET /api/customer/lightdata/monthly
    Returnerer P3’s månedlige data, aggregeret pr. dag i nuværende måned, for alle kunder.
    """

    customer_id = get_jwt_identity()
    if customer_id is None:
        return jsonify({
            "success": False,
            "message": "Ugyldig token eller tomt identity."
        }), 401

    from datetime import datetime
    now_utc = datetime.utcnow()
    year = now_utc.year
    month = now_utc.month

    try:
        rows = (
            db.session.query(
                func.day(LightSensorData.captured_at).label('day'),
                func.avg(LightSensorData.melanopic_edi).label('avg_edi'),
                func.avg(LightSensorData.lux_level).label('avg_lux'),
                func.avg(LightSensorData.exposure_score).label('avg_exposure'),
                func.sum(LightSensorData.action_required).label('actions')
            )
            .filter(LightSensorData.patient_id == 'P3')
            .filter(func.year(LightSensorData.captured_at) == year)
            .filter(func.month(LightSensorData.captured_at) == month)
            .group_by(func.day(LightSensorData.captured_at))
            .order_by(func.day(LightSensorData.captured_at))
            .all()
        )
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Fejl ved hentning af månedlige data: {str(e)}"
        }), 500

    monthly_list = []
    for row in rows:
        monthly_list.append({
            "day": row.day,
            "average_melanopic_edi": float(row.avg_edi or 0.0),
            "average_lux": float(row.avg_lux or 0.0),
            "average_exposure_score": float(row.avg_exposure or 0.0),
            "action_required_count": int(row.actions or 0),
        })

    return jsonify({
        "success": True,
        "data": monthly_list
    }), 200
