from pathlib import Path
content = Path('src/app/security/observer.py').read_text()
lines = content.splitlines()
print('total_lines=', len(lines))
for idx, line in enumerate(lines[max(0, len(lines)-60):], start=max(1, len(lines)-59)):
    print(idx, repr(line))
