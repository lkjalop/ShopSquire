from src.app.main import create_app
app = create_app()
for r in app.routes:
    try:
        methods = getattr(r, 'methods', None)
    except Exception:
        methods = None
    print(f"{r.path} {methods}")
