"""
HTML 报告导出
"""
import re
from datetime import datetime
from .paths import DIRS, ensure_dirs
from .text_utils import HIGHLIGHT_PATTERNS


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
body{{font-family:'微软雅黑',sans-serif;max-width:900px;margin:30px auto;
     padding:0 20px;background:#f8f9fb;color:#222;line-height:1.7}}
h1{{color:#2680ff;border-bottom:3px solid #2680ff;padding-bottom:10px}}
.meta{{color:#666;font-size:13px;margin-bottom:20px}}
.stock-card{{background:#fff;border-radius:8px;padding:18px 22px;
            margin-bottom:18px;box-shadow:0 2px 8px rgba(0,0,0,0.06);
            border-left:4px solid #2680ff}}
.stock-card.fail{{border-left-color:#e63232;background:#fef0f0}}
.stock-title{{font-size:18px;font-weight:bold;color:#1f2330;margin-bottom:8px}}
.stock-title .code{{color:#888;font-size:14px;margin-left:8px}}
.content{{white-space:pre-wrap;font-size:14px;background:#f5f7fa;
         padding:12px;border-radius:4px;margin-top:8px}}
.policy{{background:#fff3cd;padding:1px 4px;border-radius:3px}}
.concept{{background:#d4edda;padding:1px 4px;border-radius:3px}}
.money{{color:#e63232;font-weight:bold}}
.percent{{color:#1ba864;font-weight:bold}}
.summary{{background:#e7f3ff;padding:12px;border-radius:6px;margin-bottom:20px}}
</style></head>
<body>
<h1>{title}</h1>
<div class="meta">生成时间：{gen_time}  ·  共 {total} 只股票</div>
<div class="summary">✅ 成功 {ok}    ❌ 失败 {fail}</div>
{cards}
</body></html>
"""


def export_html_report(records, title="涨停复盘分析报告", subdir="reports"):
    """records: [{name, code, content, success}]"""
    ensure_dirs()
    ok   = sum(1 for r in records if r.get("success"))
    fail = len(records) - ok
    cards = []
    for r in records:
        cls = "stock-card" if r.get("success") else "stock-card fail"
        content = r.get("content", "")
        # 转义 HTML 特殊字符
        content = (content.replace("&", "&amp;")
                          .replace("<", "&lt;")
                          .replace(">", "&gt;"))
        # 高亮关键词
        for tag, pattern in HIGHLIGHT_PATTERNS.items():
            if tag in ("policy", "concept"):
                content = re.sub(pattern,
                    r'<span class="{}">\1</span>'.format(tag), content)
            elif tag == "money":
                content = re.sub(pattern, r'<span class="money">\1</span>', content)
            elif tag == "percent":
                content = re.sub(pattern, r'<span class="percent">\1</span>', content)
        cards.append(
            '<div class="{cls}"><div class="stock-title">{name}'
            '<span class="code">{code}</span></div>'
            '<div class="content">{content}</div></div>'.format(
                cls=cls, name=r.get("name",""), code=r.get("code",""),
                content=content))
    html = HTML_TEMPLATE.format(
        title=title,
        gen_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total=len(records), ok=ok, fail=fail,
        cards="\n".join(cards))
    filename = DIRS[subdir] / "{}_{}.html".format(
        title.replace(" ","_"), datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    return str(filename)
