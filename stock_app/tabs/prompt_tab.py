"""
提示词编辑 Tab
- 🆕 双模块切换：股票分析模板 / 标签聚类模板
- 独立保存，互不干扰
"""
import tkinter as tk
from tkinter import scrolledtext, messagebox

from .base import BaseTab
from ..widgets import make_card, styled_btn
from ..core import config as cfg_mod


class PromptTab(BaseTab):
    title = "提示词"

    def __init__(self, app):
        super().__init__(app)
        self._cur_mode = "analysis"  # analysis / cluster

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=16, pady=12)

        tk.Label(body, text="📝 提示词模块化管理", font=('微软雅黑', 12, 'bold'),
                 bg=C['bg'], fg=C['text']).pack(anchor='w', pady=(0, 4))

        # ── 🆕 顶部模式切换 ──
        mode_frame = tk.Frame(body, bg=C['bg'])
        mode_frame.pack(fill='x', pady=(0, 10))

        self._mode_var = tk.StringVar(value="analysis")
        
        rb_style = {'font': ('微软雅黑', 10, 'bold'), 'bg': C['bg'], 
                    'activebackground': C['bg'], 'selectcolor': C['card'],
                    'anchor': 'w', 'padx': 10, 'pady': 4, 'indicatoron': 0, 'relief': 'flat', 'cursor': 'hand2'}
        
        # 🌟 需求3：使用不同颜色区分模版
        tk.Radiobutton(mode_frame, text="🔍 股票分析模板", 
                       variable=self._mode_var, value="analysis",
                       command=self._switch_mode, fg=C['accent'], activeforeground=C['accent'], **rb_style).pack(side='left', padx=(0, 20), ipady=4)
        tk.Radiobutton(mode_frame, text="🕸️ 标签聚类模板", 
                       variable=self._mode_var, value="cluster",
                       command=self._switch_mode, fg=C['purple'], activeforeground=C['purple'], **rb_style).pack(side='left', ipady=4)

        # ── 提示区 ──
        self._hint_var = tk.StringVar(value="可用变量: {stock_name} = 股票名称    {stock_code} = 股票代码")
        tk.Label(body, textvariable=self._hint_var,
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['yellow']).pack(anchor='w', pady=(0, 6))

        # ── 编辑区 ──
        pc = make_card(body, "📝  当前模板内容", pady_top=0)
        self.prompt_text = scrolledtext.ScrolledText(
            pc, font=('微软雅黑', 9), wrap='word',
            bg=C['card'], fg=C['text'],
            insertbackground='white', relief='flat', height=20)
        self.prompt_text.pack(fill='both', expand=True)

        # ── 底部按钮 ──
        btn_row = tk.Frame(body, bg=C['bg'])
        btn_row.pack(fill='x', pady=(10, 0))
        styled_btn(btn_row, "💾  保存当前模板", C['green'],
                   self._save, pady=8).pack(side='left', padx=(0, 8))
        styled_btn(btn_row, "↩  恢复当前模板默认", C['idle'],
                   self._reset, pady=8).pack(side='left')

        self.char_var = tk.StringVar(value="")
        tk.Label(btn_row, textvariable=self.char_var,
                 font=('微软雅黑', 8), bg=C['bg'], fg=C['dim']).pack(side='right')
        self.prompt_text.bind('<KeyRelease>', self._update_count)

        # 初始加载
        self._load_template()

    def _switch_mode(self):
        mode = self._mode_var.get()
        if mode == self._cur_mode:
            return
        
        # 切换前简单提示保存（防止丢失）
        self._cur_mode = mode
        self._load_template()

    def _load_template(self):
        self.prompt_text.delete('1.0', 'end')
        if self._cur_mode == "analysis":
            self._hint_var.set("可用变量: {stock_name} = 股票名称    {stock_code} = 股票代码")
            content = self.app.cfg.get("prompt_template", cfg_mod.DEFAULT_CONFIG["prompt_template"])
        else:
            self._hint_var.set("可用变量: {tag_list} = 标签清单    {cooccur_list} = 共现关系清单")
            from ..core import tag_relation as tr
            content = tr.load_bulk_prompt_template()
            
        self.prompt_text.insert('1.0', content)
        self._update_count()

    def _update_count(self, e=None):
        n = len(self.prompt_text.get('1.0', 'end'))
        self.char_var.set("字符数: {}".format(n))

    def _save(self):
        content = self.prompt_text.get('1.0', 'end').strip()
        if self._cur_mode == "analysis":
            self.app.cfg["prompt_template"] = content
            cfg_mod.save_config(self.app.cfg)
            messagebox.showinfo("保存成功", "🔍 股票分析提示词已保存")
        else:
            from ..core import tag_relation as tr
            tr.save_bulk_prompt_template(content)
            messagebox.showinfo("保存成功", "🕸️ 标签聚类提示词已保存")

    def _reset(self):
        target = "股票分析" if self._cur_mode == "analysis" else "标签聚类"
        if messagebox.askyesno("确认", "恢复「{}」模板为默认？".format(target)):
            self.prompt_text.delete('1.0', 'end')
            if self._cur_mode == "analysis":
                self.prompt_text.insert('1.0', cfg_mod.DEFAULT_CONFIG["prompt_template"])
            else:
                from ..core import tag_relation as tr
                self.prompt_text.insert('1.0', tr.DEFAULT_BULK_PROMPT)