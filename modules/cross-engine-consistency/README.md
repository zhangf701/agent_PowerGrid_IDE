# cross-engine-consistency

跨引擎一致性与算例转换保真度

由 `create_module` 脚手架生成，**默认 L0 声明式** —— 只需编辑 `module.yaml` 即可开工。

| 目录 | 用途 | 何时需要 |
|---|---|---|
| `prompts/` | 选题专属提示词 | L0（可选） |
| `schema/` | 实体与结果表的结构定义 | L1 |
| `checks/` | 领域自检规则（区别于 8 类**接口**契约） | L0（可选） |
| `templates/` | 报告模板 | L0（可选） |
| `ui/` | React 组件 | **L2 才需要** |

## 三层成熟度

- **L0 声明式**：仅 `module.yaml` —— 多数选题到此为止。
- **L1 数据式**：加 `entities` / `result_tables` + schema 文件，内核自动渲染成表与图。
- **L2 组件式**：加 `ui/` 下的 React 组件，经槽位注入。

## 硬约束

- ❌ 不得访问 `PowerMCP/`
- ❌ 不得绕过网关直连 MCP server
- ❌ 不得写 `~/.powermcp/`
- ❌ 不得 import 内核内部模块
