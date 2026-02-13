Webhook testing

1. Copy the example config to the real config path (adjust path if needed):

```bash
cp config/webhooks.yml.example config/webhooks.yml
```

2. Start the backend server (ensure API keys or auth as required):

```powershell
& .venv\Scripts\Activate.ps1
uvicorn src.app.main:app --reload --factory --port 8000
```

3. Trigger a block/escalate via the admin endpoints or via the UI. The admin `block`/`escalate` handlers will read `config/webhooks.yml` and POST payloads to the URLs listed.

4. View the received test webhooks in `dump/webhook_test.log` (newline-delimited JSON):

```bash
cat dump/webhook_test.log
```

5. For local development, you can also use ngrok or a public webhook receiver and point `config/webhooks.yml` to that URL.
