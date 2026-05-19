# 程序化分析 · AI 涨停复盘工作台

> 在量化策略一秒扫完全市场的今天,手动盘最稀缺的不是信息,而是**单位时间内形成结构化结论的速度**。
> 这是一个用 AI + Agent 协同把手动盘"扫盘 → 归因 → 联动校验 → 决策推送"压缩进秒级的桌面工作台。

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

---

## ✨ 核心特性

### 🧠 五段式 AI 推理引擎
让 LLM 严格按 ①核心业务 → ②市场主要上涨共识 → ③次要共识 → ④同逻辑联动标的 → ⑤板块事件共识 五段输出,每段强制 `【关联原因】` 与 `【传播来源类型】` 元信息标注。把发散的 AI 输出变成可对账的结构化字段。

### 🔗 同花顺双向桥(Windows)
- **写方向**:`WriteProcessMemory + WM_HEXIN_PUSH (0x490)` 自定义消息直写同花顺进程内存,**不抢焦点 / 不被杀软拦截 / 不要求前台**
- **读方向**:进程内存偏移读取当前股票,毫秒级响应
- **防回环**:双层 push-silencer(全局 10s ttl + 浮窗本地 lock),杜绝自激回声

### 📊 三层 Agent 协同
| Agent | 职责 |
|---|---|
| 归因 Agent | 单股深度推理,产出五段结构化结论 |
| 抽取 Agent | 正则 + NER 从结论里提取联动标的代码 |
| 校验 Agent | 实时行情接口回填,验证 AI 联动结论与盘面真实走势的吻合度 |

三层串联形成**自反馈闭环**——错判会被次日表现记录,沉淀为 prompt 调优依据,系统越用越准。

### 🪟 常驻浮窗工作台
- 无边框 Toplevel 窗口,始终置顶
- 顶部联动股 2×3 网格,一眼看清同主线标的
- 所有 6 位股票代码渲染成蓝字下划线,**点击即推送同花顺**,带 80ms 字号放大微交互
- 支持最小化折叠成 32px 标题条
- **Ctrl+Z** 回退浮窗历史 50 步(同花顺同步回退)
- **F1** 显隐 / **F2** 折叠 / 12 个快捷键全部可在设置自定义

### 🗂 9 个 Tab 覆盖完整工作流
单股深度分析 · 批量扫盘(多 Key 并发)· 板块复盘 · 龙头梯队 · 自选监控 · 雷达预警 · 历史回放 · API/Prompt 管理 · 设置

---

## 📸 截图

> 把你的截图放到 `docs/screenshots/` 目录下,这里就能展示

| 主界面 | 浮窗 |
|---|---|
| ![main](docs/screenshots/main.png) | ![popup](docs/screenshots/popup.png) |

---

## 🚀 快速开始

### 1. 环境要求
- Python **3.8+**(推荐 3.10/3.11)
- Windows 10/11(同花顺联动功能需要;其它平台可用核心 AI 分析)
- 4GB 以上内存

### 2. 克隆并安装

```bash
git clone https://github.com/你的用户名/你的仓库名.git
cd 你的仓库名

# 推荐用虚拟环境
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt
```

### 3. 配置 API Key

启动后在 **"⚙️ API 设置" Tab** 里填入:

- **千帆 API Key**:[百度千帆控制台](https://console.bce.baidu.com/qianfan/) 获取,形如 `bce-v3/ALTAK-xxx/yyy`
- **火山方舟 API Key**(可选):[火山引擎控制台](https://console.volcengine.com/ark) 获取

> 选千帆是因为综合权衡后,A 股舆情语境下中文金融垂类的搜索质量最优——这是结论质量的上限。

> 💡 配置自动保存到 `data/config/config.json`,**该文件已在 `.gitignore` 中,不会进 git**。

### 4. 启动

```bash
python main.py
```

---

## 🔧 可选:同花顺联动配置

仅 Windows,需要同花顺已经登录运行。

### 安装额外依赖
```bash
pip install pywin32 psutil pymem
```

### 联动能力一览
- **📥 跟随同花顺**:浮窗顶栏开关,在同花顺切股时浮窗自动跟随
- **📤 推送同花顺**:主程序 / 浮窗里点击任意蓝字股票代码,同花顺秒级切股
- **🔁 防回环**:本程序推送的代码不会触发浮窗自身回声刷新

### 常见问题
**Q: 点蓝字没反应?**
A: ① 确认同花顺已启动登录;② 同花顺以管理员启动时,本程序也要以管理员启动;③ 部分杀毒软件会拦截 `WriteProcessMemory`,加入白名单。

**Q: 浮窗读不到同花顺当前股票?**
A: 同花顺主程序版本不同,内存偏移可能漂移。在"⚙️ 设置 → 同花顺联动"里运行诊断,根据提示调整 `hexin_offset`。

---

## ⌨️ 默认快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+Enter` | 单股搜索触发 |
| `Ctrl+L` | 清空当前 Tab 日志 |
| `Ctrl+Z` | 回退浮窗上一只股(同花顺同步回退) |
| `F1` | 显示 / 隐藏浮窗 |
| `F2` | 最小化 / 复原浮窗 |
| `Ctrl+1` ~ `Ctrl+8` | 切换 Tab |

全部可在 **"⚙️ 设置 → ⌨️ 快捷键"** 自定义,保存即生效不需重启。

---程序化分析/
├── main.py                      # 入口
├── requirements.txt
├── README.md
├── CHANGELOG.md                 # 详细版本日志
├── .gitignore
└── stock_app/                   # 核心包
├── app.py                   # 主 App + 快捷键调度
├── popup_window.py          # 常驻浮窗
├── widgets.py               # 通用 UI 组件 + 蓝字 link 工具
├── bus.py                   # 事件总线
├── core/                    # 内核
│   ├── api_client.py        # 千帆 / 火山 API 客户端
│   ├── hexin_bridge.py      # 同花顺双向桥
│   ├── config.py            # 配置管理
│   ├── paths.py             # 路径常量
│   ├── theme.py             # 主题
│   ├── history.py           # 历史记录
│   ├── tag_relation.py      # 标签关联度计算
│   └── ...
└── tabs/                    # 9 个功能 Tab
├── single_tab.py        # 单股分析
├── batch_tab.py         # 批量扫盘
├── sector_tab.py        # 板块复盘 + 龙头梯队
├── my_sectors_tab.py    # 自选股 / 自定义板块
├── radar_tab.py         # 雷达预警
├── replay_tab.py        # 历史回放
├── history_tab.py       # 历史记录管理
├── api_tab.py           # API & Prompt 管理
└── settings_tab.py      # 设置---

## 🛠 技术栈

| 类别 | 用什么 |
|---|---|
| GUI | Tkinter + ttk(零额外依赖) |
| AI API | 百度千帆(主)/ 火山方舟(备) |
| HTTP | requests + urllib3 |
| 数据 | pandas + openpyxl |
| 行情 | 腾讯财经接口 |
| Windows 集成 | pywin32 + pymem + psutil |
| 图像 | Pillow |

---

## 🗺 Roadmap

- [ ] 自定义 prompt 模板可视化编辑
- [ ] 板块联动图(力导向布局)
- [ ] 多账户隔离 & 云端 sync 选项
- [ ] 通达信适配(目前仅同花顺)
- [ ] Webhook 推送(把信号推到企业微信 / Telegram / Discord)
- [ ] 本地大模型支持(Ollama / vLLM)

欢迎在 Issues 里提需求。

---

## 🤝 贡献

PR 与 Issue 都欢迎。本项目坚持几个原则:

1. **数据本地化**:用户的密钥、配置、历史记录绝不离开本地
2. **手动盘友好**:任何特性都要服务"人是最终决策者"这个前提,不做自动交易
3. **工程整洁**:每个 Tab 独立模块、共享 widgets/core,避免改一处崩三处

提 PR 前请先开 Issue 讨论方向,避免白做。

---

## ⚠️ 免责声明

- 本项目**仅供学习交流与个人复盘使用**,所有分析输出均为 AI 生成,**不构成任何投资建议**
- 股市有风险,任何基于本工具的交易决策由使用者本人承担
- 同花顺联动通过公开接口与公开内存偏移实现,仅供个人使用,**严禁用于商业代理、撞库、批量爬取等违反同花顺用户协议的用途**
- 大模型 API Key 由用户自备,使用产生的费用由 Key 所有者承担

---

## 📜 协议

本项目采用 **MIT License** 开源。---

## 🛠 技术栈

| 类别 | 用什么 |
|---|---|
| GUI | Tkinter + ttk(零额外依赖) |
| AI API | 百度千帆(主)/ 火山方舟(备) |
| HTTP | requests + urllib3 |
| 数据 | pandas + openpyxl |
| 行情 | 腾讯财经接口 |
| Windows 集成 | pywin32 + pymem + psutil |
| 图像 | Pillow |

---

## 🗺 Roadmap

- [ ] 自定义 prompt 模板可视化编辑
- [ ] 板块联动图(力导向布局)
- [ ] 多账户隔离 & 云端 sync 选项
- [ ] 通达信适配(目前仅同花顺)
- [ ] Webhook 推送(把信号推到企业微信 / Telegram / Discord)
- [ ] 本地大模型支持(Ollama / vLLM)

欢迎在 Issues 里提需求。

---

## 🤝 贡献

PR 与 Issue 都欢迎。本项目坚持几个原则:

1. **数据本地化**:用户的密钥、配置、历史记录绝不离开本地
2. **手动盘友好**:任何特性都要服务"人是最终决策者"这个前提,不做自动交易
3. **工程整洁**:每个 Tab 独立模块、共享 widgets/core,避免改一处崩三处

提 PR 前请先开 Issue 讨论方向,避免白做。

---

## ⚠️ 免责声明

- 本项目**仅供学习交流与个人复盘使用**,所有分析输出均为 AI 生成,**不构成任何投资建议**
- 股市有风险,任何基于本工具的交易决策由使用者本人承担
- 同花顺联动通过公开接口与公开内存偏移实现,仅供个人使用,**严禁用于商业代理、撞库、批量爬取等违反同花顺用户协议的用途**
- 大模型 API Key 由用户自备,使用产生的费用由 Key 所有者承担

---

## 📜 协议

本项目采用 **MIT License** 开源。

## 📁 项目结构

MIT License
Copyright (c) 2026 你的名字
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
> 不喜欢 MIT 想要更严格的可以换 GPL-3.0 / Apache-2.0,Issue 留言告诉我。

---

## 💬 联系

- 提 Issue:[GitHub Issues](https://github.com/你的用户名/你的仓库名/issues)
- 邮箱:`2801320619q@gmail.com
`(可选)

---

**⭐ 如果这个项目对你有帮助,Star 一下是最好的鼓励。**
