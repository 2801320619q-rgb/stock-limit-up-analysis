"""
批量分析 Tab
- 支持多 Key 多线程
- Key 状态卡监听 API_KEYS_CHANGED 事件，动态刷新
- 支持自选股/雷达请求自动启动批量
"""
import os, queue, threading, time, signal
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import pandas as pd
import re

from .base import BaseTab
from ..widgets import make_card, styled_btn, styled_entry, make_log_widget, write_log, clear_log
from ..core import api_client, config as cfg_mod, history as hist_mod, reports
from ..core.paths import DIRS
from ..bus import bus, Events, state


def _read_stock_data(file_path):
    """读取 Excel，必须含【股票名称】【股票代码】，可选【涨停类别】"""
    df = pd.read_excel(file_path)
    cols = [c.strip() for c in df.columns]
    found = {}
    # 必填列
    for req in ['股票名称', '股票代码']:
        for c in cols:
            if req in c or c in req:
                found[req] = c
                break
    if len(found) < 2:
        raise ValueError("缺少列: {}".format(
            [r for r in ['股票名称','股票代码'] if r not in found]))
    # 可选列：涨停类别
    category_col = None
    for c in cols:
        # 匹配各种变体：涨停类别 / 类别 / 标签 / 板块 / 概念
        if any(kw in c for kw in ['涨停类别', '类别', '细分标签', '板块标签']):
            category_col = c
            break

    rename_map = {found[r]: r for r in found if found[r] != r}
    if category_col and category_col != '涨停类别':
        rename_map[category_col] = '涨停类别'
    if rename_map:
        df = df.rename(columns=rename_map)

    df['股票名称'] = df['股票名称'].astype(str).str.strip().str.replace('*','',regex=False)
    df['股票代码'] = df['股票代码'].astype(str).str.strip().str.replace(r'\D','',regex=True).str.zfill(6).str[:6]
    if '涨停类别' in df.columns:
        df['涨停类别'] = df['涨停类别'].fillna('').astype(str).str.strip()
    else:
        df['涨停类别'] = ''  # 没有该列就填空
    df = df.drop_duplicates(subset=['股票代码'], keep='first').reset_index(drop=True)
    return df


class BatchTab(BaseTab):
    title = "批量分析"

    def __init__(self, app):
        super().__init__(app)
        self.running = False

    def build(self, parent):
        C = self.C
        body = tk.Frame(parent, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=12, pady=10)

        left = tk.Frame(body, bg=C['bg'], width=300)
        left.pack(side='left', fill='y', padx=(0, 10))
        left.pack_propagate(False)
        right = tk.Frame(body, bg=C['bg'])
        right.pack(side='left', fill='both', expand=True)

        # 文件选择
        fc = make_card(left, "📁  输入文件", pady_top=0)
        fr = tk.Frame(fc, bg=C['panel']); fr.pack(fill='x')
        self.file_var = tk.StringVar(value="未选择文件")
        tk.Label(fr, textvariable=self.file_var, font=('微软雅黑', 8),
                 bg=C['card'], fg=C['dim'], anchor='w',
                 padx=6).pack(side='left', fill='x', expand=True, ipady=6)
        styled_btn(fr, "浏览", C['accent'], self._browse).pack(side='right', padx=(4, 0))

        # 参数
        pc = make_card(left, "⚙️  请求参数")
        self.params = {}
        for lbl, key, default in [
            ("延迟(秒)",     "request_delay", self.app.cfg.get("request_delay", 2)),
            ("超时(秒)",     "timeout",        self.app.cfg.get("timeout", 120)),
            ("最大Token",   "max_tokens",     self.app.cfg.get("max_tokens", 2500)),
            ("Temperature", "temperature",    self.app.cfg.get("temperature", 0.2)),
        ]:
            row = tk.Frame(pc, bg=C['panel']); row.pack(fill='x', pady=2)
            tk.Label(row, text=lbl, font=('微软雅黑', 8),
                     bg=C['panel'], fg=C['dim'], width=13, anchor='w').pack(side='left')
            v = tk.StringVar(value=str(default))
            self.params[key] = v
            styled_entry(row, v, 10).pack(side='right', ipady=3)

        # 🆕 开关：使用涨停类别 / 详细日志
        sc = make_card(left, "🔧  高级开关")
        self._use_category_var = tk.BooleanVar(value=True)
        tk.Checkbutton(sc, text="📌 把【涨停类别】列作为 AI 提示词上下文",
                       variable=self._use_category_var,
                       font=('微软雅黑', 8), bg=C['panel'], fg=C['text'],
                       selectcolor=C['card'], activebackground=C['panel'],
                       anchor='w').pack(fill='x', anchor='w')
        tk.Label(sc, text="   AI 会结合该类别深度分析，命中率更高",
                 font=('微软雅黑', 7), bg=C['panel'], fg=C['dim']).pack(anchor='w', padx=(20,0))

        self._verbose_batch_var = tk.BooleanVar(value=True)
        tk.Checkbutton(sc, text="📋 显示详细日志（HTTP/字数/数据源数）",
                       variable=self._verbose_batch_var,
                       font=('微软雅黑', 8), bg=C['panel'], fg=C['text'],
                       selectcolor=C['card'], activebackground=C['panel'],
                       anchor='w').pack(fill='x', anchor='w', pady=(4,0))

        # Key 状态卡
        kc = make_card(left, "🔑  Key 实时状态")
        self.key_card_container = kc
        self.key_ui = {}
        self._rebuild_keys()

        # 操作按钮
        bc = make_card(left, "🚀  操作")
        self.btn_start = styled_btn(bc, "▶  开始批量分析", C['green'], self._start, pady=9)
        self.btn_start.pack(fill='x', pady=(0, 4))
        self.btn_pause = styled_btn(bc, "⏸  暂停", C['yellow'], self._toggle_pause, pady=9)
        self.btn_pause.pack(fill='x', pady=(0, 4))
        self.btn_pause.config(state='disabled')
        self.btn_stop = styled_btn(bc, "⏹  停止", C['red'], self._stop, pady=9)
        self.btn_stop.pack(fill='x')
        self.btn_stop.config(state='disabled')

        # 右侧：统计 + 进度 + 日志
        sr = tk.Frame(right, bg=C['bg']); sr.pack(fill='x', pady=(0, 8))
        self.sv = {}
        for lbl, key, col in [("总计","total",C['accent']),("成功","ok",C['green']),
                                ("失败","fail",C['red']),("进度","pct",C['yellow'])]:
            c = tk.Frame(sr, bg=C['panel'],
                         highlightbackground=C['border'], highlightthickness=1)
            c.pack(side='left', fill='both', expand=True, padx=(0, 6))
            tk.Label(c, text=lbl, font=('微软雅黑', 8),
                     bg=C['panel'], fg=C['dim']).pack(pady=(8, 2))
            v = tk.StringVar(value="0")
            self.sv[key] = v
            tk.Label(c, textvariable=v, font=('微软雅黑', 18, 'bold'),
                     bg=C['panel'], fg=col).pack(pady=(0, 8))

        style = ttk.Style()
        style.theme_use('default')
        style.configure('Batch.Horizontal.TProgressbar',
                        troughcolor=C['card'], background=C['accent'], thickness=14)
        self.progress = ttk.Progressbar(right, mode='determinate',
                                         style='Batch.Horizontal.TProgressbar')
        self.progress.pack(fill='x', pady=(0, 8))

        lhdr = tk.Frame(right, bg=C['panel'],
                        highlightbackground=C['border'], highlightthickness=1)
        lhdr.pack(fill='x')
        tk.Label(lhdr, text="📋  运行日志", font=('微软雅黑', 9, 'bold'),
                 bg=C['panel'], fg=C['accent']).pack(side='left', padx=12, pady=6)
        tk.Button(lhdr, text="清空", font=('微软雅黑', 8),
                  bg=C['border'], fg=C['dim'], relief='flat', cursor='hand2',
                  command=lambda: clear_log(self.log_w)).pack(side='right', padx=8, pady=4)

        self.log_w = make_log_widget(right, font_size=9)

        # 订阅事件
        bus.on(Events.API_KEYS_CHANGED, lambda *a: self._rebuild_keys())
        bus.on(Events.REQUEST_BATCH_RUN, self._handle_run_request)

    # ── Key 状态卡动态重建 ─────────────────────
    def _rebuild_keys(self):
        C = self.C
        for w in self.key_card_container.winfo_children():
            w.destroy()
        self.key_ui = {}
        keys = self.app.cfg.get("api_keys", [])
        for i, k in enumerate(keys):
            if not k.strip():
                continue
            lbl = "Key-{}".format(i + 1)
            row = tk.Frame(self.key_card_container, bg=C['card'],
                           highlightbackground=C['border'], highlightthickness=1)
            row.pack(fill='x', pady=2)
            dot = tk.Label(row, text="●", font=('Arial', 10),
                           bg=C['card'], fg=C['idle'])
            dot.pack(side='left', padx=(6, 3), pady=4)
            tk.Label(row, text=lbl, font=('微软雅黑', 8, 'bold'),
                     bg=C['card'], fg=C['text'], width=6, anchor='w').pack(side='left')
            stk = tk.Label(row, text="待机", font=('微软雅黑', 8),
                           bg=C['card'], fg=C['dim'], anchor='w')
            stk.pack(side='left', fill='x', expand=True, padx=4)
            self.key_ui[lbl] = {'dot': dot, 'stock': stk}

    def _set_key(self, label, st, stock=''):
        C = self.C
        col_map  = {'idle':C['idle'],'running':C['accent'],'ok':C['green'],'fail':C['red']}
        text_map = {'idle':'待机','running':stock,'ok':'✓ '+stock,'fail':'✗ '+stock}
        def _upd():
            ui = self.key_ui.get(label)
            if ui:
                ui['dot'].config(fg=col_map.get(st, C['idle']))
                ui['stock'].config(text=text_map.get(st, ''), fg=col_map.get(st, C['idle']))
        state.ui_queue.put(_upd)

    # ── 文件浏览 ───────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(
            title="选择输入文件",
            filetypes=[("Excel", "*.xlsx *.xls"), ("所有", "*.*")])
        if p:
            self.file_var.set(os.path.basename(p))
            self.input_file = p

    # ── 接受其他Tab的请求 ─────────────────────
    def _handle_run_request(self, stocks, source):
        """
        自选股/雷达/板块/历史 Tab 发起的批量分析请求
        stocks 可以是：
          [(name, code), ...]              → 无类别
          [(name, code, category), ...]    → 含类别
        """
        if self.running:
            messagebox.showwarning("提示", "当前已有任务运行中")
            return
        # 兼容两种格式
        normalized = []
        for s in stocks:
            if len(s) >= 3:
                normalized.append((s[0], s[1], s[2]))
            else:
                normalized.append((s[0], s[1], ""))
        df = pd.DataFrame(normalized, columns=['股票名称', '股票代码', '涨停类别'])
        tmp_path = DIRS["temp"] / "_tmp_{}_{}.xlsx".format(
            source, datetime.now().strftime('%H%M%S'))
        df.to_excel(tmp_path, index=False)
        self.input_file = str(tmp_path)
        self.file_var.set("({}) {} 只".format(source, len(stocks)))
        self.app.nb.select(0)
        self._start()

    # ── 暂停/停止 ─────────────────────────────
    def _toggle_pause(self):
        if state.paused.is_set():
            state.paused.clear()
            self.btn_pause.config(text="⏸  暂停")
            write_log(self.log_w, "▶▶  继续运行...", 'ok')
        else:
            state.paused.set()
            self.btn_pause.config(text="▶  继续")
            write_log(self.log_w, "⏸  已暂停", 'yellow')

    def _stop(self):
        if messagebox.askyesno("确认停止", "停止分析？已完成的结果已保存"):
            state.shutdown.set()
            state.paused.clear()

    # ── 启动批量分析 ──────────────────────────
    def _start(self):
        if not hasattr(self, 'input_file') or not self.input_file:
            messagebox.showwarning("提示", "请先选择输入文件")
            return
        if not os.path.exists(self.input_file):
            messagebox.showerror("错误", "文件不存在")
            return

        state.shutdown.clear()
        state.paused.clear()
        state.failed_stocks = []
        self.running = True

        self.btn_start.config(state='disabled')
        self.btn_pause.config(state='normal', text="⏸  暂停")
        self.btn_stop.config(state='normal')

        write_log(self.log_w, "=" * 52, 'dim')
        write_log(self.log_w, "🚀  开始分析: " + os.path.basename(self.input_file), 'accent')

        cfg = self._get_cfg()
        threading.Thread(target=self._run, args=(cfg,),
                         daemon=True, name="BatchMain").start()

    def _get_cfg(self):
        cfg = dict(self.app.cfg)
        try:
            cfg["request_delay"] = float(self.params["request_delay"].get())
            cfg["timeout"]       = int(self.params["timeout"].get())
            cfg["max_tokens"]    = int(self.params["max_tokens"].get())
            cfg["temperature"]   = float(self.params["temperature"].get())
        except Exception:
            pass
        # 高级开关
        cfg["use_category"]  = self._use_category_var.get()
        cfg["verbose_batch"] = self._verbose_batch_var.get()
        return cfg

    def _run(self, cfg):
        try:
            df = _read_stock_data(self.input_file)
        except Exception as e:
            state.log_queue.put((self.log_w, "❌ 读取失败: " + str(e), 'fail'))
            state.ui_queue.put(self._on_complete)
            return

        total = len(df)
        state.log_queue.put((self.log_w, "📊 共 {} 只股票".format(total), 'info'))
        # 显示是否使用涨停类别
        has_category = '涨停类别' in df.columns and df['涨停类别'].str.len().sum() > 0
        if has_category:
            cat_count = (df['涨停类别'].str.len() > 0).sum()
            if cfg.get("use_category", True):
                state.log_queue.put((self.log_w,
                    "📌 检测到「涨停类别」列  {}只有标签 → 已启用上下文增强".format(cat_count), 'purple'))
            else:
                state.log_queue.put((self.log_w,
                    "📌 检测到「涨停类别」列但开关已关闭，将忽略此列", 'dim'))

        def _init_stats():
            self.sv['total'].set(str(total))
            self.sv['ok'].set("0"); self.sv['fail'].set("0"); self.sv['pct'].set("0%")
            self.progress.config(maximum=total, value=0)
        state.ui_queue.put(_init_stats)

        now = datetime.now()
        output_file = DIRS["output"] / "{}_{}.xlsx".format(
            cfg["output_prefix"], now.strftime('%Y%m%d_%H%M%S'))
        df['上涨原因分析'] = ''

        keys = [k for k in cfg.get("api_keys", []) if k.strip()]
        if not keys:
            state.log_queue.put((self.log_w, "❌ 没有可用 API Key", 'fail'))
            state.ui_queue.put(self._on_complete)
            return

        task_q = queue.Queue()
        for idx, row in df.iterrows():
            category = row.get('涨停类别', '') if '涨停类别' in df.columns else ''
            task_q.put((idx, row['股票名称'], row['股票代码'], category))

        counter  = [0]
        ok_cnt   = [0]
        fail_cnt = [0]

        def _worker(api_key, key_label):
            while not state.shutdown.is_set():
                if state.paused.is_set():
                    self._set_key(key_label, 'idle', '已暂停')
                    while state.paused.is_set() and not state.shutdown.is_set():
                        time.sleep(0.3)
                    if state.shutdown.is_set(): break
                    self._set_key(key_label, 'idle')
                try:
                    idx, sname, scode, category = task_q.get(timeout=2)
                except queue.Empty:
                    break

                self._set_key(key_label, 'running', "{} ({})".format(sname, scode))
                # 富日志：显示类别
                category_str = "  📌 {}".format(category) if category else ""
                state.log_queue.put((self.log_w,
                    "[{}] 🔍 ({}/{}) {} ({}){}".format(
                        key_label, counter[0]+1, total, sname, scode, category_str), 'accent'))

                # 用类别感知的 prompt 调用 AI
                t0 = time.time()
                # 局部日志：写入 batch 日志
                def _on_log(msg, tag='dim'):
                    state.log_queue.put((self.log_w,
                        "  [{}] {}".format(key_label, msg), tag))
                result, ok, sources = api_client.call_qianfan(
                    sname, scode, api_key, cfg,
                    on_log=_on_log if cfg.get("verbose_batch", True) else None,
                    category=category)
                elapsed = time.time() - t0
                src_n = len(sources)

                with state.save_lock:
                    df.at[idx, '上涨原因分析'] = result
                    counter[0] += 1
                    done = counter[0]
                    if ok:
                        ok_cnt[0] += 1
                    else:
                        fail_cnt[0] += 1
                        state.failed_stocks.append((sname, scode))
                    # 🛡️ 间隔写盘（每 10 只 / 末尾兜底）：避免每次都全量重写 xlsx 阻塞 worker
                    #    跑批中实时持久化走 CSV（快），xlsx 仅周期性写一次
                    try:
                        csv_path = output_file.with_suffix(".csv")
                        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                    except Exception:
                        pass
                    if done % 10 == 0 or done == total:
                        try:
                            df.to_excel(output_file, index=False)
                        except Exception:
                            pass
                    try:
                        hist_mod.save_history(sname, scode, result, success=ok, category=category)
                        if ok:
                            cfg_mod.learn_stocks([(sname, scode)])
                    except Exception:
                        pass

                self._set_key(key_label, 'ok' if ok else 'fail',
                              "{} ({})".format(sname, scode))
                icon = '✅' if ok else '❌'
                tag  = 'ok' if ok else 'fail'
                state.log_queue.put((self.log_w,
                    "[{}] {} {} ({}) | {}字 | 数据源 {} | 耗时 {:.1f}s | {}/{}".format(
                        key_label, icon, sname, scode,
                        len(result), src_n, elapsed, done, total), tag))

                _ok, _fail = ok_cnt[0], fail_cnt[0]
                def _upd_stats(d=done, o=_ok, f=_fail, t=total):
                    self.sv['ok'].set(str(o))
                    self.sv['fail'].set(str(f))
                    self.sv['pct'].set("{}%".format(int(d/t*100)))
                    self.progress.config(value=d)
                state.ui_queue.put(_upd_stats)

                task_q.task_done()
                if not state.shutdown.is_set():
                    time.sleep(cfg["request_delay"])

        threads = []
        for i, key in enumerate(keys):
            lbl = "Key-{}".format(i + 1)
            t = threading.Thread(target=_worker, args=(key, lbl),
                                 daemon=True, name=lbl)
            threads.append(t)
            t.start()

        task_q.join()

        # 备份
        backup = DIRS["backup"] / "{}_{}.xlsx".format(
            cfg["output_prefix"], now.strftime('%Y%m%d_%H%M%S'))
        df.to_excel(backup, index=False)
        state.last_batch_df = df
        state.last_output = str(output_file)

        try:
            cfg_mod.learn_stocks([(r['股票名称'], r['股票代码']) for _, r in df.iterrows()])
        except Exception:
            pass

        state.log_queue.put((self.log_w, "=" * 52, 'dim'))
        state.log_queue.put((self.log_w,
            "🎉  完成！✅{} ❌{}  输出: {}".format(
                ok_cnt[0], fail_cnt[0], output_file.name), 'ok'))
        bus.emit(Events.HISTORY_UPDATED)
        state.ui_queue.put(self._on_complete)
        _ok, _fail, _path = ok_cnt[0], fail_cnt[0], str(output_file)
        state.ui_queue.put(lambda: self._show_complete_dialog(_ok, _fail, _path))

    def _on_complete(self):
        self.running = False
        self.btn_start.config(state='normal')
        self.btn_pause.config(state='disabled')
        self.btn_stop.config(state='disabled')
        for lbl in self.key_ui:
            self._set_key(lbl, 'idle')
        # 🆕 v9.9.6：批量日志里所有 6 位代码加蓝字下划线 → 推送同花顺
        try:
            from ..widgets import attach_code_links
            attach_code_links(self.log_w, self.app, scope='main')
        except Exception:
            import traceback; traceback.print_exc()

    def _show_complete_dialog(self, ok, fail, output_file):
        C = self.C
        dlg = tk.Toplevel(self.app.root)
        dlg.title("✅ 分析完成")
        dlg.geometry("440x300")
        dlg.configure(bg=C['bg'])
        dlg.transient(self.app.root)
        dlg.resizable(False, False)

        tk.Label(dlg, text="✅  分析完成", font=('微软雅黑', 14, 'bold'),
                 bg=C['bg'], fg=C['green']).pack(pady=(20, 8))
        tk.Label(dlg, text="成功: {} 只     失败: {} 只".format(ok, fail),
                 font=('微软雅黑', 10), bg=C['bg'], fg=C['text']).pack(pady=(0, 8))
        tk.Label(dlg, text="输出: " + os.path.basename(output_file),
                 font=('微软雅黑', 9), bg=C['bg'], fg=C['dim']).pack(pady=(0, 16))

        btn_frame = tk.Frame(dlg, bg=C['bg']); btn_frame.pack(pady=10)

        def _html():
            if state.last_batch_df is not None:
                records = []
                for _, row in state.last_batch_df.iterrows():
                    c = str(row.get('上涨原因分析', ''))
                    records.append({
                        "name":    row['股票名称'],
                        "code":    row['股票代码'],
                        "content": c,
                        "success": not c.startswith(('❌', '⚠️')),
                    })
                try:
                    fn = reports.export_html_report(records)
                    messagebox.showinfo("导出成功", "已生成: " + fn)
                except Exception as e:
                    messagebox.showerror("失败", str(e))

        def _retry():
            if not state.failed_stocks:
                messagebox.showinfo("提示", "没有失败记录")
                return
            stocks = list(state.failed_stocks)
            dlg.destroy()
            self._handle_run_request(stocks, "失败重试")

        def _open():
            try:
                import sys
                folder = os.path.dirname(os.path.abspath(output_file)) or "."
                if sys.platform.startswith('win'):
                    os.startfile(folder)
                elif sys.platform == 'darwin':
                    os.system('open "{}"'.format(folder))
                else:
                    os.system('xdg-open "{}"'.format(folder))
            except Exception as e:
                messagebox.showerror("失败", str(e))

        styled_btn(btn_frame, "📄 导出HTML", C['accent'], _html, pady=8).pack(side='left', padx=4)
        if fail > 0:
            styled_btn(btn_frame, "🔄 重试失败({}只)".format(fail), C['yellow'],
                       _retry, pady=8).pack(side='left', padx=4)
        styled_btn(btn_frame, "📁 打开目录", C['idle'], _open, pady=8).pack(side='left', padx=4)

        tk.Button(dlg, text="关闭", font=('微软雅黑', 9),
                  bg=C['border'], fg=C['text'], relief='flat',
                  command=dlg.destroy, padx=20, pady=6).pack(pady=(16, 0))
