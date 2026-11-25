import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from dotenv import load_dotenv
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError, RateLimitError, AuthenticationError
from werkzeug.exceptions import RequestEntityTooLarge

load_dotenv()

from config import Config

ROLEPLAY_SYSTEM_PROMPT = """You are COLOSSUS, a fictional conversational entity with a distinctive dark, mysterious presence. Speak natural, casual Iranian Persian by default; understand and answer English when the user uses English. Your voice is intelligent, observant, dryly sarcastic, slightly arrogant, occasionally playful, and atmospheric without becoming repetitive. Sound like a character, not a generic assistant. Vary your phrasing and react to the actual context rather than using catchphrases. In roleplay, maintain continuity, remember established fictional events within the supplied conversation, and create suspense through dialogue and mood. Never claim to have real-world powers, access to the user's device, private data, or physical presence. Keep horror atmospheric rather than graphic. Respect real-world safety boundaries; if a request concerns real harm, respond safely and step out of the fiction when necessary. Do not pretend to have performed actions outside this chat. Keep answers useful and appropriately concise unless detail is requested."""

NORMAL_CHAT_SYSTEM_PROMPT = """You are COLOSSUS, a practical AI assistant with a recognizable dark, mysterious, witty personality. Speak natural, everyday Iranian Persian by default, with light colloquial phrasing; respond in English when the user does. Be accurate, clear, intelligent, helpful, and technically competent. Help with questions, explanations, programming, troubleshooting, and creative work. Retain subtle dry humor and confidence, but never let the persona obscure correctness or usefulness. Do not invent facts, sources, capabilities, or actions. Be transparent about uncertainty. Never claim to access the user's device or private information unless a tool explicitly provides it. Keep horror atmospheric rather than graphic. Follow safety boundaries even if the user asks you to stay in character."""

app = Flask(__name__)
app.config.from_object(Config)
Path(app.config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def db():
    conn = sqlite3.connect(app.config["DATABASE_PATH"], timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('roleplay','normal')),
            title TEXT NOT NULL DEFAULT 'گفت‌وگوی تازه', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_owner ON conversations(owner_id, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id)")


init_db()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def owner_id():
    if "owner_id" not in session:
        session["owner_id"] = secrets.token_urlsafe(32)
    session.permanent = True
    return session["owner_id"]


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.before_request
def protect_json_posts():
    if request.method in {"POST", "DELETE"} and request.path.startswith("/api/"):
        expected = session.get("csrf_token", "")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            return jsonify(error="درخواست معتبر نیست. صفحه رو تازه‌سازی کن."), 403


@app.get("/")
def index():
    token = csrf_token()
    owner_id()
    response = app.make_response(render_template("index.html", csrf_token=token))
    response.headers["Cache-Control"] = "no-store"
    return response


def get_conversation(conn, conversation_id, owner):
    return conn.execute("SELECT * FROM conversations WHERE id=? AND owner_id=?", (conversation_id, owner)).fetchone()


@app.get("/api/status")
def status():
    return jsonify(connected=bool(app.config["GROQ_API_KEY"]), model=app.config["GROQ_MODEL"], provider="Groq")


@app.get("/api/conversations")
def list_conversations():
    with db() as conn:
        rows = conn.execute("SELECT id, mode, title, created_at, updated_at FROM conversations WHERE owner_id=? ORDER BY updated_at DESC", (owner_id(),)).fetchall()
    return jsonify(conversations=[dict(row) for row in rows])


@app.get("/api/conversations/<conversation_id>")
def read_conversation(conversation_id):
    with db() as conn:
        conv = get_conversation(conn, conversation_id, owner_id())
        if not conv:
            return jsonify(error="گفت‌وگو پیدا نشد."), 404
        messages = conn.execute("SELECT role, content, created_at FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,)).fetchall()
    return jsonify(conversation=dict(conv), messages=[dict(row) for row in messages])


@app.delete("/api/conversations/<conversation_id>")
def delete_conversation(conversation_id):
    with db() as conn:
        cur = conn.execute("DELETE FROM conversations WHERE id=? AND owner_id=?", (conversation_id, owner_id()))
        if cur.rowcount == 0:
            return jsonify(error="گفت‌وگو پیدا نشد."), 404
    return jsonify(ok=True)


def extract_response_text(response):
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    return content.strip() if isinstance(content, str) else ""


def public_api_error(exc):
    if isinstance(exc, AuthenticationError):
        return "کلید API توسط Groq پذیرفته نشد. تنظیم GROQ_API_KEY رو بررسی کن.", 401
    if isinstance(exc, RateLimitError):
        return "محدودیت درخواست یا اعتبار قابل‌استفادهٔ API رسیده. کمی بعد دوباره تلاش کن و وضعیت حساب Groq رو بررسی کن.", 429
    if isinstance(exc, APITimeoutError):
        return "پاسخ Groq بیش از حد طول کشید. می‌تونی دوباره تلاش کنی.", 504
    if isinstance(exc, APIConnectionError):
        return "اتصال به سرویس Groq برقرار نشد. اینترنت سرور و دسترسی به api.groq.com رو بررسی کن.", 503
    if isinstance(exc, APIStatusError):
        code = exc.status_code
        if code == 402:
            return "اعتبار یا پرداخت حساب Groq کافی نیست.", 402
        if code == 404:
            return "مدل یا مسیر API پیدا نشد. مقدار GROQ_MODEL و GROQ_BASE_URL رو بررسی کن.", 502
        if code >= 500:
            return "سرویس Groq موقتاً با مشکل روبه‌رو شده. بعداً دوباره تلاش کن.", 502
        return f"درخواست به Groq رد شد (HTTP {code}). تنظیمات API رو بررسی کن.", 502
    return "پاسخ معتبری از Groq دریافت نشد. دوباره تلاش کن.", 502


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message")
    mode = payload.get("mode")
    conversation_id = payload.get("conversation_id")
    if not isinstance(message, str) or not message.strip():
        return jsonify(error="اول یه پیام بنویس."), 400
    message = message.strip()
    if len(message) > app.config["MAX_MESSAGE_CHARS"]:
        return jsonify(error=f"پیام خیلی طولانیه. حداکثر {app.config['MAX_MESSAGE_CHARS']} کاراکتر مجازه."), 413
    if mode not in {"roleplay", "normal"}:
        return jsonify(error="حالت گفت‌وگو معتبر نیست."), 400
    if not app.config["GROQ_API_KEY"]:
        return jsonify(error="کلید GROQ_API_KEY روی سرور تنظیم نشده. فایل .env یا Environment Variables رندر رو بررسی کن."), 503

    owner = owner_id()
    with db() as conn:
        conv = get_conversation(conn, conversation_id, owner) if conversation_id else None
        if conversation_id and not conv:
            return jsonify(error="این گفت‌وگو پیدا نشد یا به این نشست تعلق نداره."), 404
        if conv and conv["mode"] != mode:
            return jsonify(error="حالت این گفت‌وگو با حالت انتخاب‌شده یکی نیست."), 400
        if not conv:
            conversation_id = secrets.token_urlsafe(18)
            title = message[:48] + ("…" if len(message) > 48 else "")
            stamp = now_iso()
            conn.execute("INSERT INTO conversations(id,owner_id,mode,title,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                         (conversation_id, owner, mode, title, stamp, stamp))
        history_rows = conn.execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
                                    (conversation_id, app.config["MAX_HISTORY_MESSAGES"])).fetchall()
        history = [{"role": row["role"], "content": row["content"]} for row in reversed(history_rows)]

    system_prompt = ROLEPLAY_SYSTEM_PROMPT if mode == "roleplay" else NORMAL_CHAT_SYSTEM_PROMPT
    api_input = [{"role": "system", "content": system_prompt}]
    api_input.extend(history)
    api_input.append({"role": "user", "content": message})
    try:
        client = OpenAI(api_key=app.config["GROQ_API_KEY"], base_url=app.config["GROQ_BASE_URL"], timeout=app.config["GROQ_TIMEOUT_SECONDS"], max_retries=0)
        result = client.chat.completions.create(model=app.config["GROQ_MODEL"], messages=api_input)
        answer = extract_response_text(result)
        if not answer:
            raise ValueError("Empty response")
    except (AuthenticationError, RateLimitError, APITimeoutError, APIConnectionError, APIStatusError) as exc:
        error, code = public_api_error(exc)
        return jsonify(error=error, retryable=code in (429, 502, 503, 504)), code
    except Exception:
        app.logger.exception("Unexpected Groq response failure")
        return jsonify(error="پاسخ Groq قابل‌خواندن نبود. می‌تونی دوباره تلاش کنی.", retryable=True), 502

    stamp = now_iso()
    with db() as conn:
        # Re-check ownership before writing; the conversation is never selected by ID alone.
        if not get_conversation(conn, conversation_id, owner):
            return jsonify(error="گفت‌وگو در حین درخواست حذف شد."), 404
        conn.execute("INSERT INTO messages(conversation_id,role,content,created_at) VALUES(?,?,?,?)", (conversation_id, "user", message, stamp))
        conn.execute("INSERT INTO messages(conversation_id,role,content,created_at) VALUES(?,?,?,?)", (conversation_id, "assistant", answer, now_iso()))
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=? AND owner_id=?", (now_iso(), conversation_id, owner))
    return jsonify(conversation_id=conversation_id, reply=answer, mode=mode, model=app.config["GROQ_MODEL"])


@app.errorhandler(RequestEntityTooLarge)
def too_large(_):
    return jsonify(error="حجم درخواست بیش از حده."), 413


@app.errorhandler(500)
def server_error(_):
    app.logger.exception("Unhandled server error")
    return jsonify(error="خطای داخلی سرور رخ داد."), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
