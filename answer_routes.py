# routes/answer_routes.py
from flask import Blueprint, request, jsonify
from app import db
from models.answer   import Answer
from models.customer import Customer
from models.question import Question
from models.choice   import Choice

answer_bp = Blueprint("answer_bp", __name__)

@answer_bp.route("", methods=["POST"])
def post_answer():
    data = request.get_json()

    # Udvid “required” med 'score'
    required = ["customer_id", "question_id", "choice_id", "score", "answer_text", "question_text_snap"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Feltet '{field}' mangler"}), 400

    # Valider at customer, question og choice findes (valgfrit, men anbefales)
    cust = Customer.query.get(data["customer_id"])
    if not cust:
        return jsonify({"error": "Customer ikke fundet"}), 404

    q = Question.query.get(data["question_id"])
    if not q:
        return jsonify({"error": "Spørgsmål ikke fundet"}), 404

    c = Choice.query.get(data["choice_id"])
    if not c:
        return jsonify({"error": "Choice ikke fundet"}), 404

    # Opret det nye svar, inklusiv score
    new_answer = Answer(
        customer_id        = data["customer_id"],
        question_id        = data["question_id"],
        choice_id          = data["choice_id"],
        score              = data["score"],
        answer_text        = data["answer_text"],
        question_text_snap = data["question_text_snap"]
    )
    db.session.add(new_answer)
    db.session.commit()

    return jsonify({"message": "Svar gemt", "answer_id": new_answer.id}), 201
