# Il Claude Agent SDK Python richiede il CLI Node.js di Claude Code come
# sottoprocesso runtime ("The Claude Code CLI is a required runtime
# dependency" - vedi DECISIONS.md, voce sul cambio Nixpacks -> Dockerfile).
# Nixpacks (solo Python) non lo installava: da qui il Dockerfile esplicito.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app
COPY codice/requirements.txt codice/requirements.txt
RUN pip install --no-cache-dir -r codice/requirements.txt

COPY codice/ codice/
COPY .claude/ codice/.claude/

WORKDIR /app/codice
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
