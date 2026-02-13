# Secrets Management (MVP → Production)

MVP
- Use environment variables for all secrets (tokens, DB creds). Do not commit secrets.
- Optional: local `config/secrets.json` for developer convenience only; override via env in CI/Prod.
- Access via `src/app/config/secrets.get_secret()`.

Production Target
- Integrate a secrets manager (Azure Key Vault, AWS Secrets Manager, or HashiCorp Vault).
- Inject secrets into the runtime using managed identity or short-lived tokens.
- Rotate secrets on incident and on schedule; track rotation in an audit log.

Controls
- Set `SPLUNK_HEC_URL`/`SPLUNK_HEC_TOKEN`, `JANUSEC_API_URL`/`JANUSEC_API_KEY` and other integration creds via secret store.
- Disable plaintext logging of payloads: keep `SECURITY_EVENT_PERSIST_CONTENT=false` by default.
- Restrict env var visibility in orchestrator; avoid mounting secrets into build steps.
