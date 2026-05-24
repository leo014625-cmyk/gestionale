import os
path = 'app.py'
content = open(path).read()
replacements = [
    ('lavorato == 1', 'lavorato is True'),
    ('lavorato == 0', 'lavorato is False'),
    ('lavorato == True', 'lavorato is True'),
    ('lavorato == False', 'lavorato is False'),
    ('lavorato == "1"', 'lavorato is True'),
    ("lavorato == '1'", 'lavorato is True'),
    ('lavorato == "0"', 'lavorato is False'),
    ("lavorato == '0'", 'lavorato is False'),
]
for old, new in replacements:
    content = content.replace(old, new)
open(path, 'w').write(content)
