from flask import Blueprint, request, jsonify
from schemas.question_schema import QuestionSchema

question_bp = Blueprint("question_bp", __name__)

@question_bp.route("/", methods=["GET"], strict_slashes=False)
def get_questions():
    # Forsink importen, så vi ikke skaber cirkulær import
    from app import db
    from models.question import Question

    # Håndter ?question_id=<id>
    question_id = request.args.get("question_id")
    if question_id:
        question = Question.query.get(question_id)
        if not question:
            return jsonify({"error": "Spørgsmål ikke fundet"}), 404

        return jsonify(question.to_dict()), 200

    # Ellers returner alle
    questions = Question.query.all()
    return jsonify([q.to_dict() for q in questions]), 200

@question_bp.route("/", methods=["POST"], strict_slashes=False)
def post_question():
    # Forsink importen
    from app import db
    from models.question import Question

    data = request.get_json()
    schema = QuestionSchema()
    try:
        validated = schema.load(data)
    except Exception as err:
        return jsonify({"error": err.messages}), 400

    new_q = Question(question_text=validated["question_text"])
    db.session.add(new_q)
    db.session.commit()
    return jsonify({"status": "ok", "id": new_q.id}), 201
