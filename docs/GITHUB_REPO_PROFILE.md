# GitHub Repository Profile

## Suggested Repository Name

```text
ai-juejin-toutiao-agent
```

## Short Description

```text
本地优先的新闻 Agent 学习项目：FastAPI + Vue + MCP + RAG + OCR，演示可检索、可追溯、可评测的单 Agent 架构。
```

## English Description

```text
A local-first news Agent learning project with FastAPI, Vue, MCP, RAG, Qdrant, Ollama, and OCR.
```

## Topics

```text
agent
rag
mcp
fastapi
vue
qdrant
ollama
ocr
paddleocr
llm
news-agent
learning-project
```

## Website

Leave empty unless a demo page or documentation site is published.

## Visibility

Recommended: `public`, because the project is positioned as an open-source learning project.

## Release Notes For First Push

```markdown
Initial open-source cleanup and release.

- Added GitHub-friendly README.
- Added open-source architecture documentation.
- Removed local secrets, logs, reports, backups, runtime caches, and generated artifacts.
- Kept source code, tests, schema, configuration templates, docs, and small sample data.
- Verified secret hygiene and Python test suite locally.
```

## Publish Commands After Login

After `gh auth login -h github.com` succeeds and the license choice is confirmed:

```powershell
git init
git branch -M main
git add -A
git commit -m "Initial open-source release"
gh repo create ai-juejin-toutiao-agent --public --source . --remote origin --push --description "本地优先的新闻 Agent 学习项目：FastAPI + Vue + MCP + RAG + OCR，演示可检索、可追溯、可评测的单 Agent 架构。"
gh repo edit --add-topic agent --add-topic rag --add-topic mcp --add-topic fastapi --add-topic vue --add-topic qdrant --add-topic ollama --add-topic ocr --add-topic paddleocr --add-topic llm --add-topic news-agent --add-topic learning-project
```

If the target repository already exists, replace `gh repo create ...` with:

```powershell
git remote add origin https://github.com/<owner>/<repo>.git
git push -u origin main
```
