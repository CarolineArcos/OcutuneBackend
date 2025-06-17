# routes/chronotype_routes.py

from flask import Blueprint, request, jsonify
from mysql_db import get_db_connection   # Din egen helper til at åbne en MySQL‐forbindelse

chronotype_bp = Blueprint("chronotype_bp", __name__)

# ── 1) POST: Beregn og opdater REMQ‐score for en kunde ────────────────────
# routes/chronotype_routes.py


chronotype_bp = Blueprint("chronotype_bp", __name__, url_prefix="/api/chronotypes")

@chronotype_bp.route("/calculate-rmeq-score/<int:customer_id>", methods=["POST"])
def calculate_rmeq_score(customer_id):
    """
    POST /api/chronotypes/calculate-rmeq-score/<customer_id>
    1) Beregner total RMEQ‐score for den givne customer_id (sum af alle choice.score).
    2) Opdaterer customers.rmeq_score‐feltet.
    3) Finder den række i chronotypes‐tabellen, hvor remq_score ligger i [min_score, max_score].
    4) Opdaterer customers.chronotype med den fundne type_key.
    5) Returnerer rmeq_score og chronotype_key i JSON.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # -----------------------------------------------------------
        # 1) Beregn RMEQ‐score ved at summere alle choice.score for kunden
        # ------------------------------------------------------------
        cursor.execute("""
            SELECT IFNULL(SUM(cc.score), 0) AS total_rmeq
            FROM customer_answers ca
            JOIN customer_choices cc ON ca.choice_id = cc.id
            WHERE ca.customer_id = %s
        """, (customer_id,))
        row = cursor.fetchone()
        remq_score = row[0] if row is not None else 0

        # ------------------------------------------------------------
        # 2) Opdater customers.rmeq_score
        # ------------------------------------------------------------
        cursor.execute("""
            UPDATE customers
            SET rmeq_score = %s
            WHERE id = %s
        """, (remq_score, customer_id))

        # ------------------------------------------------------------
        # 3) Slå op i chronotypes‐tabellen efter type_key, hvor
        #    remq_score ligger mellem min_score og max_score
        # ------------------------------------------------------------
        cursor.execute("""
            SELECT type_key
            FROM chronotypes
            WHERE %s BETWEEN min_score AND max_score
            LIMIT 1
        """, (remq_score,))
        chronotype_row = cursor.fetchone()
        # Hvis ingen række findes (f.eks. score uden for range), kan man sætte default:
        if chronotype_row:
            chronotype_key = chronotype_row[0]
        else:
            # Hvis remq_score er udenfor værdierne i tabellen, kan I enten sætte None
            # eller en “fallback”-værdi som f.eks. 'neither'
            chronotype_key = None

        # ------------------------------------------------------------
        # 4) Opdater customers.chronotype med det fundne type_key
        # ------------------------------------------------------------
        cursor.execute("""
            UPDATE customers
            SET chronotype = %s
            WHERE id = %s
        """, (chronotype_key, customer_id))

        conn.commit()

        # ------------------------------------------------------------
        # 5) Returnér begge værdier i JSON
        # ------------------------------------------------------------
        return jsonify({
            "message":        "rMEQ-score og chronotype opdateret",
            "rmeq_score":     remq_score,
            "chronotype_key": chronotype_key
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({
            "error": f"Fejl ved beregning/opdatering: {str(e)}"
        }), 500

    finally:
        cursor.close()
        conn.close()


# ── 2) GET: Hent alle chronotypes (inkl. billede‐URL osv.) ─────────────────
@chronotype_bp.route("/", methods=["GET"])
def get_chronotypes():
    """
    GET /api/chronotypes
    Returnerer alle rækker i chronotypes, hvor language = 'da'.
    JSON‐objektet indeholder alle kolonner inkl.:
      - id
      - type_key
      - title
      - short_description
      - long_description
      - facts
      - image_url
      - icon_url
      - language
      - min_score
      - max_score
      - summary_text

    Klienten kan så lave Image.network('https://<din‐domæne>/images/<image_url>')
    for at hente billederne.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT 
              id,
              type_key,
              title,
              short_description,
              long_description,
              facts,
              image_url,
              icon_url,
              language,
              min_score,
              max_score,
              summary_text
            FROM chronotypes
            WHERE language = 'da'
        """)
        results = cursor.fetchall()
        return jsonify(results), 200

    except Exception as e:
        return jsonify({
            'error': f'Fejl ved hentning: {str(e)}'
        }), 500

    finally:
        cursor.close()
        conn.close()


# ── 3) GET: Hent ét chronotype via type_key ────────────────────────────────
@chronotype_bp.route("/<string:type_key>", methods=["GET"])
def get_chronotype(type_key):
    """
    GET /api/chronotypes/<type_key>
    Returnerer ét chronotype‐objekt for givet type_key og language = 'da'.
    JSON‐objektet indeholder alle kolonner som beskrevet i get_chronotypes().
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT 
              id,
              type_key,
              title,
              short_description,
              long_description,
              facts,
              image_url,
              icon_url,
              language,
              min_score,
              max_score,
              summary_text
            FROM chronotypes
            WHERE type_key = %s AND language = 'da'
        """, (type_key,))
        result = cursor.fetchone()

        if result:
            return jsonify(result), 200
        else:
            return jsonify({'error': 'Chronotype ikke fundet'}), 404

    except Exception as e:
        return jsonify({
            'error': f'Fejl ved hentning: {str(e)}'
        }), 500

    finally:
        cursor.close()
        conn.close()


# ── 4) GET: Hent chronotype ud fra score ───────────────────────────────────
@chronotype_bp.route("/rmeq-by-score/<int:score>", methods=["GET"])
def get_chronotype_by_score(score):
    """
    GET /api/chronotypes/rmeq-by-score/<score>
    Returnerer det chronotype, hvor (score BETWEEN min_score AND max_score) og language = 'da'.
    JSON‐objektet indeholder alle kolonner som beskrevet i get_chronotypes().
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
              id,
              type_key,
              title,
              short_description,
              long_description,
              facts,
              image_url,
              icon_url,
              language,
              min_score,
              max_score,
              summary_text
            FROM chronotypes
            WHERE %s BETWEEN min_score AND max_score
              AND language = 'da'
        """, (score,))
        result = cursor.fetchone()

        if result:
            return jsonify(result), 200
        else:
            return jsonify({'error': 'No matching chronotype'}), 404

    except Exception as e:
        return jsonify({
            'error': f'Fejl ved hentning: {str(e)}'
        }), 500

    finally:
        cursor.close()
        conn.close()
