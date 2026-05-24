
import re

with open('app.py', 'r') as f:
    content = f.read()

# 1. Add @contextmanager to get_db
if '@contextmanager\ndef get_db():' not in content:
    content = content.replace('def get_db():', '@contextmanager\ndef get_db():')

# 2. Fix the timestamp comparison in index
content = content.replace(
    "WHERE data_registrazione >= %s AND data_registrazione <= %s",
    "WHERE data_registrazione >= %s::timestamp AND data_registrazione <= %s::timestamp"
)

# 3. Fix the template for /volantini
content = content.replace(
    'render_template("04_volantino/01_lista_volantini.html",',
    'render_template("05_beta_volantino/05_beta_volantino_lista.html",'
)

with open('app.py', 'w') as f:
    f.write(content)
print("Fixes applied to app.py")
