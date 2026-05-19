"""
📊 全市场快照 Tab (带列表展示版)
- 一键拉取东方财富全 A 股行情（涨跌幅、最高、最低）
- 按日期自动保存为 CSV
- 支持查看历史快照
"""
import os, sys, threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from .base import BaseTab
from ..widgets import make_card, styled_btn, make_log_widget, write_log
from ..core import api_client
from ..core.paths import DIRS, ensure_dirs
from ..bus import state


class MarketTab(BaseTab):
    title = "全市场快照"

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=12, pady=10)

        # ── 顶部控制区 ──
        hdr = tk.Frame(body, bg=C['bg']); hdr.pack(fill='x', pady=(0, 6))
        tk.Label(hdr, text="📊 全市场行情快照", font=('微软雅黑', 12, 'bold'),
                 bg=C['bg'], fg=C['text']).pack(side='left')
        tk.Label(hdr, text="  ·  东方财富实时推送 · 自动存CSV",
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['dim']).pack(side='left')
        
        styled_btn(hdr, "📂 打开目录", C['idle'], self._open_dir).pack(side='right', padx=(6, 0))

        # ── 抓取配置 ──
        ctrl = make_card(body, "⚙️  数据抓取", pady_top=0)
        cr = tk.Frame(ctrl, bg=C['panel']); cr.pack(fill='x')
        
        self._today_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        tk.Label(cr, text="日期", font=('微软雅黑', 9), bg=C['panel'], fg=C['dim']).pack(side='left', padx=(0, 4))
        tk.Entry(cr, textvariable=self._today_var, font=('微软雅黑', 9),
                 bg=C['card'], fg=C['text'], insertbackground='white', relief='flat', width=12).pack(side='left', ipady=4, padx=(0, 12))
        
        self._fetch_btn = styled_btn(cr, "🚀 一键抓取全市场", C['green'], self._start_fetch, pady=6)
        self._fetch_btn.pack(side='left', padx=(0, 20))
        
        self._status_var = tk.StringVar(value="就绪")
        tk.Label(cr, textvariable=self._status_var, font=('微软雅黑', 9, 'bold'),
                 bg=C['panel'], fg=C['yellow']).pack(side='left')

        # ── 统计概览 ──
        self._stat_frame = tk.Frame(body, bg=C['bg'])
        self._stat_frame.pack(fill='x', pady=(6, 4))

        # ── 🆕 股票列表展示区 ──
        list_hdr = tk.Frame(body, bg=C['panel'], highlightbackground=C['border'], highlightthickness=1)
        list_hdr.pack(fill='x')
        tk.Label(list_hdr, text="📋  涨跌幅排名", font=('微软雅黑', 9, 'bold'),
                 bg=C['panel'], fg=C['accent']).pack(side='left', padx=12, pady=6)
        self._count_var = tk.StringVar(value="共 0 只")
        tk.Label(list_hdr, textvariable=self._count_var, font=('微软雅黑', 8),
                 bg=C['panel'], fg=C['dim']).pack(side='right', padx=12, pady=6)

        tree_frame = tk.Frame(body, bg=C['bg'])
        tree_frame.pack(fill='both', expand=True, pady=(0, 4))

        cols = ('rank', 'code', 'name', 'price', 'pct', 'high', 'low')
        self.tree = ttk.Treeview(tree_frame, columns=cols, show='headings', height=20)
        
        widths = {'rank': 50, 'code': 80, 'name': 120, 'price': 80, 'pct': 80, 'high': 80, 'low': 80}
        texts = {'rank': '排名', 'code': '代码', 'name': '名称', 'price': '现价', 'pct': '涨跌幅%', 'high': '最高', 'low': '最低'}
        
        for col in cols:
            self.tree.heading(col, text=texts[col])
            self.tree.column(col, width=widths[col], anchor='center', minwidth=40)
            
        vsb = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        # 颜色标记
        self.tree.tag_configure('up', foreground=C['red'])
        self.tree.tag_configure('down', foreground=C['green'])
        self.tree.tag_configure('flat', foreground=C['dim'])
        self.tree.tag_configure('limit_up', foreground='white', background=C['acc_dark'])

        # ── 日志区 (缩小版) ──
        self.log_w = make_log_widget(body, font_size=8)
        
    def _start_fetch(self):
        date_str = self._today_var.get().strip().replace("-", "")
        if not date_str or len(date_str) != 8:
            messagebox.showwarning("提示", "日期格式错误"); return
            
        self._fetch_btn.config(state='disabled', text="抓取中...")
        self._count_var.set("共 0 只")
        for i in self.tree.get_children(): self.tree.delete(i)
        write_log(self.log_w, "🚀 开始抓取全市场行情...", 'accent')
        
        def _run():
            def on_progress(page, total):
                state.log_queue.put((self.log_w, "📡 拉取第 {}/{} 页...".format(page, total), 'dim'))
                
            data = api_client.fetch_all_market_stocks(on_progress=on_progress)
            
            if isinstance(data, dict) and 'error' in data:
                state.log_queue.put((self.log_w, "❌ 抓取失败: " + data['error'], 'fail'))
                state.ui_queue.put(lambda: self._fetch_btn.config(state='normal', text="🚀 一键抓取全市场"))
                return
                
            state.log_queue.put((self.log_w, "✅ 拉取完成，共 {} 只，正在保存与渲染...".format(len(data)), 'ok'))
            
            # 保存为 CSV
            try:
                import pandas as pd
                ensure_dirs()
                save_dir = DIRS["market"]
                save_dir.mkdir(parents=True, exist_ok=True)
                fn = save_dir / "market_{}.csv".format(date_str)
                df = pd.DataFrame(data)
                df.to_csv(fn, index=False, encoding="utf-8-sig")
                state.log_queue.put((self.log_w, "💾 已保存: {}".format(fn.name), 'ok'))
            except Exception as e:
                state.log_queue.put((self.log_w, "❌ 保存失败: {}".format(e), 'fail'))

            # 统计与渲染
            up = len([s for s in data if s['change_pct'] > 0])
            down = len([s for s in data if s['change_pct'] < 0])
            flat = len(data) - up - down
            limit_up = len([s for s in data if s['change_pct'] >= 9.8])
            
            def _upd_ui():
                self._fetch_btn.config(state='normal', text="🚀 一键抓取全市场")
                self._render_stats(len(data), up, down, flat, limit_up)
                self._populate_tree(data)
            state.ui_queue.put(_upd_ui)

        threading.Thread(target=_run, daemon=True).start()

    def _populate_tree(self, data):
        """将数据填充到表格"""
        for i, s in enumerate(data, 1):
            pct = s['change_pct']
            if pct >= 9.8:
                tag = 'limit_up'
            elif pct > 0:
                tag = 'up'
            elif pct < 0:
                tag = 'down'
            else:
                tag = 'flat'
                
            self.tree.insert('', 'end', values=(
                i, s['code'], s['name'], 
                "{:.2f}".format(s['price']), 
                "{:+.2f}".format(pct), 
                "{:.2f}".format(s['high']), 
                "{:.2f}".format(s['low'])
            ), tags=(tag,))
        self._count_var.set("共 {} 只".format(len(data)))

    def _render_stats(self, total, up, down, flat, limit_up):
        C = self.C
        for w in self._stat_frame.winfo_children(): w.destroy()
        row = tk.Frame(self._stat_frame, bg=C['bg']); row.pack(fill='x')
        
        items = [
            ('📊 总数', str(total), C['text']),
            ('📈 上涨', str(up), C['red']),
            ('📉 下跌', str(down), C['green']),
            ('➖ 平盘', str(flat), C['dim']),
            ('🔥 涨停', str(limit_up), C['yellow']),
        ]
        for lbl, val, color in items:
            cell = tk.Frame(row, bg=C['panel'], highlightbackground=C['border'], highlightthickness=1)
            cell.pack(side='left', fill='both', expand=True, padx=2)
            tk.Label(cell, text=lbl, font=('微软雅黑', 8), bg=C['panel'], fg=C['dim']).pack(pady=(4, 0))
            tk.Label(cell, text=val, font=('微软雅黑', 12, 'bold'), bg=C['panel'], fg=color).pack(pady=(0, 4))

    def _open_dir(self):
        try:
            folder = DIRS["market"].resolve()
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith('win'):
                os.startfile(str(folder))
            elif sys.platform == 'darwin':
                import subprocess; subprocess.Popen(['open', str(folder)])
            else:
                import subprocess; subprocess.Popen(['xdg-open', str(folder)])
        except Exception as e:
            messagebox.showerror("失败", str(e))