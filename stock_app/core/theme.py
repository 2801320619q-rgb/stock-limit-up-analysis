"""
主题色板 - 暗色 / 亮色
"""

THEMES = {
    "dark": {
        'bg':       '#1a1d23', 'panel':    '#22262f', 'card':     '#2a2f3a',
        'border':   '#3a3f4b', 'accent':   '#4f9eff', 'acc_dark': '#2d5fa0',
        'green':    '#3ddc84', 'red':      '#ff5c5c', 'yellow':   '#ffc94d',
        'purple':   '#b07cff', 'text':     '#e8eaf0', 'dim':      '#8b8fa8',
        'idle':     '#555b6e', 'star':     '#ffd700',
    },
    "light": {
        'bg':       '#f5f6fa', 'panel':    '#ffffff', 'card':     '#eef0f5',
        'border':   '#d0d4dc', 'accent':   '#2680ff', 'acc_dark': '#1968d6',
        'green':    '#1ba864', 'red':      '#e63232', 'yellow':   '#d49d20',
        'purple':   '#7a4cdb', 'text':     '#1f2330', 'dim':      '#6b7080',
        'idle':     '#aab0bc', 'star':     '#e8b800',
    },
}

# 默认色板（暗色）—— 必须用 dict() 复制，不能直接赋引用
# 否则 C.clear() 会同时清掉 THEMES["dark"]，导致 KeyError: 'bg'
C = dict(THEMES["dark"])

def set_theme(name):
    """切换主题，用 dict() 拷贝防止污染 THEMES 原始数据"""
    src = THEMES.get(name, THEMES["dark"])
    C.clear()
    C.update(dict(src))

def get():
    return C
