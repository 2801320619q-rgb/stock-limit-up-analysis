"""
文本处理 - 符号清洗、格式校验、关键词高亮
"""
import re
from .paths import REQUIRED_SECTIONS


# ══════════════════════════════════════════════════
# 符号清洗
# ══════════════════════════════════════════════════
def clean_symbols(text):
    """去除 AI 回答中的多余符号"""
    text = re.sub(r'\^\[\d{1,2}\]', '', text)
    text = re.sub(r'\[\d{1,2}\]', '', text)
    text = re.sub(r'\^', '', text)
    text = re.sub(r'\*{2,3}(.+?)\*{2,3}', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*', '', text)
    text = re.sub(r'(?m)^[ \t]*[-\u2022][ \t]+', '  ', text)
    text = re.sub(r'(?m)^[ \t]*#{1,6}[ \t]*', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [l.rstrip() for l in text.splitlines()]
    return '\n'.join(lines).strip()


# ══════════════════════════════════════════════════
# 格式校验（宽松版）
# ══════════════════════════════════════════════════
def validate_response(content):
    if not content or len(content.strip()) < 300:
        return False, "内容过短（< 300字）"
    if "核心信息总结" not in content:
        return False, "缺少【核心信息总结】标记"
    hit = sum(1 for p in REQUIRED_SECTIONS if re.search(p, content))
    if hit < 3:
        return False, "模块命中数不足（{}/5）".format(hit)
    m = re.search(r'【?核心信息总结】?', content)
    if m:
        content = content[m.start():]
    content = clean_symbols(re.sub(r'\n\s*\n', '\n\n', content).strip())
    return True, content


# ══════════════════════════════════════════════════
# 关键词高亮
# ══════════════════════════════════════════════════
HIGHLIGHT_PATTERNS = {
    "policy":   r'(国务院|工信部|发改委|证监会|央行|国资委|政策|文件|意见|规划|十五五|十四五|两会|政府工作报告)',
    "concept":  r'(算力|算电协同|AI|人工智能|大模型|新能源|储能|光伏|风电|核电|绿电|氢能|半导体|芯片|存储|光刻|HBM|CPO|消费电子|苹果链|华为链|折叠屏|医药|创新药|减肥药|GLP-1|脑机接口|机器人|低空经济|无人驾驶|智能驾驶|军工|国防|大飞机|商业航天|卫星|金融|券商|银行|国资改革|央企|数字货币|区块链|稳定币|传感器|MCU|功率半导体)',
    "money":    r'(\d+\.?\d*\s*亿元|\d+\.?\d*\s*万元|\d+\.?\d*\s*万亿)',
    "percent":  r'([+\-]?\d+\.?\d*\s*%)',
    "date":     r'(\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日)',
    # 涨停类别标签 —— 用特殊 tag，颜色更醒目
    "category": r'(【细分标签】[^\n]+)',
}


def extract_category_keywords(text):
    """从结果中提取【细分标签】行里的关键词，用于额外高亮"""
    m = re.search(r'【细分标签】[：:]?\s*([^\n]+)', text)
    if not m:
        return []
    tag_line = m.group(1)
    # 按 +、、、空格、/、|、, 分割
    parts = re.split(r'[+、，,\s/|]+', tag_line)
    return [p.strip() for p in parts if len(p.strip()) >= 2]


def find_highlights(text):
    spans = []
    # 基础关键词
    for tag, pattern in HIGHLIGHT_PATTERNS.items():
        for m in re.finditer(pattern, text):
            spans.append((m.start(), m.end(), tag))
    # 动态：从结果开头的【细分标签】里抓关键词，全文高亮这些词
    keywords = extract_category_keywords(text)
    for kw in keywords:
        for m in re.finditer(re.escape(kw), text):
            spans.append((m.start(), m.end(), "category_kw"))

    # 排序：先按起始位置，相同位置 category 行优先
    spans.sort(key=lambda x: (x[0], 0 if x[2] == 'category' else 1))
    # 去重：相同区间只保留第一个
    # 但允许重叠（如 category 行 + 内部 category_kw 共存）
    # 策略：完全相同区间去重，部分重叠保留
    seen_ranges = set()
    cleaned = []
    for s, e, t in spans:
        key = (s, e, t)
        if key in seen_ranges:
            continue
        seen_ranges.add(key)
        cleaned.append((s, e, t))
    return cleaned


# ══════════════════════════════════════════════════
# 微信精简格式
# ══════════════════════════════════════════════════
def to_wechat_format(name, code, content):
    core_biz = re.search(r'核心业务[】：:\s]*([^。\n]+)', content)
    main_up  = re.search(r'市场主要核心上涨共识[】：:\s]*([^。\n]+)', content)
    linked   = re.search(r'同逻辑联动标的[】：:\s]*(.*?)(?=⑤|同逻辑标的板块事件|$)', content, re.DOTALL)
    linked_text = linked.group(1)[:200].strip() if linked else ""

    parts = ["📈 {}({})".format(name, code), ""]
    if core_biz:
        parts.append("【主营】{}".format(core_biz.group(1).strip()[:80]))
    if main_up:
        parts.append("【催化】{}".format(main_up.group(1).strip()[:120]))
    if linked_text:
        parts.append("【联动】{}".format(linked_text.replace("\n", " ")[:120]))
    return "\n".join(parts)
