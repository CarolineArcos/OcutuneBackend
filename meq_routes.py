from flask import Blueprint, jsonify, request, g
from mysql_db import get_db_connection
from models.meq_question import MEQQuestion
from models.meq_answer   import MEQAnswer

meq_bp = Blueprint("meq", __name__)

@meq_bp.route('/questions', methods=['GET'])
def get_meq_questions():
    try:
        # 1) Brug din egen all()-metode
        questions = MEQQuestion.all()

        # 2) Serialisér til JSON
        return jsonify([q.to_dict() for q in questions]), 200
    except Exception as e:
        # Log exception og returnér 500 med fejlbesked
        current_app.logger.exception("Fejl i get_meq_questions")
        return jsonify({'success': False, 'message': str(e)}), 500

@meq_bp.route('/answers', methods=['POST'])
def save_meq_answers():
    data = request.get_json(force=True)
    pid  = data.get('participant_id')
    ans  = data.get('answers', [])

    if not pid or not isinstance(ans, list):
        return jsonify({'error': 'Ugyldigt payload'}), 400

    # Gem alle svar via en klasse-metode på MEQAnswer
    MEQAnswer.save(pid, ans)

    return jsonify({'status': 'OK'}), 200


@meq_bp.teardown_app_request
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()
