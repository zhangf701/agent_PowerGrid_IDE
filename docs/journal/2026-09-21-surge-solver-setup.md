# surge 求解器配置记录（HiGHS / Ipopt）

- **日期**：2026-09-21
- **起因**：审计发现 surge 的 OPF 相关工具与脚本全部不可用，原因是缺 HiGHS / Ipopt 的 **C 共享库**（`pip install highspy` 不提供）
- **前置**：[PowerSkills 审计报告](2026-09-21-powerskills-audit.md)

---

## 一、⚠️ 首先更正一处我先前的错误结论

本轮我曾判断「`references/API_REFERENCE.md` 缺 5 个工具，SKILL.md 声称的 *44-tool catalog* 不实」。

**该结论是错的。** 原因是我的提取正则 `^### \`([a-z_][a-z0-9_]*)\(` **只取了每个标题里的第一个工具名**，而该文档把同类工具**合并写在同一个标题下**：

```markdown
### `remove_bus(number)` / `remove_branch(...)` / `remove_generator(id)` / `remove_load(bus, load_id="1")`
### `set_generator_limits(id, pmax_mw, pmin_mw)` / `set_generator_in_service(id, in_service)`
### `scale_loads(factor, area=None)` / `scale_generators(factor, area=None)`
```

**修正后的实测**：

```
API_REFERENCE 覆盖的工具 : 44 个  (标题行 39 条)
surge server 实际工具    : 44 个
文档缺失: 无 ✓     文档多出: 无 ✓
```

**结论：`API_REFERENCE.md` 完整覆盖全部 44 个工具，无需修复。** SKILL.md 的 "44-tool catalog" 说法**准确**。

> 该错误结论**未进入任何文档**，仅在对话中提出，已在此更正。

---

## 二、环境变更

新建**专用 conda 环境**（未改动 `base`，完全可逆 —— 删除环境即可还原）：

```bash
conda create -n powersolvers -c conda-forge highs ipopt --yes
```

| 项 | 值 |
|---|---|
| 环境路径 | `C:\Users\Z\.conda\envs\powersolvers` |
| 库目录 | `...\Library\bin` |
| `highs.dll` | 8.67 MB（conda highs 1.15.1，与 highspy 1.15.1 同版） |
| `ipopt-3.dll` | 2.92 MB（conda ipopt 3.14.20，属 surge 要求的 3.x） |
| 附带依赖 | `dmumps/zmumps/smumps/cmumps.dll`、`libblas.dll`、`sipopt-3.dll` 等 |

**手工添加的别名**（诊断用，未解决问题）：`ipopt.dll`、`libipopt.dll` —— 均为 `ipopt-3.dll` 的副本。

---

## 三、实测结果

### ✅ HiGHS（DC OPF）—— **可靠可用**

设置 `HIGHS_LIB_DIR` 后：

```
DcOpfResult(cost=125948.01, feasible=true, hvdc_links=0, gen_limit_violations=0)
ScopfResult(formulation="dc", mode="preventive", converged=true, iterations=1, ...)
```

**稳定性**：连续 3 次运行结果完全一致（cost=125948.01），**确定性通过**。

**对照**：不设 `HIGHS_LIB_DIR` → `No LP solver found — install HiGHS`。

> `highs.dll` 的文件名恰好与 surge 期望的一致，故无需别名。

### ❌ Ipopt（AC OPF）—— **未能可靠解决**

`solve_ac_opf` 仍报 `No AC-OPF NLP solver found. Install Ipopt (libipopt.so)`。

**已尝试且失败的组合**（全部实测）：

| 配置 | 结果 |
|---|---|
| 仅 `IPOPT_LIB_DIR` | ❌ |
| 仅 `PATH`（含库目录） | ❌ |
| `IPOPT_LIB_DIR` + `PATH` | ❌ |
| `HIGHS_LIB_DIR` + `IPOPT_LIB_DIR` | ❌ |
| `HIGHS_LIB_DIR` + `IPOPT_LIB_DIR` + `PATH` | ❌ |
| 用 `ctypes.WinDLL()` 预加载 `libipopt.dll` | ❌ |
| 预加载 + 上述全部环境变量 | **无输出 —— 进程静默崩溃** |

**一次不可复现的"成功"**：某次在预加载 4 个 DLL 后 `solve_ac_opf` 返回
`AcOpfHvdcResult(cost=137023.38, ...)`，但后续用**完全相同的配置**重跑即失败，
另一次尝试中进程**无任何输出地死亡**（非 Python 异常，是硬崩溃）。

> **本报告不声称 Ipopt 已解决。** 该成功无法复现，不足以作为配置依据。

### 线索：surge 的 Windows Ipopt 支持可能未经充分测试

对 `_surge.cp312-win_amd64.pyd` 做字符串提取：

```
libipopt   出现 10 次      ← Unix 命名（.so/.dylib）占绝对多数
ipopt.dll  出现  1 次      ← 且紧邻 '/opt/ipopt-spral/opt/ipopt'（构建机的 Linux 路径）
```

即：二进制的 Ipopt 搜索逻辑以 Unix 命名为中心，Windows 分支的痕迹极少。
结合"偶发成功 + 静默崩溃"的表现，**推测**其 Windows NLP 加载路径不完整或存在 DLL 冲突。

> ⚠️ 这是**推测，非结论**。未做进一步验证，不据此断言上游缺陷。

---

## 四、当前可用性

| surge 能力 | 状态 | 需要 |
|---|---|---|
| 潮流 / PTDF / LODF / N-1 / N-2 / ATC | ✅ | 无（本就可用） |
| **DC OPF / SCOPF** | ✅ **新解锁** | `HIGHS_LIB_DIR` |
| **AC OPF / AC SCOPF** | ❌ | Ipopt 未解决 |
| SCED / SCUC | ⚠️ 未验证 | 推测同 HiGHS（LP 类） |

**配置方式**（当前仅在 shell 会话内，**未持久化**）：

```bash
export HIGHS_LIB_DIR="C:/Users/Z/.conda/envs/powersolvers/Library/bin"
```

> **未写入任何配置文件或系统环境变量** —— 符合「禁止未经确认修改系统环境变量」的约束。
> 若需持久化（以便 `powermcp run surge` 的子进程也能拿到），需单独确认。

---

## 四·五、Gurobi 路径的排查（2026-09-21 追查）

用户提示本机装有 Gurobi。追查后**确认这条路当前走不通**，但过程有价值。

### 事实链

| 环节 | 实测 |
|---|---|
| surge 是否支持 Gurobi | ✅ **支持**。二进制内写明：LP = `"default", "highs", "gurobi", "cplex", "copt"`；NLP = `"default", "ipopt", "copt", **"gurobi"**` |
| 传参方式 | MCP 工具 `run_ac_opf(nlp_solver=...)`；Python API 为 `surge.AcOpfRuntime(nlp_solver='gurobi')` |
| 实际调用结果 | ❌ `Gurobi 13 not found` |
| 本机 Gurobi 版本 | **11.0.3**（`gurobi110.dll`，`GUROBI_HOME=D:\Program disk\Gurobi\win64`） |
| surge 的版本要求 | **只要 Gurobi 13.x**。报错原文：*"Only Gurobi 13.x (API version 13, library libgurobi130) is supported; older versions (gurobi120, gurobi110, …) **have incompatible APIs**"* |
| 许可文件 | `C:\gurobi\gurobi.lic` → `TYPE=NODE` · **`VERSION=12`** · **`EXPIRATION=2026-03-31`** |
| 许可实测 | ❌ **`Error 10009: License expired 2026-03-31`** |

### 结论

**Gurobi 路径当前不可行，且有两重阻塞**：

1. **许可已过期**（2026-03-31，距今约 6 个月）→ Gurobi 在本机**完全不可用**，与 surge 无关
2. **版本不匹配**：许可为 `VERSION=12`，即使续期也**无法运行 surge 要求的 Gurobi 13**

> ⚠️ **改 DLL 名（`gurobi110.dll` → `gurobi130.dll`）行不通** —— surge 已明说旧版本 API 不兼容，
> 强行改名会在符号解析阶段崩溃，而非优雅报错。

### 连带提醒（超出 surge 范围）

许可过期影响**所有依赖 Gurobi 的工作流**。已确认的例外：

- ✅ `pandapower.runopp` **不受影响**（实测目标值 41842.3→41872.3 稳定）—— 它用 PYPOWER 内建求解器
- ⚠️ 若在 pypsa 中显式指定 `solver_name='gurobi'`，会失败
- ⚠️ 其他项目（本机多个 conda 环境与 RL 相关）若依赖 Gurobi，同样会失败 —— **未逐一验证**

### 但这重要吗？—— 需要重新框定

**AC OPF 其实早就可用**，surge 只是第三条实现：

| 路径 | 状态 | 出处 |
|---|---|---|
| pandapower `runopp` / `rundcopp` | ✅ 可用（含节点边际电价） | [示例 04](../../examples/04_pandapower_opf_demo.py) |
| pypsa `optimize_network` | ✅ 可用（原生算例） | 审计已验证 |
| **surge `run_ac_opf`** | ❌ 需 Gurobi 13 或 Ipopt | 本文件 |

**故 surge 的 AC-OPF 缺失不阻塞任何能力目标**，只影响"用 surge 而非 pandas/pypsa 做 AC 优化"这一偏好。

---

## 五、待决

- [ ] 是否持久化 `HIGHS_LIB_DIR`（否则每次启动 surge 的 MCP 服务都需手动带上）
- [ ] 是否继续排查 Ipopt（当前无确定路径，且已出现进程崩溃，风险不低）
- [ ] 是否将「Windows 下 surge 的 Ipopt 不可用」作为 issue 上游报告（目前证据不足以断言是缺陷）
- [ ] **Gurobi 许可已过期** —— 是否续期？若要跑 surge 的 AC-OPF，还需是 **13.x** 的许可
- [ ] 排查其他项目是否因 Gurobi 许可过期而受影响（未逐一验证）
