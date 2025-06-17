# routes/message_routes.py

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from mysql_db import get_db_connection   # Din egen funktion til MySQL-forbindelsen

message_bp = Blueprint("message_bp", __name__)



# ── 1) GET Indbakke for kliniker og patient ───────────────────────────────
@message_bp.route("/inbox", methods=["GET"])
@jwt_required()
def get_inbox():
    """
    GET /api/messages/inbox
    Henter seneste besked i hver tråd for enten kliniker eller patient.
    """
    # Hent user_id og user_role fra JWT
    user_id   = get_jwt_identity()         # identiteten (typisk user_id)
    user_role = get_jwt().get("role")       # ekstra claim "role"

    if user_role not in ("clinician", "patient"):
        return jsonify({"error": "Ukendt rolle"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if user_role == "clinician":
            cursor.execute("""
                SELECT m.*,
                       CONCAT(c.first_name, ' ', c.last_name) AS sender_name,
                       CONCAT(p.first_name, ' ', p.last_name) AS receiver_name
                FROM messages m
                JOIN clinician_patients cp 
                  ON (m.sender_type = 'patient'   AND m.sender_id   = cp.patient_id)
                  OR (m.sender_type = 'clinician' AND m.receiver_id = cp.patient_id)
                LEFT JOIN clinicians c 
                  ON c.id = CASE 
                               WHEN m.sender_type = 'clinician' THEN m.sender_id 
                               ELSE m.receiver_id 
                            END
                LEFT JOIN patients p 
                  ON p.id = CASE 
                               WHEN m.sender_type = 'patient' THEN m.sender_id 
                               ELSE m.receiver_id 
                            END
                JOIN (
                    SELECT thread_id, MAX(id) AS latest_id
                    FROM messages
                    WHERE sender_id = %s OR receiver_id = %s
                    GROUP BY thread_id
                ) latest_msg
                  ON m.thread_id = latest_msg.thread_id 
                 AND m.id        = latest_msg.latest_id
                WHERE cp.clinician_id = %s
                ORDER BY m.sent_at DESC
            """, (user_id, user_id, user_id))

        else:  # user_role == "patient"
            cursor.execute("""
                SELECT m.*,
                       CONCAT(c.first_name, ' ', c.last_name) AS sender_name,
                       CONCAT(p.first_name, ' ', p.last_name) AS receiver_name
                FROM messages m
                LEFT JOIN clinicians c 
                  ON c.id = CASE 
                               WHEN m.sender_type = 'clinician' THEN m.sender_id 
                               ELSE m.receiver_id 
                            END
                LEFT JOIN patients p 
                  ON p.id = CASE 
                               WHEN m.sender_type = 'patient' THEN m.sender_id 
                               ELSE m.receiver_id 
                            END
                JOIN (
                    SELECT thread_id, MAX(id) AS latest_id
                    FROM messages
                    WHERE sender_id = %s OR receiver_id = %s
                    GROUP BY thread_id
                ) latest_msg
                  ON m.thread_id = latest_msg.thread_id 
                 AND m.id        = latest_msg.latest_id
                WHERE m.receiver_id = %s OR m.sender_id = %s
                ORDER BY m.sent_at DESC
            """, (user_id, user_id, user_id, user_id))

        messages = cursor.fetchall()
        conn.close()
        return jsonify({"messages": messages}), 200

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500



# ── 2) POST Sender besked ─────────────────────────────────────────────────
@message_bp.route("/send", methods=["POST"])
@jwt_required()
def send_message():
    """
    POST /api/messages/send
    Sender en ny besked eller svarer i en eksisterende tråd.
    Forventet JSON-body:
      {
        "receiver_id": <int>,
        "message":     "<string>",
        "subject":     "<string>",
        "reply_to":    <int>   # (valgfrit)
      }
    """
    user_id   = get_jwt_identity()
    user_role = get_jwt().get("role")

    if user_role not in ("clinician", "patient"):
        return jsonify({"error": "Ukendt rolle"}), 400

    try:
        data = request.get_json(force=True)
    except:
        return jsonify({"error": "Ugyldigt JSON"}), 400

    receiver_id = data.get("receiver_id")
    subject     = (data.get("subject") or "").strip()
    message_txt = (data.get("message") or "").strip()
    reply_to    = data.get("reply_to", None)

    if not receiver_id or not subject or not message_txt:
        return jsonify({"error": "Manglende data"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        thread_id = None
        if reply_to:
            cursor.execute("SELECT thread_id FROM messages WHERE id = %s", (int(reply_to),))
            orig = cursor.fetchone()
            if not orig:
                conn.close()
                return jsonify({"error": "Oprindelig besked ikke fundet"}), 404
            thread_id = orig["thread_id"]

        # Rollevalidering: kliniker → patient eller patient → kliniker
        if user_role == "clinician":
            cursor.execute("""
                SELECT 1 FROM clinician_patients
                WHERE clinician_id = %s AND patient_id = %s
            """, (user_id, receiver_id))
            if not cursor.fetchone():
                conn.close()
                return jsonify({"error": "Du er ikke tilknyttet denne patient"}), 403

        else:  # user_role == "patient"
            cursor.execute("""
                SELECT 1 FROM clinician_patients
                WHERE clinician_id = %s AND patient_id = %s
            """, (receiver_id, user_id))
            if not cursor.fetchone():
                conn.close()
                return jsonify({"error": "Denne kliniker er ikke tilknyttet dig"}), 403

        # Indsæt besked i DB
        cursor.execute("""
            INSERT INTO messages (
                sender_id, sender_type, receiver_id,
                subject, message, sent_at, `read`, thread_id
            ) VALUES (%s, %s, %s, %s, %s, NOW(), 0, %s)
        """, (
            user_id, user_role, receiver_id, subject, message_txt, thread_id
        ))
        last_id = cursor.lastrowid

        if not thread_id:
            cursor.execute(
                "UPDATE messages SET thread_id = %s WHERE id = %s",
                (last_id, last_id)
            )

        conn.commit()
        conn.close()
        return jsonify({"status": "Besked sendt"}), 200

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500



# ── 3) GET Hent én tråd ────────────────────────────────────────────────────
@message_bp.route("/thread-by-id/<int:thread_id>", methods=["GET"])
@jwt_required()
def get_thread_by_id(thread_id):
    """
    GET /api/messages/thread-by-id/<thread_id>
    Henter alle beskeder i den pågældende tråd, sorteret efter sent_at.
    Returnerer 403, hvis brugeren ikke er afsender eller modtager i tråden.
    """
    user_id   = get_jwt_identity()
    user_role = get_jwt().get("role")

    if user_role not in ("clinician", "patient"):
        return jsonify({"error": "Ukendt rolle"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT 
                m.id, m.sender_id, m.receiver_id, m.sender_type,
                m.message, m.subject, m.sent_at, m.read, m.thread_id,
                CASE
                    WHEN m.sender_type = 'patient' THEN CONCAT(p.first_name, ' ', p.last_name)
                    WHEN m.sender_type = 'clinician' THEN CONCAT(c.first_name, ' ', c.last_name)
                    ELSE 'Ukendt'
                END AS sender_name,
                CASE
                    WHEN m.sender_type = 'patient' THEN CONCAT(c.first_name, ' ', c.last_name)
                    WHEN m.sender_type = 'clinician' THEN CONCAT(p.first_name, ' ', p.last_name)
                    ELSE 'Ukendt'
                END AS receiver_name
            FROM messages m
            LEFT JOIN patients p 
              ON (m.sender_type = 'patient'   AND m.sender_id   = p.id)
              OR (m.sender_type = 'clinician' AND m.receiver_id = p.id)
            LEFT JOIN clinicians c 
              ON (m.sender_type = 'clinician' AND m.sender_id   = c.id)
              OR (m.sender_type = 'patient'   AND m.receiver_id = c.id)
            WHERE m.thread_id = %s
            ORDER BY m.sent_at ASC
        """, (thread_id,))

        messages = cursor.fetchall()
        conn.close()

        if not messages:
            return jsonify([]), 200

        adgang = any(
            (msg["sender_id"] == user_id or msg["receiver_id"] == user_id)
            for msg in messages
        )
        if not adgang:
            return jsonify({"error": "Ingen adgang til denne tråd"}), 403

        return jsonify(messages), 200

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500



# ── 4) DELETE Slet en tråd ─────────────────────────────────────────────────
@message_bp.route("/thread/<int:thread_id>", methods=["DELETE"])
@jwt_required()
def delete_message_thread(thread_id):
    """
    DELETE /api/messages/thread/<thread_id>
    Flytter alle beskeder i tråden til deleted_messages, derefter sletter dem.
    """
    user_id   = get_jwt_identity()
    user_role = get_jwt().get("role")

    if user_role not in ("clinician", "patient"):
        return jsonify({"error": "Ukendt rolle"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM messages WHERE thread_id = %s", (thread_id,))
        messages = cursor.fetchall()

        if not messages:
            conn.close()
            return "", 204

        for msg in messages:
            cursor.execute("""
                INSERT INTO deleted_messages (
                    original_message_id, sender_id, receiver_id, sender_type,
                    message, sent_at, subject, thread_id, deleted_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                msg["id"],
                msg["sender_id"],
                msg["receiver_id"],
                msg["sender_type"],
                msg["message"],
                msg["sent_at"],
                msg["subject"],
                msg["thread_id"],
                user_role
            ))

        cursor.execute("DELETE FROM messages WHERE thread_id = %s", (thread_id,))
        conn.commit()
        conn.close()
        return "", 204

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500



# ── 5) GET Modtagere ───────────────────────────────────────────────────────
@message_bp.route("/recipients", methods=["GET"])
@jwt_required()
def get_recipients():
    """
    GET /api/messages/recipients
    Returnerer liste over klinikere for patient, eller patienter for kliniker.
    """
    user_id   = get_jwt_identity()
    user_role = get_jwt().get("role")

    if user_role not in ("clinician", "patient"):
        return jsonify({"error": "Ukendt rolle"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if user_role == "patient":
            cursor.execute("""
                SELECT c.id, CONCAT(c.first_name, ' ', c.last_name) AS name
                FROM clinicians c
                JOIN clinician_patients cp ON cp.clinician_id = c.id
                WHERE cp.patient_id = %s
            """, (user_id,))

        else:  # user_role == "clinician"
            cursor.execute("""
                SELECT p.id, CONCAT(p.first_name, ' ', p.last_name) AS name
                FROM patients p
                JOIN clinician_patients cp ON cp.patient_id = p.id
                WHERE cp.clinician_id = %s
            """, (user_id,))

        recipients = cursor.fetchall()
        conn.close()
        return jsonify(recipients), 200

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500



# ── 6) GET Enkelt besked ───────────────────────────────────────────────────
@message_bp.route("/<int:message_id>", methods=["GET"])
@jwt_required()
def get_message(message_id):
    """
    GET /api/messages/<message_id>
    Henter én besked, hvis brugeren er afsender eller modtager.
    """
    user_id   = get_jwt_identity()
    user_role = get_jwt().get("role")

    if user_role not in ("clinician", "patient"):
        return jsonify({"error": "Ukendt rolle"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT *,
                   CASE WHEN sender_id = %s OR receiver_id = %s THEN TRUE ELSE FALSE END AS access_granted
            FROM messages
            WHERE id = %s
        """, (user_id, user_id, message_id))

        msg = cursor.fetchone()
        conn.close()

        if not msg:
            return jsonify({"error": "Ikke fundet"}), 404

        if not msg["access_granted"]:
            return jsonify({"error": "Ingen adgang"}), 403

        del msg["access_granted"]
        return jsonify(msg), 200

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500

# ── 7) PATCH: Markér en hel tråd som læst ──────────────────────────────────
@message_bp.route("/thread/<int:thread_id>/read", methods=["PATCH"])
@jwt_required()
def mark_thread_as_read(thread_id):
    """
    PATCH /api/messages/thread/<thread_id>/read
    Sætter alle beskeder i tråden med given thread_id til read = 1,
    men kun hvis den indloggede bruger er modtager.
    Returnerer 204, hvis alt går godt, ellers 404 eller 500.
    """
    user_id   = get_jwt_identity()
    user_role = get_jwt().get("role")

    if user_role not in ("clinician", "patient"):
        return jsonify({"error": "Ukendt rolle"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor()

    try:
        # Opdater kun de beskeder i tråden, hvor current_user er receiver
        cursor.execute("""
            UPDATE messages
            SET `read` = 1
            WHERE thread_id = %s
              AND receiver_id = %s
        """, (thread_id, user_id))

        # Hvis der ikke blev opdateret nogen rækker, kan vi returnere 404 (enten forkert thread eller ingen beskeder til bruger)
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({"error": "Ingen ulæste beskeder i tråden for denne bruger"}), 404

        conn.commit()
        conn.close()
        return "", 204

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500
