"""Write the eight buildless HTML entry points. Runtime is plain local JS/CSS."""
from pathlib import Path
import re,json
root=Path(__file__).resolve().parent
pages=[('index.html','index','LevelUProject · 完整交互原型'),('00-design-system.html','system','设计规范 · LevelUProject'),('01-core-learning.html','L','核心学习与分享 · LevelUProject'),('02-review-center.html','R','个人学习中心 · LevelUProject'),('03-knowledge-library.html','K','私有知识库 · LevelUProject'),('04-social-challenge.html','S','社交知识挑战 · LevelUProject'),('05-account-and-extensions.html','A','账户与扩展功能 · LevelUProject'),('06-states.html','E','异常与恢复状态 · LevelUProject')]
for name,page,title in pages:
    (root/name).write_text(f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#FFD84D">
  <meta name="description" content="LevelUProject AI 闯关学习小程序，原创漫画风格的完整 HTML 交互原型。">
  <title>{title}</title>
  <link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="assets/style.css">
</head>
<body data-page="{page}">
  <div id="app"></div>
  <noscript>请启用 JavaScript 查看完整的本地交互原型。所有资源均包含在 prototype 文件夹中。</noscript>
  <script src="assets/ui.js"></script>
  <script src="assets/screens.js"></script>
  <script src="assets/app.js"></script>
</body>
</html>
''',encoding='utf-8')
print(f'Generated {len(pages)} HTML entry points.')
entries=re.findall(r"add\('([A-Z]\d+)','([^']+)','([^']+)'",(root/'assets/screens.js').read_text(encoding='utf-8'))
(root/'页面清单.json').write_text(json.dumps([dict(id=i,name=n,note=d) for i,n,d in entries],ensure_ascii=False,indent=2),encoding='utf-8')
assert len(entries)==69 and len(set(i for i,_,_ in entries))==69
