# 单文件 MVP 人工测试指引（2026-09-25）

> 按张老师裁决：MVP 保留，**先人工测试再定后续**。本文件是测试步骤与验收清单；
> 测完把结果（哪条 ✓ / 哪条 ✗ / 现象）发给助手，据此决定 MVP 去向与 React 是否起步。

## 一、启动（三步）

### 1. 设置 LLM 密钥（只需一次，当前会话有效）

```bash
# git-bash / bash：
export POWERMCP_LLM_API_KEY="sk-你的DeepSeek密钥"
```

或双击 `gateway\run_gateway.cmd` 前在系统环境变量里设置（密钥不进代码、不落盘）。

### 2. 启动网关（二选一）

```bash
# 方式 A：bash（推荐，日志直接在终端）
cd /d/coding/powerMcp_Pskills/gateway && ./run_gateway.sh

# 方式 B：资源管理器双击 gateway\run_gateway.cmd
```

启动脚本会自动设置**路径围笼**（`POWERIO_MCP_ALLOWED_ROOTS` = 项目根，
已实测可读 `examples/data/` 与 `GridData/MatpowerData/`，见 journal）。
看到 `Uvicorn running on http://127.0.0.1:8765` 即成功。

### 3. 打开 MVP

浏览器访问：<http://127.0.0.1:8765/ui/mvp.html>（必须走这个地址——同源，用 `file://` 打开会被跨源拦截）。

## 二、测试清单（按顺序，预计 10 分钟）

| # | 测什么 | 怎么测 | 预期 |
|---|---|---|---|
| 1 | 页面渲染 | 打开页面 | 无白屏；顶部有校验层状态条 |
| 2 | 环境就绪 | 环境面板 | Python/网关版本、LLM `api_key_set: true`；**不显示**密钥本体 |
| 3 | 技能手册 | 技能面板 | 能看到 surge 等技能与 escalation triggers；ltspice 标记"缺 escalation 表" |
| 4 | 算例登记 | 登记一个算例：路径填 `D:\coding\powerMcp_Pskills\examples\data\case39.m` | 200 登记成功；显示 sha256 与标签 |
| 5 | 算例解析 | 对已登记算例点"解析" | **首次约 5–10 秒**（真实拉起 powerio）；完成后可看 IR / 诊断（case39 诊断应为 0 条） |
| 6 | 围笼拦截（反向） | 登记一个项目外路径的算例（如 `D:\某其他目录\xxx.m`）再解析 | 409，提示"不在允许根内" |
| 7 | 对话 + 工具 | 对话输入"加载 case39 并做基态潮流，告诉我最低电压" | 流式回答；出现 `tool_call` 事件（surge.load_network / run_power_flow）|
| 8 | 契约拦截 | 故意让模型调工具但删掉必填参数（或直接观察） | 违规时状态条出现 `contract_violation`，且调用**未转发** |
| 9 | 模块提示词 | 对话里问"你现在带着哪个选题模块的提示词？" | 回答能体现 n1-ranking / cross-engine-consistency 的工作流要点（G-4 新能力）|
| 10 | 禁用模块自证 | 把 `modules/` 临时改名 → 重启网关 → 重复 #2/#7 | 内核全部照常（无模块 = 正常状态）|

## 三、已知预期行为（不是 bug）

1. **首次对话等十几秒才开始出字** —— `/chat` 每轮要真实拉起 MCP server（根因 T6-M5，
   归子项目 4）。界面会显示"正在准备工具面"提示。
2. 部分未配置的 server（andes/egret/hope/genx/powerworld…）拉不起来 → 顶部出现
   **notice**"N 个 server 未拉起，本轮工具面不完整" —— 这是**设计内**的如实上报。
3. 网关 `notes` 字段含 markdown 星号，界面按原样显示 —— 待最小 markdown 渲染。
4. 本机 Gurobi 许可过期（2026-03-31）→ 涉及 Gurobi 的操作必然失败，与 MVP 无关。

## 四、调试模式（出问题时用）

| URL | 用途 |
|---|---|
| `http://127.0.0.1:8765/ui/mvp.html?selftest=1` | 渲染自检（不连 SSE） |
| `http://127.0.0.1:8765/ui/mvp.html?nosse=1` | 轻量模式（不用流式） |
| `http://127.0.0.1:8765/ui/mvp.html?dark` | 深色主题 |
| `http://127.0.0.1:8765/ui/preview.html` | 设计令牌预览 |

## 五、反馈方式

把每条编号的结果记下来即可，例如：`1✓ 2✓ 3✓ 4✓ 5✗（现象：…）6✓ …`。
现象尽量带上：**浏览器控制台报错截图**（F12）+ 网关终端最后几行日志。
