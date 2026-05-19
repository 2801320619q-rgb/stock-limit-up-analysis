"""
独立浮窗子进程入口（v9.8）

启动方式：
    python -m stock_app.stock_popup_main
环境变量：
    STOCK_APP_DATA_DIR  = 项目 data 目录的绝对路径（主程序拉起时设置）
    STOCK_APP_POPUP_PARENT_PID = 主程序 PID（可选，仅用于状态展示）

退出方式：
    用户点 ✕  /  收到 shutdown 信号  /  手动 kill python 进程
"""
import os, sys, time, threading, traceback
from pathlib import Path

# 让 stock_app 包能被 import
_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

import tkinter as tk
from tkinter import ttk

from stock_app.core import api_client, history as hist_mod
from stock_app.core import config as cfg_mod
from stock_app.core.theme import get as theme
from stock_app.core import hexin_bridge as hexin   # 🆕 v9.9.0：双向桥
from stock_app.popup_ipc import SignalReader, find_data_dir
from stock_app.widgets import apply_highlight


# ════════════════════════════════════════════════
# 同花顺监听已迁移到 stock_app.core.hexin_bridge.HexinReadWatcher
# 这里只剩薄薄一层封装，传 settings 进去即可
# ════════════════════════════════════════════════
def start_hexin_watcher(on_stock_change, get_follow_mode, on_status=None):
    """
    v9.9.0：改为基于 hexin_bridge.HexinReadWatcher，
    内部按"窗口标题 → 内存 → 剪贴板"三档自动降级。
    """
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
# 浮窗 UI
# ════════════════════════════════════════════════
class PopupApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # 先隐藏避免闪烁
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
        # 🆕 v9.9.4：三向联动开关（独立 toggle，可全关；点其中一个时另两个自动关）
        #   _follow_mode    = 同花顺 → 浮窗刷新       (📥 跟随同花顺)
        #   _push_mode      = 主程序点击 → 同花顺切股 (📤 推送同花顺)
        #   _main_link_mode = 主程序点击 → 浮窗刷新   (📍 主程序联动)  ★ v9.9.4 新增
        #
        # 旧版本里 _follow_mode 同时承担了"同花顺→浮窗"和"主程序→浮窗"，
        # 导致用户关掉 follow 后主程序点击也不刷新——v9.9.4 把这两个职责
        # 拆开，IPC 'follow' 信号（来自主程序点击）现在由 _main_link_mode
        # 独立把关，与同花顺监听完全解耦。
        try:
            self._settings = cfg_mod.load_settings()
        except Exception:
            self._settings = {}
        # 兼容老 settings key
        legacy_follow = self._settings.get("popup_follow_mode")
        self._follow_mode = bool(self._settings.get("popup_follow_hexin",
                                        True if legacy_follow is None else legacy_follow))
        self._push_mode = bool(self._settings.get("popup_push_hexin", False))
        # 🆕 v9.9.4：首次启动默认关闭，让 📥 跟随同花顺 来当主角
        self._main_link_mode = bool(self._settings.get("popup_main_link", False))
        # 互斥兜底：三个最多开一个；优先级 follow > main_link > push
        if self._follow_mode:
            self._main_link_mode = False
            self._push_mode = False
        elif self._main_link_mode:
            self._push_mode = False
        # 🆕 v9.8.1：同花顺监听状态（供 UI 显示）
        self._hexin_status = "⏳ 同花顺联动: 启动中..."
        self._hexin_last_code = None
        self._hexin_event_count = 0
        # 推送统计
        self._push_count = 0

        # IPC
        self._ipc = SignalReader(find_data_dir())

        self._build_window()
        self._start_signal_poll()
        # 同花顺监听
        start_hexin_watcher(self._on_hexin_stock,
                             lambda: self._follow_mode,
                             on_status=self._on_hexin_status)

        # 初始隐藏；等收到第一个信号或用户操作再显示
        self.root.deiconify()
        self.root.update()

    # ────────────────────────────────────────────
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

        btn_close = tk.Label(title_bar, text=" ✕ ",
                              font=('微软雅黑', 11, 'bold'),
                              bg=C['acc_dark'], fg='white',
                              cursor='hand2', padx=8)
        btn_close.pack(side='right')
        btn_close.bind('<Button-1>', lambda e: self._shutdown())
        btn_close.bind('<Enter>', lambda e: btn_close.config(bg=C['red']))
        btn_close.bind('<Leave>', lambda e: btn_close.config(bg=C['acc_dark']))

        # 🆕 v9.9.4：三向联动开关（独立 toggle，可全关；点其中一个另两个自动关）
        #   📥 跟随同花顺 = 同花顺 → 浮窗
        #   📤 推送同花顺 = 主程序点击 → 同花顺切股
        #   📍 主程序联动 = 主程序点击 → 浮窗刷新   ★ v9.9.4 新增
        # 标题栏从右到左布局：✕ → 📤 → 📍 → 📥（最常用的 📥 靠左）
        self._btn_push = tk.Label(title_bar, text=" 📤 ",
                                   font=('微软雅黑', 10),
                                   bg=C['acc_dark'],
                                   fg=C['purple'] if self._push_mode else C['dim'],
                                   cursor='hand2', padx=6)
        self._btn_push.pack(side='right')
        self._btn_push.bind('<Button-1>',
            lambda e: self._set_modes(
                push=not self._push_mode,
                follow=False if not self._push_mode else None,
                main_link=False if not self._push_mode else None))
        _tip_push = "推送同花顺：在主程序点击股票时，让同花顺跟着切到那只股"
        self._btn_push.bind('<Enter>',
            lambda e: self._hexin_status_var.set(_tip_push))
        self._btn_push.bind('<Leave>',
            lambda e: self._hexin_status_var.set(self._hexin_status))

        self._btn_main_link = tk.Label(title_bar, text=" 📍 ",
                                        font=('微软雅黑', 10),
                                        bg=C['acc_dark'],
                                        fg=C['yellow'] if self._main_link_mode else C['dim'],
                                        cursor='hand2', padx=6)
        self._btn_main_link.pack(side='right')
        self._btn_main_link.bind('<Button-1>',
            lambda e: self._set_modes(
                main_link=not self._main_link_mode,
                follow=False if not self._main_link_mode else None,
                push=False if not self._main_link_mode else None))
        _tip_main = "主程序联动：在主程序点击股票时，浮窗自动切到那只股"
        self._btn_main_link.bind('<Enter>',
            lambda e: self._hexin_status_var.set(_tip_main))
        self._btn_main_link.bind('<Leave>',
            lambda e: self._hexin_status_var.set(self._hexin_status))

        self._btn_follow = tk.Label(title_bar, text=" 📥 ",
                                     font=('微软雅黑', 10),
                                     bg=C['acc_dark'],
                                     fg=C['green'] if self._follow_mode else C['dim'],
                                     cursor='hand2', padx=6)
        self._btn_follow.pack(side='right')
        self._btn_follow.bind('<Button-1>',
            lambda e: self._set_modes(
                follow=not self._follow_mode,
                push=False if not self._follow_mode else None,
                main_link=False if not self._follow_mode else None))
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
        summary = tk.Frame(w, bg=C['card'])
        summary.pack(fill='x', side='top', padx=8, pady=(8, 0))
        inner = tk.Frame(summary, bg=C['card'])
        inner.pack(fill='x', padx=12, pady=10)
        line1 = tk.Frame(inner, bg=C['card']); line1.pack(fill='x')
        self._name_lbl = tk.Label(line1, text="—",
                                   font=('微软雅黑', 16, 'bold'),
                                   bg=C['card'], fg=C['text'])
        self._name_lbl.pack(side='left')
        self._code_lbl = tk.Label(line1, text="",
                                   font=('微软雅黑', 11),
                                   bg=C['card'], fg=C['dim'])
        self._code_lbl.pack(side='left', padx=(8, 0), pady=(6, 0))
        # 🆕 v9.8.1：右上角 AI 分析按钮（永远显示）
        self._btn_ai = tk.Label(line1, text="  📋 立即 AI 分析  ",
                                 font=('微软雅黑', 9, 'bold'),
                                 bg=C['purple'], fg='white',
                                 cursor='hand2', padx=8, pady=4)
        self._btn_ai.pack(side='right', pady=(4, 0))
        self._btn_ai.bind('<Button-1>', lambda e: self._request_ai_analyze())
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
        detail_wrap = tk.Frame(w, bg=C['bg'])
        detail_wrap.pack(fill='both', expand=True, padx=8, pady=8)
        self._detail = tk.Text(detail_wrap, font=('微软雅黑', 10), wrap='word',
                                bg=C['card'], fg=C['text'],
                                relief='flat', padx=12, pady=10,
                                state='disabled', cursor='arrow')
        d_vsb = ttk.Scrollbar(detail_wrap, orient='vertical',
                               command=self._detail.yview)
        self._detail.configure(yscrollcommand=d_vsb.set)
        self._detail.pack(side='left', fill='both', expand=True)
        d_vsb.pack(side='right', fill='y')

        # 完整 tag 配置（与历史详情区一致 + apply_highlight 6 个）
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
        bottom = tk.Frame(w, bg=C['bg'], height=36)
        bottom.pack(fill='x', side='bottom')
        bottom.pack_propagate(False)
        tk.Label(bottom, text="📅 日期:", font=('微软雅黑', 9),
                 bg=C['bg'], fg=C['dim']).pack(side='left', padx=(10, 2))
        self._date_var = tk.StringVar()
        self._date_combo = ttk.Combobox(bottom, textvariable=self._date_var,
                                         state='readonly', width=22,
                                         font=('微软雅黑', 9))
        self._date_combo.pack(side='left', padx=(0, 8))
        self._date_combo.bind('<<ComboboxSelected>>',
                               lambda e: self._on_date_change())
        refresh_btn = tk.Label(bottom, text="🔄 刷新行情",
                                font=('微软雅黑', 9), bg=C['bg'],
                                fg=C['accent'], cursor='hand2', padx=8)
        refresh_btn.pack(side='left')
        refresh_btn.bind('<Button-1>', lambda e: self._refresh_quote())

        # 🆕 v9.8.1：同花顺监听状态条（底部细条，方便诊断）
        status_bar = tk.Frame(w, bg=C['panel'], height=22)
        status_bar.pack(fill='x', side='bottom')
        status_bar.pack_propagate(False)
        self._hexin_status_var = tk.StringVar(value=self._hexin_status)
        tk.Label(status_bar, textvariable=self._hexin_status_var,
                 font=('微软雅黑', 8), bg=C['panel'],
                 fg=C['dim']).pack(side='left', padx=8)
        self._hexin_count_var = tk.StringVar(value="切换 0 次")
        tk.Label(status_bar, textvariable=self._hexin_count_var,
                 font=('微软雅黑', 8), bg=C['panel'],
                 fg=C['accent']).pack(side='right', padx=8)

        # 右下角拖拽手柄（调整窗口大小）
        grip = tk.Label(w, text="◢", font=('微软雅黑', 9),
                        bg=C['bg'], fg=C['dim'], cursor='bottom_right_corner')
        grip.place(relx=1.0, rely=1.0, anchor='se')
        grip.bind('<Button-1>', self._resize_start)
        grip.bind('<B1-Motion>', self._resize_motion)
        grip.bind('<ButtonRelease-1>', self._resize_end)

    # ────────────────────────────────────────────
    def _drag_start(self, e):
        self._drag_data['x'] = e.x_root - self.root.winfo_x()
        self._drag_data['y'] = e.y_root - self.root.winfo_y()
    def _drag_motion(self, e):
        x = e.x_root - self._drag_data['x']
        y = e.y_root - self._drag_data['y']
        self.root.geometry("+{}+{}".format(x, y))

    def _drag_end(self, e):
        """拖动结束后保存窗口位置"""
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
        """缩放结束后保存窗口大小"""
        self._save_geometry()

    def _save_geometry(self):
        """保存当前窗口几何尺寸到设置文件"""
        try:
            geo = self.root.geometry()
            s = cfg_mod.load_settings()
            s["popup_geometry"] = geo
            cfg_mod.save_settings(s)
        except Exception:
            pass

    def _title_context_menu(self, e):
        """标题栏右键菜单"""
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
        """弹出对话框让用户输入自定义宽高"""
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
                           relief='solid', bd=1,
                           justify='center')
        w_entry.grid(row=0, column=1, padx=(8, 20), pady=8)
        w_entry.select_range(0, 'end')
        w_entry.focus_set()

        tk.Label(frame, text="高度:", font=('微软雅黑', 10),
                 bg=self.C['card'], fg=self.C['text']).grid(
                     row=0, column=2, sticky='e', pady=8)
        h_var = tk.StringVar(value=str(cur_h))
        h_entry = tk.Entry(frame, textvariable=h_var, width=8,
                           font=('微软雅黑', 11),
                           bg=self.C['bg'], fg=self.C['text'],
                           insertbackground=self.C['text'],
                           relief='solid', bd=1,
                           justify='center')
        h_entry.grid(row=0, column=3, padx=(8, 0), pady=8)

        def apply_size():
            try:
                nw = max(self._MIN_W, int(w_var.get()))
                nh = max(self._MIN_H, int(h_var.get()))
            except ValueError:
                dialog.destroy()
                return
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            self.root.geometry("{}x{}+{}+{}".format(nw, nh, x, y))
            self._save_geometry()
            dialog.destroy()

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
        """重置窗口为默认大小"""
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry("600x700+{}+{}".format(x, y))
        self._save_geometry()

    def _update_title(self):
        # 🆕 v9.9.4：标题反映当前联动模式（三选一）
        if self._follow_mode:
            suffix = "  📥 跟随同花顺"
        elif self._main_link_mode:
            suffix = "  📍 主程序联动"
        elif self._push_mode:
            suffix = "  📤 推送同花顺"
        else:
            suffix = ""
        if self._cur_name or self._cur_code:
            text = "📊  {} ({}){}".format(
                self._cur_name or "", self._cur_code or "", suffix)
        else:
            text = "📊  股票详情" + suffix
        self._title_label.config(text=text)

    # ────────────────────────────────────────────
    # 🆕 v9.9.4：三向独立 toggle 模式开关
    #   - 三个参数任一传 None 表示"不变"
    #   - 三个开关独立，可全关（手动模式）
    #   - 但兜底：同时为 True 时按 follow > main_link > push 优先级关闭其它
    # ────────────────────────────────────────────
    def _set_modes(self, follow=None, push=None, main_link=None):
        """
        统一设置三个联动模式。
        参数传 None 表示保持当前值；传 True/False 显式设置。
        """
        C = self.C
        if follow is None:
            follow = self._follow_mode
        if push is None:
            push = self._push_mode
        if main_link is None:
            main_link = self._main_link_mode
        # 互斥兜底：UI 上 click handler 已经保证传进来最多一个为 True，
        # 这里再做一次防御性兜底，防止 IPC set_modes 调用打破不变量
        if follow:
            main_link = False
            push = False
        elif main_link:
            push = False

        # 切到 push 模式时先做一次能力检查（pyautogui / pywin32 任一可用即可）
        if push and not self._push_mode:
            caps = hexin.capabilities()
            if not caps["can_write"]:
                self._hexin_status_var.set(
                    "❌ 推送不可用：缺少 pyautogui/pywin32 依赖")
                push = False  # 拒绝开启

        self._follow_mode = follow
        self._push_mode = push
        self._main_link_mode = main_link

        # 更新按钮颜色
        try:
            self._btn_follow.config(
                fg=C['green'] if follow else C['dim'])
            self._btn_push.config(
                fg=C['purple'] if push else C['dim'])
            self._btn_main_link.config(
                fg=C['yellow'] if main_link else C['dim'])
        except Exception:
            pass

        # 持久化
        try:
            s = cfg_mod.load_settings()
            s["popup_follow_hexin"] = follow
            s["popup_push_hexin"] = push
            s["popup_main_link"] = main_link
            # 清理旧 key
            s.pop("popup_follow_mode", None)
            cfg_mod.save_settings(s)
        except Exception:
            traceback.print_exc()

        self._update_title()

        # 状态条提示
        if follow:
            self._hexin_status = "✅ 已启用 📥 跟随同花顺 (同花顺 → 浮窗)"
        elif main_link:
            self._hexin_status = "✅ 已启用 📍 主程序联动 (主程序 → 浮窗)"
        elif push:
            self._hexin_status = "✅ 已启用 📤 推送同花顺 (主程序 → 同花顺)"
        else:
            self._hexin_status = "⏸️ 联动全部关闭 (手动模式)"
        try: self._hexin_status_var.set(self._hexin_status)
        except Exception: pass

    # ────────────────────────────────────────────
    # IPC 信号轮询
    # ────────────────────────────────────────────
    def _start_signal_poll(self):
        def _poll():
            sig = self._ipc.poll()
            if sig:
                self._dispatch(sig)
            self.root.after(300, _poll)
        self.root.after(300, _poll)

    def _dispatch(self, sig):
        action = sig.get("action")
        data = sig.get("data") or {}
        if action == 'show':
            self.show(data.get('code'), data.get('name'))
        elif action == 'follow':
            # 🆕 v9.9.4：'follow' IPC 信号 = "主程序点击/选中股票"通知
            #   - 旧版本里被 _follow_mode 把关，但 _follow_mode 同时绑定同花顺
            #     监听，导致用户关掉 follow 后主程序点击也不响应。
            #   - v9.9.4 起：本信号由 _main_link_mode 和 _push_mode 两个独立
            #     开关分别消费——可同时启用，互不冲突；同花顺监听完全走
            #     浮窗内部的 HexinReadWatcher，与 IPC 'follow' 信号解耦。
            if self._main_link_mode:
                self.show(data.get('code'), data.get('name'))
            if self._push_mode:
                self._do_push_to_hexin(data.get('code'), data.get('name'))
        elif action == 'push':
            # 显式推送请求（不管模式开关，调用方明确要推就推）
            self._do_push_to_hexin(data.get('code'), data.get('name'))
        elif action == 'set_follow':
            # 旧 API 兼容：等价于"开 follow、关其它"
            on = bool(data.get('on'))
            if on:
                self._set_modes(follow=True, push=False, main_link=False)
            else:
                self._set_modes(follow=False)
        elif action == 'set_modes':
            # 🆕 v9.9.4：支持三参（main_link 字段；老调用方只传 follow/push 也兼容）
            self._set_modes(
                follow=data.get('follow'),
                push=data.get('push'),
                main_link=data.get('main_link'))
        elif action == 'shutdown':
            self._shutdown()

    def _do_push_to_hexin(self, code, name=None):
        """🆕 v9.9.0：把 code 推送给同花顺，让它跳转"""
        if not code:
            return
        threading.Thread(
            target=self._push_worker, args=(code, name),
            daemon=True).start()

    def _push_worker(self, code, name):
        ok, reason = hexin.push_code_to_hexin(code)
        def _ui():
            if ok:
                self._push_count += 1
                msg = "📤 已推送 {} 到同花顺 (累计 {} 次)".format(
                    code, self._push_count)
            else:
                msg = "❌ 推送失败: " + reason
            self._hexin_status = msg
            try: self._hexin_status_var.set(msg)
            except Exception: pass
        try: self.root.after(0, _ui)
        except Exception: pass

    def _on_hexin_stock(self, code):
        """同花顺监听线程回调（已经过 follow 模式判断）"""
        def _do():
            self._hexin_event_count += 1
            self._hexin_last_code = code
            try:
                self._hexin_count_var.set("✅ 切换 {} 次 · 最近 {}".format(
                    self._hexin_event_count, code))
            except Exception: pass
            self.show(code, None)
        try: self.root.after(0, _do)
        except Exception: pass

    def _on_hexin_status(self, msg):
        """同花顺监听状态回调（用于显示在底部状态栏）"""
        self._hexin_status = msg
        def _do():
            try: self._hexin_status_var.set(msg)
            except Exception: pass
        try: self.root.after(0, _do)
        except Exception: pass

    def _request_ai_analyze(self):
        """
        🆕 v9.8.1：点击"📋 立即 AI 分析"按钮
        - 把当前股票代码 + 名字写到 IPC 信号
        - 主程序收到后切到单股搜索 Tab 并触发分析
        """
        if not self._cur_code:
            return
        # 我们用一个简单的方式：写一个独立的 trigger 文件
        # 主程序的 trigger 轮询会读到并执行
        try:
            from stock_app.popup_ipc import find_data_dir
            import json, os, tempfile, time
            path = find_data_dir() / "popup" / "trigger.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "action": "ai_analyze",
                "code": self._cur_code,
                "name": self._cur_name or "",
                "ts": time.time(),
            }
            fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                                        prefix=".tmp_", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, str(path))
            # 视觉反馈
            self._btn_ai.config(text="  ✅ 已发送到主程序  ")
            self.root.after(2000,
                lambda: self._btn_ai.config(text="  📋 立即 AI 分析  "))
        except Exception:
            traceback.print_exc()

    # ────────────────────────────────────────────
    # 显示一只股票
    # ────────────────────────────────────────────
    def show(self, code, name=None):
        if not code: return
        code6 = str(code).zfill(6)
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
        else:
            self._date_combo['values'] = []
            self._date_combo.set("")
            self._render_no_history()
        threading.Thread(target=self._fetch_quote, daemon=True).start()

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
        self._render_record(self._records[idx])

    # ────────────────────────────────────────────
    # 渲染
    # ────────────────────────────────────────────
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
        T.see('1.0')

    def _render_no_history(self):
        T = self._detail
        T.config(state='normal'); T.delete('1.0', 'end')
        T.insert('end', "\n\n  📭  本地暂无该股票的历史分析记录。\n\n", 'dim')
        T.insert('end', "  浮窗会等候你在主程序里分析这只股票后自动刷新。\n\n", 'dim')
        T.config(state='disabled')

    # ────────────────────────────────────────────
    def _shutdown(self):
        try: self.root.destroy()
        except Exception: pass

    def run(self):
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self._shutdown()


def main():
    try:
        app = PopupApp()
        app.run()
    except Exception:
        traceback.print_exc()
        input("\n[发生异常] 按回车关闭...")


if __name__ == "__main__":
    main()
