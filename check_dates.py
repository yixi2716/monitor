import urllib.request
for name, path in [('黄金', 'gold/latest.json'), ('铜', 'copper/latest.json')]:
    try:
        raw = urllib.request.urlopen(f'https://yixi2716.github.io/monitor/data/{path}').read().decode('utf-8')
        print(f'=== {name} 前200字 ===')
        print(raw[:200])
    except Exception as e:
        print(f'{name}: {e}')
