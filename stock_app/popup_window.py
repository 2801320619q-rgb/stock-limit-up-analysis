"""
浮窗 - 主程序内嵌版本 (v9.9.6.2)

v9.9.6.2 变化：
  • 修复浮窗内点蓝字会让浮窗自己刷新的问题（双层防御：global push_silencer 10s
    + 浮窗本地 _popup_locked 10s）
  • 加 Ctrl+Z 回退上一只浮窗显示过的股 + 同花顺也跟着回退
  • 加 F1 隐藏/显示浮窗
  • 两个快捷键支持设置里自定义
"""
import threading
import time
import traceback

import tkinter as tk
from tkinter import ttk

from .core import api_client, history as hist_mod
from .core import config as cfg_mod
from .core.theme import get as theme
from .core import hexin_bridge as hexin
from .widgets import apply_highlight, attach_code_links


# ════════════════════════════════════════════════
# 同花顺监听薄封装
# ════════════════════════════════════════════════
def _start_hexin_watcher(on_stock_change, get_follow_mode, on_status=None):
    try:
        s = cfg_mod.load_settings()
    except Exception:
        s = {}
    if not s.get("hexin_watcher_enabled", True):
        if on_status:
            try: on_status("⏸️ 设置中已关闭监听")
            except Exception: pass
        return None
    w = hexin.HexinReadWatcher(
        on_change=on_stock_change,
        on_status=on_status,
        enabled_fn=get_follow_mode,
        settings=s,
    )
    w.start()
    return w


# ════════════════════════════════════════════════
# 浮窗 UI - 主程序内嵌
# ════════════════════════════════════════════════
class PopupWindow:
    def __init__(self, app):
        self.app = app
        self.root = tk.Toplevel(app.root)
        self.root.withdraw()
        self.root.title("📊 股票浮窗")
        self.C = theme()

        # 状态
        self._cur_code = None
        self._cur_name = None
        self._records = []
        self._drag_data = {"x": 0, "y": 0}
        self._resize_data = {"x": 0, "y": 0, "w": 0, "h": 0}
        self._MIN_W = 380
        self._MIN_H = 320

        # 🔁 v9.9.6：只剩一个 follow 开关（📥 跟随同花顺）
        # 旧的 _push_mode / _main_link_mode 整套已移除
        try:
            self._settings = cfg_mod.load_settings()
        except Exception:
            self._settings = {}
        legacy_follow = self._settings.get("popup_follow_mode")
        self._follow_mode = bool(self._settings.get("popup_follow_hexin",
                                        True if legacy_follow is None else legacy_follow))

        self._hexin_status = "⏳ 同花顺联动: 启动中..."
        self._hexin_event_count = 0
        self._hexin_watcher = None

        # 🆕 v9.9.6.2：浮窗本地代码 lock（防 watcher 把"自己刚推的代码"绕回来）
        # key: 6 位代码字符串，value: 过期时间戳
        # 跟全局 _push_silencer 是双保险——10 秒内 watcher 读到这个 code 浮窗不刷新
        self._popup_locked = {}

        # 🆕 v9.9.6.2：浮窗显示历史栈，支持 Ctrl+Z 回到上一只
        # 每个元素 (code, name)
        self._show_history = []
        self._undoing = False  # undo 触发的 show 不能再 push 回 history（防死循环）

        # 🆕 v9.9.6.5：最小化状态
        # 浮窗是 overrideredirect 窗口，没法扔到 Windows 任务栏，所以"最小化"
        # 是在程序内把窗口折叠成只剩标题栏 32px 高度
        self._minimized = False
        self._geo_before_min = None  # 最小化前的 geometry，复原用

        self._build_window()
        try:
            self.root.protocol("WM_DELETE_WINDOW", self.hide)
        except Exception:
            pass
        # 同花顺监听
        self._hexin_watcher = _start_hexin_watcher(
            self._on_hexin_stock,
            lambda: self._follow_mode,
            on_status=self._on_hexin_status)

        self.root.deiconify()
        self.root.update()

    # ════════════════════════════════════════════════
    # 公有 API
    # ════════════════════════════════════════════════
    def lock_code(self, code, ttl=10.0):
        """
        🆕 v9.9.6.2：标记 "这个 code 是浮窗自己主动推的，不要在 watcher
        读到时刷新浮窗"。是 hexin_bridge.push_silencer 之外的二级保险，
        因为有些同花顺切换比较慢（>3s），全局 silencer 可能已过期。
        """
        if not code:
            return
        try:
            self._popup_locked[str(code).zfill(6)] = time.time() + ttl
        except Exception:
            pass

    def _is_locked(self, code):
        if not code:
            return False
        code6 = str(code).zfill(6)
        exp = self._popup_locked.get(code6)
        if exp is None:
            return False
        if time.time() > exp:
            try: del self._popup_locked[code6]
            except KeyError: pass
            return False
        return True

    def toggle_visibility(self):
        """🆕 v9.9.6.2：F1 切换浮窗显示/隐藏"""
        try:
            # overrideredirect 窗口用 winfo_viewable 判断比 state 可靠
            if not self.root.winfo_viewable():
                self.root.deiconify()
                try:
                    self.root.lift()
                    self.root.attributes('-topmost', True)
                except Exception:
                    pass
            else:
                self.hide()
        except Exception:
            traceback.print_exc()

    def toggle_minimize(self):
        """
        🆕 v9.9.6.5：浮窗最小化（折叠成只剩标题栏）
        由于浮窗是 overrideredirect 无边框窗口，没法扔到 Windows 任务栏，
        所以"最小化"在程序内实现：把非标题栏的所有容器 pack_forget，
        窗口高度调到标题栏的 32px。再点一次按钮（变成 □ 复原）就还原。

        最小化后窗口本身仍可拖动（标题栏拖动逻辑不依赖其它容器），
        点 ✕ 仍可关闭/隐藏。
        """
        try:
            if not self._minimized:
                self._do_minimize()
            else:
                self._do_restore()
        except Exception:
            traceback.print_exc()

    def _do_minimize(self):
        """折叠成只剩标题栏 32px"""
        # 1. 记录当前几何尺寸供复原
        try:
            self._geo_before_min = self.root.geometry()
        except Exception:
            self._geo_before_min = None
        # 2. 把 4 个顶级容器 pack_forget
        for w in (self._summary_frame, self._detail_wrap,
                  self._bottom_frame, self._status_bar):
            try:
                w.pack_forget()
            except Exception:
                pass
        # 右下角 grip 也藏起来
        try:
            self._grip.place_forget()
        except Exception:
            pass
        # 3. 调整窗口高度到只剩标题栏（32px）
        try:
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            w_now = self.root.winfo_width()
            self.root.geometry("{}x{}+{}+{}".format(w_now, 32, x, y))
        except Exception:
            pass
        # 4. 按钮换图标，文字微调
        self._minimized = True
        try:
            self._btn_min.config(text=" □ ")
        except Exception:
            pass
        try:
            self._hexin_status_var.set("📐 浮窗已最小化（点 □ 复原）")
        except Exception:
            pass

    def _do_restore(self):
        """从最小化状态复原"""
        # 1. 恢复 4 个顶级容器（按原 pack 参数）
        try:
            self._summary_frame.pack(fill='x', side='top', padx=8, pady=(8, 0))
        except Exception: pass
        try:
            # status_bar 与 bottom 都 side=bottom；要保证 status_bar 在 bottom 下面，
            # 先 pack status_bar，再 pack bottom（side=bottom 是栈底优先，先 pack 的更靠下）
            # 但实际看 _build_window 是先 pack bottom 再 pack status_bar——
            # 我们这里反过来：先 status_bar 后 bottom（status_bar 在更下面）
            # 注意 build_window 里也是先 bottom 后 status_bar，所以我们也保持一致
            self._bottom_frame.pack(fill='x', side='bottom')
        except Exception: pass
        try:
            self._status_bar.pack(fill='x', side='bottom')
        except Exception: pass
        try:
            self._detail_wrap.pack(fill='both', expand=True, padx=8, pady=8)
        except Exception: pass
        try:
            self._grip.place(relx=1.0, rely=1.0, anchor='se')
        except Exception: pass
        # 2. 恢复几何尺寸
        if self._geo_before_min:
            try:
                self.root.geometry(self._geo_before_min)
            except Exception:
                pass
            self._geo_before_min = None
        # 3. 按钮还原
        self._minimized = False
        try:
            self._btn_min.config(text=" ─ ")
        except Exception:
            pass
        try:
            self._hexin_status_var.set("📐 浮窗已复原")
        except Exception:
            pass

    def undo(self):
        """🆕 v9.9.6.2：Ctrl+Z 回退到上一只浮窗显示过的股，同花顺也跟着回退"""
        if not self._show_history:
            self._hexin_status_var.set("⏪ 无可回退的历史")
            return
        prev_code, prev_name = self._show_history.pop()
        self._undoing = True
        try:
            # 同花顺也跟着回退到这只股
            try:
                ok, reason = hexin.push_code_to_hexin(prev_code)
                # 推送成功的话会自动 mark 全局 silencer；这里再加浮窗本地 lock
                self.lock_code(prev_code)
            except Exception:
                traceback.print_exc()
            # 浮窗自己也切到这只股
            self.show(prev_code, prev_name)
            self._hexin_status_var.set(
                "⏪ 已回退到 {} ({})".format(prev_name or "?", prev_code))
        finally:
            self._undoing = False

    def notify_main_click(self, code, name=None):
        """
        🔁 v9.9.6：主程序里任何"看了一眼这只股"的动作（选中行 / 鼠标点击）
        都让浮窗刷新。不再需要 main_link 开关——浮窗就该跟随主程序。
        """
        if not code:
            return
        self.show(code, name)

    def push_to_hexin(self, code, name=None):
        """老 API 兼容：显式推送一只股票（不刷新浮窗）"""
        try:
            ok, reason = hexin.push_code_to_hexin(str(code or "").zfill(6))
            self._update_push_status(ok, reason, code)
        except Exception:
            traceback.print_exc()

    def is_follow_mode(self):
        """兼容旧 API"""
        return self._follow_mode

    def follow(self, code, name=None):
        """兼容旧 API：等价于 notify_main_click"""
        self.notify_main_click(code, name)

    def restart_hexin_watcher(self):
        """设置变更后用新参数重启同花顺监听"""
        try:
            if self._hexin_watcher:
                try: self._hexin_watcher.stop()
                except Exception: pass
        except Exception:
            pass
        self._hexin_watcher = _start_hexin_watcher(
            self._on_hexin_stock,
            lambda: self._follow_mode,
            on_status=self._on_hexin_status)
        self._hexin_status = "🔄 同花顺监听已重启"
        try: self._hexin_status_var.set(self._hexin_status)
        except Exception: pass

    def hide(self):
        try: self.root.withdraw()
        except Exception: pass

    def destroy(self):
        try:
            if self._hexin_watcher:
                try: self._hexin_watcher.stop()
                except Exception: pass
            self._hexin_watcher = None
        except Exception: pass
        try: self.root.destroy()
        except Exception: pass

    # ════════════════════════════════════════════════
    # 窗体构建
    # ════════════════════════════════════════════════
    def _build_window(self):
        C = self.C
        w = self.root
        saved_geo = self._settings.get("popup_geometry", "600x700+200+120")
        w.geometry(saved_geo)
        w.minsize(self._MIN_W, self._MIN_H)
        w.configure(bg=C['bg'])
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        # 周期重申 topmost
        def _keep_top():
            try:
                w.attributes('-topmost', True)
                w.after(2000, _keep_top)
            except tk.TclError: pass
        w.after(2000, _keep_top)

        # 标题栏
        title_bar = tk.Frame(w, bg=C['acc_dark'], height=32)
        title_bar.pack(fill='x', side='top')
        title_bar.pack_propagate(False)
        self._title_label = tk.Label(title_bar, text="📊  股票详情",
                                      font=('微软雅黑', 10, 'bold'),
                                      bg=C['acc_dark'], fg='white')
        self._title_label.pack(side='left', padx=10)

        # ✕ 关闭
        btn_close = tk.Label(title_bar, text=" ✕ ",
                              font=('微软雅黑', 11, 'bold'),
                              bg=C['acc_dark'], fg='white',
                              cursor='hand2', padx=8)
        btn_close.pack(side='right')
        btn_close.bind('<Button-1>', lambda e: self.hide())
        btn_close.bind('<Enter>', lambda e: btn_close.config(bg=C['red']))
        btn_close.bind('<Leave>', lambda e: btn_close.config(bg=C['acc_dark']))

        # 🆕 v9.9.6.5：─ 最小化（折叠成只剩标题栏；再点 □ 复原）
        self._btn_min = tk.Label(title_bar, text=" ─ ",
                                  font=('微软雅黑', 11, 'bold'),
                                  bg=C['acc_dark'], fg='white',
                                  cursor='hand2', padx=8)
        self._btn_min.pack(side='right')
        self._btn_min.bind('<Button-1>', lambda e: self.toggle_minimize())
        self._btn_min.bind('<Enter>',
            lambda e: self._btn_min.config(bg=C['acc_dark2'] if 'acc_dark2' in C else '#3a5878'))
        self._btn_min.bind('<Leave>',
            lambda e: self._btn_min.config(bg=C['acc_dark']))

        # 📥 跟随同花顺（唯一一个开关）
        self._btn_follow = tk.Label(title_bar, text=" 📥 ",
                                     font=('微软雅黑', 10),
                                     bg=C['acc_dark'],
                                     fg=C['green'] if self._follow_mode else C['dim'],
                                     cursor='hand2', padx=6)
        self._btn_follow.pack(side='right')
        self._btn_follow.bind('<Button-1>', lambda e: self._toggle_follow())
        _tip_follow = "跟随同花顺：在同花顺里切股票时，浮窗自动跟着切"
        self._btn_follow.bind('<Enter>',
            lambda e: self._hexin_status_var.set(_tip_follow))
        self._btn_follow.bind('<Leave>',
            lambda e: self._hexin_status_var.set(self._hexin_status))

        # 标题栏拖动
        for widget in (title_bar, self._title_label):
            widget.bind('<Button-1>', self._drag_start)
            widget.bind('<B1-Motion>', self._drag_motion)
            widget.bind('<ButtonRelease-1>', self._drag_end)
        # 标题栏右键菜单
        title_bar.bind('<Button-3>', self._title_context_menu)
        self._title_label.bind('<Button-3>', self._title_context_menu)

        # 顶部摘要
        # 🆕 v9.9.6.5：4 个顶级容器存到 self.xxx 上，最小化时 pack_forget，
        # 复原时按原 pack 参数重新 pack
        self._summary_frame = tk.Frame(w, bg=C['card'])
        self._summary_frame.pack(fill='x', side='top', padx=8, pady=(8, 0))
        inner = tk.Frame(self._summary_frame, bg=C['card'])
        inner.pack(fill='x', padx=12, pady=10)

        # 第一行：股票名 + 代码 + 联动股网格 + AI 分析按钮
        line1 = tk.Frame(inner, bg=C['card']); line1.pack(fill='x')
        self._name_lbl = tk.Label(line1, text="—",
                                   font=('微软雅黑', 16, 'bold'),
                                   bg=C['card'], fg=C['text'])
        self._name_lbl.pack(side='left')
        # 🆕 v9.9.6：代码做成蓝字下划线 → 点击推送同花顺，浮窗不刷新
        self._code_lbl = tk.Label(line1, text="",
                                   font=('微软雅黑', 11, 'underline'),
                                   bg=C['card'], fg='#4ea8ff',
                                   cursor='hand2')
        self._code_lbl.pack(side='left', padx=(8, 0), pady=(6, 0))
        self._code_lbl.bind('<Button-1>', lambda e: self._push_current_code())
        self._code_lbl.bind('<Enter>',
            lambda e: self._code_lbl.config(fg='#8bc6ff'))
        self._code_lbl.bind('<Leave>',
            lambda e: self._code_lbl.config(fg='#4ea8ff'))

        # 右上角 AI 分析（先 pack right，给联动股 grid 让出右边界）
        self._btn_ai = tk.Label(line1, text="  📋 立即 AI 分析  ",
                                 font=('微软雅黑', 9, 'bold'),
                                 bg=C['purple'], fg='white',
                                 cursor='hand2', padx=8, pady=4)
        self._btn_ai.pack(side='right', pady=(4, 0))
        self._btn_ai.bind('<Button-1>', lambda e: self._request_ai_analyze())

        # 🆕 v9.9.6.4：联动股 grid，夹在"名字代码"与"AI按钮"之间
        # 数据源是最近一次分析记录的 content，解析"名字（代码）"对
        # 点击代码 → 推送同花顺，浮窗不变（lock 该 code）
        self._linked_frame = tk.Frame(line1, bg=C['card'])
        self._linked_frame.pack(side='left', expand=True, fill='x',
                                 padx=(20, 12), pady=(2, 0))

        # 第二行：价格 + 涨跌
        line2 = tk.Frame(inner, bg=C['card']); line2.pack(fill='x', pady=(6, 0))
        self._price_lbl = tk.Label(line2, text="—",
                                    font=('微软雅黑', 22, 'bold'),
                                    bg=C['card'], fg=C['text'])
        self._price_lbl.pack(side='left')
        self._chg_lbl = tk.Label(line2, text="",
                                  font=('微软雅黑', 13, 'bold'),
                                  bg=C['card'], fg=C['dim'])
        self._chg_lbl.pack(side='left', padx=(14, 0), pady=(8, 0))
        self._quote_time_lbl = tk.Label(line2, text="",
                                         font=('微软雅黑', 9),
                                         bg=C['card'], fg=C['dim'])
        self._quote_time_lbl.pack(side='right', pady=(10, 0))

        # 详情区
        self._detail_wrap = tk.Frame(w, bg=C['bg'])
        self._detail_wrap.pack(fill='both', expand=True, padx=8, pady=8)
        self._detail = tk.Text(self._detail_wrap, font=('微软雅黑', 10), wrap='word',
                                bg=C['card'], fg=C['text'],
                                relief='flat', padx=12, pady=10,
                                state='disabled', cursor='arrow')
        d_vsb = ttk.Scrollbar(self._detail_wrap, orient='vertical',
                               command=self._detail.yview)
        self._detail.configure(yscrollcommand=d_vsb.set)
        self._detail.pack(side='left', fill='both', expand=True)
        d_vsb.pack(side='right', fill='y')

        # 完整 tag 配置
        for tag, fg, bg in [
            ('h1', C['accent'], ''), ('h2', C['yellow'], ''),
            ('dim', C['dim'], ''), ('green', C['green'], ''),
            ('red', C['red'], ''),  ('star', C['star'], ''),
            ('star_tag', C['star'], ''), ('accent', C['accent'], ''),
            ('policy', C['yellow'], ''), ('concept', C['green'], ''),
            ('money', C['red'], ''), ('percent', C['accent'], ''),
            ('category', 'white', C['purple']),
            ('category_kw', '#1a1d23', C['star']),
            ('up', C['red'], ''), ('down', C['green'], ''),
            ('flat', C['dim'], ''),
        ]:
            kw = {'foreground': fg}
            if bg: kw['background'] = bg
            if tag in ('category', 'category_kw'):
                kw['font'] = ('微软雅黑', 10, 'bold')
            self._detail.tag_config(tag, **kw)
        self._detail.tag_config('h1bold',
            font=('微软雅黑', 12, 'bold'), foreground=C['accent'])

        # 底栏
        self._bottom_frame = tk.Frame(w, bg=C['bg'], height=36)
        self._bottom_frame.pack(fill='x', side='bottom')
        self._bottom_frame.pack_propagate(False)
        tk.Label(self._bottom_frame, text="📅 日期:", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(10, 2))
        self._date_var = tk.StringVar()
        self._date_combo = ttk.Combobox(self._bottom_frame, textvariable=self._date_var,
                                         state='readonly', width=22,
                                         font=('微软雅黑', 9))
        self._date_combo.pack(side='left', padx=(0, 8))
        self._date_combo.bind('<<ComboboxSelected>>',
                               lambda e: self._on_date_change())
        refresh_btn = tk.Label(self._bottom_frame, text="🔄 刷新行情",
                                font=('微软雅黑', 9), bg=C['bg'],
                                fg=C['accent'], cursor='hand2', padx=8)
        refresh_btn.pack(side='left')
        refresh_btn.bind('<Button-1>', lambda e: self._refresh_quote())

        # 同花顺监听状态条
        self._status_bar = tk.Frame(w, bg=C['panel'], height=22)
        self._status_bar.pack(fill='x', side='bottom')
        self._status_bar.pack_propagate(False)
        self._hexin_status_var = tk.StringVar(value=self._hexin_status)
        tk.Label(self._status_bar, textvariable=self._hexin_status_var,
                 font=('微软雅黑', 8), bg=C['panel'],
                 fg=C['dim']).pack(side='left', padx=8)
        self._hexin_count_var = tk.StringVar(value="切换 0 次")
        tk.Label(self._status_bar, textvariable=self._hexin_count_var,
                 font=('微软雅黑', 8), bg=C['panel'],
                 fg=C['accent']).pack(side='right', padx=8)

        # 右下角拖拽手柄
        self._grip = tk.Label(w, text="◢", font=('微软雅黑', 9),
                        bg=C['bg'], fg=C['dim'], cursor='bottom_right_corner')
        self._grip.place(relx=1.0, rely=1.0, anchor='se')
        self._grip.bind('<Button-1>', self._resize_start)
        self._grip.bind('<B1-Motion>', self._resize_motion)
        self._grip.bind('<ButtonRelease-1>', self._resize_end)

    # ════════════════════════════════════════════════
    # 拖动 / 缩放
    # ════════════════════════════════════════════════
    def _drag_start(self, e):
        self._drag_data['x'] = e.x_root - self.root.winfo_x()
        self._drag_data['y'] = e.y_root - self.root.winfo_y()
    def _drag_motion(self, e):
        x = e.x_root - self._drag_data['x']
        y = e.y_root - self._drag_data['y']
        self.root.geometry("+{}+{}".format(x, y))
    def _drag_end(self, e):
        self._save_geometry()

    def _resize_start(self, e):
        self._resize_data['x'] = e.x_root
        self._resize_data['y'] = e.y_root
        self._resize_data['w'] = self.root.winfo_width()
        self._resize_data['h'] = self.root.winfo_height()
    def _resize_motion(self, e):
        dx = e.x_root - self._resize_data['x']
        dy = e.y_root - self._resize_data['y']
        new_w = max(self._MIN_W, self._resize_data['w'] + dx)
        new_h = max(self._MIN_H, self._resize_data['h'] + dy)
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry("{}x{}+{}+{}".format(new_w, new_h, x, y))
    def _resize_end(self, e):
        self._save_geometry()

    def _save_geometry(self):
        # 🆕 v9.9.6.5：最小化状态下不存 geometry，否则下次启动浮窗会是折叠的
        if self._minimized:
            return
        try:
            geo = self.root.geometry()
            s = cfg_mod.load_settings()
            s["popup_geometry"] = geo
            cfg_mod.save_settings(s)
        except Exception:
            pass

    def _title_context_menu(self, e):
        menu = tk.Menu(self.root, tearoff=0,
                       font=('微软雅黑', 10),
                       bg=self.C['card'], fg=self.C['text'],
                       activebackground=self.C['accent'],
                       activeforeground='white')
        menu.add_command(label="📐 自定义窗口大小...",
                         command=self._show_size_dialog)
        menu.add_command(label="🔄 重置为默认大小 (600×700)",
                         command=self._reset_size)
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _show_size_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("自定义浮窗大小")
        dialog.geometry("300x160+{}+{}".format(
            self.root.winfo_x() + 80, self.root.winfo_y() + 120))
        dialog.resizable(False, False)
        dialog.configure(bg=self.C['card'])
        dialog.attributes('-topmost', True)
        dialog.transient(self.root)

        cur_w = self.root.winfo_width()
        cur_h = self.root.winfo_height()

        frame = tk.Frame(dialog, bg=self.C['card'])
        frame.pack(fill='both', expand=True, padx=16, pady=12)
        tk.Label(frame, text="宽度:", font=('微软雅黑', 10),
                 bg=self.C['card'], fg=self.C['text']).grid(
                     row=0, column=0, sticky='e', pady=8)
        w_var = tk.StringVar(value=str(cur_w))
        w_entry = tk.Entry(frame, textvariable=w_var, width=8,
                           font=('微软雅黑', 11),
                           bg=self.C['bg'], fg=self.C['text'],
                           insertbackground=self.C['text'],
                           relief='solid', bd=1, justify='center')
        w_entry.grid(row=0, column=1, padx=(8, 20), pady=8)
        w_entry.select_range(0, 'end'); w_entry.focus_set()
        tk.Label(frame, text="高度:", font=('微软雅黑', 10),
                 bg=self.C['card'], fg=self.C['text']).grid(
                     row=0, column=2, sticky='e', pady=8)
        h_var = tk.StringVar(value=str(cur_h))
        h_entry = tk.Entry(frame, textvariable=h_var, width=8,
                           font=('微软雅黑', 11),
                           bg=self.C['bg'], fg=self.C['text'],
                           insertbackground=self.C['text'],
                           relief='solid', bd=1, justify='center')
        h_entry.grid(row=0, column=3, padx=(8, 0), pady=8)

        def apply_size():
            try:
                nw = max(self._MIN_W, int(w_var.get()))
                nh = max(self._MIN_H, int(h_var.get()))
            except ValueError:
                dialog.destroy(); return
            x = self.root.winfo_x(); y = self.root.winfo_y()
            self.root.geometry("{}x{}+{}+{}".format(nw, nh, x, y))
            self._save_geometry(); dialog.destroy()

        btn_frame = tk.Frame(frame, bg=self.C['card'])
        btn_frame.grid(row=1, column=0, columnspan=4, pady=(16, 0))
        btn_ok = tk.Label(btn_frame, text="  确定  ",
                          font=('微软雅黑', 10, 'bold'),
                          bg=self.C['accent'], fg='white',
                          cursor='hand2', padx=14, pady=4)
        btn_ok.pack(side='left', padx=4)
        btn_ok.bind('<Button-1>', lambda e: apply_size())
        btn_cancel = tk.Label(btn_frame, text="  取消  ",
                              font=('微软雅黑', 10),
                              bg=self.C['dim'], fg='white',
                              cursor='hand2', padx=14, pady=4)
        btn_cancel.pack(side='left', padx=4)
        btn_cancel.bind('<Button-1>', lambda e: dialog.destroy())
        dialog.bind('<Return>', lambda e: apply_size())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def _reset_size(self):
        x = self.root.winfo_x(); y = self.root.winfo_y()
        self.root.geometry("600x700+{}+{}".format(x, y))
        self._save_geometry()

    def _update_title(self):
        # 🔁 v9.9.6：只有一个 follow 状态可显示
        suffix = "  📥 跟随同花顺" if self._follow_mode else ""
        if self._cur_name or self._cur_code:
            text = "📊  {} ({}){}".format(
                self._cur_name or "", self._cur_code or "", suffix)
        else:
            text = "📊  股票详情" + suffix
        self._title_label.config(text=text)

    # ════════════════════════════════════════════════
    # 📥 跟随开关
    # ════════════════════════════════════════════════
    def _toggle_follow(self):
        C = self.C
        self._follow_mode = not self._follow_mode
        try:
            self._btn_follow.config(
                fg=C['green'] if self._follow_mode else C['dim'])
        except Exception: pass

        try:
            s = cfg_mod.load_settings()
            s["popup_follow_hexin"] = self._follow_mode
            # 清掉老 key
            s.pop("popup_follow_mode", None)
            s.pop("popup_push_hexin", None)
            s.pop("popup_main_link", None)
            cfg_mod.save_settings(s)
        except Exception:
            traceback.print_exc()

        self._update_title()
        if self._follow_mode:
            self._hexin_status = "✅ 已启用 📥 跟随同花顺 (同花顺 → 浮窗)"
        else:
            self._hexin_status = "⏸️ 跟随已关闭 (手动模式)"
        try: self._hexin_status_var.set(self._hexin_status)
        except Exception: pass

    # ════════════════════════════════════════════════
    # 推送同花顺（浮窗内代码点击 + 老 API 入口）
    # ════════════════════════════════════════════════
    def _push_current_code(self):
        """点摘要区代码 → 推送到同花顺（不刷新浮窗）"""
        if not self._cur_code:
            return
        # 🆕 v9.9.6.2：先 lock 自己，防止 watcher 把同花顺切到的代码绕回来刷浮窗
        self.lock_code(self._cur_code)
        threading.Thread(
            target=self._push_worker, args=(self._cur_code,),
            daemon=True).start()

    def _push_worker(self, code):
        ok, reason = hexin.push_code_to_hexin(code)
        def _ui():
            self._update_push_status(ok, reason, code)
        try: self.root.after(0, _ui)
        except Exception: pass

    def _update_push_status(self, ok, reason, code):
        if ok:
            msg = "📤 已推送 {} 到同花顺 (前缀 {})".format(code, reason)
        else:
            msg = "❌ 推送失败: " + reason
        self._hexin_status = msg
        try: self._hexin_status_var.set(msg)
        except Exception: pass

    # ════════════════════════════════════════════════
    # 同花顺监听回调
    # ════════════════════════════════════════════════
    def _on_hexin_stock(self, code):
        """
        监听线程回调（hexin_bridge 已经做了"自推回声"过滤，这里再做一次
        浮窗本地 lock 检查作为二级保险）。
        """
        # 🆕 v9.9.6.2：浮窗本地 lock 二级防御
        if self._is_locked(code):
            try:
                self._hexin_status_var.set(
                    "🔁 跳过自推回声 (popup-lock, code={})".format(code))
            except Exception: pass
            return
        def _do():
            self._hexin_event_count += 1
            try:
                self._hexin_count_var.set("✅ 切换 {} 次 · 最近 {}".format(
                    self._hexin_event_count, code))
            except Exception: pass
            self.show(code, None)
        try: self.root.after(0, _do)
        except Exception: pass

    def _on_hexin_status(self, msg):
        self._hexin_status = msg
        def _do():
            try: self._hexin_status_var.set(msg)
            except Exception: pass
        try: self.root.after(0, _do)
        except Exception: pass

    # ════════════════════════════════════════════════
    # AI 分析按钮 → 主程序
    # ════════════════════════════════════════════════
    def _request_ai_analyze(self):
        if not self._cur_code:
            return
        code = self._cur_code
        name = self._cur_name or ""
        self._btn_ai.config(text="  ✅ 已发送到主程序  ")
        self.root.after(2000,
            lambda: self._btn_ai.config(text="  📋 立即 AI 分析  "))
        try:
            self.app.root.after(0,
                lambda: self.app._do_ai_analyze_from_popup(code, name))
        except Exception:
            traceback.print_exc()

    # ════════════════════════════════════════════════
    # 显示一只股票
    # ════════════════════════════════════════════════
    def show(self, code, name=None):
        if not code: return
        code6 = str(code).zfill(6)
        # 🆕 v9.9.6.5：如果当前是最小化状态，先复原（否则窗口"开但是空的"）
        if self._minimized:
            self._do_restore()
        # 🆕 v9.9.6.2：把"上一只显示过的股"推进历史栈（供 Ctrl+Z 回退）
        # 但 undo 自己引起的 show 不要再 push（否则 stack 永远清不空）
        # 也不要把"切到当前已显示的股"算成切换（重复刷新不进栈）
        if (not self._undoing
                and self._cur_code
                and self._cur_code != code6):
            self._show_history.append((self._cur_code, self._cur_name))
            # 限制历史深度，避免无限堆积
            if len(self._show_history) > 50:
                self._show_history.pop(0)
        self._cur_code = code6
        self._cur_name = name or ""
        try: self.root.deiconify(); self.root.lift()
        except tk.TclError: pass
        self._update_title()
        self._name_lbl.config(text=name or "—")
        self._code_lbl.config(text="(" + code6 + ")")
        self._price_lbl.config(text="加载中…", fg=self.C['dim'])
        self._chg_lbl.config(text="", fg=self.C['dim'])
        self._quote_time_lbl.config(text="")
        # 历史
        records = hist_mod.find_by_code(code6)
        self._records = records
        if records:
            options = ["{} {}  {}".format(
                r.get('date',''), r.get('time',''),
                "⭐" if r.get('starred') else "")
                for r in records]
            self._date_combo['values'] = options
            self._date_combo.current(0)
            self._render_record(records[0])
            # 🆕 v9.9.6.4：用最新一条分析记录的 content 渲染顶部联动股网格
            self._render_linked_grid(records[0].get('content', ''))
        else:
            self._date_combo['values'] = []
            self._date_combo.set("")
            self._render_no_history()
            self._render_linked_grid('')  # 清空 grid
        threading.Thread(target=self._fetch_quote, daemon=True).start()

    # ════════════════════════════════════════════════
    # 🆕 v9.9.6.4：顶部联动股 grid 渲染 + 点击逻辑
    # ════════════════════════════════════════════════
    def _render_linked_grid(self, content):
        """
        从 content 里抓"名字（代码）"对，去重 + 排除主股自己 + 最多 6 个，
        摆成 2 列 × 3 行 grid。每个代码做成蓝字下划线，点击推送但浮窗不变。
        """
        # 清掉旧 cell
        try:
            for child in self._linked_frame.winfo_children():
                child.destroy()
        except Exception:
            return
        if not content:
            return
        import re as _re
        # "彩虹股份（600707）" / "凯盛科技 (600552)" 都能匹配
        pat = _re.compile(
            r'([\u4e00-\u9fa5A-Z][\u4e00-\u9fa5A-Z0-9·\*]{1,7})\s*[（(]\s*(\d{6})\s*[)）]'
        )
        cur = (self._cur_code or "").zfill(6)
        seen = {cur} if cur else set()
        items = []
        for name, code in pat.findall(content):
            if code in seen:
                continue
            seen.add(code)
            items.append((name, code))
            if len(items) >= 6:
                break
        if not items:
            return
        C = self.C
        # 2 列 grid
        for i, (name, code) in enumerate(items):
            row = i // 2
            col = i % 2
            cell = tk.Frame(self._linked_frame, bg=C['card'])
            cell.grid(row=row, column=col, sticky='w',
                      padx=(0, 18), pady=1)
            tk.Label(cell, text=name,
                     font=('微软雅黑', 9),
                     bg=C['card'], fg=C['text']).pack(side='left')
            link = tk.Label(cell, text=" (" + code + ")",
                             font=('微软雅黑', 9, 'underline'),
                             bg=C['card'], fg='#4ea8ff',
                             cursor='hand2')
            link.pack(side='left')
            # 闭包陷阱：用默认参数把 code/name 锁住
            link.bind('<Button-1>',
                lambda e, c=code, n=name: self._push_linked(c, n))
            link.bind('<Enter>',
                lambda e, l=link: l.config(fg='#8bc6ff'))
            link.bind('<Leave>',
                lambda e, l=link: l.config(fg='#4ea8ff'))

    def _push_linked(self, code, name):
        """点联动股代码 → 推送同花顺，浮窗内容不变"""
        if not code:
            return
        # lock 防止 watcher 把同花顺切到的这只股回声给浮窗
        self.lock_code(code)
        threading.Thread(
            target=self._push_worker, args=(code,),
            daemon=True).start()
        # 状态条立即给反馈，等推送线程回来再 update 一次
        try:
            self._hexin_status_var.set(
                "📤 正在推送联动股 {} ({})...".format(name or "?", code))
        except Exception:
            pass

    def _fetch_quote(self):
        code = self._cur_code
        if not code: return
        try:
            data = api_client.fetch_change_pct([code])
        except Exception:
            data = {}
        info = data.get(code) or data.get(str(code).zfill(6))
        if info and not self._cur_name:
            self._cur_name = info.get('name', '')
        def _upd():
            if not info:
                self._price_lbl.config(text="—", fg=self.C['dim'])
                self._chg_lbl.config(text="无行情", fg=self.C['dim'])
                return
            chg = info.get('change_pct', 0)
            try: chg = float(chg)
            except (TypeError, ValueError): chg = 0.0
            if chg > 0:
                color = self.C['red']; sign = "+"; arrow = "▲"
            elif chg < 0:
                color = self.C['green']; sign = ""; arrow = "▼"
            else:
                color = self.C['dim']; sign = ""; arrow = "─"
            self._price_lbl.config(text="{:.2f}".format(info.get('price', 0)),
                                    fg=color)
            self._chg_lbl.config(text="{}  {}{:.2f}%".format(arrow, sign, chg),
                                  fg=color)
            self._quote_time_lbl.config(text=info.get('time', ''))
            if self._cur_name:
                self._name_lbl.config(text=self._cur_name)
                self._update_title()
        try: self.root.after(0, _upd)
        except Exception: pass

    def _refresh_quote(self):
        if not self._cur_code: return
        threading.Thread(target=self._fetch_quote, daemon=True).start()

    def _on_date_change(self):
        idx = self._date_combo.current()
        if idx < 0 or idx >= len(self._records): return
        rec = self._records[idx]
        self._render_record(rec)
        # 🆕 v9.9.6.4：切到老分析记录时，联动股网格也用对应那条 content 重建
        self._render_linked_grid(rec.get('content', ''))

    # ════════════════════════════════════════════════
    # 渲染
    # ════════════════════════════════════════════════
    def _render_record(self, rec):
        T = self._detail
        T.config(state='normal'); T.delete('1.0', 'end')
        def w(txt, tg=None):
            if tg: T.insert('end', txt, tg)
            else:  T.insert('end', txt)

        w("📅 {}  {}".format(rec.get('date',''), rec.get('time','')), 'dim')
        if rec.get('starred'): w("  ⭐ 已加星", 'star')
        if rec.get('success'): w("  ✅ 分析成功", 'green')
        else:                  w("  ❌ 分析失败", 'red')
        w("\n")
        cat = rec.get('category', '')
        if cat:
            w("🏷️  细分标签:  ", 'dim')
            w(" {} ".format(cat), 'category')
            w("\n")
        tags = rec.get('tags', [])
        if tags:
            w("📌  自定义标签: ", 'dim')
            w("、".join(tags) + "\n", 'star')
        nd = rec.get('next_day')
        if nd and isinstance(nd, dict):
            pct = nd.get('change_pct')
            if pct is not None:
                try: pct = float(pct)
                except: pct = 0
                tag = 'up' if pct > 0 else ('down' if pct < 0 else 'flat')
                arrow = '▲' if pct > 0 else ('▼' if pct < 0 else '─')
                sign = '+' if pct > 0 else ''
                w("📈 次日表现 ({}):  ".format(nd.get('date','')), 'dim')
                w("{} {}{:.2f}%\n".format(arrow, sign, pct), tag)
        note = rec.get('note', '')
        if note:
            w("📝  备注:  ", 'dim')
            w(note + "\n", 'star')
        w("─" * 40 + "\n", 'dim')
        content = rec.get('content', '') or '（无内容）'
        w(content + "\n")
        try:
            apply_highlight(T, keep_editable=True)
        except Exception:
            traceback.print_exc()
        T.config(state='disabled')
        # 🆕 v9.9.6.1：浮窗内的代码 → scope='popup'，点击只推送不刷浮窗
        try:
            attach_code_links(T, self.app,
                               main_code=self._cur_code, scope='popup')
        except Exception:
            traceback.print_exc()
        T.see('1.0')

    def _render_no_history(self):
        T = self._detail
        T.config(state='normal'); T.delete('1.0', 'end')
        T.insert('end', "\n\n  📭  本地暂无该股票的历史分析记录。\n\n", 'dim')
        T.insert('end', "  浮窗会等候你在主程序里分析这只股票后自动刷新。\n\n", 'dim')
        T.config(state='disabled')
