import re

for filename in ['index.html', 'landing.html']:
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'window.API_BASE_URL' not in content:
        head_end = content.find('</head>')
        if head_end != -1:
            script_tag = '\n<script>\n  window.API_BASE_URL = "YOUR_RENDER_URL";\n</script>\n'
            content = content[:head_end] + script_tag + content[head_end:]
            
    content = re.sub(r"fetch\('(/api/[^']+)'", r"fetch(window.API_BASE_URL + '\1'", content)
    content = re.sub(r"fetch\(/api/([^]+)", r"fetch(window.API_BASE_URL + /api/\1", content)
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
