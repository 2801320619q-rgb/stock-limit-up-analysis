"""
同花顺双向桥（v9.9.6）
═══════════════════════════════════════════════════════════════════
v9.9.6 重大重构：
  • 写方向：完全换成"远程内存写入 + WM_HEXIN_PUSH (0x490) 自定义消息"
    方案。来自用户提供的《写入同花顺.py》参考实现。比 v9.9.4 的
    pyautogui / SendInput 模拟键盘更可靠：不抢焦点、不受输入法干扰、
    不要求同花顺窗口在前台。
  • 读方向：只保留"内存偏移读"一条路。窗口标题法 / 剪贴板法兜底全部
    移除——前者依赖标题文本格式，同花顺多个版本里压根没有 6 位代码；
    后者要求用户主动 Ctrl+C，不是真正的"自动跟随"。读不到就是读不到，
    在状态栏老老实实告诉用户即可。
  • 防回环：维护"最近推送过的 code + 时间戳"静默期，watcher 读到
    在静默期内的代码就不外抛 on_change。这是给上层用的——用户在
    主程序点蓝字推送 600519，同花顺切过去后 watcher 不应该再"绕回来"
    让浮窗刷新（事实上浮窗已经在显示 600519 了，多此一举）。
═══════════════════════════════════════════════════════════════════
"""
import ctypes
import re
import sys
import threading
import time
import traceback


# ════════════════════════════════════════════════════════════════
# 平台 / 依赖能力探测
# ════════════════════════════════════════════════════════════════
IS_WIN = sys.platform == "win32"

try:
    import win32api      # type: ignore
    import win32gui      # type: ignore
    import win32process  # type: ignore
    HAS_WIN32 = True
except Exception:
    HAS_WIN32 = False

try:
    import psutil  # type: ignore
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

try:
    import pymem          # type: ignore
    import pymem.process  # type: ignore
    HAS_PYMEM = True
except Exception:
    HAS_PYMEM = False


# 6 位股票代码（沪深 A 股 + 创业板 + 科创板 + 北交所等）
_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


# ════════════════════════════════════════════════════════════════
# 工具
# ════════════════════════════════════════════════════════════════
def _safe_call(fn, *a, **kw):
    """调任何 win32 函数都包一下，防止偶发抛错把监听线程拖死"""
    try:
        return fn(*a, **kw)
    except Exception:
        return None


def _extract_code_from_text(text):
    """从字符串里挑出 6 位股票代码（取第一个匹配）"""
    if not text:
        return None
    m = _CODE_RE.search(text)
    return m.group(1) if m else None


# ════════════════════════════════════════════════════════════════
# 读方向（同花顺 → 本程序）：仅内存偏移法
# ════════════════════════════════════════════════════════════════
class _MemReader:
    """封装 pymem 二级指针读取，attach 一次后复用"""
    def __init__(self, process_name, offset, str_len, encoding):
        self.process_name = process_name
        self.offset = offset
        # 默认 32 字节：旧默认 6 在某些版本/状态下会截掉带前缀字符串的尾巴
        self.str_len = max(6, int(str_len or 32))
        # 实测 ascii 比 gbk 稳；保留配置项做向后兼容
        self.encoding = encoding or "ascii"
        self._pm = None
        self._pointer_addr = None
        # 失败现场（给诊断用）
        self.last_error = ""
        self.last_raw = b""
        self.last_addr = 0
        self.attach_attempts = 0
        self.attach_failures = 0
        self.read_ok_count = 0

    def attach(self):
        if self._pm is not None:
            return True
        if not HAS_PYMEM:
            self.last_error = "pymem 未安装"
            return False
        self.attach_attempts += 1
        try:
            self._pm = pymem.Pymem(self.process_name)
            mod = pymem.process.module_from_name(
                self._pm.process_handle, self.process_name)
            self._pointer_addr = mod.lpBaseOfDll + self.offset
            self.last_error = ""
            return True
        except Exception as e:
            self.attach_failures += 1
            etype = type(e).__name__
            msg = str(e) or repr(e)
            low = msg.lower()
            if "could not be found" in low or "not found" in low:
                hint = "进程未运行（同花顺没开？）"
            elif "access" in low or "denied" in low or "0x5" in msg:
                hint = "拒绝访问（同花顺以管理员启动？请同样以管理员启动主程序）"
            elif "module" in low and "not" in low:
                hint = "模块定位失败（进程名是否真的叫 {}？）".format(self.process_name)
            else:
                hint = msg
            self.last_error = "{}: {}".format(etype, hint)
            self._pm = None
            self._pointer_addr = None
            return False

    def detach(self):
        self._pm = None
        self._pointer_addr = None

    def read(self):
        """
        读一次。返回 6 位代码字符串，或 None。
        失败原因留在 self.last_error。
        """
        if self._pm is None and not self.attach():
            return None
        try:
            addr = self._pm.read_int(self._pointer_addr)
            self.last_addr = addr
            raw = self._pm.read_bytes(addr, self.str_len)
            self.last_raw = raw
            # ① 截断到 NUL（保留前缀字符）
            chunk = raw.split(b'\x00')[0]
            # ② 解码（按配置 → 失败则降级 ASCII）
            try:
                txt = chunk.decode(self.encoding, errors='ignore')
            except Exception:
                txt = chunk.decode('ascii', errors='ignore')
            # ③ 用正则找第一个"独立的 6 位数字"
            m = _CODE_RE.search(txt)
            if m:
                self.read_ok_count += 1
                self.last_error = ""
                return m.group(1)
            # ④ 兜底：纯数字串（无前缀）filter 后正好 6 位也算
            val = ''.join(ch for ch in txt if ch.isdigit())
            if len(val) == 6:
                self.read_ok_count += 1
                self.last_error = ""
                return val
            # 没找到：记录现场
            self.last_error = (
                "已 attach 但提不到 6 位代码: "
                "raw={!r} 解码后={!r} 净化={!r}(len={})"
            ).format(bytes(raw), txt, val, len(val))
            return None
        except Exception as e:
            self.last_error = "read 异常 ({}): {}".format(
                type(e).__name__, str(e) or repr(e))
            # 进程消失 / 偏移瞬时失效 → 解附加，下次循环重 attach
            self.detach()
            return None


# ════════════════════════════════════════════════════════════════
# 写方向（本程序 → 同花顺）：WriteProcessMemory + WM_HEXIN_PUSH (0x490)
# ════════════════════════════════════════════════════════════════
# 这是用户提供的《写入同花顺.py》方案。原理：
#   1. 在同花顺进程里 VirtualAllocEx 8 字节缓冲
#   2. 写 1 字节"市场前缀" + 6 字节 ASCII 代码进去
#   3. 发自定义消息 0x490 给同花顺主窗口，lParam 传缓冲区地址
#   4. 同花顺就会跳转到这只股
# 比 pyautogui 模拟键盘可靠：不抢焦点、不受输入法干扰、能后台执行
PROCESS_ALL_ACCESS  = 0x001F0FFF
MEM_COMMIT_RESERVE  = 0x1000 | 0x2000
PAGE_READWRITE      = 0x04
MEM_RELEASE         = 0x8000
WM_HEXIN_PUSH       = 0x490

# kernel32 句柄惰性初始化（非 Win 系统也能 import 这个模块）
_kernel32 = ctypes.windll.kernel32 if IS_WIN else None


def _get_prefix_byte(code):
    """
    根据股票代码前缀返回"市场前缀字节"。
    沿用《写入同花顺.py》里的实测对照表。
    """
    if "ST" in code.upper():
        return 0x16
    if code.startswith("6"):
        return 0x11
    if code.startswith("11"):
        return 0x13
    if code.startswith("12"):
        return 0x23
    if code.startswith("92"):
        return 0x97
    if code.startswith("43") or code.startswith("87") or code.startswith("83"):
        return 0x91
    if code.startswith("0") or code.startswith("3"):
        return 0x21
    return 0x21  # 兜底深市


def _find_hexin_pid():
    """枚举进程找 hexin.exe"""
    if not HAS_PSUTIL:
        return None
    for p in psutil.process_iter(['name']):
        try:
            if p.info['name'] and p.info['name'].lower() == 'hexin.exe':
                return p.pid
        except Exception:
            continue
    return None


def _find_hexin_main_hwnd(pid):
    """
    在指定 PID 下找到面积最大且标题以"同花顺"开头的可见窗口。
    返回 (hwnd, title) 或 (None, None)。
    """
    if not HAS_WIN32:
        return None, None
    candidates = []

    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, p = win32process.GetWindowThreadProcessId(hwnd)
            if p != pid:
                return True
            title = win32gui.GetWindowText(hwnd) or ""
            if title.startswith('同花顺'):
                r = win32gui.GetWindowRect(hwnd)
                area = (r[2] - r[0]) * (r[3] - r[1])
                candidates.append((hwnd, area, title))
        except Exception:
            pass
        return True

    _safe_call(win32gui.EnumWindows, _cb, None)
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: -x[1])
    return candidates[0][0], candidates[0][2]


def push_code_to_hexin(code, focus_back_hwnd=None):
    """
    把 code 推送给同花顺。返回 (ok: bool, reason: str)
    成功的 reason 形如 "0x11"（实际用的市场前缀，方便调试）。

    focus_back_hwnd：写完后焦点切回的窗口（一般传主程序 HWND）。
                     0x490 方案不抢焦点，但保留这个参数维持调用方签名。
    """
    code = str(code or "").strip()
    if not (code.isdigit() and len(code) == 6):
        return False, "代码格式不对（应为 6 位数字）"
    if not IS_WIN:
        return False, "非 Windows 平台，不支持推送"
    if not HAS_WIN32:
        return False, "缺少 pywin32 (pip install pywin32)"
    if not HAS_PSUTIL:
        return False, "缺少 psutil (pip install psutil)"

    pid = _find_hexin_pid()
    if not pid:
        return False, "找不到同花顺进程（请先启动同花顺）"
    hwnd, title = _find_hexin_main_hwnd(pid)
    if not hwnd:
        return False, "找不到同花顺主窗口"

    proc = _kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not proc:
        return False, "OpenProcess 失败（可能权限不足；同花顺如以管理员启动，请同样以管理员启动本程序）"
    addr = None
    try:
        prefix = _get_prefix_byte(code)
        addr = _kernel32.VirtualAllocEx(
            proc, 0, 8, MEM_COMMIT_RESERVE, PAGE_READWRITE)
        if not addr:
            return False, "VirtualAllocEx 失败"
        payload = bytes([prefix]) + code.encode('ascii')
        written = ctypes.c_size_t(0)
        ok = _kernel32.WriteProcessMemory(
            proc, addr, payload, len(payload), ctypes.byref(written))
        if not ok:
            return False, "WriteProcessMemory 失败"
        # 自定义消息：同花顺主窗口收到后会跳转。lParam 为缓冲区地址
        win32api.SendMessage(hwnd, WM_HEXIN_PUSH, 0, addr)
        # 推送完登记静默期，让 watcher 别把"我自己推的代码"绕回来再触发联动
        _push_silencer.mark(code)
        return True, "0x{:02X}".format(prefix)
    except Exception as e:
        return False, "推送异常 ({}): {}".format(type(e).__name__,
                                                  str(e) or repr(e))
    finally:
        try:
            if addr:
                _kernel32.VirtualFreeEx(proc, addr, 0, MEM_RELEASE)
            _kernel32.CloseHandle(proc)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
# 防回环：最近推送过的代码静默期
# ════════════════════════════════════════════════════════════════
class _PushSilencer:
    """
    push_code_to_hexin 成功后会调 mark(code)，在 ttl 秒内 watcher
    读到同一 code 时不外抛 on_change。这是消除自激回环用的。

    线程安全：mark 和 is_silenced 之间会有读写并发，用 lock 兜底。
    """
    def __init__(self, ttl=3.0):
        self._ttl = ttl
        self._lock = threading.Lock()
        # code → expire_ts
        self._marks = {}

    def mark(self, code):
        if not code:
            return
        with self._lock:
            self._marks[code] = time.time() + self._ttl

    def is_silenced(self, code):
        if not code:
            return False
        now = time.time()
        with self._lock:
            exp = self._marks.get(code)
            if exp is None:
                return False
            if now > exp:
                # 过期了顺手清掉
                try: del self._marks[code]
                except KeyError: pass
                return False
            return True


_push_silencer = _PushSilencer(ttl=10.0)


# ════════════════════════════════════════════════════════════════
# 读监听器（只走内存法）
# ════════════════════════════════════════════════════════════════
class HexinReadWatcher:
    """
    后台线程持续读同花顺当前股，变化时回调 on_change(code)。
    在静默期内（刚被本程序推送过 ttl 秒内）的代码不外抛。

    用法：
        w = HexinReadWatcher(on_change=..., on_status=...,
                              enabled_fn=lambda: True)
        w.start()
        ...
        w.stop()
    """
    def __init__(self, on_change, on_status=None, enabled_fn=None,
                 settings=None):
        """
        on_change(code)        : 探测到股票切换时调用（已过静默过滤）
        on_status(msg)         : 状态文本（用于 UI 状态栏）
        enabled_fn() -> bool   : 实时查询当前是否启用监听
        settings: dict         : 用户配置（偏移、字符串长度等），可选
        """
        self.on_change = on_change
        self.on_status = on_status or (lambda m: None)
        self.enabled_fn = enabled_fn or (lambda: True)
        s = settings or {}

        # 内存偏移配置
        try:
            off = s.get("hexin_offset", "0x1E9A5B0")
            if isinstance(off, int):
                self._offset = off
            else:
                self._offset = int(str(off), 16) if str(off).lower().startswith("0x") \
                    else int(off)
        except Exception:
            self._offset = 0x1E9A5B0
        self._str_len = int(s.get("hexin_string_length", 32))
        self._encoding = s.get("hexin_encoding", "ascii")
        self._proc_name = s.get("hexin_process_name", "hexin.exe")
        self._poll_ms = int(s.get("hexin_poll_ms", 30))

        self._mem = _MemReader(self._proc_name, self._offset,
                                self._str_len, self._encoding)
        self._last_emitted = None  # 上次成功通知的代码
        self._last_read = None
        self._last_status = ""

        self._stop = threading.Event()
        self._thread = None

    # ────────────────────────────────────────────────────────────
    def _status(self, msg):
        if msg != self._last_status:
            self._last_status = msg
            print("[hexin-bridge]", msg)
            try:
                self.on_status(msg)
            except Exception:
                pass

    def _try_emit(self, code):
        """通知外部，但只在 enabled_fn() 为真且代码确实变了时"""
        if not code:
            return
        if not self.enabled_fn():
            return
        if code == self._last_emitted:
            return
        # 🆕 v9.9.6：防回环——本程序刚推过的代码不外抛
        if _push_silencer.is_silenced(code):
            self._status("🔁 跳过自推回声 (code={})".format(code))
            # 把 last_emitted 也更新，避免静默期过后再次触发
            self._last_emitted = code
            return
        try:
            self.on_change(code)
            self._last_emitted = code
        except Exception:
            traceback.print_exc()

    # ────────────────────────────────────────────────────────────
    def _loop(self):
        if not IS_WIN:
            self._status("⚠️ 非 Windows，监听功能不可用")
            return
        if not HAS_PYMEM:
            self._status("❌ 缺少 pymem，监听不可用 (pip install pymem)")
            return

        self._status("⏳ 监听就绪：内存(0x{:X})".format(self._offset))
        attached = False
        backoff = 1.0

        while not self._stop.is_set():
            try:
                code = self._mem.read()
                if code:
                    if not attached:
                        attached = True
                        self._status("✅ 已通过内存偏移附加 hexin.exe")
                    if code != self._last_read:
                        self._last_read = code
                        self._try_emit(code)
                    self._status("✅ 同花顺 已联动 (内存法)")
                else:
                    if attached:
                        # 上一轮还能读，这轮读不到——可能同花顺关了
                        attached = False
                    reason = self._mem.last_error
                    if reason:
                        self._status("⚠️ 同花顺读不到代码 · " + reason[:80])
                    else:
                        self._status("⏳ 等待同花顺启动…")

                time.sleep(self._poll_ms / 1000.0)
                backoff = 1.0
            except Exception:
                traceback.print_exc()
                time.sleep(backoff)
                backoff = min(10.0, backoff * 1.5)

    # ────────────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="HexinReadWatcher")
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop.set()


# ════════════════════════════════════════════════════════════════
# 能力查询（给 UI 用，决定显示 / 禁用哪些功能）
# ════════════════════════════════════════════════════════════════
def capabilities():
    return {
        "platform_ok": IS_WIN,
        "can_read_mem": IS_WIN and HAS_PYMEM,
        "can_write": IS_WIN and HAS_WIN32 and HAS_PSUTIL,
        "has_win32": HAS_WIN32,
        "has_pymem": HAS_PYMEM,
        "has_psutil": HAS_PSUTIL,
    }


def diagnose():
    """返回诊断字符串，用户看一眼就知道哪能用哪不能用"""
    c = capabilities()
    lines = []
    lines.append("平台: " + ("Windows ✅" if c["platform_ok"] else "非 Windows ❌"))
    lines.append("pywin32: " + ("已安装 ✅" if c["has_win32"]
                                 else "未安装 ❌  pip install pywin32"))
    lines.append("pymem: "   + ("已安装 ✅" if c["has_pymem"]
                                 else "未安装 ❌  pip install pymem"))
    lines.append("psutil: "  + ("已安装 ✅" if c["has_psutil"]
                                 else "未安装 ❌  pip install psutil"))
    lines.append("─" * 36)
    lines.append("📥 跟随同花顺 (读): " +
                  ("可用 ✅" if c["can_read_mem"] else "不可用 ❌"))
    lines.append("📤 推送同花顺 (写): " +
                  ("可用 ✅" if c["can_write"] else "不可用 ❌"))
    pid = _find_hexin_pid() if c["has_psutil"] else None
    if pid:
        hwnd, title = _find_hexin_main_hwnd(pid)
        if hwnd:
            lines.append("同花顺进程: ✅ PID={} HWND={}".format(pid, hwnd))
            lines.append("  └─ 主窗口标题: " + (title or "<空>"))
        else:
            lines.append("同花顺进程: PID={} 但找不到主窗口".format(pid))
    else:
        lines.append("同花顺进程: 未检测到 ❌")
    return "\n".join(lines)


def diagnose_now(offset=0x1E9A5B0, process_name="hexin.exe",
                 str_len=32, encoding="ascii"):
    """活体诊断：同步跑一次完整探测，把每条路径的具体失败原因写出来。"""
    out = [diagnose(), "─" * 36, "【实时探测】"]

    # 1) 读：内存法
    if HAS_PYMEM and IS_WIN:
        r = _MemReader(process_name, offset, str_len, encoding)
        if r.attach():
            v = r.read()
            if v:
                out.append("内存法 ✅ 当前读到 → {}  (基址+偏移={})".format(
                    v, hex(r._pointer_addr)))
            else:
                out.append("内存法 ⚠️ attach 成功但 read 没拿到 6 位代码")
                out.append("    └─ 失败原因: " + (r.last_error or "未知"))
                out.append("    └─ 指针目标地址: " + hex(r.last_addr))
                try:
                    hex_dump = " ".join("{:02X}".format(b) for b in r.last_raw)
                    out.append("    └─ 原始 6 字节: " + hex_dump)
                except Exception:
                    pass
                out.append("    💡 这通常意味着偏移漂移了。试着改 settings 里的 hexin_offset。")
        else:
            out.append("内存法 ❌ attach 失败")
            out.append("    └─ " + (r.last_error or "未知错误"))
            if "拒绝访问" in r.last_error:
                out.append("    💡 解决方案：右键主程序 → 以管理员身份运行")
    elif not HAS_PYMEM:
        out.append("内存法 ⊘ 跳过 (pymem 未安装)")
    else:
        out.append("内存法 ⊘ 跳过 (非 Windows)")

    # 2) 写：进程定位
    if IS_WIN and HAS_PSUTIL and HAS_WIN32:
        pid = _find_hexin_pid()
        if pid:
            hwnd, title = _find_hexin_main_hwnd(pid)
            if hwnd:
                out.append("推送链路 ✅ PID={} HWND={} 标题={!r}".format(
                    pid, hwnd, title))
            else:
                out.append("推送链路 ⚠️ 找到 PID={} 但无可见主窗口".format(pid))
        else:
            out.append("推送链路 ⊘ 同花顺进程未找到")
    else:
        out.append("推送链路 ⊘ 跳过 (缺 pywin32/psutil 或非 Windows)")

    return "\n".join(out)


# ════════════════════════════════════════════════════════════════
# 兼容旧接口（即将弃用，但留几个 stub 让老 import 不炸）
# ════════════════════════════════════════════════════════════════
def find_hexin_main_hwnd():
    """老 API 兼容：只返回 hwnd，不返回 title"""
    pid = _find_hexin_pid()
    if not pid:
        return None
    hwnd, _ = _find_hexin_main_hwnd(pid)
    return hwnd


def read_current_code_by_title():
    """老 API 兼容：标题法已弃用，永远返回 None"""
    return None
