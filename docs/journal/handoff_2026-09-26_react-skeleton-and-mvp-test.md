# 交接：React 迁移第 1 步完成 + MVP 人工测试闭环（2026-09-26）

> 接手人请先读 `docs/journal/_index.md` 回溯，再读本文。
> 一句话状态：**MVP 人工测试已完成（8✓/#6 坐实 bug/#8 待补测）；React 骨架 DoD 7/7 全过、
> 视图 1（技能手册）迁移完成且 A/B 无差异；迁移第 2 步进行到"下一个：算例库"。**

## 一、今天发生的事（按序）

1. **技术栈裁决输入**：MVP 调试期崩溃后，产出《docs/MVP崩溃后技术栈评估与建议.md》——
   结论"MVP 毕业而非失败"，三步走迁移（骨架先行 → 逐视图 → MVP 存档），张老师裁决启动第 1 步。
2. **MVP 人工测试 10 条完成**（结果已由张老师标注在 `docs/MVP人工测试指引.md`，正式记录在
   `2026-09-26-mvp-manual-test-results.md`）：`1-5✓ 6✗ 7✓ 8未完成 9✓ 10✓`。
3. **React 骨架落地**（`docs/React骨架_完成标志与验证清单.md` = DoD 定义 + 验收清单），
   张老师确认**全部通过**（`2026-09-26-react-skeleton-dod-passed.md`）。
4. **视图 1 技能手册迁移 + A/B 通过**（`2026-09-26-view1-skills-migration-ab.md`）。

## 二、关键事实与裁决（接手必读）

- **Agent 循环在网关侧**（2026-09-25 裁决）：模型输出的工具参数经 `agent.py::_parse_args`
  仅 `json.loads`，**无客户端 schema 校验**，原样进 `proxy.call_tool`（契约 3 位置）；
  `llm.py` 调 LLM 未开 strict。⇒ **对话路径触发契约违规不可靠**（模型会拒绝/修正/改道），
  确定性路径 = HTTP 直构 `POST /sessions/{sid}/tools/call`（同走 `call_with_contracts`，
  api.py:437），命令见 `docs/MVP测试_契约拦截示例.md` 路径 B。React 版验收应以 HTTP 直构为准绳。
- **★ 母线编号口径（长期有效）**：surge 报 **Matpower 1-based** 母线号（Bus 31=slack=0.9820 pu），
  项目基线经 pandapower `from_mcp` 为 **0-based 索引**（母线 30），恒差 +1。跨引擎对数先统一口径。
- **#6 是真 bug（未诊断）**：登记真实存在的项目外文件
  `C:\Users\Z\Downloads\_科研项目\case5.m` → 400「算例文件不存在」而非 409 围笼拦截。
  已核实：文件存在（mtime 2025-05-29）、venv Python `exists()=True`、
  前端 trim（mvp.html）/服务端 strip（api.py:612）均正常 ⇒ 疑点在**到达网关的字符串**
  （不可见/全角字符/引号——400 回显视觉上无法分辨）或网关运行时环境。
  **诊断命令已写在 journal**：curl 直 POST 同路径，201 ⇒ 输入侧问题；400 ⇒ 网关运行时问题。
- **DOM 对照方法论**：dump-dom 会把页内 `<script>` 模板串计入 class 匹配
  （MVP 23 vs React 22 的"差异"实为 `${esc(s.name)}` 模板串）——DOM 计数必须剔除脚本内容。

## 三、未决事项（按优先级）

| # | 事项 | 状态 | 入口 |
|---|---|---|---|
| 1 | **#6 登记误报 bug** 诊断 | curl 二分复现一条命令，见上 | journal mvp-manual-test-results |
| 2 | **#8 契约拦截补测**（A 方案） | curl 路径 B，5 分钟 | docs/MVP测试_契约拦截示例.md |
| 3 | **视图 2：算例库迁移** | 未开始；含围笼 409 分支（依赖 #6 修复或并行确认） | 顺序：算例库 → 对话+校验层 |
| 4 | 测试基线 ≈501 passed 待复跑确证 | 沿用上期交接 | 旧 handoff |
| 5 | opendss 根因已定位、修复未做 | 冻结中 | 2026-09-25 journal |

## 四、环境踩坑档案（本机迁移/重装时必读）

- **npm 不可直呼**：`npm.cmd` 触发 WSL shim 被沙箱拦截 →
  `"C:/Users/Z/.workbuddy/binaries/node/versions/22.22.2-3/node.exe"
  .../npm/bin/npm-cli.js` 直调；
- **@testing-library/dom@^10.5.0 不存在**（最新 10.4.0）→ package.json 已锁 10.4.0；
- **esbuild postinstall `spawnSync EBUSY`**（沙箱）→ 重试即可过；
- **平台二进制包是 optionalDependencies，中断安装会静默缺失** → 显式补装
  `@esbuild/win32-x64@0.21.5` + `@rollup/rollup-win32-x64-msvc@4.63.5`（须与
  esbuild/rollup 版本精确匹配），网络不通挂 VPN 代理 `--proxy http://127.0.0.1:10090`；
- **guard cwd 陷阱**：`frontend/` 下用 `npm run guard`（内部 `python ../tools/...`）；
  `python tools/...` 只能在项目根敲；
- **DoD 文档已修正**：`frontend/react/src` 假路径残留已改为 `frontend/src`，
  原始色扫描须排除生成物 `styles/tokens.css`（86 处合法 hex）。

## 五、仓库状态（截至本 handoff）

- HEAD = `6f5d454`（ANDES 接入工具面），未新增提交；
- **未提交（改动）**：`gateway/run_gateway.cmd/.sh`（路径围笼扩围，上期遗留）、
  `docs/MVP人工测试指引.md`（张老师的测试标记）、`docs/journal/_index.md`；
- **未提交（新增）**：今天全部产出——3 份 docs、7 份 journal、
  `frontend/` React 骨架全套（package.json/vite.config.ts/tsconfig/tailwind+postcss 配置/
  index.html/src{main,App,api,index.css,App.test,test-setup}/.gitignore/package-lock.json；
  `node_modules/`、`dist/` 已 ignore）；
- `examples/` 仍未纳入版本控制（历史遗留，未动）；
- **建议**：今天产出较多，建议单独提交 `frontend/` 骨架 + 文档（提交前跑
  `npm run build && npm run guard && npx vitest run` 三连确认绿）。

## 六、快速验证命令（接手自检）

```bash
# 前端三连（frontend/ 下）
npm run build && npm run guard && npx vitest run
# 网关（项目根）→ 后开 MVP 与 React 页对照
cd gateway && ./run_gateway.sh
# MVP: http://127.0.0.1:8765/ui/mvp.html   React dev: http://localhost:5173
# 后端测试基线（≈501 待复跑）
cd gateway && ../PowerMCP/.venv/Scripts/python.exe -m pytest -q -m "not integration" \
  -p no:cacheprovider --basetemp=./.pytest_tmp/rN
```

## 七、下游依赖提示

- `PowerSkills/` 仍在 `fix/pypsa-pandapower-api-drift`（PR #8），**用户指令冻结**；
- `PowerMCP/` 在 `fix/pandapower-deepcopy`；运行环境 `PowerMCP/.venv`（Python 3.12.6）。
