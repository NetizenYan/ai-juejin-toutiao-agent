# Contributing

Thanks for your interest in this project.

AI 掘金头条 is a learning-oriented Agent engineering repository. Contributions should keep the project local-first, evidence-aware, and safe to publish.

## Development Setup

```bash
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn main:app --host 127.0.0.1 --port 8030
```

Frontend:

```bash
cd apps/frontend
npm install
copy .env.example .env
npm run dev
```

## Before Opening a Pull Request

Run:

```bash
python scripts/security_secret_scan.py
python -m pytest -q
```

Keep generated files out of commits:

- `.env`
- logs
- runtime screenshots
- OCR captures
- database dumps
- Qdrant dumps
- local reports
- `node_modules`
- frontend `dist`

## Contribution Principles

- Keep model providers configurable through environment variables.
- Do not put secrets in source code, tests, docs, or examples.
- Prefer station-internal RAG evidence before external or OCR evidence.
- Treat external/OCR content as low-trust unless it is cross-checked.
- Add focused tests for Agent routing, tool contracts, memory behavior, and validation behavior.
- Avoid adding large datasets or copyrighted full-text news corpora.

## Issue Reports

Useful issue reports include:

- clear reproduction steps
- expected and actual behavior
- relevant logs with secrets removed
- local environment details
- whether the issue affects backend, frontend, RAG, OCR, MCP, or tests

## Pull Request Notes

Please explain:

- what changed
- why it changed
- how it was tested
- whether it changes data, security, model behavior, or public API behavior
