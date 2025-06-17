# routes/choice_routes.py

from flask import Blueprint, request, jsonify
from schemas.choice_schema import ChoiceSchema

choice_bp = Blueprint("choice_bp", __name__)

@choice_bp.route("/", methods=["GET"], strict_slashes=False)
def get_choices():
    from app import db
    from models.choice import Choice

    question_id = request.args.get("question_id")
    if question_id:
        choices = Choice.query.filter_by(question_id=question_id).all()
    else:
        choices = Choice.query.all()
    return jsonify([c.to_dict() for c in choices]), 200

@choice_bp.route("/", methods=["POST"], strict_slashes=False)
def post_choice():
    from app import db
    from models.choice import Choice
    from models.question import Question

    data = request.get_json()
    schema = ChoiceSchema()
    try:
        validated = schema.load(data)
    except Exception as err:
        return jsonify({"error": err.messages}), 400

    question = Question.query.get(validated["question_id"])
    if not question:
        return jsonify({"error": "Spørgsmål ikke fundet"}), 404

    new_c = Choice(
        question_id=validated["question_id"],
        choice_text=validated["choice_text"],
        score=validated["score"]
    )
    db.session.add(new_c)
    db.session.commit()
    return jsonify({"status": "ok", "id": new_c.id}), 201
