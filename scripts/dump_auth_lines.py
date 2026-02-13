from pathlib import Path
p = Path('src/app/routers/auth.py')
with p.open('r', encoding='utf-8') as f:
    for i, l in enumerate(f, 1):
        print(f"{i:03}: {l.rstrip()}")
