"""
单股搜索 Tab
- 名称补全
- 数据源可视化
- 字号调节
- 微信格式/导出HTML
"""
import threading, time
import tkinter as tk
from tkinter import messagebox

from .base import BaseTab
from ..widgets import make_card, styled_btn, styled_entry, make_log_widget, clear_log, apply_highlight
from ..core import api_client, config as cfg_mod, history as hist_mod, text_utils, reports
from ..bus import bus, Events, state


class SingleTab(BaseTab):
    title = "单股搜索"

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=12, pady=10)

        left  = tk.Frame(body, bg=C['bg'], width=320)
        left.pack(side='left', fill='y', padx=(0, 10))
        left.pack_propagate(False)
        right = tk.Frame(body, bg=C['bg'])
        right.pack(side='left', fill='both', expand=True)

        # 左侧：搜索区
        sc = make_card(left, "🔍  搜索股票", pady_top=0)

        tk.Label(sc, text="股票名称（输入有提示）", font=('微软雅黑', 8),
                 bg=C['panel'], fg=C['dim']).pack(anchor='w')
        self.name_var = tk.StringVar()
        name_entry = styled_entry(sc, self.name_var)
        name_entry.pack(fill='x', ipady=5, pady=(2, 2))

        # 自动补全 Listbox
        self.suggest = tk.Listbox(sc, height=4, font=('微软雅黑', 8),
                                   bg=C['card'], fg=C['text'],
                                   selectbackground=C['acc_dark'],
                                   selectforeground='white',
                                   relief='flat', highlightthickness=0)
        self.suggest.pack(fill='x', pady=(0, 6))
        self.suggest.pack_forget()

        tk.Label(sc, text="股票代码", font=('微软雅黑', 8),
                 bg=C['panel'], fg=C['dim']).pack(anchor='w')
        self.code_var = tk.StringVar()
        styled_entry(sc, self.code_var).pack(fill='x', ipady=5, pady=(2, 8))

        # 🆕 涨停类别（可选）
        tk.Label(sc, text="涨停类别 / 细分标签（可选）", font=('微软雅黑', 8),
                 bg=C['panel'], fg=C['dim']).pack(anchor='w')
        self.category_var = tk.StringVar()
        styled_entry(sc, self.category_var).pack(fill='x', ipady=5, pady=(2, 2))
        # 开关：是否把类别加入搜索
        self.use_category_var = tk.BooleanVar(value=True)
        tk.Checkbutton(sc, text="📌 把类别作为 AI 上下文",
                       variable=self.use_category_var,
                       font=('微软雅黑', 7),
                       bg=C['panel'], fg=C['text'],
                       selectcolor=C['card'],
                       activebackground=C['panel']).pack(anchor='w', pady=(0, 8))

        tk.Label(sc, text="使用 API Key（序号）", font=('微软雅黑', 8),
                 bg=C['panel'], fg=C['dim']).pack(anchor='w')
        self.key_idx = tk.StringVar(value="1")
        styled_entry(sc, self.key_idx, 6).pack(anchor='w', ipady=4, pady=(2, 10))

        self.search_btn = styled_btn(sc, "🔍  开始搜索", C['accent'],
                                      self._search, pady=10)
        self.search_btn.pack(fill='x')

        # 绑定名称变化触发补全
        self.name_var.trace_add('write', lambda *a: self._update_suggest(sc))
        self.suggest.bind('<<ListboxSelect>>', self._on_suggest_click)

        # 数据源
        dc = make_card(left, "🌐  数据源")
        self.src_frame = tk.Frame(dc, bg=C['panel'])
        self.src_frame.pack(fill='x')
        self.src_status = tk.StringVar(value="等待搜索...")
        tk.Label(dc, textvariable=self.src_status,
                 font=('微软雅黑', 8), bg=C['panel'], fg=C['dim']).pack(anchor='w', pady=(4, 0))

        # 右侧：结果头部 + 日志
        rhdr = tk.Frame(right, bg=C['panel'],
                        highlightbackground=C['border'], highlightthickness=1)
        rhdr.pack(fill='x')
        tk.Label(rhdr, text="📄  分析结果", font=('微软雅黑', 9, 'bold'),
                 bg=C['panel'], fg=C['accent']).pack(side='left', padx=12, pady=6)
        self.status_var = tk.StringVar(value="")
        tk.Label(rhdr, textvariable=self.status_var,
                 font=('微软雅黑', 9), bg=C['panel'], fg=C['green']).pack(side='left')

        # 右侧头部按钮组
        tk.Button(rhdr, text="清空", font=('微软雅黑', 8),
                  bg=C['border'], fg=C['dim'], relief='flat', cursor='hand2',
                  command=lambda: clear_log(self.log_w)).pack(side='right', padx=8, pady=4)
        tk.Button(rhdr, text="📋 复制", font=('微软雅黑', 8),
                  bg=C['acc_dark'], fg='white', relief='flat', cursor='hand2',
                  command=self._copy).pack(side='right', padx=(0, 4), pady=4)
        tk.Button(rhdr, text="💬 微信", font=('微软雅黑', 8),
                  bg=C['green'], fg='white', relief='flat', cursor='hand2',
                  command=self._to_wechat).pack(side='right', padx=(0, 4), pady=4)
        tk.Button(rhdr, text="📄 HTML", font=('微软雅黑', 8),
                  bg=C['yellow'], fg='#111', relief='flat', cursor='hand2',
                  command=self._export_html).pack(side='right', padx=(0, 4), pady=4)
        # 字号
        tk.Label(rhdr, text="字号", font=('微软雅黑', 8),
                 bg=C['panel'], fg=C['dim']).pack(side='right', padx=(0, 2), pady=4)
        self.font_size = tk.IntVar(value=10)
        tk.Button(rhdr, text="▲", font=('Arial', 8), width=2,
                  bg=C['border'], fg=C['text'], relief='flat', cursor='hand2',
                  command=self._font_up).pack(side='right', pady=4)
        tk.Label(rhdr, textvariable=self.font_size,
                 font=('微软雅黑', 8), bg=C['panel'],
                 fg=C['yellow'], width=2).pack(side='right', pady=4)
        tk.Button(rhdr, text="▼", font=('Arial', 8), width=2,
                  bg=C['border'], fg=C['text'], relief='flat', cursor='hand2',
                  command=self._font_down).pack(side='right', padx=(4, 0), pady=4)

        self.log_w = make_log_widget(right, font_size=10)

    # ── 名称补全 ───────────────────────────────
    def _update_suggest(self, parent):
        kw = self.name_var.get().strip()
        if not kw:
            self.suggest.pack_forget()
            return
        matches = cfg_mod.search_stocks(kw, limit=6)
        if not matches:
            self.suggest.pack_forget()
            return
        self.suggest.delete(0, 'end')
        for n, c in matches:
            self.suggest.insert('end', "{}  →  {}".format(n, c))
        try:
            self.suggest.pack(fill='x', pady=(0, 6),
                              before=parent.winfo_children()[2])
        except Exception:
            self.suggest.pack(fill='x', pady=(0, 6))

    def _on_suggest_click(self, e):
        sel = self.suggest.curselection()
        if not sel:
            return
        item = self.suggest.get(sel[0])
        try:
            name, code = [p.strip() for p in item.split("→")]
            self.name_var.set(name)
            self.code_var.set(code)
            self.suggest.pack_forget()
        except Exception:
            pass

    # ── 搜索逻辑 ───────────────────────────────
    def _search(self):
        name = self.name_var.get().strip()
        code = self.code_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入股票名称")
            return
        if not code:
            code = "000000"

        keys = [k for k in self.app.cfg.get("api_keys", []) if k.strip()]
        if not keys:
            messagebox.showerror("错误", "没有可用的 API Key")
            return
        try:
            ki = int(self.key_idx.get()) - 1
            api_key = keys[ki]
            key_label = "Key-{}".format(ki + 1)
        except Exception:
            api_key   = keys[0]
            key_label = "Key-1"

        self.search_btn.config(state='disabled', text="搜索中...")
        self.status_var.set("")
        clear_log(self.log_w)
        for w in self.src_frame.winfo_children():
            w.destroy()
        self.src_status.set("搜索中...")

        cfg = self._get_cfg()
        # 取类别（如果开关打开）
        category = self.category_var.get().strip() if self.use_category_var.get() else ""

        def _run():
            def on_log(msg, tag='dim'):
                state.log_queue.put((self.log_w, msg, tag))

            cat_str = "  📌 {}".format(category) if category else ""
            on_log("[ {} ] 开始搜索: {} ({}){}".format(
                key_label, name, code, cat_str), 'accent')
            t0 = time.time()
            result, ok, sources = api_client.call_qianfan(
                name, code, api_key, cfg, on_log=on_log, category=category)
            elapsed = time.time() - t0
            on_log("耗时: {:.1f}s".format(elapsed), 'dim')
            on_log("─" * 50, 'dim')
            on_log(result, 'ok' if ok else 'fail')

            # 保存历史 + 学习名称
            try:
                hist_mod.save_history(name, code, result, success=ok)
                if ok:
                    cfg_mod.learn_stocks([(name, code)])
                bus.emit(Events.HISTORY_UPDATED)
            except Exception:
                pass

            def _ui():
                self.search_btn.config(state='normal', text="🔍  开始搜索")
                self.status_var.set(
                    "✅ 成功 | {}字 | {:.1f}s".format(len(result), elapsed) if ok
                    else "❌ 失败 | {:.1f}s".format(elapsed))
                self._render_sources(sources)
                if ok:
                    apply_highlight(self.log_w)
                # 🆕 v9.9.6：日志里所有 6 位代码渲染为蓝字下划线 → 点击推送同花顺
                try:
                    from ..widgets import attach_code_links
                    attach_code_links(self.log_w, self.app, main_code=code, scope='main')
                except Exception:
                    import traceback; traceback.print_exc()
            state.ui_queue.put(_ui)

        threading.Thread(target=_run, daemon=True).start()

    def _render_sources(self, sources):
        C = self.C
        for w in self.src_frame.winfo_children():
            w.destroy()
        self.src_status.set("共找到 {} 个数据源".format(len(sources)))
        colors = [C['accent'], C['green'], C['yellow'], C['purple'],
                  C['red'], '#ff9a3c', '#3cddc8']
        for i, src in enumerate(sources[:12]):
            col = colors[i % len(colors)]
            row = tk.Frame(self.src_frame, bg=C['card'],
                           highlightbackground=col, highlightthickness=1)
            row.pack(fill='x', pady=2)
            tk.Label(row, text="●", font=('Arial', 8),
                     bg=C['card'], fg=col).pack(side='left', padx=(5, 2), pady=3)
            title = src.get("title", "")[:38]
            tk.Label(row, text=title, font=('微软雅黑', 7),
                     bg=C['card'], fg=C['text'], anchor='w').pack(side='left',
                     fill='x', expand=True, padx=(0, 4))

    # ── 字号 ───────────────────────────────────
    def _font_up(self):
        cur = self.font_size.get()
        if cur < 24:
            self.font_size.set(cur + 1)
            self.log_w.config(font=('微软雅黑', cur + 1))

    def _font_down(self):
        cur = self.font_size.get()
        if cur > 6:
            self.font_size.set(cur - 1)
            self.log_w.config(font=('微软雅黑', cur - 1))

    # ── 复制/导出 ─────────────────────────────
    def _copy(self):
        txt = self.log_w.get('1.0', 'end').strip()
        if txt:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(txt)
            messagebox.showinfo("已复制", "结果已复制到剪贴板")

    def _to_wechat(self):
        content = self.log_w.get('1.0', 'end').strip()
        if not content:
            messagebox.showinfo("提示", "没有可转换的内容")
            return
        wx = text_utils.to_wechat_format(
            self.name_var.get().strip() or "?",
            self.code_var.get().strip() or "?",
            content)
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(wx)
        messagebox.showinfo("微信格式已复制", wx[:300] + ("..." if len(wx) > 300 else ""))

    def _export_html(self):
        content = self.log_w.get('1.0', 'end').strip()
        if not content:
            messagebox.showinfo("提示", "没有可导出的内容")
            return
        records = [{
            "name":    self.name_var.get().strip() or "未命名",
            "code":    self.code_var.get().strip() or "",
            "content": content,
            "success": True,
        }]
        try:
            fn = reports.export_html_report(records, title="单股分析报告")
            messagebox.showinfo("导出成功", "HTML 已生成:\n" + fn)
        except Exception as e:
            messagebox.showerror("失败", str(e))

    def _get_cfg(self):
        return dict(self.app.cfg)

    def trigger_search(self):
        """被外部（如快捷键）调用"""
        self._search()
