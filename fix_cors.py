with open('app/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('allow_origins=["*"]', 'allow_origins=["https://ai-visual-scheduler-production.up.railway.app"]')

with open('app/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
