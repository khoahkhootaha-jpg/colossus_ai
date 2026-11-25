# COLOSSUS AI

A Persian-first, horror-atmosphere chatbot built with Flask, HTML/CSS/JavaScript, SQLite, and the Groq's OpenAI-compatible Chat Completions API. It has two separate modes: Roleplay and Normal Chat. No fake fallback responses are generated: if Groq fails, the UI shows an error and offers retry when appropriate.

## Requirements

- Python 3.10+
- A Groq API key and an account with API access/limits
- Network access from the server to `https://api.groq.com`

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then set `GROQ_API_KEY` and a strong `SECRET_KEY`. The app loads `.env` automatically when using `python-dotenv` through your environment/runner; to make that explicit, add `from dotenv import load_dotenv; load_dotenv()` at the top of `app.py` before importing `Config`, or export the variables in your shell. (Render environment variables need no `.env` file.)

```bash
python app.py
```

Open `http://127.0.0.1:5000`.

## Character image

Place the supplied, authorized COLOSSUS character image at:

`static/images/colossus.png`

The application intentionally does not substitute another character. Until the file is supplied, a built-in CSS fallback tile appears.

## xAI configuration

The app uses the official Groq endpoint and OpenAI-compatible Python SDK with the Chat Completions API:

- `GROQ_API_KEY` — required, server-side only
- `GROQ_BASE_URL` — defaults to `https://api.groq.com/v1`
- `GROQ_MODEL` — defaults to `openai/gpt-oss-120b`
- `GROQ_TIMEOUT_SECONDS` — defaults to `90`

The API key is never sent to the browser. A real request is made for each new message. API usage may incur charges under the xAI account's current pricing and limits. The app cannot verify live credentials until you configure a key and send a test message.

## Render deployment

1. Push this folder to a Git repository.
2. Create a Render **Web Service** from that repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --workers 2 --threads 4 --timeout 120`
5. Add environment variables: `GROQ_API_KEY`, `GROQ_MODEL=grok-4.7`, `GROQ_BASE_URL=https://api.groq.com/v1`, a long random `SECRET_KEY`, and `COOKIE_SECURE=true`.
6. For durable SQLite storage, attach a Render persistent disk (for example mounted at `/var/data`) and set `DATABASE_PATH=/var/data/conversations.db`.
7. Deploy and test `/api/status`, then send a real message in both modes.

**Important:** Render's ordinary filesystem is ephemeral. Without a persistent disk, SQLite conversation history can disappear during redeploys or restarts. SQLite is suitable for a modest single-instance app; for multiple instances or heavier traffic, use a managed database such as PostgreSQL and adapt the data layer.

## Security notes

- Conversations are scoped to a random server-side session owner ID; knowing another conversation ID is not sufficient to read/delete it.
- Mutating API requests require a session CSRF token.
- Session cookies are HTTP-only and SameSite=Lax; set `COOKIE_SECURE=true` behind HTTPS in production.
- Keep `.env` out of Git. Never put the Groq key in frontend code.
- This starter does not include user accounts or cross-device identity. Each browser session has its own private conversation archive; clearing cookies creates a new session.
- Set a stable, secret `SECRET_KEY` in production. Do not rely on the development fallback.

## Endpoints

- `GET /api/status`
- `GET /api/conversations`
- `GET /api/conversations/<conversation_id>`
- `DELETE /api/conversations/<conversation_id>`
- `POST /api/chat` with JSON `{ "message": "...", "mode": "roleplay|normal", "conversation_id": null }`

## Notes

The model receives the selected mode's system prompt plus a bounded window of the current conversation. Roleplay and Normal Chat histories are stored as separate conversations and are never merged. A failed Groq call does not save a fake assistant response; the user can retry the same message.
