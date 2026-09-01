with open('app/main.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('ROOT_DIR / "index.html"', 'ROOT_DIR / "frontend" / "index.html"')
content = content.replace('ROOT_DIR / "landing.html"', 'ROOT_DIR / "frontend" / "landing.html"')
with open('app/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
