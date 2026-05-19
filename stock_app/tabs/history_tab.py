"""
历史记录 Tab
- 单条/批量/全天 删除
- ⭐ 星标（行高亮）+ 📝 备注（双击编辑）
- 仅显示星标过滤 + 跨日期搜索
- 🔄 重新识别联动标的行情（一键重查腾讯接口）
- 📝 可编辑详情文本（像 txt 一样自由编辑）
- 💾 保存修改回历史记录
- 右键菜单：复制/剪切/粘贴/全选/手动高亮/清除高亮/微信格式/导出HTML/重新识别/撤销
- 手动高亮：选中文字 → 右键 → 5种颜色
- 字号调节
"""
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from .base import BaseTab
from ..widgets import make_card, styled_btn, styled_entry, apply_highlight
from ..core import history as hist_mod, api_client, text_utils, reports
from ..bus import bus, Events


MANUAL_HL_TAGS = [
    ("🟡 黄色",  "hl_yellow", "#ffc94d", "#1a1d23"),
    ("🟢 绿色",  "hl_green",  "#3ddc84", "#1a1d23"),
    ("🔵 蓝色",  "hl_blue",   "#4f9eff", "#1a1d23"),
    ("🟣 紫色",  "hl_purple", "#b07cff", "#1a1d23"),
    ("🔴 红色",  "hl_red",    "#ff5c5c", "#1a1d23"),
    ("🟠 橙色",  "hl_orange", "#ff9a3c", "#1a1d23"),
]


class HistoryTab(BaseTab):
    title = "历史记录"

    def __init__(self, app):
        super().__init__(app)
        self._cur_date_key  = None
        self._cur_record_id = None
        self._cur_record_code = None    # 🆕 v9.3：当前记录的股票代码（联动行情主股标识用）
        self._dirty         = False
        self._row_data = {}
        # 自动保存相关
        self._auto_save_id    = None
        self._auto_save_delay = 1500
        self._loading         = False
        # 🔑 内容快照：用于精确判断是否需要保存（不依赖 <<Modified>> 事件）
        # 中文 IME 输入下 <<Modified>> 经常漏触发，靠快照对比最可靠
        self._original_content = ""
        # 自动批量识别模式
        self._auto_mode_on     = False
        self._auto_mode_id     = None       # after() 句柄
        self._auto_mode_minutes = 5         # 默认每 5 分钟一次

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=16, pady=12)

        # ── 顶部 ──────────────────────────────────────────
        hr = tk.Frame(body, bg=C['bg']); hr.pack(fill='x', pady=(0, 8))
        tk.Label(hr, text="📜 历史记录", font=('微软雅黑', 12, 'bold'),
                 bg=C['bg'], fg=C['text']).pack(side='left')
        # 一键批量重识别按钮（最显眼位置）
        styled_btn(hr, "🔄 一键重识别当日全部", C['purple'],
                   self._batch_requery_all).pack(side='left', padx=(20, 0))

        # 自动模式开关
        self._auto_mode_var = tk.BooleanVar(value=False)
        self._auto_chk = tk.Checkbutton(hr, text="🔁 自动模式",
                                          variable=self._auto_mode_var,
                                          font=('微软雅黑', 9, 'bold'),
                                          bg=C['bg'], fg=C['yellow'],
                                          activebackground=C['bg'],
                                          activeforeground=C['yellow'],
                                          selectcolor=C['card'],
                                          command=self._toggle_auto_mode)
        self._auto_chk.pack(side='left', padx=(8, 0))

        tk.Label(hr, text="间隔(分钟)", font=('微软雅黑', 8),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(8, 2))
        self._auto_interval_var = tk.StringVar(value=str(self._auto_mode_minutes))
        styled_entry(hr, self._auto_interval_var, 4).pack(side='left', ipady=2)

        self._auto_status_var = tk.StringVar(value="")
        tk.Label(hr, textvariable=self._auto_status_var,
                 font=('微软雅黑', 8), bg=C['bg'],
                 fg=C['green']).pack(side='left', padx=(8, 0))
        styled_btn(hr, "📈 导出当日行情Excel", C['purple'],
                   self._export_daily_quotes).pack(side='right', padx=(4, 0))
        styled_btn(hr, "📊 导出星标Excel", C['green'],
                   self._export_excel).pack(side='right', padx=(4, 0))
        styled_btn(hr, "📄 导出星标HTML", C['accent'],
                   self._export_html).pack(side='right', padx=(4, 0))
        styled_btn(hr, "📊 导出星标Excel", C['green'],
                   self._export_excel).pack(side='right', padx=(4, 0))
        styled_btn(hr, "📄 导出星标HTML", C['accent'],
                   self._export_html).pack(side='right', padx=(4, 0))

        # ── 搜索/过滤行 ──────────────────────────────────
        sr = tk.Frame(body, bg=C['bg']); sr.pack(fill='x', pady=(0, 8))
        tk.Label(sr, text="日期", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self.date_var = tk.StringVar()
        self.date_combo = ttk.Combobox(sr, textvariable=self.date_var,
                                        state='readonly', width=14,
                                        font=('微软雅黑', 9))
        self.date_combo.pack(side='left', padx=(0, 12))
        self.date_combo.bind('<<ComboboxSelected>>', lambda e: self._load_day())

        tk.Label(sr, text="搜索", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(0, 4))
        self.kw_var = tk.StringVar()
        kw_e = styled_entry(sr, self.kw_var, 20)
        kw_e.pack(side='left', ipady=3)
        kw_e.bind('<Return>', lambda e: self._search())
        styled_btn(sr, "🔍", C['accent'], self._search).pack(side='left', padx=(2, 0))
        styled_btn(sr, "重置", C['idle'],
                   lambda: [self.kw_var.set(""), self._load_day()]).pack(side='left', padx=(2, 12))
        self.only_star = tk.BooleanVar(value=False)
        tk.Checkbutton(sr, text="⭐ 仅显示星标",
                       variable=self.only_star, font=('微软雅黑', 9),
                       bg=C['bg'], fg=C['text'], selectcolor=C['card'],
                       activebackground=C['bg'],
                       command=self._load_day).pack(side='left')
        styled_btn(sr, "刷新", C['idle'], self._refresh_dates).pack(side='right')

        # ── 双栏布局 ─────────────────────────────────────
        pw = tk.PanedWindow(body, bg=C['bg'], sashwidth=5,
                            sashrelief='flat', orient='horizontal')
        pw.pack(fill='both', expand=True)
        left  = tk.Frame(pw, bg=C['bg'])
        right = tk.Frame(pw, bg=C['bg'])
        pw.add(left,  minsize=360)
        pw.add(right, minsize=440)

        # ── 左侧列表 ─────────────────────────────────────
        cols = ('star','time','name','code','status','note')
        # 加载持久化列宽
        from ..widgets import load_col_widths, save_col_widths
        col_widths = load_col_widths('history')
        defaults = {'star':40,'time':80,'name':100,'code':80,'status':50,'note':110}
        self.tree = ttk.Treeview(left, columns=cols, show='headings', height=20)
        for col, txt, w in [('star','⭐',40),('time','时间',80),('name','名称',100),
                              ('code','代码',80),('status','状态',50),('note','备注',110)]:
            self.tree.heading(col, text=txt)
            self.tree.column(col,
                              width=col_widths.get(col, defaults[col]),
                              minwidth=30,
                              anchor='center' if col!='note' else 'w',
                              stretch=True)
        vsb = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        self.tree.tag_configure('starred', background=C['acc_dark'], foreground='white')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self._show_detail())
        self.tree.bind('<Delete>',           lambda e: self._delete_selected())
        self.tree.bind('<Double-1>',         lambda e: self._edit_note_dialog())

        # 列宽拖动后保存
        def _save_widths(*_):
            widths = {c: self.tree.column(c, 'width') for c in cols}
            save_col_widths('history', widths)
        self.tree.bind('<ButtonRelease-1>', _save_widths, add='+')

        # 右键菜单（在Treeview上）
        self._build_tree_context_menu()

        lb = tk.Frame(left, bg=C['bg']); lb.pack(fill='x', pady=(4, 0))
        styled_btn(lb, "⭐ 星标",    C['yellow'], self._toggle_star).pack(side='left', padx=(0, 3))
        styled_btn(lb, "📝 备注",    C['accent'],  self._edit_note_dialog).pack(side='left', padx=(0, 3))
        styled_btn(lb, "🗑 删除",    C['red'],     self._delete_selected).pack(side='left', padx=(0, 3))
        styled_btn(lb, "🧹 清空当日",C['idle'],   self._clear_day).pack(side='left', padx=(0, 3))
        styled_btn(lb, "🏷️ 标签",   C['purple'], self._edit_tags_dialog).pack(side='left', padx=(0, 3))
        styled_btn(lb, "➕ 加入自选",C['green'],  self._add_to_favorites).pack(side='left')
        tk.Label(left, text="💡 单击=查看  双击=改备注  Del=删除",
                 font=('微软雅黑', 7), bg=C['bg'], fg=C['dim']).pack(anchor='w', pady=(2, 0))

        # ── 右侧工具栏 ──────────────────────────────────
        rh = tk.Frame(right, bg=C['panel'],
                      highlightbackground=C['border'], highlightthickness=1)
        rh.pack(fill='x')
        tk.Label(rh, text="📄 详情（可直接编辑）",
                 font=('微软雅黑', 9, 'bold'),
                 bg=C['panel'], fg=C['accent']).pack(side='left', padx=8, pady=5)

        self._save_btn = tk.Button(rh, text="💾 保存",
                                    font=('微软雅黑', 8), pady=3, padx=6,
                                    bg=C['green'], fg='white', relief='flat',
                                    cursor='hand2', state='disabled',
                                    command=self._save_edit)
        self._save_btn.pack(side='right', padx=4, pady=4)

        # Inline Toast 提示标签（取代弹窗）
        self._toast_var = tk.StringVar(value="")
        self._toast_lbl = tk.Label(rh, textvariable=self._toast_var,
                                    font=('微软雅黑', 9, 'bold'),
                                    bg=C['panel'], fg=C['green'])
        self._toast_lbl.pack(side='right', padx=8, pady=4)

        tk.Button(rh, text="🔄 重新识别行情",
                  font=('微软雅黑', 8), pady=3, padx=6,
                  bg=C['purple'], fg='white', relief='flat', cursor='hand2',
                  command=self._requery_realtime).pack(side='right', padx=(0, 4), pady=4)

        tk.Button(rh, text="✨ 自动高亮",
                  font=('微软雅黑', 8), pady=3, padx=6,
                  bg=C['acc_dark'], fg='white', relief='flat', cursor='hand2',
                  command=lambda: apply_highlight(self.detail, keep_editable=True)).pack(side='right', padx=(0, 4), pady=4)

        # 字号
        tk.Label(rh, text="字", font=('微软雅黑', 8),
                 bg=C['panel'], fg=C['dim']).pack(side='right', padx=(0, 1), pady=4)
        self._fsize = tk.IntVar(value=10)
        tk.Button(rh, text="▲", font=('Arial', 7), width=2,
                  bg=C['border'], fg=C['text'], relief='flat', cursor='hand2',
                  command=self._font_up).pack(side='right', pady=4)
        tk.Label(rh, textvariable=self._fsize, font=('微软雅黑', 8),
                 bg=C['panel'], fg=C['yellow'], width=2).pack(side='right', pady=4)
        tk.Button(rh, text="▼", font=('Arial', 7), width=2,
                  bg=C['border'], fg=C['text'], relief='flat', cursor='hand2',
                  command=self._font_down).pack(side='right', padx=(4, 0), pady=4)

        # ── 右侧可编辑文本框 ──────────────────────────
        txt_frame = tk.Frame(right, bg=C['bg'])
        txt_frame.pack(fill='both', expand=True)

        self.detail = tk.Text(txt_frame,
                              font=('微软雅黑', 10), wrap='word',
                              bg=C['card'], fg=C['text'],
                              insertbackground=C['accent'],
                              selectbackground=C['acc_dark'],
                              selectforeground='white',
                              relief='flat', undo=True, maxundo=50,
                              padx=8, pady=6)
        d_vsb = ttk.Scrollbar(txt_frame, orient='vertical',
                               command=self.detail.yview)
        self.detail.configure(yscrollcommand=d_vsb.set)
        self.detail.pack(side='left', fill='both', expand=True)
        d_vsb.pack(side='right', fill='y')

        # 颜色 tag
        for tag, fg, bg in [
            ('accent',   C['accent'],  ''),
            ('star_tag', C['star'],    ''),
            ('dim',      C['dim'],     ''),
            ('policy',   C['yellow'],  ''),
            ('concept',  C['green'],   ''),
            ('money',    C['red'],     ''),
            ('percent',  C['accent'],  ''),
            ('category', 'white',       C['purple']),
            ('category_kw', '#1a1d23',  C['star']),
            # 🆕 v9.3 联动行情行级染色：A 股习惯红涨绿跌
            ('up',       C['red'],     ''),
            ('down',     C['green'],   ''),
            ('flat',     C['dim'],     ''),
            # 🆕 v9.3 主股票标识：当前记录对应的股票，加深背景突出
            ('main_stock', C['star'],  '#3a2f1a'),
        ]:
            kw = {'foreground': fg}
            if bg: kw['background'] = bg
            # category 加粗
            if tag == 'category':
                kw['font'] = ('微软雅黑', 10, 'bold')
            # 主股票也加粗
            if tag == 'main_stock':
                kw['font'] = ('微软雅黑', 10, 'bold')
            self.detail.tag_config(tag, **kw)

        for _, tag, bg, fg in MANUAL_HL_TAGS:
            self.detail.tag_config(tag, background=bg, foreground=fg)

        self.detail.bind('<<Modified>>', self._on_modified)
        # 🔑 兜底：用 KeyRelease 检测编辑（IME 中文输入下 <<Modified>> 不可靠）
        self.detail.bind('<KeyRelease>', self._on_key_release)

        # 右键菜单
        self._ctx = self._build_context_menu()
        self.detail.bind('<Button-3>', self._show_ctx)
        self.detail.bind('<Button-2>', self._show_ctx)  # macOS
        # 🆕 v9.6：左键联动 — 单击文字时识别附近股票通知浮窗（不阻止默认）
        self.detail.bind('<Button-1>', self._detail_left_click_follow, add='+')

        self._refresh_dates()
        bus.on(Events.HISTORY_UPDATED,
               lambda *a: self.app.root.after(100, self._refresh_dates))

    # ════════════════════════════════════════════
    # 右键菜单
    # ════════════════════════════════════════════
    def _build_context_menu(self):
        C = self.C
        ctx = tk.Menu(self.detail, tearoff=0,
                       bg=C['panel'], fg=C['text'],
                       activebackground=C['acc_dark'],
                       activeforeground='white',
                       font=('微软雅黑', 9))

        # 🆕 v9.5：浮窗查看（基于右键位置自动识别）
        ctx.add_command(label="🔎  查看此股详情",
                         command=self._ctx_show_stock_popup)
        ctx.add_separator()

        ctx.add_command(label="📋  复制       Ctrl+C",
                         command=lambda: self.detail.event_generate('<<Copy>>'))
        ctx.add_command(label="✂️  剪切       Ctrl+X",
                         command=lambda: self.detail.event_generate('<<Cut>>'))
        ctx.add_command(label="📌  粘贴       Ctrl+V",
                         command=lambda: self.detail.event_generate('<<Paste>>'))
        ctx.add_command(label="⬛  全选       Ctrl+A",
                         command=lambda: self.detail.tag_add('sel','1.0','end'))
        ctx.add_separator()

        # 手动高亮子菜单
        hl = tk.Menu(ctx, tearoff=0,
                      bg=C['panel'], fg=C['text'],
                      activebackground=C['acc_dark'],
                      activeforeground='white',
                      font=('微软雅黑', 9))
        for label, tag, bg, fg in MANUAL_HL_TAGS:
            hl.add_command(label=label,
                           command=lambda t=tag: self._hl_apply(t))
        hl.add_separator()
        hl.add_command(label="🚫  清除选中高亮",
                        command=self._hl_clear_sel)
        ctx.add_cascade(label="🎨  高亮选中文字", menu=hl)
        ctx.add_command(label="✨  自动关键词高亮",
                         command=lambda: apply_highlight(self.detail, keep_editable=True))
        ctx.add_command(label="🚫  清除全部高亮",
                         command=self._hl_clear_all)
        ctx.add_separator()
        ctx.add_command(label="💬  转微信格式并复制",
                         command=self._ctx_wechat)
        ctx.add_command(label="📄  导出此条为HTML",
                         command=self._ctx_export_html)
        ctx.add_separator()
        ctx.add_command(label="🔄  重新识别联动行情",
                         command=self._requery_realtime)
        ctx.add_command(label="💾  保存当前修改",
                         command=self._save_edit)
        ctx.add_separator()
        ctx.add_command(label="↩️  撤销       Ctrl+Z",
                         command=lambda: self.detail.event_generate('<<Undo>>'))
        ctx.add_command(label="↪️  重做       Ctrl+Y",
                         command=lambda: self.detail.edit_redo())
        return ctx

    def _show_ctx(self, event):
        # 🆕 v9.5：记录右键点击位置，用于"查看此股详情"识别附近的代码/股名
        try:
            self._ctx_click_index = self.detail.index(
                "@{},{}".format(event.x, event.y))
        except Exception:
            self._ctx_click_index = None
        try:
            self._ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx.grab_release()

    def _ctx_show_stock_popup(self):
        """
        从右键位置附近识别股票，弹浮窗。识别规则（按优先级）：
          1. 若用户先选中了文本（sel），优先用选中文本
          2. 当前行匹配 6 位代码（含括号也行）→ 用代码
          3. 当前行匹配本地 stock_dict 里的股票名 → 用名字反查代码
          4. 都失败 → 退而求其次用当前记录本身的 code/name
        """
        import re
        text_at_cursor = ""
        # 1. 用选中文本
        try:
            text_at_cursor = self.detail.get('sel.first', 'sel.last')
        except tk.TclError:
            text_at_cursor = ""

        # 2. 当前行整行
        line_text = ""
        idx = getattr(self, '_ctx_click_index', None) or self.detail.index('insert')
        try:
            line_no = idx.split('.')[0]
            line_text = self.detail.get("{}.0".format(line_no), "{}.end".format(line_no))
        except Exception:
            pass

        target_code = ""
        target_name = ""

        search_text = text_at_cursor or line_text
        # 优先匹配 6 位代码（带括号或裸数字）
        m = re.search(r'[（(](\d{6})[)）]', search_text)
        if not m:
            m = re.search(r'(?<![.\d])(\d{6})(?![.\d])', search_text)
        if m:
            target_code = m.group(1)
            # 同行向前找 2-6 字的中文名（最靠近 ( 的那段）
            before = search_text[:m.start()]
            mname = re.search(r'([\u4e00-\u9fa5A-Z][\u4e00-\u9fa5A-Z0-9·\*]{1,7})\s*$',
                              before.rstrip())
            if mname: target_name = mname.group(1)

        # 还没拿到 → 用当前记录的 code/name 兜底
        if not target_code:
            target_code = self._cur_record_code or ""
            recs = self._get_sel()
            if recs:
                _, r, _ = recs[0]
                target_name = r.get('name', '')

        if not target_code:
            messagebox.showinfo("提示", "未能从光标附近识别到股票代码，请选中带 6 位代码的文字后再试")
            return
        self.app.show_stock_popup(target_code, target_name)

    def _detail_left_click_follow(self, event):
        """v9.9.6：左键单击 → 通知浮窗刷新（浮窗永远跟随）"""
        import re
        try:
            idx = self.detail.index("@{},{}".format(event.x, event.y))
            ln = idx.split('.')[0]
            line_text = self.detail.get("{}.0".format(ln), "{}.end".format(ln))
        except Exception:
            return
        m = re.search(r'[（(](\d{6})[)）]', line_text) or \
            re.search(r'(?<![.\d])(\d{6})(?![.\d])', line_text)
        if not m: return
        code = m.group(1)
        before = line_text[:m.start()]
        mname = re.search(r'([\u4e00-\u9fa5A-Z][\u4e00-\u9fa5A-Z0-9·\*]{1,7})\s*$',
                          before.rstrip())
        name = mname.group(1) if mname else ""
        self.app.notify_stock_focus(code, name)

    # ════════════════════════════════════════════
    # 手动高亮
    # ════════════════════════════════════════════
    def _hl_apply(self, tag):
        try:
            s = self.detail.index('sel.first')
            e = self.detail.index('sel.last')
        except tk.TclError:
            messagebox.showinfo("提示", "请先用鼠标选中要高亮的文字")
            return
        self.detail.tag_add(tag, s, e)

    def _hl_clear_sel(self):
        try:
            s = self.detail.index('sel.first')
            e = self.detail.index('sel.last')
        except tk.TclError:
            messagebox.showinfo("提示", "请先选中文字")
            return
        for _, tag, _, _ in MANUAL_HL_TAGS:
            self.detail.tag_remove(tag, s, e)
        for t in ('policy','concept','money','percent'):
            self.detail.tag_remove(t, s, e)

    def _hl_clear_all(self):
        for _, tag, _, _ in MANUAL_HL_TAGS:
            self.detail.tag_remove(tag, '1.0', 'end')
        for t in ('policy','concept','money','percent','category','category_kw'):
            self.detail.tag_remove(t, '1.0', 'end')

    # ════════════════════════════════════════════
    # 字号
    # ════════════════════════════════════════════
    def _font_up(self):
        v = self._fsize.get()
        if v < 24:
            self._fsize.set(v+1)
            self.detail.config(font=('微软雅黑', v+1))

    def _font_down(self):
        v = self._fsize.get()
        if v > 6:
            self._fsize.set(v-1)
            self.detail.config(font=('微软雅黑', v-1))

    # ════════════════════════════════════════════
    # 日期/列表
    # ════════════════════════════════════════════
    def _refresh_dates(self):
        dates = hist_mod.list_history_dates()
        display = [d[:4]+'-'+d[4:6]+'-'+d[6:] for d in dates]
        self.date_combo['values'] = display
        if dates and not self.date_var.get():
            self.date_combo.current(0)
        if self.date_var.get():
            self._load_day()

    def _get_date_key(self):
        return self.date_var.get().replace('-', '')

    def _load_day(self):
        d = self._get_date_key()
        if not d: return
        for i in self.tree.get_children():
            self.tree.delete(i)
        self._row_data.clear()   # 清空旧的行数据缓存
        only_star = self.only_star.get()
        for r in hist_mod.load_history(d):
            if only_star and not r.get('starred'): continue
            self._insert_row(r, d)

    def _insert_row(self, r, date_key):
        star = '⭐' if r.get('starred') else ''
        ok   = '✅' if r.get('success') else '❌'
        note = r.get('note','')[:20]
        tags = ('starred',) if r.get('starred') else ()
        iid  = self.tree.insert('', 'end',
                                 values=(star, r.get('time',''),
                                         r.get('name',''), r.get('code',''),
                                         ok, note), tags=tags)
        # 用 Python 字典缓存完整数据，不再依赖 tree.set 隐藏列
        self._row_data[iid] = {**r, 'date': date_key}

    def _get_sel(self):
        result = []
        for item in self.tree.selection():
            d = self._row_data.get(item)
            if d:
                result.append((d['date'], d, item))
        return result

    # ════════════════════════════════════════════
    # 详情显示 + 编辑 + 保存
    # ════════════════════════════════════════════
    def _show_detail(self):
        # 🔑 切换前：用快照对比检查内容是否有变化（不依赖 <<Modified>> 事件）
        # 这样即使中文 IME 输入下 <<Modified>> 漏触发，也能可靠保存
        if self._cur_record_id:
            current = self.detail.get('1.0', 'end-1c')
            if current and current != self._original_content:
                self._do_save_content_to_history()
        self._dirty = False
        # 取消已调度的自动保存
        if self._auto_save_id:
            try:
                self.app.root.after_cancel(self._auto_save_id)
            except Exception:
                pass
            self._auto_save_id = None

        recs = self._get_sel()
        if not recs: return
        _, r, _ = recs[0]
        self._cur_date_key  = r['date']
        self._cur_record_id = r.get('id')
        # 🆕 v9.3 记录"主股票"代码：用于在联动行情中标识
        self._cur_record_code = str(r.get('code', '')).zfill(6)
        # 🆕 v9.6 通知浮窗（联动模式开启时刷新）
        self.app.notify_stock_focus(r.get('code',''), r.get('name',''))

        # 屏蔽加载期间的 modified 事件
        self._loading = True
        try:
            self.detail.edit_reset()
            self.detail.delete('1.0', 'end')

            star = "⭐  " if r.get('starred') else ""
            head = "{}{}  {}({})  {}\n".format(
                star, r.get('time',''),
                r.get('name',''), r.get('code',''),
                '✅成功' if r.get('success') else '❌失败')
            self.detail.insert('end', head, 'accent')
            if r.get('note'):
                self.detail.insert('end', "📝 备注: " + r['note'] + "\n", 'star_tag')

            # 🆕 标签显示
            tags_list = r.get('tags', []) or []
            if tags_list:
                from ..core.replay import PRESET_TAGS
                tag_map = {v: lbl for lbl, v in PRESET_TAGS}
                tag_display = "  ".join(tag_map.get(t, t) for t in tags_list)
                self.detail.insert('end', "🏷️ 标签: " + tag_display + "\n", 'star_tag')

            # 🆕 次日表现
            nd = r.get('next_day')
            if nd and nd.get('change_pct') is not None:
                pct = nd['change_pct']
                arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")
                sign  = "+" if pct > 0 else ""
                line = "📈 次日表现 ({}): {}  {}{}%\n".format(
                    nd.get('date',''), arrow, sign, pct)
                self.detail.insert('end', line,
                                   'concept' if pct > 0 else 'money')

            self.detail.insert('end', "\n" + r.get('content', ''))
            apply_highlight(self.detail, keep_editable=True)
            # 🆕 v9.4：识别"📊 同逻辑联动标的"区段并染色
            self._apply_quote_coloring(self.detail,
                main_code=self._cur_record_code or "")
            # 🆕 v9.9.6：把所有 6 位代码渲染为蓝字下划线 → 点击推送同花顺
            try:
                from ..widgets import attach_code_links
                attach_code_links(self.detail, self.app,
                                   main_code=self._cur_record_code or "", scope='main')
            except Exception:
                import traceback; traceback.print_exc()

            self.detail.edit_modified(False)
            self._dirty = False
            self._save_btn.config(state='disabled', text="💾 保存")
            self.detail.see('1.0')
            # 🔑 关键：记录加载后的内容快照，作为后续对比基准
            self._original_content = self.detail.get('1.0', 'end-1c')
        finally:
            self._loading = False

    def _on_modified(self, e):
        # _show_detail 加载内容时会触发，不算用户修改
        if self._loading:
            try:
                self.detail.edit_modified(False)
            except Exception:
                pass
            return
        if not self.detail.edit_modified():
            return
        # 🔑 立刻把 modified flag 重置回 False，这样下一次按键还会触发本事件
        # 否则 Tkinter 只在 False→True 时触发一次，连续打字将不再触发！
        try:
            self.detail.edit_modified(False)
        except Exception:
            pass

        if not self._dirty:
            self._dirty = True
            self._save_btn.config(state='normal', text="💾 保存中...")
        # 防抖自动保存：每次编辑后重置定时器
        self._schedule_auto_save()

    def _on_key_release(self, e):
        """KeyRelease 兜底：用快照对比直接判断有无变化"""
        if self._loading:
            return
        # 忽略修饰键和导航键
        if e.keysym in ('Control_L','Control_R','Shift_L','Shift_R','Alt_L','Alt_R',
                         'Left','Right','Up','Down','Home','End','Prior','Next'):
            return
        current = self.detail.get('1.0', 'end-1c')
        if current != self._original_content:
            if not self._dirty:
                self._dirty = True
                self._save_btn.config(state='normal', text="💾 保存中...")
            self._schedule_auto_save()

    def _schedule_auto_save(self):
        """每次编辑后调度自动保存（防抖：1.5秒内无新编辑才真正保存）"""
        if self._auto_save_id:
            try:
                self.app.root.after_cancel(self._auto_save_id)
            except Exception:
                pass
        self._auto_save_id = self.app.root.after(
            self._auto_save_delay, self._auto_save_now)

    def _auto_save_now(self):
        """实际执行自动保存"""
        self._auto_save_id = None
        if not self._cur_record_id:
            return
        # 用快照对比判断是否真的需要保存
        current = self.detail.get('1.0', 'end-1c')
        if current == self._original_content:
            return  # 没变化，不保存
        if self._do_save_content_to_history():
            self._dirty = False
            self._original_content = current  # 更新快照
            self.detail.edit_modified(False)
            self._save_btn.config(text="✅ 已自动保存", state='disabled')
            self.app.root.after(2000,
                lambda: self._save_btn.config(text="💾 保存"))

    def _do_save_content_to_history(self):
        """把当前详情面板内容（去掉元信息头）写回历史记录"""
        if not self._cur_date_key or not self._cur_record_id:
            return False
        full  = self.detail.get('1.0', 'end-1c')
        lines = full.splitlines(keepends=True)
        # 跳过第1行（时间/名称头）和备注行
        content_start = 0
        for i, line in enumerate(lines):
            if i == 0:
                continue
            stripped = line.strip()
            if stripped.startswith('📝 备注:'):
                continue
            if stripped.startswith('🏷️ 标签:'):
                continue
            if stripped.startswith('📈 次日表现'):
                continue
            if stripped == '':
                continue
            content_start = i
            break
        content = ''.join(lines[content_start:]).strip()
        hist_mod.update_record(self._cur_date_key, self._cur_record_id,
                               content=content)
        # 🔑 关键修复：同步更新内存中的 _row_data 缓存
        # 否则切换回来时会用旧的缓存数据覆盖文件中的新内容（导致编辑"丢失"）
        self._sync_row_data_cache(self._cur_record_id, content=content)
        return True

    def _sync_row_data_cache(self, record_id, **fields):
        """更新内存中 _row_data 缓存的指定记录字段"""
        for iid, data in self._row_data.items():
            if data.get('id') == record_id:
                data.update(fields)
                break

    def _save_edit(self):
        if not self._do_save_content_to_history():
            return
        self._dirty = False
        self.detail.edit_modified(False)
        self._save_btn.config(text="✅ 已保存", state='disabled')
        self.app.root.after(2000,
            lambda: self._save_btn.config(text="💾 保存"))

    # ════════════════════════════════════════════
    # 🆕 v9.4：联动行情区段染色（统一处理单条/批量重识别两条路径）
    # ════════════════════════════════════════════
    def _apply_quote_coloring(self, widget, main_code=""):
        """
        扫描 widget 全文，找到「📊 同逻辑联动标的  实时行情」区段，
        对该区段内每一行整行染色：
          - 涨 → up（红）
          - 跌 → down（绿）
          - 平 → flat（暗）
          - 主股票 → 整行额外加 main_stock 背景（覆盖 fg 但能看清）
        """
        RT_MARKER = "📊 同逻辑联动标的"
        text = widget.get('1.0', 'end-1c')
        idx = text.find(RT_MARKER)
        if idx == -1:
            return
        # 找到 marker 所在行的行号
        start_offset = idx
        # 计算行号 + 列号：tkinter 用 "{line}.{col}" 索引
        # 行号 = 该 offset 之前换行数 + 1
        line_no = text.count("\n", 0, start_offset) + 1

        # 先清掉已有的 up/down/flat/main_stock tag（避免重复叠加）
        for t in ('up', 'down', 'flat', 'main_stock'):
            widget.tag_remove(t, '1.0', 'end')

        main6 = str(main_code or "").zfill(6) if main_code else ""

        # 从 marker 行开始扫到文末，逐行识别：
        #   匹配 ▲/▼/─ + 涨跌幅 → up/down/flat
        #   含 "小结" 且含 "上涨/下跌" → dim
        # 其他行（空行/分隔线/标题）跳过。
        # 注：行情区段固定在 marker 之后，且通常是 content 的末尾，扫到 EOF 安全。
        import re as _re
        cur_line = line_no + 1  # 跳过 marker 行本身
        total_lines = int(widget.index('end-1c').split('.')[0])
        while cur_line <= total_lines:
            line_start = "{}.0".format(cur_line)
            line_end   = "{}.end".format(cur_line)
            row_text = widget.get(line_start, line_end)
            stripped = row_text.strip()
            if not stripped:
                cur_line += 1
                continue
            # 小结行 → dim
            if "小结" in stripped and ("上涨" in stripped or "下跌" in stripped):
                widget.tag_add('dim', line_start, line_end)
                cur_line += 1
                continue
            # 行情行：含 ▲/▼/─ 后跟百分比
            m_pct = _re.search(r'([▲▼─])\s*([+\-]?\d+(?:\.\d+)?)\s*%', row_text)
            if not m_pct:
                cur_line += 1
                continue
            try:
                pct = float(m_pct.group(2))
            except ValueError:
                pct = 0.0
            if pct > 0:
                color_tag = 'up'
            elif pct < 0:
                color_tag = 'down'
            else:
                color_tag = 'flat'
            widget.tag_add(color_tag, line_start, line_end)
            # 主股票判断
            if main6:
                m_code = _re.search(r'[（(](\d{6})[)）]', row_text)
                if m_code and m_code.group(1) == main6:
                    widget.tag_add('main_stock', line_start, line_end)
            cur_line += 1

    # ════════════════════════════════════════════
    # 重新识别联动标的行情
    # ════════════════════════════════════════════
    def _requery_realtime(self):
        content = self.detail.get('1.0', 'end-1c')
        if not content.strip():
            messagebox.showinfo("提示", "请先选择一条记录")
            return

        SEP       = "─" * 40
        RT_MARKER = "📊 同逻辑联动标的  实时行情（腾讯财经）"

        # 移除旧的实时行情块
        if RT_MARKER in content:
            idx = content.find("\n\n" + SEP)
            if idx == -1:
                idx = content.rfind(SEP)
                if idx != -1:
                    idx = content.rfind("\n", 0, idx)
            if idx != -1:
                self.detail.delete("1.0+{}c".format(idx), 'end')
                content = content[:idx]

        # 提取联动标的代码
        codes = api_client.extract_linked_codes(content)
        # 🆕 v9.9.6：把当前主股票也加进去（放在最前面），让"本股票"也参与
        # 行情展示和 ⭐ 标记
        main_code = (self._cur_record_code or "").zfill(6) if self._cur_record_code else ""
        if main_code and main_code.isdigit() and len(main_code) == 6:
            if main_code in codes:
                codes.remove(main_code)
            codes = [main_code] + codes
        if not codes:
            self._show_inline_toast(
                "⚠️ 未在④段落找到6位股票代码（AI可能只给了名称没给代码）", "fail")
            return

        # 追加"查询中"提示
        self.detail.insert('end', "\n\n🔄 正在查询 {} 只联动标的行情，请稍候...".format(len(codes)))
        self.detail.see('end')

        def _do():
            data = api_client.fetch_change_pct(codes)

            def _update():
                # 删掉"查询中"提示
                txt = self.detail.get('1.0', 'end-1c')
                p   = txt.rfind("\n\n🔄")
                if p != -1:
                    self.detail.delete("1.0+{}c".format(p), 'end')

                if not data:
                    self._show_inline_toast(
                        "❌ 行情查询失败（非交易时段或网络问题）", "fail")
                    return

                lines_head = ["\n\n" + SEP, RT_MARKER, SEP, ""]
                # 先插入静态文本头（保留 plain 样式）
                self.detail.insert('end', "\n".join(lines_head) + "\n")
                main_code = (self._cur_record_code or "").zfill(6) if self._cur_record_code else ""
                up_n = down_n = 0
                for code, info in data.items():
                    chg = info.get("change_pct", 0)
                    try: chg = float(chg)
                    except (TypeError, ValueError): chg = 0.0
                    is_main = (str(code).zfill(6) == main_code) and main_code
                    if chg > 0:
                        arrow, sign = "▲", "+"; up_n += 1
                    elif chg < 0:
                        arrow, sign = "▼", "";  down_n += 1
                    else:
                        arrow, sign = "─", ""
                    prefix = "  ⭐ " if is_main else "    "
                    # 整行一次性插入，颜色由 _apply_quote_coloring 统一处理
                    self.detail.insert('end',
                        "{}{}（{}）  {}  {}{}{}%    {}\n".format(
                            prefix, info.get("name",""), code,
                            info.get("price",""), arrow, sign, chg,
                            info.get("time","")))
                # 底部汇总条
                if up_n or down_n:
                    self.detail.insert('end', SEP + "\n")
                    self.detail.insert('end',
                        "  小结：上涨 {}  ·  下跌 {}  ·  共 {}\n".format(
                            up_n, down_n, len(data)))
                self.detail.insert('end', SEP + "\n")

                # 🆕 v9.4：统一染色（涨红跌绿 + 主股突出）
                self._apply_quote_coloring(self.detail, main_code=main_code)
                # 🆕 v9.9.6：新追加的行情区里也加蓝字下划线链接
                try:
                    from ..widgets import attach_code_links
                    attach_code_links(self.detail, self.app,
                                       main_code=main_code, scope='main')
                except Exception:
                    import traceback; traceback.print_exc()
                self.detail.see('end')

                # 🔑 自动保存：把更新后的内容写回历史记录文件
                if self._cur_date_key and self._cur_record_id:
                    self._do_save_content_to_history()
                    self.detail.edit_modified(False)
                    self._dirty = False
                    self._save_btn.config(state='disabled')

                self._show_inline_toast(
                    "✅ 已识别 {} 只联动代码，{} 只成功获取行情，已自动保存".format(
                        len(codes), len(data)))

            self.app.root.after(0, _update)

        threading.Thread(target=_do, daemon=True).start()

    # ════════════════════════════════════════════
    # 右键菜单功能
    # ════════════════════════════════════════════
    def _ctx_wechat(self):
        content = self.detail.get('1.0', 'end-1c')
        recs = self._get_sel()
        name = recs[0][1].get('name','?') if recs else '?'
        code = recs[0][1].get('code','?') if recs else '?'
        wx = text_utils.to_wechat_format(name, code, content)
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(wx)
        messagebox.showinfo("已复制", "微信格式已复制到剪贴板")

    def _ctx_export_html(self):
        content = self.detail.get('1.0', 'end-1c')
        recs = self._get_sel()
        if not recs:
            messagebox.showinfo("提示", "请先选中左侧列表中的记录")
            return
        _, r, _ = recs[0]
        try:
            fn = reports.export_html_report([{
                "name":    r.get("name",""),
                "code":    r.get("code",""),
                "content": content,
                "success": True,
            }], title="{} 分析报告".format(r.get("name","")))
            messagebox.showinfo("导出成功", fn)
        except Exception as e:
            messagebox.showerror("失败", str(e))

    # ════════════════════════════════════════════
    # 列表右键菜单（直接快捷操作）
    # ════════════════════════════════════════════
    def _build_tree_context_menu(self):
        C = self.C
        m = tk.Menu(self.tree, tearoff=0,
                     bg=C['panel'], fg=C['text'],
                     activebackground=C['acc_dark'],
                     activeforeground='white',
                     font=('微软雅黑', 9))
        m.add_command(label="🔎  查看股票详情",    command=self._tree_show_popup)
        m.add_separator()
        m.add_command(label="⭐  切换星标",        command=self._toggle_star)
        m.add_command(label="📝  编辑备注",        command=self._edit_note_dialog)
        m.add_command(label="🏷️  编辑标签",        command=self._edit_tags_dialog)
        m.add_separator()
        m.add_command(label="➕  加入自选股",      command=self._add_to_favorites)
        m.add_command(label="📋  复制代码",        command=self._tree_copy_code)
        m.add_command(label="📋  复制 名称+代码",  command=self._tree_copy_name_code)
        m.add_separator()
        m.add_command(label="🔄  重新分析（送AI）", command=self._tree_reanalyze)
        m.add_separator()
        m.add_command(label="🗑  删除记录",        command=self._delete_selected)
        self._tree_ctx = m
        self.tree.bind('<Button-3>', self._show_tree_ctx)
        self.tree.bind('<Button-2>', self._show_tree_ctx)

    def _tree_show_popup(self):
        """🆕 v9.5：在浮窗打开股票详情"""
        recs = self._get_sel()
        if not recs: return
        _, r, _ = recs[0]
        self.app.show_stock_popup(r.get('code',''), r.get('name',''))

    def _show_tree_ctx(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            try:
                self._tree_ctx.tk_popup(event.x_root, event.y_root)
            finally:
                self._tree_ctx.grab_release()

    def _tree_copy_code(self):
        recs = self._get_sel()
        if not recs: return
        _, r, _ = recs[0]
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(r.get('code', ''))

    def _tree_copy_name_code(self):
        recs = self._get_sel()
        if not recs: return
        _, r, _ = recs[0]
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append("{} {}".format(r.get('name', ''), r.get('code', '')))

    def _tree_reanalyze(self):
        recs = self._get_sel()
        if not recs: return
        stocks = []
        for _, r, _ in recs:
            stocks.append((r.get('name', ''), r.get('code', ''), ''))
        bus.emit(Events.REQUEST_BATCH_RUN, stocks, "历史重分析")

    # ════════════════════════════════════════════
    # 星标 / 备注 / 删除
    # ════════════════════════════════════════════
    def _toggle_star(self):
        recs = self._get_sel()
        if not recs:
            messagebox.showinfo("提示", "请先选中记录")
            return
        for dk, r, _ in recs:
            hist_mod.toggle_star(dk, r.get('id'))
        self._reload_list()

    def _edit_note_dialog(self):
        recs = self._get_sel()
        if not recs: return
        dk, r, _ = recs[0]
        new = simpledialog.askstring(
            "编辑备注",
            "为 {} ({}) 添加备注：".format(r.get('name',''), r.get('code','')),
            initialvalue=r.get('note',''), parent=self.app.root)
        if new is None: return
        hist_mod.set_note(dk, r.get('id'), new.strip())
        self._reload_list()

    def _delete_selected(self):
        recs = self._get_sel()
        if not recs: return
        if not messagebox.askyesno("确认删除",
                "确认删除选中的 {} 条记录？".format(len(recs))):
            return
        by_date = {}
        for dk, r, _ in recs:
            by_date.setdefault(dk, []).append(r.get('id'))
        for dk, ids in by_date.items():
            hist_mod.delete_records(dk, ids)
        self.detail.delete('1.0', 'end')
        self._cur_date_key = self._cur_record_id = None
        self._dirty = False
        self._save_btn.config(state='disabled')
        self._reload_list()

    def _clear_day(self):
        d = self._get_date_key()
        if not d: return
        if not messagebox.askyesno("确认清空",
                "将清空 {} 当天所有记录？".format(d)):
            return
        hist_mod.clear_day(d)
        self.detail.delete('1.0', 'end')
        self._refresh_dates()

    def _reload_list(self):
        if self.kw_var.get().strip():
            self._search()
        else:
            self._load_day()

    def _search(self):
        kw = self.kw_var.get().strip()
        if not kw:
            self._load_day(); return
        for i in self.tree.get_children():
            self.tree.delete(i)
        self._row_data.clear()   # 清空旧的行数据缓存
        only_star = self.only_star.get()
        for r in hist_mod.search_history(kw)[:300]:
            if only_star and not r.get('starred'): continue
            d    = r.get('date','')
            star = '⭐' if r.get('starred') else ''
            ok   = '✅' if r.get('success') else '❌'
            note = r.get('note','')[:20]
            tags = ('starred',) if r.get('starred') else ()
            iid  = self.tree.insert('', 'end',
                                     values=(star,
                                             "{} {}".format(d[4:6]+'-'+d[6:], r.get('time','')),
                                             r.get('name',''), r.get('code',''), ok, note),
                                     tags=tags)
            self._row_data[iid] = r    # 用字典缓存完整数据

    # ════════════════════════════════════════════
    # 自动模式：定时批量识别行情
    # ════════════════════════════════════════════
    def _toggle_auto_mode(self):
        """开关自动模式"""
        if self._auto_mode_var.get():
            # 解析间隔
            try:
                m = int(self._auto_interval_var.get())
                if m < 1: m = 1
                self._auto_mode_minutes = m
            except Exception:
                self._auto_mode_minutes = 5
                self._auto_interval_var.set("5")
            self._auto_mode_on = True
            self._auto_status_var.set("✅ 已启用 · 每{}分钟自动批量识别".format(self._auto_mode_minutes))
            # 立刻执行一次
            self._schedule_next_auto_run(initial=True)
        else:
            self._auto_mode_on = False
            self._auto_status_var.set("已关闭")
            if self._auto_mode_id:
                try:
                    self.app.root.after_cancel(self._auto_mode_id)
                except Exception:
                    pass
                self._auto_mode_id = None
            self.app.root.after(3000, lambda: self._auto_status_var.set(""))

    def _schedule_next_auto_run(self, initial=False):
        """安排下一次自动批量识别"""
        if not self._auto_mode_on:
            return
        # initial=True 时延迟 3 秒（避免开关刚打开立刻触发），否则按间隔
        delay_ms = 3000 if initial else self._auto_mode_minutes * 60 * 1000
        self._auto_mode_id = self.app.root.after(delay_ms, self._auto_run_batch)

    def _auto_run_batch(self):
        """自动模式触发的批量识别（无确认弹窗）"""
        if not self._auto_mode_on:
            return
        d = self._get_date_key()
        if not d:
            self._schedule_next_auto_run()
            return
        records = hist_mod.load_history(d)
        if not records:
            self._auto_status_var.set("⚠️ 当日无记录，等待下一次")
            self._schedule_next_auto_run()
            return
        # 在后台执行，完成后自动调度下一次
        import threading
        def _worker():
            self._do_batch_requery(d, records, silent=True)
            self.app.root.after(0, lambda: (
                self._auto_status_var.set("✅ 已完成第 {} 轮 · 下一轮 {} 分钟后".format(
                    getattr(self, "_auto_round", 0) + 1, self._auto_mode_minutes)),
                setattr(self, "_auto_round", getattr(self, "_auto_round", 0) + 1)
            ))
            self.app.root.after(0, self._schedule_next_auto_run)
        threading.Thread(target=_worker, daemon=True).start()
        self._auto_status_var.set("🔄 第 {} 轮识别中...".format(
            getattr(self, "_auto_round", 0) + 1))

    # ════════════════════════════════════════════
    # Inline Toast 提示（取代弹窗）
    # ════════════════════════════════════════════
    def _show_inline_toast(self, msg, kind="ok"):
        """在详情面板顶部显示一行短暂提示，3 秒后自动消失"""
        C = self.C
        color = {"ok": C['green'], "fail": C['red'], "info": C['accent']}.get(kind, C['green'])
        self._toast_lbl.config(fg=color)
        self._toast_var.set(msg)
        # 取消旧定时器
        if hasattr(self, "_toast_after_id") and self._toast_after_id:
            try:
                self.app.root.after_cancel(self._toast_after_id)
            except Exception:
                pass
        self._toast_after_id = self.app.root.after(
            3500, lambda: self._toast_var.set(""))

    # ════════════════════════════════════════════
    # 一键批量重识别当日全部记录
    # ════════════════════════════════════════════
    def _batch_requery_all(self):
        d = self._get_date_key()
        if not d:
            messagebox.showinfo("提示", "请先在左上角选择日期")
            return
        records = hist_mod.load_history(d)
        if not records:
            messagebox.showinfo("提示", "当日无历史记录")
            return
        if not messagebox.askyesno("确认",
            "将对 {} 当日全部 {} 条记录批量重新识别联动行情。\n\n"
            "预计耗时约 {} 秒（每条记录查询一次腾讯接口）。\n\n"
            "完成后自动保存到历史文件。确定继续？".format(
                d, len(records), len(records) * 1)):
            return

        # 后台线程跑，避免UI卡死
        import threading, time
        threading.Thread(
            target=lambda: self._do_batch_requery(d, records),
            daemon=True).start()

    def _do_batch_requery(self, date_key, records, silent=False):
        import time
        SEP       = "─" * 40
        RT_MARKER = "📊 同逻辑联动标的  实时行情（腾讯财经）"

        ok, fail, skip = 0, 0, 0
        total = len(records)

        for i, r in enumerate(records, 1):
            # 更新进度
            name = r.get('name', '')
            self.app.root.after(0,
                lambda i=i, n=name: self._show_inline_toast(
                    "🔄 批量识别中 ({}/{})  {}".format(i, total, n), "info"))

            content = r.get('content', '') or ''

            # 移除旧的实时行情块
            if RT_MARKER in content:
                idx = content.rfind("\n\n" + SEP)
                if idx == -1:
                    p = content.rfind(SEP)
                    if p > 0:
                        idx = content.rfind("\n", 0, p)
                if idx != -1:
                    content = content[:idx]

            # 提取代码
            codes = api_client.extract_linked_codes(content)
            # 🆕 v9.9.6：把当前记录对应的主股票也加进去（最前面）
            rec_main = str(r.get('code', '') or '').zfill(6)
            if rec_main and rec_main.isdigit() and len(rec_main) == 6:
                if rec_main in codes:
                    codes.remove(rec_main)
                codes = [rec_main] + codes
            if not codes:
                skip += 1
                continue

            # 查询行情
            data = api_client.fetch_change_pct(codes)
            if not data:
                fail += 1
                time.sleep(0.5)
                continue

            # 拼接新的实时行情块
            lines = ["\n\n" + SEP, RT_MARKER, SEP]
            for code, info in data.items():
                chg   = info["change_pct"]
                arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "─")
                sign  = "+" if chg > 0 else ""
                # 主股加 ⭐ 前缀
                prefix = "  ⭐ " if (rec_main and code == rec_main) else "    "
                lines.append("{}{}（{}）  {}  {}{}%   {}".format(
                    prefix, info["name"], code, info["price"],
                    arrow, sign + str(chg), info["time"]))
            lines.append(SEP)
            new_content = content + "\n".join(lines)

            hist_mod.update_record(date_key, r['id'], content=new_content)
            ok += 1
            time.sleep(0.3)   # 防止请求过密被限流

        # 完成
        def _done():
            self._show_inline_toast(
                "✅ 批量完成：成功 {} / 失败 {} / 跳过 {}".format(ok, fail, skip), "ok")
            self._load_day()
            if not silent:
                messagebox.showinfo("批量识别完成",
                    "✅ 成功更新: {} 条\n"
                    "❌ 行情查询失败: {} 条\n"
                    "⏭️ 跳过(无代码): {} 条".format(ok, fail, skip))
        self.app.root.after(0, _done)

    # ════════════════════════════════════════════
    # 编辑标签（多选）
    # ════════════════════════════════════════════
    def _edit_tags_dialog(self):
        from ..core.replay import PRESET_TAGS
        recs = self._get_sel()
        if not recs:
            messagebox.showinfo("提示", "请先选中一条记录")
            return
        date_key, r, _ = recs[0]
        cur_tags = set(r.get('tags', []) or [])

        # 构建对话框
        dlg = tk.Toplevel(self.app.root)
        dlg.title("🏷️ 编辑标签")
        dlg.geometry("360x460")
        dlg.configure(bg=self.C['bg'])
        dlg.transient(self.app.root)
        dlg.resizable(False, False)

        tk.Label(dlg,
                 text="为 {} ({}) 选择标签".format(r.get('name',''), r.get('code','')),
                 font=('微软雅黑', 10, 'bold'),
                 bg=self.C['bg'], fg=self.C['text']).pack(pady=(16, 4))
        tk.Label(dlg, text="可多选，关闭对话框自动保存",
                 font=('微软雅黑', 8), bg=self.C['bg'], fg=self.C['dim']).pack(pady=(0, 12))

        # 标签复选框
        check_frame = tk.Frame(dlg, bg=self.C['bg'])
        check_frame.pack(fill='both', expand=True, padx=24)

        var_dict = {}
        for lbl, val in PRESET_TAGS:
            v = tk.BooleanVar(value=(val in cur_tags))
            var_dict[val] = v
            cb = tk.Checkbutton(check_frame, text=lbl,
                                 variable=v, font=('微软雅黑', 10),
                                 bg=self.C['bg'], fg=self.C['text'],
                                 selectcolor=self.C['card'],
                                 activebackground=self.C['bg'],
                                 anchor='w', padx=8)
            cb.pack(fill='x', pady=1)

        def _on_close():
            new_tags = [val for val, v in var_dict.items() if v.get()]
            hist_mod.update_record(date_key, r.get('id'), tags=new_tags)
            # 同步缓存
            self._sync_row_data_cache(r.get('id'), tags=new_tags)
            dlg.destroy()
            # 如果是当前显示的记录，刷新详情
            if self._cur_record_id == r.get('id'):
                self._show_detail()

        styled_btn(dlg, "💾 保存并关闭", self.C['green'],
                   _on_close, pady=8).pack(pady=12, fill='x', padx=24)
        dlg.protocol("WM_DELETE_WINDOW", _on_close)

    # ════════════════════════════════════════════
    # 从历史记录加入自选股
    # ════════════════════════════════════════════
    def _add_to_favorites(self):
        from ..core import config as cfg_mod
        recs = self._get_sel()
        if not recs:
            messagebox.showinfo("提示", "请先选中一条或多条记录")
            return
        added, dup = 0, 0
        for _, r, _ in recs:
            name = r.get("name", "").strip()
            code = r.get("code", "").strip()
            if not name or not code or code == "000000":
                continue
            if cfg_mod.add_favorite(name, code, tag="历史记录"):
                added += 1
            else:
                dup += 1
        bus.emit(Events.FAVORITES_UPDATED)
        if added:
            messagebox.showinfo("完成",
                "已加入自选股 {} 只{}".format(
                    added, "，{} 只已存在跳过".format(dup) if dup else ""))
        elif dup:
            messagebox.showinfo("提示", "选中的股票已全部在自选股中了")
        else:
            messagebox.showinfo("提示", "没有找到有效的股票代码（代码为000000的记录无法添加）")

    # ════════════════════════════════════════════
    # 导出星标
    # ════════════════════════════════════════════
    def _export_excel(self):
        try:
            path = hist_mod.export_starred_to_excel()
            messagebox.showinfo("导出成功", path) if path else messagebox.showinfo("提示", "没有星标记录")
        except Exception as e:
            messagebox.showerror("失败", str(e))

    def _export_html(self):
        try:
            path = hist_mod.export_starred_to_html()
            messagebox.showinfo("导出成功", path) if path else messagebox.showinfo("提示", "没有星标记录")
        except Exception as e:
            messagebox.showerror("失败", str(e))

    # ════════════════════════════════════════════════
    # 导出当日历史股票的实时行情
    # ════════════════════════════════════════════════
    def _export_daily_quotes(self):
        d = self._get_date_key()
        if not d:
            messagebox.showinfo("提示", "请先在左上角选择日期")
            return
        records = hist_mod.load_history(d)
        if not records:
            messagebox.showinfo("提示", "当日无历史记录")
            return

        # 收集所有有效代码（去重）
        codes = list(set(r.get('code', '') for r in records if r.get('code') and r['code'] != '000000'))
        if not codes:
            messagebox.showinfo("提示", "未找到有效的股票代码")
            return

        self._show_inline_toast("⏳ 正在查询 {} 只股票行情...".format(len(codes)), "info")

        def _do():
            # 使用项目内置的腾讯接口，每次批量查30个，稳定可靠
            data = api_client.fetch_change_pct(codes)
            
            if not data:
                state.ui_queue.put(lambda: self._show_inline_toast("❌ 行情查询失败", "fail"))
                return

            # 组装数据
            import pandas as pd
            rows = []
            for r in records:
                code = r.get('code', '')
                name = r.get('name', '')
                if code == '000000' or not code:
                    continue
                
                q = data.get(code, {})
                rows.append({
                    "股票代码": code,
                    "股票名称": q.get('name', name), # 优先用行情接口返回的最新名
                    "分析状态": "✅成功" if r.get('success') else "❌失败",
                    "分析时间": r.get('time', ''),
                    "备注": r.get('note', ''),
                    "细分标签": r.get('category', ''),
                    "现价": q.get('price', ''),
                    "涨跌幅%": q.get('change_pct', ''),
                    "行情时间": q.get('time', ''),
                })

            # 按涨跌幅降序排列
            df = pd.DataFrame(rows)
            df = df.sort_values(by="涨跌幅%", ascending=False, na_position='last').reset_index(drop=True)

            # 保存
            from ..core.paths import DIRS
            fn = DIRS["output"] / "历史行情_{}_{}.xlsx".format(d, datetime.now().strftime("%H%M%S"))
            try:
                df.to_excel(fn, index=False)
                state.ui_queue.put(lambda: (
                    self._show_inline_toast("✅ 已导出: {}".format(fn.name), "ok"),
                    messagebox.showinfo("导出成功", "已保存至:\n{}".format(str(fn)))
                ))
            except Exception as e:
                state.ui_queue.put(lambda: self._show_inline_toast("❌ 保存失败: {}".format(e), "fail"))

        threading.Thread(target=_do, daemon=True).start()



