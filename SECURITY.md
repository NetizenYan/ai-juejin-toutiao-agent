# Security Policy

## Supported Scope

This repository is a local-first learning project for Agent/RAG/OCR engineering. Security reports are welcome for issues that affect the source code, example configuration, local development workflow, or documented deployment patterns in this repository.

## Please Do Not Report

- Missing production controls that are already documented as out of scope.
- Issues requiring real private datasets, API keys, or third-party accounts not included in the repository.
- General model quality concerns unless they create a concrete security or privacy impact.

## Reporting a Vulnerability

Please open a private security advisory on GitHub when possible. If that is not available, open an issue with a minimal description and avoid posting secrets, tokens, exploit payloads against live services, or private data.

Include:

- affected file or feature
- expected behavior
- actual behavior
- reproduction steps using local test data when possible
- impact and suggested mitigation

## Secret Handling

Do not commit `.env`, API keys, database passwords, cookies, private keys, dumps, logs, screenshots, or OCR captures. Run this before publishing changes:

```bash
python scripts/security_secret_scan.py
```

GitHub secret scanning and push protection are enabled for the public repository.
