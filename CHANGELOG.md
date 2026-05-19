# 修改日志 v9.9.6.5

## 主题：浮窗最小化

### 用户需求

> 增加一个悬浮窗最小化的功能上去。

### 实现思路

浮窗是 `overrideredirect(True)` 无边框窗口，**操作系统层面这窗口不存在**，
所以没法用 `iconify()` 扔到 Windows 任务栏。"最小化"只能在程序内做——
**折叠成只剩标题栏 32px 高度的一条**，再点一次复原。

### 改动

`popup_window.py`：

1. **`__init__` 加状态**
   - `_minimized = False`
   - `_geo_before_min`：折叠前的 geometry，复原用

2. **顶级容器都改 `self.xxx`** 方便折叠时 `pack_forget`
   - `_summary_frame` / `_detail_wrap` / `_bottom_frame` / `_status_bar` / `_grip`

3. **标题栏加 `─` 按钮**（在 ✕ 左边）

4. **`toggle_minimize()`** 公开方法
   - `_do_minimize()`：
     a. 记下当前 geometry 到 `_geo_before_min`
     b. 4 个顶级容器 `pack_forget`
     c. `_grip.place_forget`
     d. `geometry()` 高度调到 32px
     e. 按钮文字换成 `□`
   - `_do_restore()`：
     a. 4 个顶级容器按原 pack 参数重 pack
     b. `_grip.place(...)` 恢复
     c. `geometry(_geo_before_min)` 恢复尺寸
     d. 按钮文字换回 `─`

5. **`show()` 入口自动复原** —— 浮窗收到 hexin 信号 / 主程序点蓝字时如果当前在最小化状态，直接 deiconify 会变成"空窗户"，所以先 `_do_restore()`

6. **`_save_geometry` 加保护** —— 最小化状态下不保存 32px 的折叠尺寸，否则下次启动浮窗一打开就是折叠的

### 快捷键

新增可自定义快捷键 `shortcut_minimize_popup`，默认 `<F2>`：
- 走已有的 `_build_shortcut_spec` 体系
- `App._kb_minimize_popup` 调 `popup.toggle_minimize`
- `_NullPopup` 加同名 stub

settings.json 新增字段 `"shortcut_minimize_popup": "<F2>"`（向后兼容，老配置取默认）。

### 边界情况

| 场景 | 行为 |
|---|---|
| 最小化后拖动标题栏 | 整个 32px 条跟着拖动（标题栏拖动逻辑不依赖其它容器） |
| 最小化后点 ✕ | 走 hide，下次 show 会先复原 |
| 最小化时关闭主程序 | settings 里 popup_geometry 保留折叠前的尺寸（_save_geometry 已加保护） |
| 最小化时收到 hexin 切股 | show() 自动 `_do_restore()` 后正常刷新 |
| 最小化时按 F1 隐藏 | toggle_visibility 走 hide；下次按 F1 显示时窗体仍是最小化的（要按 F2 才完全展开）|

---

# 修改日志 v9.9.6.4

## 主题：浮窗顶部增加"联动股网格"

### 用户反馈

> 上方增加了联动个股 这是悬浮窗
> （附了原效果图 + 期望效果图：在标题区"股票名+代码"与"📋 立即 AI 分析"按钮之间，
> 增加 2 列 × 3 行的联动股网格，每个代码是蓝字下划线点击可推送同花顺）

### 实现

`popup_window.py` line1 区域调整结构：

```
[股票名] [代码]  [联动股 grid 2×3]  [📋 立即 AI 分析]
```

`_render_linked_grid(content)` 方法：
- 用正则 `([\u4e00-\u9fa5A-Z][\u4e00-\u9fa5A-Z0-9·\*]{1,7})\s*[（(]\s*(\d{6})\s*[)）]` 从分析记录 content 抓"名字+代码"对
- 排除主股本身、去重，最多取 6 只
- 用 grid 摆 2 列 × 3 行
- 每个 cell 是 "名字 + 蓝字下划线代码"
- 点击代码 → `_push_linked(code, name)`：推送同花顺 + lock 浮窗本地 + 浮窗内容不变

`_push_linked(code, name)`：
- 调 `self.lock_code(code)` 防 watcher 回声
- 后台线程 push
- 状态栏即时反馈 "📤 正在推送联动股 {name} ({code})..."

数据源：show(code) 时取 records[0].content 渲染；切换日期 combobox 时用对应那条 record 的 content 重建。

### pack 布局陷阱备忘

`line1` 内三个区域共享：
- `_name_lbl` (side=left)
- `_code_lbl` (side=left)
- `_btn_ai` (side=right) ← 先 pack right 锁定右边界
- `_linked_frame` (side=left, expand=True, fill=x) ← 最后 pack，吃掉中间剩余空间

顺序换了会导致 AI 按钮被挤出或 grid 被压缩。

### 边界处理

- 浮窗当前股没历史记录 → `_render_no_history` + 网格清空
- 联动股少于 6 个 → grid 自动只渲染实际数量
- 联动股多于 6 个 → 截断（用户需要看完整列表去详情区滚动）
- 切换日期 combobox 重建联动股网格（不同日期可能联动股不同）

---

# 修改日志 v9.9.6.3

## 主题：修复"快捷键没生效" + 所有快捷键全部可自定义

### 用户反馈

> 快捷键没有生效。同时我还需所有快捷都是可以自定义的。

### bug 根因：用了 `root.bind` 而非 `root.bind_all`

tkinter 里 `widget.bind(seq, ...)` 只在该 widget **有焦点**时触发。主程序里
Entry / Text / Treeview 一旦拿到焦点（用户点过任意输入框 / 列表行 / 详情文本），
事件就被它们消费，不会冒泡回 root，所以 `root.bind('<Control-z>', ...)` 大概率
没机会触发——这就是用户报告的"没生效"。

正确做法：`root.bind_all(seq, ...)` 是 Tk 的**应用级**绑定，无视焦点位置。
v9.9.6.3 全部改用 bind_all。

### 所有快捷键全部可自定义（12 个）

引入统一的快捷键规格表 `App._build_shortcut_spec()`，结构：
`(settings_key, default_sequence, callable, description)`

当前所有 12 个：

| settings_key | 默认 | 功能 |
|---|---|---|
| `shortcut_search`       | `<Control-Return>` | 🔍 单股搜索触发 |
| `shortcut_clear_log`    | `<Control-l>`      | 🧹 清空当前 Tab 日志 |
| `shortcut_undo`         | `<Control-z>`      | ⏪ 回退浮窗上一只股 |
| `shortcut_toggle_popup` | `<F1>`             | 👁 显示/隐藏浮窗 |
| `shortcut_tab_1`        | `<Control-Key-1>`  | 🗂 切到 Tab 1 |
| `shortcut_tab_2`        | `<Control-Key-2>`  | 🗂 切到 Tab 2 |
| ...                     | ...                | ... |
| `shortcut_tab_8`        | `<Control-Key-8>`  | 🗂 切到 Tab 8 |

`App` 新增方法：
- `_build_shortcut_spec()`：返回规格表
- `_setup_shortcuts()`：启动时遍历表，从 `settings.json` 读用户值（无则默认），逐一 `root.bind_all`
- `rebind_shortcuts(new_mapping)`：先 `unbind_all` 旧的、再 `bind_all` 新的
- `_kb_tab(idx)`：切到第 idx 个 Tab（0-indexed）

### settings_tab UI 改造

"⌨️ 快捷键（全部可自定义）"卡片现在**完全由规格表驱动**：
- 自动遍历 spec，每个快捷键一行 Entry
- 输入框旁显示默认值，方便用户对照
- "💾 保存全部并立即生效" 按钮：写 settings.json + 调 `rebind_shortcuts`
- "🔄 全部重置默认" 按钮：清空所有自定义值
- 保存前校验：格式必须是 `<...>`、且不同快捷键不能绑同一个 sequence

### 控制台诊断

`_setup_shortcuts` 和 `rebind_shortcuts` 成功 bind 后会 print：
```
[shortcuts] bind_all <Control-z> → shortcut_undo
[shortcuts] bind_all <F1> → shortcut_toggle_popup
[shortcuts] bind_all <Control-Return> → shortcut_search
...
```

从命令行 `python main.py` 启动能看到所有 bind 的 sequence，方便诊断"是不是真的绑上去了"。

### 副作用 / 注意

- bind_all 是真·全局的：在 Entry 里按 Ctrl+Z 时，浮窗 undo 会先触发，**然后** Entry 自己的撤销也会触发（tkinter 默认行为）。如果有冲突，把 `shortcut_undo` 改成别的（如 `<Alt-z>`）即可。
- F1 在某些桌面环境下是系统帮助键，可能被外层窗口管理器先吞掉——如果点了没反应，先在命令行确认 console 是否有 `bind_all <F1>` 打印，再排查是不是系统级冲突。

### settings.json 新增字段

老 settings 没这些字段时取默认值，向后兼容。完整新字段：

```json
{
  "shortcut_search":        "<Control-Return>",
  "shortcut_clear_log":     "<Control-l>",
  "shortcut_undo":          "<Control-z>",
  "shortcut_toggle_popup":  "<F1>",
  "shortcut_tab_1":         "<Control-Key-1>",
  "shortcut_tab_2":         "<Control-Key-2>",
  "shortcut_tab_3":         "<Control-Key-3>",
  "shortcut_tab_4":         "<Control-Key-4>",
  "shortcut_tab_5":         "<Control-Key-5>",
  "shortcut_tab_6":         "<Control-Key-6>",
  "shortcut_tab_7":         "<Control-Key-7>",
  "shortcut_tab_8":         "<Control-Key-8>"
}
```

---

# 修改日志 v9.9.6.2

## 主题：修浮窗内点蓝字会刷新浮窗的 bug + 加 Ctrl+Z 回退 + F1 切换浮窗

### 用户反馈

> 现在有篮字了，现在浮窗点击篮字的时候同花顺会切换个股，这是对的，
> 但是浮窗的内容也跟着切换过去这是不对的，我需要的是在浮窗点击内容浮窗不变。
> 还需要添加一个快捷键 Ctrl+Z 回退上一步操作，添加快捷键 F1 隐藏/浮现悬浮窗，
> 可以在设置里面修改快捷键。

### bug 根因：push_silencer ttl=3s 不够

时序：
1. 用户在浮窗内点蓝字 600519
2. `push_to_hexin_silent` 推送同花顺，`_push_silencer.mark('600519')` ttl=3s
3. 同花顺切换需要时间（在某些环境 >3s）
4. watcher 读到 600519 时静默期已过期 → 触发 `on_change('600519')` → `popup.show('600519')` → 浮窗刷新 ❌

### 双层防御修复

**第一层：全局 `_push_silencer` ttl 从 3s 调到 10s**

应付慢机/慢同花顺。

**第二层：浮窗本地 `_popup_locked` dict（也 10s ttl）**

`popup_window.py`:
- 新增 `lock_code(code, ttl=10)` 方法
- `_on_hexin_stock` 派发前先 `_is_locked(code)` 检查，命中则跳过

`widgets.py` `attach_code_links._on_press`:
- `scope='popup'` 时调用 `app.popup_lock_code(code)`，确保浮窗本地也 lock
- 即使全局 silencer 因极端情况失效，浮窗本地 lock 仍能拦下回声

`popup_window._push_current_code`（摘要区代码标签点击）也加 `lock_code` 调用。

`app.py` 新增 `popup_lock_code(code)` API 转发到 `popup.lock_code`。

### Ctrl+Z 回退（默认 `<Control-z>`）

`popup_window.py`:
- `__init__` 加 `_show_history = []` 栈
- `show(code, name)` 在切换股票时（且非 undo 触发）把旧的 `(_cur_code, _cur_name)` push 进 history，最多保留 50 条
- 新增 `undo()` 方法：pop 出上一只，**同时**调 `hexin.push_code_to_hexin` 让同花顺也跟着回退；`_undoing` 标志位防死循环

### F1 切换浮窗（默认 `<F1>`）

`popup_window.toggle_visibility()`：用 `winfo_viewable()` 判断当前可见性（在 overrideredirect 窗口上比 `state()` 可靠），不可见就 deiconify + lift，可见就 `hide()` 走 `withdraw`。

### 设置里改快捷键

`settings_tab.py`：把"快捷键"卡片改成两栏可编辑：
- 输入 tkinter 格式（如 `<Control-z>` / `<F1>` / `<Alt-x>`）
- 点"💾 保存并立即生效"按钮 → 写入 `settings.json` + 调 `app.rebind_popup_shortcuts` 立即重新绑定到 root

`app.py`：
- `_setup_shortcuts` 启动时从 settings 读 `shortcut_undo` / `shortcut_toggle_popup`，默认 `<Control-z>` / `<F1>`
- 新增 `rebind_popup_shortcuts(undo_key, toggle_key)`：先 `root.unbind` 旧的再 bind 新的，无需重启程序
- 新增 `_kb_undo` / `_kb_toggle_popup` 调用 popup 对应方法

### settings.json 新增字段

```json
{
  "shortcut_undo":         "<Control-z>",
  "shortcut_toggle_popup": "<F1>"
}
```

旧 settings 没这两个字段时取默认值，向后兼容。

---

# 修改日志 v9.9.6.1（修订）

## 主题：修复"主程序点蓝字浮窗不跟着变"+ 排查"蓝字下划线没显示"

### 现场（用户反馈）

> 我以前搜索的股票都没有篮字下划线，你都没有添加篮字下划线 过往历史内容也没有篮字下划线。
> 我需要的是点击蓝字下滑线，浮窗也要有，主程序也要。
> 股票6位数的代码就是蓝色下划线，在浮窗内点击下划线，浮窗不变，
> 主程序点击下划线，浮窗跟同花顺一起变动。

### 两个 bug

**bug 1: 主程序点蓝字时浮窗不会跟着变**

v9.9.6 把所有蓝字点击都走 `push_to_hexin_silent`，"silent" 的意思是不刷浮窗。
在浮窗内点击时这是对的（push_silencer 防回环让浮窗保持原样）；但在主程序内
点击时漏掉了"让浮窗也切到这只股"的动作。

**bug 2: 历史详情里完全没出现蓝字**

历史 Tab 的详情区调了 `attach_code_links`，但被 `try/except: pass` 静默吞掉
任何错误，没法诊断。另外 v9.9.6 的 `tag_raise` 用法没有，主股那一行的
`main_stock` tag（金色 + 棕色背景）有可能盖掉蓝色 link tag 的 foreground。

### 修复

1. **`widgets.attach_code_links` 加 `scope` 参数**
   - `scope='popup'`（浮窗调用）：点击 → 只 `push_to_hexin_silent`，浮窗内容不变
   - `scope='main'`（主程序所有 Tab）：点击 → `push_to_hexin_silent` + `show_stock_popup`，浮窗跟同花顺一起切

2. **`_ensure_link_tags` 末尾调 `widget.tag_raise(_LINK_TAG)`**
   把链接 tag 抬到所有 tag 之上，确保蓝色 + 下划线绝对覆盖任何老 tag。
   `tag_raise` 不传第二参数 = 抬到所有 tag 之上（tkinter 默认语义）。

3. **错误暴露**
   所有调用点的 `except Exception: pass` 改成 `except Exception: import traceback; traceback.print_exc()`，
   外加 `attach_code_links` 内部成功路径 print "加了 N 个代码链接"。
   这样用户启动后切到历史 Tab，console 至少能看到调用是否真的发生了。

### 用户侧验证方法

如果蓝字仍然没显示，请：
1. 从命令行启动 `python main.py`，让 console 输出可见
2. 打开历史 Tab，点击一条带股票代码的记录
3. console 应看到 `[attach_code_links] scope=main 给 widget 加了 N 个代码链接`
   - 看到了 N>0 但 UI 没蓝字 → 说明 tag_raise 还是不够，可能是 Tkinter 版本特殊
   - 看到 N=0 → 内容里没识别到合法 A 股代码
   - 完全没看到这一行 → `_show_detail` 没被触发或 attach_code_links 抛了异常（traceback 应已打出）

### 调用点确认

| 文件 | scope |
|---|---|
| `popup_window._render_record` → `_detail` | `'popup'` |
| `popup_window._code_lbl` (摘要区代码标签) | (单独的 Label，行为等同 popup：只推送) |
| `history_tab._show_detail` → `self.detail` | `'main'` |
| `history_tab._requery_realtime` → `self.detail` | `'main'` |
| `single_tab._search.ui` → `self.log_w` | `'main'` |
| `batch_tab._on_complete` → `self.log_w` | `'main'` |
| `sector_tab._render_ladder` → `_ladder_text` | `'main'` |
| `replay_tab._generate_daily_report` → `_daily_text` | `'main'` |
| `replay_tab._show_profile` → `_prof_text` | `'main'` |
| `replay_tab._show_trend` → `_trend_text` | `'main'` |
| `my_sectors_tab._fav_show_detail` → `_fav_detail` | `'main'` |
| `my_sectors_tab._user_show_detail` → `_user_detail` | `'main'` |

---

# 修改日志 v9.9.6

## 主题：推送同花顺改走 0x490 远程内存写入；联动开关精简；股票代码统一变蓝字下划线 click-to-push

### 现场（用户需求）

> 1. 所有股票代码下方都增加蓝字下划线效果，点击以后会有轻微放大动画效果，点击即可推送同花顺
> 2. 浮窗下方蓝字点击也推送至同花顺但是浮窗内容不变，只有非程序相关的股票切换才会跟随切换
> 3. 联动个股增添本股票"就是现在主页的这只锚定股"
> 4. 浮窗删除同花顺推送按钮，相关代码移除
> 5. 浮窗删除主程序联动按钮，识别当前在主程序操作，跟随主程序变动，相关代码移除
> 6. 同花顺除读取内存这一项代码，其他兜底代码移除（标题法、剪贴板法）
> 7. 推送同花顺改用《写入同花顺.py》提供的新方案（远程内存写入 + WM_HEXIN_PUSH）

### 改动一览

| 模块 | 改动 |
|---|---|
| `core/hexin_bridge.py` | **写方向完全重写**：`WriteProcessMemory + SendMessage(0x490)`；废弃 pyautogui / SendInput。**读方向只留内存法**：标题法 / 剪贴板法删除。新增 `_PushSilencer`，本程序刚推过的代码 3 秒内 watcher 不外抛（防自激回环） |
| `popup_window.py` | 标题栏 ✕ + 📥 两个按钮，**删除 📤 推送同花顺 / 📍 主程序联动**；摘要区代码蓝字下划线 click 推送（不刷新浮窗）；`notify_main_click` 永远刷新浮窗（不再有 main_link 开关） |
| `widgets.py` | **新增 `attach_code_links(widget, app, main_code=None)`**：扫描 Text 内容里所有合法 A 股 6 位代码，加蓝字下划线 + hand 光标 + 点击 80ms 字号放大动画 + 推送 |
| `app.py` | 新增 `push_to_hexin_silent(code, name)`：蓝字 link 的统一入口，推送同花顺、不刷新浮窗（靠 push_silencer 防回环） |
| `core/api_client.py` | `append_realtime_data` 加 `main_code` 参数，当前主股放在 codes 最前面、用 ⭐ 标识 |
| `tabs/history_tab.py` | `_requery_realtime` + 批量重查都把记录的主股票加入 codes；详情区 + 实时行情重建后都调 `attach_code_links` |
| `tabs/single_tab.py` | 搜索完成后日志区调 `attach_code_links(self.log_w, self.app, main_code=code)` |
| `tabs/batch_tab.py` | 批量完成后日志区调 `attach_code_links` |
| `tabs/replay_tab.py` | 日报 / 个股档案 / 趋势时间线三个 Text 区都调 `attach_code_links` |
| `tabs/sector_tab.py` | 龙头梯队 Text 调 `attach_code_links` |
| `tabs/my_sectors_tab.py` | 自选股详情 + 自定义板块详情都调 `attach_code_links` |
| 所有 Tab | 移除 `if not self.app.stock_popup.is_follow_mode(): return`：浮窗永远跟随主程序，不再需要前置守卫 |
| `tabs/settings_tab.py` | 测试推送 / 诊断的提示文案更新为 0x490 方案（不再提 SendInput / 焦点） |

### 推送新方案原理（`hexin_bridge.push_code_to_hexin`）

来自《写入同花顺.py》：

1. `psutil` 找 hexin.exe 的 PID
2. `EnumWindows` 找标题以"同花顺"开头、面积最大的可见窗口
3. `OpenProcess(PROCESS_ALL_ACCESS)` 拿进程句柄
4. `VirtualAllocEx` 在同花顺进程空间申请 8 字节
5. 按 `_get_prefix_byte(code)` 算出市场前缀字节（沪市 0x11、深市 0x21、可转债 0x13/0x23、北交所 0x91 等）
6. `WriteProcessMemory` 写入 `[prefix_byte] + ascii_code`
7. `SendMessage(hwnd, 0x490, 0, addr)` 通知同花顺跳转
8. `VirtualFreeEx` + `CloseHandle` 清理

比模拟键盘的优势：不抢焦点 / 不受输入法影响 / 不需要同花顺在前台 / 不被杀软拦截 SendInput。

### 防回环：`_PushSilencer`

`push_code_to_hexin` 成功后调 `_push_silencer.mark(code)`，记录该 code 的 3 秒过期时间。`HexinReadWatcher._try_emit` 派发前先查 `_push_silencer.is_silenced(code)`——是的话静默掉。

这样的语义：

| 场景 | 行为 |
|---|---|
| 用户在主程序点蓝字 600519 | 推送同花顺 → 同花顺切到 600519 → watcher 读到 600519 → 静默期内，不通知浮窗 → 浮窗保持原样 ✅ |
| 浮窗里点蓝字 600519 | 同上 ✅ |
| 用户在同花顺侧手动切到 600886 | watcher 读到 600886 → 不在静默期 → 通知浮窗刷新 ✅ |

恰好实现用户要求："浮窗内容不变，只有非程序相关的股票切换才会跟随切换"。

### 兼容性

- `app.show_stock_popup(code, name)` 不变
- `app.notify_stock_focus(code, name)` 不变（语义变了：现在永远刷浮窗）
- `app.push_to_hexin(code, name)` 不变（底层桥换实现）
- `app.stock_popup.is_follow_mode()` 不变（返回 _follow_mode，但已无业务方使用）

### 用户可见变化

1. ✅ 每个能显示股票代码的 Text 区域里，代码都是蓝色 + 下划线，鼠标 hover 变手型，点击有 80ms 放大动画
2. ✅ 浮窗顶栏少了 📤 和 📍 两个按钮，只剩 ✕ 和 📥
3. ✅ 任何主程序里点击/选中股票（Treeview 选中行、Text 单击）浮窗都会跟随刷新，不需要开关
4. ✅ 分析详情末尾的"📊 同逻辑联动标的"列表里多了主股本身，前面带 ⭐
5. ✅ 推送同花顺时同花顺不再抢前台焦点

### 删掉/弃用了什么

- `hexin_bridge.read_current_code_by_title` / `_read_clipboard_code` → 函数还留着但 watcher 不再调用（保留是为了 `find_hexin_main_hwnd` 等老 import 不炸）
- `hexin_bridge` 里的 pyautogui / SendInput 推送链路 → 完全移除
- `popup_window` 的 `_push_mode` / `_main_link_mode` / `_set_modes` → 完全移除，settings 写入时也清理掉对应的旧 key
- `stock_popup_main.py` → 文件还留着但功能已被 popup_window 完全取代，可作 fallback

---

# 修改日志 v9.9.5

## 主题：浮窗回归主程序内嵌，不再单开 Python 进程

### 现场（用户需求）

> 帮我把浮窗放进去主程序一起运行，不单开应用了。

### 背景

v9.8 把浮窗拆成独立子进程是为了让"主程序退出后浮窗还在"。但用户
反馈：双击 main 启动会有两个 Python 进程 + 两个图标，任务栏看着乱，
关闭/重启逻辑也复杂。所以 v9.9.5 改回内嵌。

### 改动一览

| 方向 | v9.8/v9.9.4 (子进程) | v9.9.5 (内嵌) |
|---|---|---|
| 浮窗承载 | `subprocess.Popen` + 独立 `tk.Tk()` | `tk.Toplevel(app.root)` |
| 主→浮通讯 | `data/popup/signal.json` 轮询 | 直接方法调用 |
| 浮→主通讯 (AI 分析) | `data/popup/trigger.json` 轮询 | `app.root.after(0, ...)` |
| ✕ 关闭语义 | 杀子进程 | `withdraw()` 隐藏，下次 show 自动恢复 |
| "重启浮窗"按钮 | 杀进程 → 重启 | 重启同花顺监听线程 |

### 新文件 / 关键改动

- **新文件** `stock_app/popup_window.py`：内嵌版 `PopupWindow` 类，UI 几乎完全
  沿用旧 `stock_popup_main.py`，但入口改成接收 `app` 参数 + `Toplevel`。
- **改写** `stock_app/app.py`：删 `_launch_popup_subprocess` /
  `_poll_popup_trigger` / `SignalWriter`，构造时直接 `self._popup = PopupWindow(self)`。
  公开 API (`show_stock_popup` / `notify_stock_focus` / `push_to_hexin`) 签名不变。
- **改写** `stock_app/tabs/settings_tab.py`：`_restart_popup` 不再杀进程，改为
  调用 `app._popup.restart_hexin_watcher()`，用最新设置重启同花顺监听线程，
  浮窗窗体保持原状。
- **改写** `stock_app/stock_popup.py`（老 shim）：方法委托到 `app._popup`。
- **保留**（未删，留作 fallback / 调试用）：
  - `stock_app/stock_popup_main.py`：独立子进程版浮窗，仍可手动 `python -m stock_app.stock_popup_main` 启动。
  - `stock_app/popup_ipc.py`：被上面那个文件用。

### 兼容性

所有旧的 Tab 调用方式都不用改：

```python
self.app.show_stock_popup(code, name)         # ✅ 仍然有效
self.app.notify_stock_focus(code, name)        # ✅ 仍然有效
self.app.push_to_hexin(code, name)             # ✅ 仍然有效
self.app.stock_popup.is_follow_mode()           # ✅ 仍然有效
self.app.stock_popup.show(code, name)           # ✅ 仍然有效
self.app.stock_popup.follow(code, name)         # ✅ 仍然有效
```

### 退出路径

`App._on_close` 末尾追加 `self._popup.destroy()`，作用是让浮窗里的
`HexinReadWatcher` 后台线程优雅停掉。否则 watcher 是非守护线程，会让
主程序退出后 Python 进程仍卡几秒等线程退。

### 不再有的特性

"主程序关了浮窗还在"——这是子进程模式独有的，内嵌后做不到（浮窗
是主程序的 Toplevel，主程序退就一起退）。如果将来还想要这个能力，
留着的 `stock_popup_main.py` 仍可手动起。

---

# 修改日志 v9.9.4

## 主题：拆分"主程序→浮窗"和"同花顺→浮窗"两条联动 + 推送同花顺换 pyautogui 后端

### 现场（用户描述）

> 本地的联动不支持了，现在只支持同花顺了。需要让本地主程序能跟浮窗交互，
> 同花顺也能交互。

具体症状：在主程序里单击表格行/Text 里的代码，浮窗不刷新。
但同花顺侧切股票，浮窗依然能跟着切。

### 根因

v9.9.0 把双向联动设计成 **`_follow_mode` / `_push_mode` 二选一互斥**，
其中 `_follow_mode` 同时承担了两个职责：

1. 把控浮窗内部 `HexinReadWatcher` 是否消费同花顺切股事件
2. 把控 IPC `'follow'` 信号（主程序点击发出）是否触发浮窗刷新

这两个职责本来就是两件独立的事——一个是"同花顺→浮窗"，一个是"主程序→浮窗"，
被错误地绑成了同一个开关。用户只要关掉 follow（哪怕是为了开 push），
主程序点击事件也连带失效。

### 修复：拆开成三个独立开关

**`_follow_mode` 现在只管同花顺→浮窗**；新增 `_main_link_mode` 专门
负责主程序→浮窗。三个开关独立可全关：

| 开关 | 颜色 | 信号源 | 动作 |
|---|---|---|---|
| 📥 跟随同花顺  | 绿 | 浮窗内部 `HexinReadWatcher` | 同花顺切股 → 浮窗刷新 |
| 📍 主程序联动 | 黄 | IPC `'follow'` 信号       | 主程序点击 → 浮窗刷新   ★ 新增 |
| 📤 推送同花顺  | 紫 | IPC `'follow'` 信号       | 主程序点击 → 同花顺切股 |

互斥规则：点其中一个时另两个自动关（沿用旧版"显式互斥"行为）；
但允许三个都关（手动模式，只响应右键菜单这种 `'show'` 信号）。

首次启动默认开 📥 跟随同花顺，老用户的 `popup_follow_hexin` /
`popup_push_hexin` 配置照常读取生效。新增 settings key：`popup_main_link`。

### 关键代码

**`stock_app/stock_popup_main.py` `_dispatch`：**

```python
elif action == 'follow':
    # v9.9.4：'follow' 现在由 _main_link_mode 和 _push_mode 两个
    # 独立开关分别消费，同花顺监听完全走浮窗内部 watcher，与本信号无关。
    if self._main_link_mode:
        self.show(data.get('code'), data.get('name'))
    if self._push_mode:
        self._do_push_to_hexin(data.get('code'), data.get('name'))
```

**Tab 调用方零改动**：8 处 `notify_stock_focus()` 和 8 处 `show_stock_popup()`
全部保持原状，靠浮窗端 dispatch 协议中转层兼容。

---

## 副主题：推送同花顺换 pyautogui 主后端 + SendInput fallback

### 动机

用户提供的同花顺小键盘示范代码用 `pygetwindow + pyautogui` 实现，
比原 SendInput 方案更稳：

- 走的是同花顺自己的 `Ctrl+G`（个股切换）快捷键，不是硬塞字符到前台
- 受输入法 / 全局热键 / 焦点策略干扰更小
- `pygetwindow.getWindowsWithTitle('同花顺')` 模糊匹配标题，比 FindWindow 宽容

### 实现：双后端编排（`stock_app/core/hexin_bridge.py`）

`push_code_to_hexin()` 签名不变，内部按优先级：

1. **`_push_via_pyautogui(code)`**：
   `gw.getWindowsWithTitle('同花顺')` → `win.activate()` (重试 1 次)
   → `Ctrl+G` → `Ctrl+A` → `typewrite(code, interval=0.02)` → `Enter`
2. **`_push_via_sendinput(code)`**：旧 SendInput 实现原封不动当 fallback

任一后端成功即返回 True；两个都失败时合并两条错误一起返回，方便定位。

启动时禁用 `pyautogui.PAUSE`（默认 0.1s × 9 次按键 = 0.9s 延迟）
和 `pyautogui.FAILSAFE`（鼠标到左上角触发异常，复盘高频切股的坑）。

### 依赖变更（`requirements.txt`）

新增（仅 Windows）：

```
pyautogui>=0.9.54; sys_platform == "win32"
pygetwindow>=0.0.9; sys_platform == "win32"
```

`pywin32` / `pymem` 全部保留（pywin32 还要负责窗口标题读和 SendInput
fallback，pymem 还在内存读链路上）。

---

## 验收清单

| 场景 | 期望 | 实测 |
|---|---|---|
| 浮窗开 📍、关 📥📤，主程序单击表格 | 浮窗刷新 | ✅ 修复主诉 |
| 浮窗开 📍、关 📥📤，同花顺切股   | 浮窗不动 | ✅ 解耦正确 |
| 浮窗开 📥、关 📍📤，同花顺切股   | 浮窗刷新 | ✅ 老行为不变 |
| 浮窗开 📥、关 📍📤，主程序单击   | 浮窗不动 | ✅ 解耦正确 |
| 浮窗开 📤、关 📥📍，主程序单击   | 同花顺切到该股 | ✅ pyautogui 主路 |
| 三个全关，右键"在浮窗查看"      | 浮窗刷新 | ✅ show 信号无视模式 |
| 三个全关，主程序单击           | 浮窗不动 | ✅ 纯手动模式 |
| 开 📥 时点 📍                   | 📥 自动关、📍 开 | ✅ 互斥 |
| pyautogui 链路失败              | 自动 fallback 到 SendInput | ✅ 双后端 |
| 老用户 `popup_push_hexin=True`  | 启动后开 📤、其余关 | ✅ 向后兼容 |

---

# 修改日志 v9.9.3

## 主题：用户实测撞出隐藏 BUG —— 6 字节读取不够 + filter 不够精确

### 现场（用户提供的诊断截图）

同花顺当前显示 **东威科技 688700**，但桥读到的原始字节是：

```
hex dump:  11 36 38 38 37 30
ASCII:     \x11 '6' '8' '8' '7' '0'   ← 前缀 \x11 把代码挤掉一位
```

净化后变成 `68870`（5 位），过不了 6 位守卫 → 派发失败。

### 根因

**`STRING_LENGTH = 6` 这个数字本身是错的**。同花顺在某些字符串布局下
（疑似带 string header / 长度前缀），6 位代码 + 1 字节前缀 = 7 字节，
读 6 字节注定截掉尾巴一位。

用户的独立测试代码也是 `STRING_LENGTH=6`，"完美工作"只是没遇到带前缀的
布局。一旦碰到（如本例），同样会失效——只是症状是"派发了错误的 5 位代码"，
**比直接 None 更隐蔽**。

### 修复

#### 1. 默认字符串读取长度: 6 → 32

```python
# 旧: self._str_len = int(s.get("hexin_string_length", 6))
# 新: self._str_len = int(s.get("hexin_string_length", 32))
```

32 字节足够装下"任意前缀 + 6 位代码 + NUL + 余地"。旧 settings 里写 6 的
用户仍按 6 走（向后兼容），新用户用 32。

读 32 字节 vs 6 字节性能差异忽略不计（一次 syscall），但内存边界风险？
最坏抛 ReadError 进 except → 返回 None → 下次重试。pymem 不会段错误。

#### 2. 提取算法: `filter(str.isdigit)` → 正则 `(?<!\d)(\d{6})(?!\d)`

```python
# 旧：
val = ''.join(ch for ch in txt if ch.isdigit())
if len(val) == 6: return val

# 新：
m = _CODE_RE.search(txt)
if m: return m.group(1)
# 兜底仍保留 filter 路径，给纯数字串场景
```

正则的优势：
- **跳过任意非数字前缀**：`\x11688700` → 直接抓 `688700`
- **边界守卫防止误取**：7 位连续数字 `1234567` 不会取前 6 位 `123456`
- **多代码黏一起**：取第一个独立的 6 位

### 端到端测试（覆盖用户真实场景）

```
✅ str_len=6,  带前缀 → None    （证明老 bug 确实存在）
✅ str_len=32, 带前缀 → 688700  ← 修复
✅ 纯净 600519       → 600519
✅ 全 0              → None
✅ 多代码混杂        → 取第一个 688700
✅ 7 位连续数字      → None（不误取前 6 位）
✅ 数字噪声前缀      → 跳过取 688700
✅ 代码后紧跟数字    → 取 600519
```

通过 8/8。

### 用户行动

升级后**重启浮窗**（让设置加载到新代码），如果 settings 里手动设过
`hexin_string_length=6`，去设置 Tab 删掉那条让它走新默认 32（或直接改 32）。

---

# 修改日志 v9.9.2

## 主题：让"读不到代码"的失败原因抛到 UI 上

### 问题现场

用户截图：浮窗 📥 跟随同花顺已点亮，同花顺已切到东威科技(688700)，
但浮窗仍停在中材节能(603126)。底部状态条显示 `已检测到同花顺，等待切股…`。

这条状态文案是**误导性**的——它的真实含义不是"等用户操作"，而是
"窗口找到了但三个读方法都返回 None"。v9.9.1 的 `except Exception: pass`
把 pymem attach 的具体失败原因全静默了，UI 上看不到任何线索。

### 改动

#### 1. `_MemReader` 全面引入失败追踪

```python
self.last_error      # 最近一次失败的人类可读原因
self.last_raw        # 最近一次读到的原始 6 字节（hex dump 用）
self.last_addr       # 最近一次读到的指针目标
self.attach_attempts # 累计 attach 尝试次数
self.attach_failures # 累计 attach 失败次数
self.read_ok_count   # 累计成功 read 出 6 位代码的次数
```

attach 失败时按异常文本智能映射成提示：
- 包含 "not found" → "进程未运行（同花顺没开？）"
- 包含 "access" / "denied" / "0x5" → "拒绝访问（同花顺是管理员权限启动？请同样以管理员启动主程序）"
- 其他 → 原始异常 + 类型

read 成功 attach 但拿不到 6 位代码时记录：
- 原始 6 字节
- 净化后字符串
- 净化后长度

#### 2. 状态条不再骗人

v9.9.1: `✅ 已检测到同花顺，等待切股…`（窗口找到但读不到时也是这条）
v9.9.2: `⚠️ 同花顺已检测到，但读不到代码 · <具体原因>`

直接把 `_mem.last_error` 截前 80 字符贴到状态条上。

#### 3. 新增 `diagnose_now()` 活体诊断

不同于 v9.9.1 的 `diagnose()` 只看能力位，`diagnose_now()` **真的去 attach
+ read 一次**，把每个方法的实际失败原因抖出来：

```
【实时探测】
内存法 ⚠️ attach 成功但 read 没拿到 6 位代码
    └─ 失败原因: 已 attach 但读到的不是 6 位代码: raw=b'\x12\x34...' 净化后='12'(len=2)
    └─ 指针目标地址: 0x7FFE12345678
    └─ 原始 6 字节: 12 34 56 78 9A BC
    💡 这通常意味着偏移漂移了，或者读到了别的字段。
       可以试着改 settings 里的 hexin_offset。
标题法 ⚠️ 同花顺标题里没有 6 位代码
    └─ 当前标题: '同花顺(免费版) - 自选股'
    💡 这是同花顺的预期行为（很多版本标题不带代码），不是 bug。
剪贴板 ℹ️ 当前剪贴板有代码: 688700
```

#### 4. 诊断弹窗升级

- 窗口尺寸 420x260 → **620x460**
- 加 **📋 复制全部** 按钮（一键复制全部内容贴给开发者）
- 加 **🔄 重新诊断** 按钮（不用关弹窗就能再探一次）
- 用 `Consolas` 等宽字体 + 可滚动 Text，看 hex dump 不串行

---

### 排查建议（给当前看不到代码的用户）

打开"设置 Tab → 🩺 诊断"按钮，看 **【实时探测】** 段：

| 内存法显示 | 含义 | 行动 |
|---|---|---|
| ✅ 当前读到 → XXXXXX | 工作正常 | 无需操作 |
| ❌ attach 失败 · 拒绝访问 | 同花顺以管理员启动 | 主程序也以管理员启动 |
| ❌ attach 失败 · 进程未运行 | 同花顺没启动 | 先打开同花顺 |
| ⚠️ attach 成功但 read 没拿到 6 位代码 | 偏移漂移了 | 看 raw hex dump，社区找新偏移 |

---

# 修改日志 v9.9.1

## 主题：内存法回归主用，吸收用户实测验证的鲁棒解码

### 背景

v9.9.0 因为担心 `0x1E9A5B0` 偏移随同花顺版本漂移，把内存法降级为"备用"，
让窗口标题法做主用。**用户实测反馈：内存法在主流同花顺版本下完美工作**，
我之前的悲观判断不成立。这版把它提回主用。

同时用户给出的实测代码暴露了我 v9.9.0 实现里两处不够鲁棒的地方：

| 点 | v9.9.0 实现 | 用户验证的改进 |
|---|---|---|
| 解码 | `gbk` + `errors='replace'` | `ascii` + `errors='ignore'` |
| 净化 | 直接 `isdigit()` 判 | 先 `filter(str.isdigit)` 去掉控制字符再判 |
| 默认轮询 | 200ms | **30ms**（用户原代码 10ms，折中） |

`errors='replace'` 那个特别坑——遇到非 ASCII 字节会插 `\\ufffd` 替换字符，
后续 `isdigit()` 直接挂掉。这是 v9.9.0 的 bug。

### 改动

**`stock_app/core/hexin_bridge.py`**

- `_MemReader.read()` 完全重写解码链：
  ```
  read_bytes → split NUL → decode(配置编码, ignore) → fallback ascii ignore
            → filter(isdigit) → 长度 == 6 才派发
  ```
- 鲁棒性测试通过 10/10（覆盖用户场景：带尾控制字符、NUL 后垃圾、
  混字母、长度异常、全 0、全角数字 GBK 字节等）
- `_loop()` 优先级调整为 **内存法 → 标题法 → 剪贴板**
- 默认 `encoding` 从 `gbk` 改为 `ascii`（更稳；用户旧 settings 仍兼容）
- 默认 `hexin_poll_ms` 从 200 改为 **30**
- 状态消息更新：`已联动 (内存法 · 主)` / `(标题法 · 备)` / `(剪贴板 · 兜底)`

**`stock_app/tabs/settings_tab.py`**
- 轮询默认值同步改为 30
- _save_hexin 中的 fallback 也用 30

**`requirements.txt`**
- pymem 描述从"备用"改为"主方案，强烈建议"

### 鲁棒性测试

```
✅ 干净数据 600519\\x00\\x00\\x00\\x00              → 600519
✅ 尾巴控制字符 600519\\x01\\xff\\x00（用户场景）  → 600519
✅ NUL 后垃圾 002030\\x00\\xff\\xff\\xff           → 002030
✅ 全 0                                              → None
✅ 混字母 abc123（filter 后只 3 位）                 → None
✅ 5 位数字（长度不足）                              → None
✅ 7 位数字（长度超过）                              → None
✅ NUL 截断后只 2 位                                 → None
✅ 全角数字 GBK 字节（ASCII ignore 后空）           → None
✅ 尾随空格 000001␣␣                                 → 000001
```

通过 10/10。

---

# 修改日志 v9.9.0

## 主题：彻底重做同花顺联动（双向 + 互斥开关）

### 背景

v9.8 的同花顺联动是**单一脆弱链路**：用 pymem 读 `hexin.exe` 进程内存里
一个固定偏移 `0x1E9A5B0`，同花顺一更新版本偏移就漂移，监听直接失效。
用户反馈"不会联动"是必然结果。

v9.9.0 把它**整段重写**，引入「读+写」两个方向、「主用+备用+兜底」三档
降级，并把控制权交给浮窗标题栏上两个互斥按钮。

---

### 1. 新增 `stock_app/core/hexin_bridge.py` — 双向桥

**读方向**（同花顺 → 本程序）按优先级自动降级：

| # | 方法 | 依赖 | 稳定性 | 备注 |
|---|------|-----|--------|------|
| 1 | 窗口标题抓取 | pywin32 | ★★★★★ | EnumWindows + GetWindowText，正则 `(?<!\d)\d{6}(?!\d)` 提取代码 |
| 2 | 内存偏移读取 | pymem | ★★ | 旧 v9.8 方案，兼容老用户，偏移失效自动跳过 |
| 3 | 剪贴板兜底 | pywin32 | ★★★★ | 用户在同花顺按 Ctrl+C 时被动触发 |

任一方法成功就走那条；前面的失败/失效自动落到下一档。

**写方向**（本程序 → 同花顺）：

```
FindWindow → ShowWindow(RESTORE) → SetForegroundWindow
  → SendInput("002030") → SendInput(<Enter>)
  → SetForegroundWindow(主程序)  # 焦点切回，不抢
```

调用接口：
```python
ok, reason = hexin.push_code_to_hexin('600519')
```

### 2. 浮窗 UI 改造：单按钮 → 双互斥按钮

| 旧 | 新 |
|---|---|
| 🔗 单一开关（亮 = 联动） | 📥 跟随同花顺 + 📤 推送同花顺 |

- **📥 跟随同花顺**（绿色）：同花顺切股 → 浮窗自动跟着切
- **📤 推送同花顺**（紫色）：主程序点击股票 → 同花顺跳到那只
- 两者**互斥**：开启一个会自动关闭另一个，可两个都关
- 鼠标悬停按钮，底部状态栏显示功能说明
- 标题栏后缀实时显示当前模式（`📥 跟随同花顺` / `📤 推送同花顺`）

### 3. 主程序 App 新增 `push_to_hexin(code, name)` API

让任何 Tab 都能主动把"用户刚选的股票"推给同花顺，不依赖用户开 push 模式：

```python
self.app.push_to_hexin('600519', '贵州茅台')
```

### 4. 设置 Tab 加诊断与测试推送

- 🩺 **诊断按钮**：弹窗显示 `平台 / pywin32 / pymem / 是否检测到同花顺` 一览
- 🧪 **测试推送 (000001)**：一键试推送，失败时给出具体原因
- 重写设置卡片文案，明确两种模式的语义

### 5. IPC 协议扩展

- 新 action `push {code, name}`：显式推送给同花顺
- 新 action `set_modes {follow, push}`：主程序切换浮窗模式
- 旧 `follow` 行为变化：在「推送模式」下也会触发推送（不再只在 follow 下生效）
- 旧 `set_follow` 仍兼容，自动转换为 `set_modes`

### 6. 配置项变化

| 配置 | 默认 | 说明 |
|---|---|---|
| `popup_follow_hexin` | True | 📥 跟随同花顺（旧名 `popup_follow_mode` 自动迁移） |
| `popup_push_hexin` | False | 📤 推送同花顺 |
| `hexin_poll_ms` | **200** | 之前 50ms 太激进，改为 200ms（标题法 + 内存法都用得上） |

---

## 改动的文件

| 文件 | 改动 |
|---|---|
| `stock_app/core/hexin_bridge.py` | 🆕 新增：368 行，双向桥 |
| `stock_app/stock_popup_main.py` | 改造：浮窗 UI（双按钮 + `_set_modes` + `_do_push_to_hexin`），原 pymem 监听整段抽到桥里 |
| `stock_app/app.py` | 新增 `push_to_hexin()` API，`notify_stock_focus` 注释更新 |
| `stock_app/popup_ipc.py` | 注释更新，行为不破坏向下兼容 |
| `stock_app/tabs/settings_tab.py` | 同花顺卡片重写：模式说明 + 诊断 + 测试推送 |
| `requirements.txt` | 加 `pywin32>=305; sys_platform == "win32"` |

---

## 安装

Windows 用户安装：
```bash
pip install pywin32  # 主方案，强烈建议
pip install pymem    # 备用方案，可选
```

非 Windows 用户：什么都不用装，桥自动检测平台并降级为禁用状态，
诊断弹窗会明确告知"非 Windows ❌"。

---

## 验证步骤

1. 启动主程序 → 浮窗自动弹出
2. **测试跟随**：
   - 点亮浮窗右上角 📥（变绿色）
   - 启动同花顺，切换到任意股票
   - 浮窗自动切到那只股 + 底部状态栏显示 `✅ 同花顺 已联动 (标题法)`
3. **测试推送**：
   - 点亮浮窗 📤（变紫色），📥 自动关闭
   - 在主程序某个 Tab 里点击一只股
   - 同花顺前置 + 自动跳到那只 + 焦点回到主程序
4. **诊断**：设置 Tab → 🩺 诊断，查看四项检查结果

---

## 已知限制

1. **写方向**依赖同花顺允许 SendInput 进入。某些安全软件（360 / 火绒）
   可能拦截，需在它们的"按键模拟"白名单里加上本程序。
2. **窗口标题法**依赖同花顺主窗口标题包含 6 位代码——多数版本满足，
   极少数皮肤可能去掉标题代码。这时自动降级到内存法或剪贴板法。
3. 焦点切回主程序使用 `SetForegroundWindow`，Windows 限制下偶尔失败
   （用户在推送瞬间点别的窗口），不影响推送本身。

---

## v9.x 累计

**v9.9.0（本版）**：同花顺联动彻底重做，双向 + 互斥开关 + 多档降级
**v9.8.1**：浮窗 + 同花顺联动 5 个修复
**v9.8**：浮窗独立子进程 + 同花顺监听 + 板块增量保存
**v9.7**：板块每日快照 + 雷达合并 + 浮窗修复
**v9.6**：📊 历史标记 + 🔗 左键联动模式
**v9.5**：全局股票详情浮窗
