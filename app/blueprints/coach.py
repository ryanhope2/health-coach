from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from ..ai_coach import get_response
from ..extensions import db
from ..models import ChatMessage, CoachNote, User, normalize_note_key

coach_bp = Blueprint("coach", __name__, url_prefix="/coach")

HISTORY_TURNS = 20  # messages (not pairs) sent to Claude as context


def _current_user_id():
    return session["user_id"]


@coach_bp.route("/")
def index():
    messages = (
        ChatMessage.query.filter_by(user_id=_current_user_id())
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return render_template("coach/index.html", messages=messages)


@coach_bp.route("/send", methods=["POST"])
def send():
    user_id = _current_user_id()
    text = request.form.get("message", "").strip()
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not text:
        if is_ajax:
            return jsonify({"error": "empty message"}), 400
        return redirect(url_for("coach.index"))

    user = User.query.get(user_id)

    history_rows = (
        ChatMessage.query.filter_by(user_id=user_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(HISTORY_TURNS)
        .all()
    )
    history_rows.reverse()
    history = [{"role": m.role, "content": m.content} for m in history_rows]

    db.session.add(ChatMessage(user_id=user_id, role="user", content=text))
    db.session.commit()

    try:
        reply = get_response(
            api_key=current_app.config["ANTHROPIC_API_KEY"],
            user=user,
            conversation_history=history,
            new_message=text,
        )
    except Exception as e:
        current_app.logger.exception("coach chat failed")
        reply = f"Sorry, I hit an error talking to the AI ({e}). Try again in a moment."

    db.session.add(ChatMessage(user_id=user_id, role="assistant", content=reply))
    db.session.commit()

    if is_ajax:
        return jsonify({"reply": reply})
    return redirect(url_for("coach.index"))


@coach_bp.route("/clear", methods=["POST"])
def clear():
    ChatMessage.query.filter_by(user_id=_current_user_id()).delete()
    db.session.commit()
    flash("Chat history cleared.", "success")
    return redirect(url_for("coach.index"))


@coach_bp.route("/notes")
def notes():
    rows = (
        CoachNote.query.filter_by(user_id=_current_user_id())
        .order_by(CoachNote.updated_at.desc())
        .all()
    )
    return render_template("coach/notes.html", notes=rows)


@coach_bp.route("/notes/new", methods=["POST"])
def add_note():
    key = normalize_note_key(request.form.get("key", ""))
    content = request.form.get("content", "").strip()
    if not key or not content:
        flash("Both a topic and details are needed.", "error")
        return redirect(url_for("coach.notes"))

    existing = CoachNote.query.filter_by(user_id=_current_user_id(), key=key).first()
    if existing:
        existing.content = content
        flash(f'Updated existing note "{key}".', "success")
    else:
        db.session.add(CoachNote(user_id=_current_user_id(), key=key, content=content))
        flash("Note added.", "success")
    db.session.commit()
    return redirect(url_for("coach.notes"))


@coach_bp.route("/notes/<int:note_id>/update", methods=["POST"])
def update_note(note_id):
    note = CoachNote.query.filter_by(id=note_id, user_id=_current_user_id()).first_or_404()
    key = normalize_note_key(request.form.get("key", ""))
    content = request.form.get("content", "").strip()
    if not key or not content:
        flash("Both a topic and details are needed.", "error")
        return redirect(url_for("coach.notes"))
    note.key = key
    note.content = content
    db.session.commit()
    flash("Note updated.", "success")
    return redirect(url_for("coach.notes"))


@coach_bp.route("/notes/<int:note_id>/delete", methods=["POST"])
def delete_note(note_id):
    note = CoachNote.query.filter_by(id=note_id, user_id=_current_user_id()).first_or_404()
    db.session.delete(note)
    db.session.commit()
    flash("Note deleted.", "success")
    return redirect(url_for("coach.notes"))
