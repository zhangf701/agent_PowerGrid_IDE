# 引用图遍历复核 —— 分页截断修复与 144 → 181 更正

| 项 | 值 |
|---|---|
| **日期** | 2026-09-24 |
| **类型** | 复核 / 更正（对既有调研结论的数据层修正） |
| **状态** | ✅ 脚本已修复并重跑；**§4.2 的引用者计数与「人机协同 2 篇」已更正** |
| **触发** | 通读 journal 时发现 `traversal.json` 的 `n` 与 `citing` 长度不一致（详见 §1） |
| **上游素材** | [2026-09-23-research-direction-summary.md](2026-09-23-research-direction-summary.md) §4.2 · [2026-09-23-case30-and-gap-research.md](2026-09-23-case30-and-gap-research.md) §三 |
| **改动文件** | `C:\Users\Z\.claude\skills\finding-research-gaps\scripts\openalex.py`（备份 `openalex.py.bak-20260924`）· 同目录 `SKILL.md` |
| **新增产物** | `work/cite/rerun-20260924/`（`traversal_full.json` · `themes_full.json` · `themes_curated_tail.json` · `classify_themes.py` · `names.json`） |
| **检索时点** | `2026-09-24T11:38:04+0800` |

---

## 0. 一句话结论

`finding-research-gaps` 技能的 `cites` 操作**默认只取一页（50 条）且不翻页**，导致
journal 里「5 锚点 → **144** 篇唯一引用者」是一个**被静默截断的下界** —— 补齐分页后实为 **181 篇**（缺 37 篇）。
**方向性结论（工具/交互层密度显著低于模型与调度层）在更完整的数据上依然成立且更清晰**；
但**「人机协同仅 2 篇」已被证伪**（181 集中至少 4 篇命中），且旧集合存在**系统性偏向新论文**的偏差。

---

## 1. 触发：一处自相矛盾

`work/cite/traversal.json` 中每个种子锚点同时记录了 `n`（OpenAlex 报告的被引总数）与 `citing`（实际抓到的列表）。两者本应相等，实测不等：

| 种子锚点 | `n` | `len(citing)` | |
|---|---:|---:|---|
| W4413371231 PowerAgent 路线图 | 11 | 11 | ✓ |
| W4392543779 LLM 应用于电力的安全威胁 | **79** | **50** | ⚠️ |
| W4413453507 变压器与 LLM 能源领域系统综述 | **58** | **50** | ⚠️ |
| W4404961535 电力网基础模型 | 40 | 40 | ✓ |
| W7128525931 LLM 电力调度智能体 | 5 | 5 | ✓ |
| **合计** | **193** | **156** | **缺 37** |

**根因**（定位到代码行）：`openalex.py` 原第 133 行
`c.add_argument("--top", type=int, default=50)`，配合第 102 行的单次请求
`per_page={top}` —— **一次请求、无 `cursor` 翻页**。被引超过 50 的锚点被静默截断，
调用方看到的是一个**外观完整**的列表，没有任何缺失标记。

> ⚠️ 这正好命中该技能自己写下的一条教训的反面：技能警告过「命中 0 可能是限流假象」，
> 但没有警告「**列表可能只是被截断**」。两者同属「静默失效」家族。

---

## 2. 修复内容

`openalex.py` 四处改动（原文件已备份为 `openalex.py.bak-20260924`）：

| # | 改动 | 说明 |
|---|---|---|
| 1 | 新增 `_paged()` | **cursor 分页**（`cursor=*` 起步，跟进 `meta.next_cursor`），`per_page=200`，`cap=None` 即取全量 |
| 2 | `cites` 改用 `_paged` | `--top` 缺省由 `50` 改为 `None` = **默认取全量**；新增 `--json` 输出 |
| 3 | 新增 `traverse` 子命令 | 多锚点遍历 + 跨锚点去重 + 落盘 JSON。**此前这一步没有脚本**，结果只能靠一次性手工查询得到，故无法重跑 |
| 4 | `_get` 增加代理回落 | 直连拿不到有效响应体时自动改用 `OPENALEX_PROXY`（缺省 `http://127.0.0.1:10090`，见用户级 MEMORY.md「零之三」） |

`search` 同步改用 `_paged` 并新增 `--all`；`_slim()` 统一归档字段（`id/t/y/src` 沿用原约定，另加 `cited_by/type/doi`）。

**验证**：`py_compile` 通过；`cites W7128525931` 冒烟测试 5/5 全取。

---

## 3. 重跑结果：144 → 181

```bash
python openalex.py traverse W4413371231 W4392543779 W4413453507 W4404961535 W7128525931 \
       --out traversal_full.json --names names.json
```

| 种子锚点 | 被引 | 旧版取到 | 新版取到 | 找回 |
|---|---:|---:|---:|---:|
| W4413371231 PowerAgent 路线图 | 11 | 11 | 11 | 0 |
| W4392543779 LLM 安全威胁 | 79 | 50 | **79** | **+29** |
| W4413453507 变压器 LLM 综述 | 58 | 50 | **58** | **+8** |
| W4404961535 电网基础模型 | 40 | 40 | 40 | 0 |
| W7128525931 LLM 调度智能体 | 5 | 5 | 5 | 0 |
| **合计** | **193** | **156** | **193** | **+37** |

**去重**：193 条 → **181 篇唯一引用者**（跨锚点重叠 **12**，与旧版一致）· 旧有新无 **0 篇**。

> 重叠数不变、无任何论文消失 → 说明旧版确实是新版集合的**真子集**，截断是唯一差异来源，
> 不存在 OpenAlex 侧的数据变动或撤回干扰。

### 3.1 ⚠️ 截断是**系统性**的，不是随机的

排序为 `publication_date:desc`，故每个列表的前 50 条是**最新的** 50 条 ——
被截掉的恰好是**最老的那一段**：

| 年份 | 旧 144 | 新 181 | Δ |
|---|---:|---:|---:|
| 2026 | 106（73.6%） | 109（60.2%） | +3 |
| 2025 | 36 | 56 | **+20** |
| 2024 | 2 | 16 | **+14** |

新增 37 篇中 **34 篇（92%）是 2024/2025 年**。

**影响**：旧集合**高估了研究的新近度**（2026 占比 73.6% vs 真实 60.2%）。
§4.3 那条「0 引用源于时间滞后」的免责声明方向正确，但当时是基于一份**偏向新论文**的样本得出的，
其量化程度需要按新集合重估。

---

## 4. 主题分布：旧 / 新 / 人工甄别 三口径对照

**口径声明**：`traversal.json` 的 `_works` 只有 `id/t/y/src` 四个字段，
**§4.2 那张表的分类产物从未归档**，故其数字无法复现。
本节用 `classify_themes.py`（机械关键词规则、**只匹配标题**、规则与逐篇标注均已落盘）
对两个集合跑**同一套规则**，得到可审计的对照：

| 主题 | 旧 144 | 新 181 | Δ | 报告原声称 |
|---|---:|---:|---:|---:|
| 基础模型 / 微调 | 53 | 68 | +15 | 50 |
| 调度 / 运行 | 18 | 22 | +4 | 25 |
| 规划 / 优化 | 18 | 22 | +4 | 22 |
| RAG / 检索 | 19 | 22 | +3 | 21 |
| **技能 / 工具 / 编排** | 10 | **12** | +2 | **14** |
| **可解释 / 审计** | 3 | **3** | 0 | **3** |
| **人机协同** | 2 | **4** | **+2** | **2** |
| **前四类合计** | 108 | **134** | +26 | 118 |
| **尾部三类合计** | 15 | **19** | +4 | 19 |

> ⚠️ **不可横向相加**：一篇论文可命中多个主题，各主题之和 > 论文总数。
> ⚠️ **机械规则必有噪声**，故上表**适合两集合间的相对比较，不适合当作绝对计数**（见 §4.2）。

### 4.1 找回的 37 篇里，有哪些落在尾部三类

| 论文 | 年 | 出处 | 归属 |
|---|---:|---|---|
| **Integration of LLM and Human-AI Coordination for Power Dispatching With Connected EVs** | 2024 | IEEE Trans. Vehicular Technology | **人机协同** |
| **A HCI Approach to Designing a Digital Twin Taxonomy for Power Grids** | 2026 | LNCS | **人机协同** |
| **RePower: An LLM-driven autonomous platform for power system data-guided research** | 2025 | Patterns | **技能/工具/编排** |
| SmartGridAgent: An Educational Framework for Reliable Digital Twin-Based Smart Grid Workforces | 2025 | Smart Grids and Sustainable Energy | 技能/工具（未命中关键词） |
| Agentic AI in Practice: Applications Across Industries | 2026 | Studies in Computational Intelligence | 编排（未命中关键词） |
| Research on Technical Route of AI Large Models for Electric Power Knowledge Services | 2024 | — | 工具/知识服务（未命中关键词） |

**这不是噪声，是实质遗漏** —— 被截掉的恰恰包含两类此前被判为「近乎空白」的方向上的真实工作。

### 4.2 人工甄别（对 181 集的尾部三类逐篇判读）

机械规则的噪声是**可查证的**：`'tool'` 命中了核能 SMR 融资、构音障碍语音识别、销售营销论文；
`'api'` 命中 `r-a-p-i-d` 的**子串**；GridSage 以期刊版与 SSRN 预印本**重复出现两次**。
逐篇判读结果（明细见 `themes_curated_tail.json`）：

| 主题 | 机械计数 | 人工 genuine | marginal / 其他 |
|---|---:|---:|---|
| 技能 / 工具 / 编排 | 12 | **4** | 1 通用设计 · 4 离域 · 1 子串误匹配 · 1 重复 · 1 种子自身 |
| 可解释 / 审计 | 3 | **1** | 2 marginal（对象是电力电子硬件 / 非 agent 审计） |
| 人机协同 | 4 | **2** | 2 marginal（数字孪生分类学 / 工程设计协作） |
| **合计** | **19** | **7** | |

**genuine 的 4 篇工具/编排**：Grid-Orch · Agentic Planning for Power System Simulation Orchestrations · RePower · GridSage。

---

## 5. 结论修正

| # | 原结论 | 修正后 |
|---|---|---|
| 1 | 5 锚点 → **144** 篇唯一引用者 | 实为 **181 篇**（193 抓全，重叠 12）。旧值是**被截断的下界** |
| 2 | **人机协同仅 2 篇** | ❌ **证伪**。181 集中至少 4 篇命中、2 篇 genuine；找回的 *Integration of LLM and Human-AI Coordination for Power Dispatching*（IEEE TVT 2024）是明确的电力人机协同论文 |
| 3 | 工具/技能/编排 **14** 篇 | **不可复现**。同规则下机械计数为 12，人工甄别后 genuine 仅 4。原值疑含 RAG/知识服务类，但原分类规则未归档，无法判定 |
| 4 | 可解释/审计 3 篇 | 机械计数一致（3），但人工甄别后仅 1 篇真正对题 |
| 5 | 尾部三类合计 19 篇 | 机械口径同为 19（巧合，构成不同）；人工甄别后 **7 篇** |
| 6 | 前四类占 118/144 | 新集合 **134/181**（74%）。**占比略降但绝对多数地位不变** |

### ✅ 稳健成立的结论

**三种口径（旧 144 / 新 181 机械 / 新 181 人工甄别）下，「模型与调度层占绝对多数、
工具与交互层密度显著更低」这一**方向性判断始终成立**：
前四类 108 → 134 篇（+26），尾部三类仅 15 → 19 篇（+4）—— **差距在更完整的数据上反而拉大**。

这与 `work/fw/aggregate.json`（future work 语料库 97 篇：「工具/技能层」3 篇、「人机协同/审批」3 篇）
构成**两套独立数据的一致指向**。

### ❌ 不成立的结论

**「仅 14 / 3 / 2」这组精确数字不可用作定量论据。** 它建在一个被截断 37 篇的不完整集合上，
分类规则未归档，且桶内噪声可查证。写进论文会被要求复现。

---

## 6. 复现命令

```bash
cd d:/coding/powerMcp_Pskills/work/cite/rerun-20260924

PY="C:/Users/Z/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe"
SK="C:/Users/Z/.claude/skills/finding-research-gaps/scripts"

# 1) 重跑引用图遍历（5 锚点，cursor 分页取全量）
PYTHONUTF8=1 "$PY" "$SK/openalex.py" traverse \
  W4413371231 W4392543779 W4413453507 W4404961535 W7128525931 \
  --out traversal_full.json --names names.json

# 2) 主题分类归档 + 与旧版对比
PYTHONUTF8=1 "$PY" classify_themes.py traversal_full.json \
  --out themes_full.json --compare ../traversal.json

# 3) 单锚点全量引用列表
PYTHONUTF8=1 "$PY" "$SK/openalex.py" cites W4392543779        # 应显示 被引 79（已取 79）
```

> ⚠️ **路径陷阱**：原生 Windows Python **不认 Git Bash 的 `/tmp`**，中间产物须用 `D:/...` 绝对路径。
> ⚠️ **编码**：`PYTHONUTF8=1` 与 `PYTHONIOENCODING=utf-8` 都要设，否则中文输出可能抛 `UnicodeDecodeError`。

---

## 7. 遗留与建议

- [ ] **§4.2 的原始分类规则若还找得到，应与 `themes_full.json` 对账** —— 判断「14 篇」是口径差异还是误分类
- [ ] 用 **abstract 级**复核尾部三类的 genuine 论文（技能自己的规则：标题匹配会漏掉措辞不同的前作）
- [ ] `work/cite/anchors.json` 与 `traversal.json` 对 2 个锚点的被引数不一致（**59 vs 58**、**38 vs 40**），
      疑为两次快照时点不同；两个文件均未记采集时间 → 建议统一补时间戳
- [ ] 3 篇种子自身出现在引用者集合中（种子互引），分析时应显式扣除或标注
- [ ] 「72 篇」与「10–12 个去重工作」两个计数**仍无原始数据支撑**（`anchors.json` 不含检索结果字段），
      与本次修复无关，需单独处理

---

## 附录：产物清单

| 路径 | 内容 |
|---|---|
| `work/cite/rerun-20260924/traversal_full.json` | 重跑结果：193 抓取 / 181 去重，含 `_meta`（分页方式、采集时间） |
| `work/cite/rerun-20260924/themes_full.json` | 机械分类：规则 + 逐篇标注 + 计数 |
| `work/cite/rerun-20260924/themes_curated_tail.json` | 尾部三类的人工甄别（逐篇 verdict + 理由） |
| `work/cite/rerun-20260924/classify_themes.py` | 分类脚本（可重跑） |
| `work/cite/rerun-20260924/names.json` | 种子 ID → 名称映射 |
| `C:\Users\Z\.claude\skills\finding-research-gaps\scripts\openalex.py.bak-20260924` | 修复前备份 |
