import urllib.request, re, os

# 修复黄金和铜的 latest.json
for name, path in [('gold', 'gold/latest.json'), ('copper', 'copper/latest.json')]:
    url = f'https://yixi2716.github.io/monitor/data/{path}'
    raw = urllib.request.urlopen(url).read().decode('utf-8')
    # 去掉 git 冲突标记，保留 HEAD 部分
    # 格式：<<<<<<< HEAD ... ======= ... >>>>>>> xxx
    # 我们保留 HEAD 部分（本地的）
    lines = raw.split('\n')
    clean = []
    in_conflict = False
    keep = True
    for line in lines:
        if line.startswith('<<<<<<<'):
            in_conflict = True
            keep = True
            continue
        if line.startswith('======='):
            keep = False
            continue
        if line.startswith('>>>>>>>'):
            in_conflict = False
            keep = True
            continue
        if not in_conflict or keep:
            clean.append(line)
    fixed = '\n'.join(clean)
    # 保存到本地
    local_path = os.path.join(r'C:\Users\member\Doubao\chats\2026-09-22\new-chat\pig-cycle-monitor\site\data', path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, 'w', encoding='utf-8') as f:
        f.write(fixed)
    print(f'{name}: 修复完成')
