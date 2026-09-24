---
title: "Grid-Orch: An LLM-Powered Orchestrator for Distribution Grid Simulation and Analytics"
authors: [Boming Liu, Jin Dong, Jamie Lian]
affiliation: "Oak Ridge National Laboratory, Electrification and Energy Infrastructures Division"
venue: "IEEE Open Access Journal of Power and Energy"
doi: "10.1109/OAJPE.2026.3721083"
arxiv: "2605.12728 (v1)"
arxiv_subjects: [eess.SY, cs.AI, cs.SE]
cited_by: 0
source_html: "https://arxiv.org/html/2605.12728v1"
converted_at: "2026-09-24"
converter: "arxiv_html2md.py（本地，beautifulsoup4 + lxml）"
---

# Grid-Orch: An LLM-Powered Orchestrator for Distribution Grid Simulation and Analytics

> **转换说明**：本文件由 arXiv HTML 版（`2605.12728v1`）自动转换为 Markdown。
> 公式取自 MathML 的 `alttext`（即 LaTeX 源），本文 20 处公式均为行内；图片链接已补为绝对 URL，图注与图片分离；表格转为 Markdown 表格。
> 章节结构：I 引言 · II 相关工作 · III 系统架构 · IV 工具库与技能 · V 平台与可视化 · VI 工作流演示 · VII 讨论与结论。**无附录**。
> 其余内容与源 HTML 一致，未做改写。

Boming Liu, *Member, IEEE*, Jin Dong, , Jamie Lian, *Senior Member, IEEE* Affiliation: B. Liu, J. Dong and J. Lian are with the Electrification and Energy Infrastructures Division, Oak Ridge National Laboratory, Oak Ridge, TN 37830 USA (e-mail: liub@ornl.gov). This material is based upon work supported by the U.S. Department of Energy, Office of Critical Minerals and Energy Innovation (CMEI), specifically the Solar Energy Technologies Office (SETO) and Office of Cybersecurity, Energy Security, and Emergency Response (CESER). This manuscript has been authored by UT-Battelle, LLC, under contract DE-AC05-00OR22725 with the US Department of Energy (DOE). The US government retains and the publisher, by accepting the work for publication, acknowledges that the US government retains a non-exclusive, paid-up, irrevocable, worldwide license to publish or reproduce the submitted manuscript version of this work, or allow others to do so, for US government purposes. DOE will provide public access to these results of federally sponsored research in accordance with the DOE Public Access Plan.

## Abstract

The power distribution engineering workforce faces a projected shortage of up to 1.5 million engineers by 2030, creating urgent demand for more accessible analysis tools. This paper introduces Grid-Orch, a framework that bridges Large Language Models (LLMs) and power system simulation through the Model Context Protocol (MCP), enabling engineers to perform complex distribution analyses via natural language. Using OpenDSS as the reference implementation, Grid-Orch provides 36 domain-specific tools across eleven categories—covering power flow, voltage analysis, quasi-static time-series (QSTS) simulation and automated optimization. A provider-agnostic LLM layer supports both cloud-hosted (Gemini, Claude) and locally deployed (Ollama, llama-cpp) models, enabling air-gapped operation for security-sensitive utility environments. Three optimization skills—capacitor placement, voltage violation analysis, and overvoltage mitigation—extend the platform beyond single-tool queries to multi-step engineering workflows. The developed Grid-Orch has an interactive web platform with chat-based interaction, a QSTS dashboard, and feeder topology visualization renders simulation results inline. Workflow demonstrations show that distribution analyses formerly requiring hours of scripting—such as distributed energy resource (DER) interconnection screening complete in under two minutes through natural language, producing numerically identical results to direct OpenDSS scripting.

**Index Terms: Distribution Grid Analytics, Agentic AI, Power Flow Analysis, LLM Agents, Model Context Protocol, Visualization**

## I Introduction

The power distribution engineering workforce faces an acute capacity crisis. IEEE PES and Kearney project a shortage of up to 1.5 million qualified engineers by 2030 [ 1 ], driven by accelerating grid modernization, mass retirements, and explosive DER integration [ 2 , 3 ]. The IEA reports that more than 60% of energy companies cite labor shortages as a primary operational constraint [ 4 ]. This imbalance (growing grid complexity against a shrinking workforce) calls for tools that let engineers run distribution analyses without specialized scripting skills.

Existing simulation platforms fall short on accessibility. OpenDSS [ 5 ], the open-source distribution power-flow and quasi-static time-series (QSTS) simulation, requires practitioners to author DSS scripts or navigate its Python bindings. Commercial alternatives (Synergi, CYME, PSCAD) offer graphical interfaces but carry substantial licensing costs that may be prohibitive for smaller utilities and research groups. Neither category provides a conversational interface: engineers must still formulate correct API calls rather than asking questions in natural language.

Recent advances in large language models (LLMs) demonstrate that natural language can serve as a practical interface for technical software. Function-calling capabilities [ 6 , 7 , 8 ] allow LLMs to reason over a tool library and invoke domain-specific operations on behalf of the user. Early power-system applications confirm the potential: LLM-based frameworks have been applied to simulation orchestration [ 9 ], optimal dispatch [ 10 ], grid control [ 11 , 12 ], and voltage regulation [ 13 ], establishing that LLMs can parse engineering intent, select tools, and interpret simulation outputs.

Despite this progress, four critical gaps remain unaddressed in the literature.

1. (i) **No standardized tool-integration protocol.** Existing integrations define bespoke function registries tied to a single codebase; no published work adopts a vendor-neutral, community-standardized protocol for exposing simulator capabilities.
2. (ii) **Vendor lock-in.** Current platforms couple their LLM layer to a specific proprietary API, precluding open-weight or locally hosted models and creating dependency on external service pricing and availability.
3. (iii) **No comprehensive distribution analysis interface.** Existing tools address isolated tasks; none provides a single interface covering load-shape management, QSTS simulation, equipment sizing, topology visualization, and optimization.
4. (iv) **No support for air-gapped deployments.** Utility OT networks routinely prohibit outbound cloud traffic; no existing LLM simulation tool supports fully local operation with both inference and simulation running on-premises.

**Fig. 1:** Comparative workflow for power distribution analysis. (a) Traditional five-step manual process spanning several hours. (b) Grid-Orch autonomous workflow completing the same analysis in under two minutes through five stages: LLM tool selection, MCP routing, OpenDSS execution, Skills optimization, and synthesized visualization.

![](https://arxiv.org/html/2605.12728v1/figures/gridOrch_vs_traditional_v12.png)

The Model Context Protocol (MCP) [ 14 ], an open standard for exposing tools to LLMs, addresses gap (i) directly. Because MCP is model- and transport-agnostic, a single server can be queried by cloud or local models without modification, resolving gap (ii). Building Grid-Orch on MCP cleanly separates the simulation layer (OpenDSS) from the inference layer (any compliant LLM).

This paper makes four primary contributions:

1. 1. **MCP adaptation for distribution simulation.** We present an integrated adaptation of MCP to a power system simulation engine, exposing 36 domain-specific tools across eleven categories through a standards-compliant server backed by OpenDSS.
2. 2. **Multi-provider LLM layer with local-deployment support.** Grid-Orch supports four backends (Gemini, Claude, Ollama, llama-cpp) via a provider-agnostic abstraction, enabling fully air-gapped operation with no cloud dependency.
3. 3. **Interactive web platform with integrated visualization.** The web application delivers a chat interface, a QSTS results dashboard, and an interactive feeder topology map, all rendered inline during conversation.
4. 4. **Skills framework for multi-step optimization workflows.** A composable skills layer encapsulates voltage violation analysis, overvoltage mitigation, and capacitor placement as natural-language-invocable multi-tool pipelines. These skills reason over user prompts, decide which tools to call and in what order, and execute multi-step optimization workflows. Because the underlying OpenDSS engine supports three-phase unbalanced distribution systems, all tools and skills operate on full three-phase models; this enables accurate and trustworthy analysis of feeders such as the IEEE 13-bus test system.

Fig. 1 illustrates the resulting workflow transformation: a five-step manual process spanning several hours is compressed into a single natural-language query completed in under two minutes.

Section II reviews related work; Section III describes the system architecture; Section IV details the tool library and skills framework; Section V covers the web platform and visualization; Section VI presents workflow demonstrations; and Section VII concludes with deployment considerations and future work.

## II Related Work

**TABLE I:** Comparison of Grid-Orch with Representative Related Systems on Distribution Analysis Dimensions. Systems differ in primary scope; see text for discussion.

| **System** | **Focus** | **Protocol** | **Tools** | **Multi-LLM** | **Local Deploy** |
|---|---|---|---|---|---|
| Grid-Agent [ 11 ] | Grid control | Custom API | $<$10 | No | No |
| X-GridAgent [ 12 ] | Grid analysis | Custom API | $<$10 | No | No |
| Jia et al. [ 9 ] | Power flow sim. | Custom API | $<$5 | No | No |
| OptDisPro [ 10 ] | Optimal dispatch | Custom API | $<$5 | No | No |
| ChatGrid [ 15 ] | Grid visualization | Custom API | $<$5 | No | No |
| Jena et al. [ 13 ] | Voltage regulation | Custom API | $<$5 | No | No |
| GridMind [ 16 ] | ACOPF + N-1 contingency | PydanticAI | 7 | Yes | No |
| **Grid-Orch (this work)** | **Full distrib. analysis** | **MCP** | **36** | **Yes** | **Yes** |

**Fig. 2:** Overall Schematic of Grid-Orch, which translates natural-language grid-analysis requests into typed tool calls, validates them through a shared MCP interface, dispatches them to swappable simulation engines, and grounds all responses and visualizations in structured simulator outputs.

![](https://arxiv.org/html/2605.12728v1/figures/GridOrch_workflow_diagram2.png)

### II-A *LLMs in Power Systems*

The application of LLMs to power systems has grown rapidly, spanning control, planning, fault diagnosis, and operator assistance [ 17 , 18 ]. Agent-level frameworks [ 8 ] underlie recent work on real-time grid control [ 11 , 12 ], simulation orchestration and dispatch [ 9 , 10 ], ACOPF and contingency analysis [ 16 ], topology reasoning [ 19 ], voltage regulation [ 13 ], control decision support [ 20 ], and grid-state visualization [ 15 ]. Across this body of work, integrations are task-specific or coupled to proprietary APIs; none exposes a standards-compliant, auditable tool protocol to the LLM.

### II-B *The Model Context Protocol*

MCP [ 14 ] standardizes LLM-to-tool communication via a capability-negotiation handshake, with demonstrated generalization to IoT contexts [ 21 ] and analyzed security properties [ 22 ]. MCP is structured around three core primitives—*tools*, *resources*, and *prompts*—which collectively enable standardized interaction between LLM agents and external systems. General-purpose LLM orchestration frameworks such as LangChain [ 23 ] provide tool-calling abstractions but lack domain-specific schema validation and the standardized capability negotiation that MCP offers. During the preparation of this manuscript, the PowerAgent project [ 24 ] released an open-source collection of MCP servers spanning multiple power system simulators. PowerAgent focuses on providing raw MCP tool interfaces and APIs for individual simulators, but does not offer an end-to-end analysis workflow. Grid-Orch complements this effort by providing a comprehensive orchestration layer with multi-provider LLM support, domain-specific tools, optimization skills, and an interactive web platform. This framework transforms raw tool calls into trustworthy, autonomous grid analytics. Future work will integrate the MCP tools developed in PowerAgent into the Grid-Orch workflow, enabling seamless access to diverse power system software through a unified natural-language interface.

To the best of our knowledge, no existing open-source platform integrates a standardized tool protocol, multi-provider LLM support with air-gapped inference, a 36-tool distribution-system library, and a multi-step optimization Skills framework within a single system; Table I summarizes the comparison with related work.

## III System Architecture

### III-A *Overview*

**Fig. 3:** Grid-Orch four-layer architecture. The MCP boundary (dashed) decouples the LLM Abstraction Layer from the Simulation Engine Layer, allowing either side to be replaced independently.

Fig. 2 illustrates the overall Grid-Orch workflow, in which natural-language requests are translated into validated MCP tool calls, dispatched to swappable simulation engines, and returned as simulator-grounded responses and visualizations based on structured simulator outputs. Fig. 3 further shows that this workflow is implemented through a four-layer architecture that cleanly separates user interaction from simulation.

**Layer 1 – UI Layer.** A React/Next.js application provides a persistent chat panel and a QSTS results dashboard with voltage time-series plots, load-shape viewers, and a force-directed feeder topology map. The UI communicates exclusively with the backend REST API, with no direct knowledge of the LLM provider or OpenDSS.

**Layer 2 – LLM Abstraction Layer.** A FastAPI backend hosts the provider-agnostic LLM service, running a *tool-use loop*: the LLM emits tool-call requests, the service dispatches them to the MCP layer, appends results as tool-response messages, and repeats until the LLM produces a final text reply. PostgreSQL persists chat sessions and circuit metadata; MinIO holds binary circuit files.

**Layer 3 – MCP Server Layer.** A dedicated Python process exposes all 36 domain tools through the Model Context Protocol, owning JSON Schema validation, parameter coercion, and error formatting. It maintains a single shared OpenDSS manager instance so that successive tool calls within one conversation operate on the same live circuit state.

**Layer 4 – Simulation Engine Layer.** OpenDSS [ 5 ] performs all numerical computation via the *opendssdirect.py* bindings [ 25 ], enabling in-process deployment on Linux-based Docker containers.

The MCP boundary acts as a *capability firewall*: the LLM interacts with the simulator only through the 36 defined tools, never through arbitrary code execution.

### III-B *MCP Integration*

The Model Context Protocol is an open standard defining a JSON-RPC 2.0 transport for connecting LLMs to external tools and data [ 14 ]. Conceptually, MCP serves as a universal adapter between LLMs and external tools, analogous to how SCADA protocols standardize communication between control centers and field devices in power system operations. Grid-Orch uses all three MCP primitives. The 36 simulation capabilities are registered as Tools with typed JSON Schema parameters. Active circuit DSS files are exposed as Resources for topology queries. A power-engineering Prompt template injects domain knowledge such as per-unit notation and standard voltage limits into every session.

The end-to-end interaction sequence is detailed in Fig. 7 (Section V). The server validates each incoming request against its JSON Schema, executes the corresponding handler, and returns a structured result to the LLM. Multiple tool calls may be chained within a single user turn.

Error handling supports LLM self-correction: failed calls return structured hints enabling the model to recover without user intervention [ 26 ] (detailed in Section IV).

Beyond the vendor-neutrality and multi-provider support that motivated this work (Section I), MCP provides a standardized resource primitive for exposing non-tool data (e.g., circuit files) without custom endpoints [ 6 , 23 ].

### III-C *Multi-LLM Provider Support*

The LLM Abstraction Layer implements a *provider adapter* interface with four concrete backends: *Gemini (Google DeepMind), Claude (Anthropic), Ollama (local Docker inference), and llama-cpp (GGUF-quantized models for resource-constrained hosts)*. All four adapters share identical upstream and downstream interfaces—receiving an MCP tool-schema list and message history, returning either a final text reply or a list of tool calls—so adding a new provider requires no changes to the MCP layer or UI. Utility environments subject to NERC CIP cybersecurity standards [ 27 ] can select the Ollama or llama-cpp adapter for fully **air-gapped operation**, ensuring circuit files and simulation results never leave the security perimeter.

### III-D *OpenDSS Integration*

Grid-Orch accesses OpenDSS [ 5 , 28 ] exclusively through the *opendssdirect.py* Python package [ 25 ], which wraps the native engine as an in-process shared library, eliminating COM interop latency and enabling Linux-based Docker deployment. The *OpenDSSManager* class maintains a single engine instance per server process across circuit loading, power-flow solve, QSTS time-stepping, and equipment state updates (capacitor switching, reactor placement, regulator tap writes). Security controls at the circuit-loading boundary validate that requested file paths resolve to a whitelisted directory and block symbolic-link traversal, preventing path-traversal attacks in multi-tenant deployments.

The current implementation maintains a single OpenDSS engine instance per server process; concurrent sessions are serialized through a request queue. Multi-user deployments requiring parallel simulations can scale horizontally by running multiple backend containers behind a load balancer, each owning an independent engine instance.

## IV Tool Library and Skills

In the context of LLM–simulator integration, a *tool* is a single callable operation, such as solving a power flow or reading a bus voltage, while a *skill* is a multi-step workflow that chains several tools together to accomplish a complex engineering task (e.g., optimizing capacitor placement). Tools and skills are critical for OpenDSS integration because they provide a structured, auditable interface between the LLM’s natural language understanding and the simulation engine’s numerical computation: every analysis step is traceable to a specific tool invocation with typed inputs and outputs, preventing the LLM from fabricating results. Grid-Orch exposes 36 tools in 11 categories (Table II), spanning the full distribution-engineering workflow from circuit loading to optimization invocation; the LLM selects tools autonomously from the full schema list.

### IV-A *Tools*

**TABLE II:** Grid-Orch MCP Tool Library (36 tools, 11 categories)

| **Category** | **Tools** | **Key Capabilities** |
|---|---|---|
| Core Circuit | 6 | Circuit loading, Newton–Raphson power flow, single-bus and system-wide voltage queries, circuit metadata |
| LoadShape | 6 | Create, edit, delete, and assign time-series load profiles to load objects |
| QSTS Simulation | 4 | Run quasi-static time-series simulations; retrieve voltage and loss time-indexed results |
| Profile Library | 3 | Browse and load built-in, NREL, and custom CSV load profiles |
| Results Export | 2 | CSV/JSON data export and HTML report generation |
| Capacitor Mgmt | 3 | Add/remove shunt capacitor banks at any bus |
| Reactor Mgmt | 3 | Add/remove shunt reactors for overvoltage absorption |
| Regulator/Tap | 3 | Read and adjust voltage regulator tap positions |
| Circuit Library | 2 | Load pre-packaged IEEE and SmartDS test feeders |
| Topology | 1 | Bus coordinates and branch connectivity for visualization |
| Skill Invocation | 3 | Recommend, execute, and monitor multi-step optimization skills |
| **Total** | **36** |  |

All 36 tools share three implementation patterns that promote reliability and LLM self-correction. First, every parameter carries a typed JSON Schema object with a plain-English description; the MCP server validates incoming calls before executing any handler code. Second, all tools return a uniform JSON envelope with explicit unit annotations to prevent silent unit-mismatch errors. Third, failed calls include a hint field with actionable recovery guidance—e.g., *“load the circuit first”*—enabling the LLM to self-correct workflow-ordering errors without user intervention [ 26 , 29 ].

In the following, we present two example user queries to illustrate how the LLM autonomously orchestrates tool usage. **User:** *Are there any voltage violations on the feeder?* **Grid-Orch:** The LLM triggers a power flow solve followed by a system-wide bus voltage scan, filtering buses outside the acceptable range ($0.95$–$1.05$ p.u.). It returns a natural-language summary identifying any violations with per-unit values. 
**Tools chained:** solve_power_flow $\rightarrow$ get_all_bus_voltages **User:** *Run a 24-hour simulation and show voltages.* **Grid-Orch:** The LLM chains load-shape assignment, a 24-hour QSTS run, and a voltage profile extraction, identifying the worst-case interval and bus. Results populate the QSTS dashboard automatically. 
 **Tools chained:** create_loadshape $\rightarrow$ assign_loadshape $\rightarrow$ run_qsts $\rightarrow$ get_qsts_voltage_profile The nine equipment-management tools (Capacitor, Reactor, and Regulator/Tap categories) enable closed-loop *what-if* analysis: for example, engineers can add or remove shunt banks, adjust regulator taps ($-16$ to $+16$), and re-solve power flow iteratively—transforming Grid-Orch from a read-only assistant into an interactive design environment.

### IV-B *Skills Framework*

While individual tools are deliberately atomic, practical distribution tasks (diagnosing undervoltage, optimizing capacitor placement, mitigating overvoltage) require coordinating multiple tools in sequence. Delegating this sequencing entirely to the LLM would introduce non-determinism, risking incorrect tool ordering or missed steps in safety-relevant analyses. To address this, Grid-Orch introduces a *Skills* layer [ 30 ]: each skill is a Python class that encapsulates a complete multi-step workflow, calling MCP tools programmatically through an inversion-of-control callback (Fig. 4). The LLM selects the appropriate skill; the skill itself executes deterministically.

**Fig. 4:** Skills Framework architecture showing query flow from natural language through skill orchestration to MCP tool execution.

Three skills are currently implemented. 1) The *capacitor placement optimization* skill addresses chronic undervoltage using Particle Swarm Optimization (PSO) [ 31 ], proceeding through baseline voltage assessment, candidate bus selection, PSO iteration over (bus, kvar) placement pairs, optimal placement, and post-optimization verification; in preliminary tests on the IEEE 13-bus feeder it substantially reduced undervoltage violations. 2) The *voltage violation analysis* skill classifies each bus against standard voltage limits—severe ($>$3% deviation), moderate (2–3%), or minor ($<$2%)—performs root-cause correlation with feeder topology and load density, and returns ranked corrective recommendations. All bus voltages are reported as positive-sequence magnitudes; per-phase analysis for unbalanced feeders is supported at the tool level but is not currently exposed through this skill. 3) The *overvoltage mitigation* skill resolves buses above 1.05 p.u. [ 32 ] through a prioritized three-strategy sequence: tap changer adjustment, shunt reactor placement sized by $Q_{\mathrm{reactor}}=(V_{\mathrm{actual}}^{2}-V_{\mathrm{target}}^{2})/X$, and excess capacitor removal. Preliminary testing resolved all overvoltage buses across the tested scenarios. Table III summarizes the structural differences between tools and skills. The key distinction is granularity: tools provide elementary operations from which skills compose deterministic workflows.

**TABLE III:** Comparison of MCP Tools and Grid-Orch Skills

| **Dimension** | **MCP Tool** | **Skill** |
|---|---|---|
| Granularity | Single operation | Multi-step workflow |
| Algorithm | None | PSO, classification |
| State | Stateless | Tracks iterations |
| Calls per use | 1 | 5–50+ |
| Determinism | Deterministic | Deterministic |
| LLM role | Argument extraction | Skill selection only |

The tools and skills described above are made accessible through an interactive web platform that unifies conversational control, data access, and integrated visualization, as described next.

## V Platform and Visualization

### V-A *Architecture and Chat Interface*

The **UI tier** hosts **Layer 1** (the Next.js frontend [ 33 ]). The **application tier** consolidates **Layers 2–3** (LLM Service and MCP Server) inside a single FastAPI container [ 34 ], communicating with the frontend via RESTful APIs and with the data tier through provider SDKs and an SQLAlchemy [ 35 ] ORM layer [ 36 ] that translates Python data objects into PostgreSQL queries for user sessions, chat histories, circuit metadata, and load profiles. The **data tier** hosts **Layer 4** (the OpenDSS simulation engine) alongside PostgreSQL [ 37 ] for relational state and MinIO/S3 for circuit package storage. Services are orchestrated by Docker Compose with JWT-based authentication and path-sanitized circuit uploads at the API boundary.

**Fig. 5:** Three-tier web platform architecture with technology stack.

The chat interface (Fig. 6) is the primary interaction mode, mirroring general-purpose LLM assistants while adding power-system-specific controls inline. A collapsible session sidebar lists all conversations for the authenticated user, restoring the full message history along with circuit, provider, model, and profile context on selection. A compact control header exposes four inline selectors that define the simulation context for the active session. When the LLM invokes MCP tools, a collapsible *Tool Call* panel above the reply lists each tool, its arguments, and the raw OpenDSS JSON result, allowing engineers to audit every simulation call underlying an answer.

Each tool returns a structured JSON envelope containing a success flag, result data with explicit unit annotations (e.g., per-unit voltages, kW losses), and, on failure, a field with actionable recovery suggestions. The frontend parses these typed JSON responses to automatically select the appropriate chart component. For example, a voltage query triggers a bar chart, while a QSTS result populates the timeseries viewer.

**Fig. 6:** Grid-Orch chat interface showing a voltage analysis session. The sidebar lists conversation sessions; the control header provides circuit, provider, model, and profile selectors; the message area displays tool invocations and inline analysis results.

![](https://arxiv.org/html/2605.12728v1/figures/chat.png)

### V-B *Provider and Data Libraries*

The provider-agnostic LLM layer (Section III) supports four backends, including two local options for air-gapped operation where no prompts or simulation data leave the operator’s network.

Load profiles govern per-unit load scaling during QSTS simulations. Ten built-in synthetic profiles derived from the End-Use Load Profiles dataset [ 38 ] cover archetypes from residential and commercial office to data center, industrial, solar generation, and a peak-stress worst-case; engineers can upload custom profiles as two-column CSV files. The circuit library bundles the IEEE 13-bus and 123-bus test feeders [ 39 ] with bus coordinate data for topology visualization, and supports download of the Smart-DS synthetic feeders [ 40 ]. Each circuit package bundles the OpenDSS master DSS file, component files, and optional bus coordinates into a versioned archive registered in PostgreSQL for simulation reproducibility.

### V-C *Visualization and User Interface*

Grid-Orch renders simulation results across three integrated surfaces—inline chat, the QSTS dashboard, and exported reports—all sharing the same component library so charts are identical regardless of surface. Charts auto-render whenever a tool response contains structured data. Fig. 8 illustrates a typical interaction: the user asks *“What are the bus voltages,”* and Grid-Orch retrieves system-wide bus voltages, returning both a natural-language summary identifying the elevated voltage at bus rg60 (1.056 p.u., the regulator-output bus) and an inline voltage profile bar chart with green/amber/red limit shading. The tool-call panel (collapsed in the figure) lets engineers audit every OpenDSS call underlying the response.

Fig. 7 traces the end-to-end data flow for a representative voltage query through six stages. The user’s natural-language prompt is converted by the LLM into a typed MCP tool call (step 2); the MCP server validates the call against its JSON Schema before forwarding to OpenDSS (step 3); OpenDSS solves the power flow and returns a structured JSON result with explicit unit annotations (step 4); the frontend pattern-matches the JSON payload to auto-render the appropriate chart (step 5); and the LLM grounds its textual reply on the same JSON (step 6). If the tool call fails schema validation, the MCP server rejects it and the LLM retries with corrected parameters. Because all numerical values originate from OpenDSS through schema-validated calls, the LLM serves as an interface and interpreter rather than a source of simulation results, substantially mitigating hallucination.

**Fig. 7:** End-to-end pipeline for a natural-language voltage query. The user’s prompt traverses six stages: LLM function selection, MCP schema validation, OpenDSS power flow execution, structured JSON return, frontend chart rendering, and grounded textual reply. Malformed tool calls are rejected at step 3 and retried.

The end-to-end data flow is also summarized in Algorithm 1.

**Algorithm 1** End-to-End LLM–MCP–OpenDSS Interaction Pipeline

    1: User query $q$ in natural language
    2: Grounded textual answer and visualization
    3: Receive user query $q$
    4: Convert $q$ into a MCP function call with JSON parameters
    5: Validate the function call using the MCP server’s JSON Schema
    6: Execute the validated request in OpenDSS
    7: Return structured JSON outputs from OpenDSS
    8: Ground the LLM response on the returned JSON outputs
    9: Render charts or tables in the frontend from the same typed JSON payload

**Fig. 8:** Inline visualization in the Grid-Orch chat interface. The user’s natural-language query triggers a system-wide voltage scan; the response includes a textual analysis and an auto-rendered voltage profile bar chart with per-unit limit shading.

![](https://arxiv.org/html/2605.12728v1/figures/chat_voltage_analysis.png)

The feeder topology map (Fig. 9) renders the circuit as an interactive SVG with voltage-colored nodes and five element-type shapes, scaling adaptively from the 13-bus to the 2,356-bus SmartDS feeder.

**Fig. 9:** Interactive feeder topology map for the IEEE 13-bus test feeder. Nodes are colored by per-unit voltage with five shapes encoding element types. Hovering displays bus name, voltage, and base kV.

![](https://arxiv.org/html/2605.12728v1/figures/topology.png)

For post-simulation exploration, a five-tab QSTS dashboard [ 41 ] rendered with the Recharts visualization library provides comprehensive analysis tools, reusing the same component set as the inline chat charts so that visual output is identical across surfaces (Figs. 10–11). The Overview tab summarizes simulation KPIs including minimum and maximum voltage, violation count, and total real and reactive losses. The Voltage Analysis tab allows users to select individual buses via clickable chips; selected timeseries are overlaid with interactive hover tooltips. The Losses tab renders time-indexed real and reactive power losses as a stacked area chart. The Voltage Heatmap displays a bus-by-time matrix color-mapped by per-unit voltage, making violation periods visible at a glance. The Topology Map reuses the interactive SVG map from the chat surface to show spatial voltage distribution. Every tab supports one-click CSV and JSON export of the underlying data. User sessions, chat history, and uploaded circuit packages are persisted per authenticated user with JWT-based email/password signup and login.

**Fig. 10:** QSTS Dashboard — Overview tab showing simulation summary KPIs, top-10 bus voltage profile (left), and 24-hour power loss chart (right) for the IEEE 13-bus feeder with residential load pattern. Five tabs (Overview, Voltage Analysis, Losses, Voltage Heatmap, Topology Map) provide comprehensive post-simulation exploration with CSV/JSON export.

![](https://arxiv.org/html/2605.12728v1/figures/qsts_dashboard_overview.png)

**Fig. 11:** QSTS Dashboard — Voltage Analysis tab. Engineers select buses via clickable chips (five buses selected: 645, 652, 670, 680, 684) and inspect their 24-hour voltage timeseries with interactive hover tooltips. Dashed red lines indicate the upper (1.05 p.u.) and lower (0.95 p.u.) voltage limits.

![](https://arxiv.org/html/2605.12728v1/figures/qsts_dashboard_voltage.png)

## VI Workflow Demonstrations

To illustrate the proposed autonomous workflow, three representative use cases are presented below.

### VI-A *Session Initialization*

On session startup, the user selects a feeder from the circuit library (IEEE 13-bus, 123-bus, or a SmartDS feeder); the selected package is fetched from local storage or pulled from MinIO cloud storage, and its bus coordinates are registered for topology rendering. In parallel, a residential load profile is assigned by default to every load object via the LoadShape tools, so the circuit is immediately ready for power flow or QSTS simulation without further user input. Users can override the default profile, upload a custom CSV, or modify per-load assignments through natural-language commands at any time.

### VI-B *Use Case 1: DER Interconnection Screening*

**Scenario.** A distribution planner needs to evaluate the voltage impact of interconnecting a 2 MW photovoltaic installation at bus 675 of the IEEE 13-bus feeder. This is a routine but time-consuming interconnection screening task encountered regularly in distribution planning departments.

As illustrated in Fig. 1(a), the conventional approach requires five sequential manual steps taking several hours. Steady-state voltage compliance is evaluated against standard voltage limits; full IEEE 1547 screening [ 42 ] (including fault current and protection coordination) is outside the current scope. With Grid-Orch, the engineer submits a single query:

**User:** *What is the impact of adding 2 MW solar PV at bus 675?*

Grid-Orch autonomously modifies the circuit model, runs a power flow solve, retrieves system-wide bus voltages, invokes the voltage violation analysis skill, and renders a voltage profile chart inline—completing the full sequence in under two minutes. The MCP protocol introduces no numerical distortion: all computation is performed by the OpenDSS engine; the LLM layer handles only tool selection and result interpretation.

### VI-C *Use Case 2: 24-Hour QSTS Analysis*

**User:** *Run a 24-hour simulation with residential profile on load 671 and find any voltage violations.*

Grid-Orch executes a six-step sequence without further user input: load-shape creation, assignment to load objects, QSTS execution, voltage profile extraction, violation analysis, and inline chart generation. The QSTS dashboard (Figs. 10–11) is automatically populated: the Overview tab reports 5 violation steps with minimum voltage 0.9608 p.u., while the Voltage Analysis tab lets engineers drill into individual bus timeseries with interactive tooltips.

### VI-D *Use Case 3: Automated Voltage Optimization*

**User:** *Fix the voltage violations using capacitor optimization.*

Grid-Orch routes the request to the capacitor optimization skill, which runs PSO to find optimal placements while excluding overvoltage buses. After convergence, the skill substantially reduces the violation count; the LLM synthesizes the results into a plain-language recommendation with a before/after voltage profile chart.

## VII Discussion and Conclusion

### VII-A *Limitations and Future Work*

LLM reliability remains a practical concern for engineering applications: in multi-tool query chains the model may select semantically similar but incorrect tools, misinterpret intermediate results, or hallucinate parameters not present in the user query. Grid-Orch mitigates these risks at three points: the MCP boundary constrains the LLM to the 36 defined tools (never arbitrary code execution), the Skills framework executes multi-step workflows deterministically once the LLM selects the appropriate skill, and the error-handling design returns structured hints that enable self-correction without user intervention. Despite these safeguards, results should be treated as preliminary analyses subject to engineering review; human-in-the-loop verification is essential before any results inform investment decisions or operational changes.

Tool selection accuracy may degrade as the catalog grows with overlapping functionality; hallucination risk also increases for complex multi-tool chains that exceed the model’s recovery capability.

Three directions for future investigation are: expanding the tool library to transient stability and protection coordination domains while integrating additional simulation engines (ANDES [ 43 ], CYME, PSCAD, GridLAB-D, PSS/E, etc.) via the MCP server interface; conducting a formal user study to validate usability improvements; and developing a semantic tool-retrieval layer that dynamically selects relevant tools per query rather than exposing the full catalog.

### VII-B *Conclusion*

This paper has introduced Grid-Orch, an MCP-based platform for conversational distribution system analysis. The system provides 36 OpenDSS tools across eleven categories, three optimization skills, a multi-provider LLM backend with air-gapped support, and a web platform with inline visualization and an interactive QSTS dashboard. Workflow demonstrations show that analyses ranging from DER interconnection screening to QSTS violation detection complete in under two minutes through natural language, producing numerically identical results to direct OpenDSS scripting. By removing the scripting requirement from distribution analysis, Grid-Orch demonstrates that the MCP protocol can make simulation tools accessible to engineers who lack programming expertise, offering a practical step toward mitigating the projected workforce shortage.

## References

[1] IEEE Power & Energy Society and Kearney (2025) The future of the energy workforce. Technical report IEEE PES/Kearney. Note: [https://resourcecenter.ieee-pes.org/industry-reports/pes_ir_01_081925](https://resourcecenter.ieee-pes.org/industry-reports/pes_ir_01_081925) Cited by: §I.

[2] U.S. Department of Energy (2024) U.S. energy and employment report 2024. Technical report DOE. Note: [https://www.energy.gov/sites/default/files/2024-06/2024-USEER-0.pdf](https://www.energy.gov/sites/default/files/2024-06/2024-USEER-0.pdf) Cited by: §I.

[3] U.S. Department of Energy (2024) Grid modernization strategy 2024. Technical report DOE. Note: [https://www.energy.gov/sites/default/files/2024-12/Grid%20Modernization%20Strategy%202024.pdf](https://www.energy.gov/sites/default/files/2024-12/Grid%20Modernization%20Strategy%202024.pdf) Cited by: §I.

[4] International Energy Agency (2025) World energy employment 2025. Technical report IEA. Note: [https://www.iea.org/reports/world-energy-employment-2025](https://www.iea.org/reports/world-energy-employment-2025)60% of energy companies report labor shortages Cited by: §I.

[5] Electric Power Research Institute (2023) OpenDSS: open distribution system simulator. Note: [https://www.epri.com/pages/sa/opendss](https://www.epri.com/pages/sa/opendss)Version 9.x Cited by: §I, §III-A, §III-D.

[6] OpenAI (2023) Function calling with large language models. Note: [https://platform.openai.com/docs/guides/function-calling](https://platform.openai.com/docs/guides/function-calling)Accessed: 2026-01-05 Cited by: §I, §III-B.

[7] S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan, and Y. Cao (2023) ReAct: synergizing reasoning and acting in language models. In International Conference on Learning Representations (ICLR), Cited by: §I.

[8] L. Wang, C. Ma, X. Feng, Z. Zhang, H. Yang, J. Zhang, Z. Chen, J. Tang, X. Chen, Y. Lin, et al. (2024) A survey on large language model based autonomous agents. Frontiers of Computer Science 18 (6), pp. 186345. External Links: [Document](https://dx.doi.org/10.1007/s11704-024-40231-1) Cited by: §I, §II-A.

[9] M. Jia, Z. Cui, and G. Hug (2025) Enhancing LLMs for power system simulations: a feedback-driven multi-agent framework. IEEE Transactions on Smart Grid 16 (6), pp. 5556–5559. External Links: [Document](https://dx.doi.org/10.1109/TSG.2025.3589114) Cited by: §I, §II-A, TABLE I.

[10] Z. Li, H. Yang, Y. Liu, Y. Xiang, H. Gao, J. Liu, and J. Liu (2026) OptDisPro: LLM-based multi-agent framework for flexibly adapting heuristic optimal DisFlow. IEEE Transactions on Smart Grid 17 (1), pp. 794–796. External Links: [Document](https://dx.doi.org/10.1109/TSG.2025.3620496) Cited by: §I, §II-A, TABLE I.

[11] Y. Zhang, A. M. Saber, A. Youssef, and D. Kundur (2025) Grid-Agent: an LLM-powered multi-agent system for power grid control. Note: arXiv preprint arXiv:2508.05702 Cited by: §I, §II-A, TABLE I.

[12] Y. Wen and X. Chen (2025) X-GridAgent: an LLM-powered agentic AI system for assisting power grid analysis. Note: arXiv preprint arXiv:2512.20789 Cited by: §I, §II-A, TABLE I.

[13] A. Jena, F. Ding, J. Wang, Y. Yao, and L. Xie (2025) LLM-based adaptive distribution voltage regulation under frequent topology changes: an in-context MPC framework. IEEE Transactions on Smart Grid 16 (5), pp. 4297–4299. External Links: [Document](https://dx.doi.org/10.1109/TSG.2025.3583934) Cited by: §I, §II-A, TABLE I.

[14] Anthropic (2024) Model context protocol specification. Note: [https://spec.modelcontextprotocol.io/](https://spec.modelcontextprotocol.io/)Version 1.0, Released November 2024 Cited by: §I, §II-B, §III-B.

[15] S. Jin and S. Abhyankar (2024) ChatGrid: power grid visualization empowered by a large language model. In 2024 IEEE Workshop on Energy Data Visualization (EnergyVis), pp. 12–16. External Links: [Document](https://dx.doi.org/10.1109/EnergyVis63885.2024.00007) Cited by: §II-A, TABLE I.

[16] H. Jin, K. Kim, and J. Kwon (2025) GridMind: LLMs-powered agents for power system analysis and operations. Note: arXiv preprint arXiv:2509.02494 Cited by: §II-A, TABLE I.

[17] M. Sarwar, M. Rizwan, M. Aziz, and A. R. Sudais (2025) Large language models for power system applications: a comprehensive literature survey. Note: arXiv preprint arXiv:2512.13004 Cited by: §II-A.

[18] Y. Chen and A. Anderson (2025) Connecting minds: AI use cases to bridge power systems and large language models for practical applications. Technical report Technical Report PNNL-38003, Pacific Northwest National Laboratory, Richland, WA. Note: Prepared for the U.S. Department of Energy under Contract DE-AC05-76RL01830 Cited by: §II-A.

[19] F. Bernier, J. Cao, M. Cordy, and S. Ghamizi (2025) PowerGraph-LLM: novel power grid graph embedding and optimization with large language models. IEEE Transactions on Power Systems 40, pp. 5483–5486. External Links: [Document](https://dx.doi.org/10.1109/TPWRS.2025.3596774) Cited by: §II-A.

[20] S. L. Choi, R. Jain, P. Emami, K. Wadsack, F. Ding, H. Sun, K. Gruchalla, J. Hong, H. Zhang, X. Zhu, and B. Kroposki (2024) eGridGPT: trustworthy AI in the control room. Technical report Technical Report NREL/TP-5D00-87440, National Renewable Energy Laboratory, Golden, CO. External Links: [Link](https://www.nrel.gov/docs/fy24osti/87440.pdf) Cited by: §II-A.

[21] N. Yang, G. Lyu, M. Ma, Y. Lu, Y. Li, Z. Gao, H. Ye, J. Zhang, T. Chen, and Y. Chen (2025) IoT-MCP: bridging LLMs and IoT systems through model context protocol. In Proceedings of the 19th ACM Workshop on Wireless Network Testbeds, Experimental evaluation & Characterization (WiNTECH ’25), Washington, DC. External Links: [Document](https://dx.doi.org/10.1145/3737895.3768303) Cited by: §II-B.

[22] X. Hou, Y. Zhao, S. Wang, and H. Wang (2025) Model context protocol (MCP): landscape, security threats, and future research directions. Note: arXiv preprint arXiv:2503.23278 Cited by: §II-B.

[23] H. Chase (2023) LangChain: building applications with LLMs through composability. Note: [https://github.com/langchain-ai/langchain](https://github.com/langchain-ai/langchain)v0.1+; open-source LLM application framework Cited by: §II-B, §III-B.

[24] Q. Zhang and L. Xie (2025) PowerAgent: a road map toward agentic intelligence in power systems: foundation model, model context protocol, and workflow. IEEE Power and Energy Magazine. Cited by: §II-B.

[25] NREL and Contributors (2023) OpenDSSDirect.py: python interface for OpenDSS. Note: [https://github.com/dss-extensions/OpenDSSDirect.py](https://github.com/dss-extensions/OpenDSSDirect.py)Version 0.9.x Cited by: §III-A, §III-D.

[26] Y. Qin, S. Liang, Y. Ye, K. Zhu, L. Yan, Y. Lu, Y. Lin, X. Cong, X. Tang, B. Qian, et al. (2024) Tool learning with foundation models. ACM Computing Surveys. External Links: [Document](https://dx.doi.org/10.1145/3704435) Cited by: §III-B, §IV-A.

[27] North American Electric Reliability Corporation (NERC) (2016) CIP-007-6 cyber security – system security management. Note: [https://www.nerc.com/standards/reliability-standards/cip/cip-007-6](https://www.nerc.com/standards/reliability-standards/cip/cip-007-6)Reliability Standard Cited by: §III-C.

[28] R. C. Dugan and D. Montenegro (2019) Reference guide: the open distribution system simulator (OpenDSS). Technical report Electric Power Research Institute. Note: Includes QSTS methodology and time-series simulation procedures Cited by: §III-D.

[29] T. Schick, J. Dwivedi-Yu, R. Dessì, R. Raileanu, M. Lomeli, E. Hambro, L. Zettlemoyer, N. Cancedda, and T. Scialom (2023) Toolformer: language models can teach themselves to use tools. Advances in Neural Information Processing Systems 36. Cited by: §IV-A.

[30] B. Zhang, K. Lazuka, and M. Murag (2025) Equipping agents for the real world with agent skills. Note: [https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)Anthropic Engineering Blog, October 2025 Cited by: §IV-B.

[31] J. Kennedy and R. Eberhart (1995) Particle swarm optimization. In Proceedings of ICNN’95 - International Conference on Neural Networks, Vol. 4, pp. 1942–1948. External Links: [Document](https://dx.doi.org/10.1109/ICNN.1995.488968) Cited by: §IV-B.

[32] H. Sun, Q. Guo, J. Qi, V. Ajjarapu, R. Bravo, J. Chow, Z. Li, R. Moghe, E. Nasr-Azadani, U. Tamrakar, et al. (2019) Review of challenges and research opportunities for voltage control in smart grids. IEEE Transactions on Power Systems 34 (4), pp. 2790–2801. External Links: [Document](https://dx.doi.org/10.1109/TPWRS.2019.2897948) Cited by: §IV-B.

[33] Vercel (2024) Next.js: the react framework for production. Note: [https://nextjs.org/](https://nextjs.org/)Accessed: 2026-04-13 Cited by: §V-A.

[34] S. Ramírez (2018) FastAPI: a modern, fast (high-performance) web framework for building apis with python. Note: [https://fastapi.tiangolo.com/](https://fastapi.tiangolo.com/)Accessed: 2026-04-13 Cited by: §V-A.

[35] M. Bayer (2026) SQLAlchemy: the python sql toolkit and object relational mapper. Note: [https://www.sqlalchemy.org/](https://www.sqlalchemy.org/)Version 2.0 Documentation, Accessed: 2026-04-13 Cited by: §V-A.

[36] S. W. Ambler (2003) Mapping objects to relational databases: o/r mapping in detail. IBM DeveloperWorks. Cited by: §V-A.

[37] P. G. D. Group (2024) PostgreSQL: the world’s most advanced open source relational database. Note: [https://www.postgresql.org/](https://www.postgresql.org/)Accessed: 2026-04-13 Cited by: §V-A.

[38] National Renewable Energy Laboratory (2022) End-use load profiles for the U.S. building stock. Note: [https://www.nrel.gov/buildings/end-use-load-profiles.html](https://www.nrel.gov/buildings/end-use-load-profiles.html) Cited by: §V-B.

[39] K. P. Schneider, B. A. Mather, B. C. Pal, et al. (2017) Analytic considerations and design basis for the IEEE distribution test feeders. IEEE Transactions on Power Systems 33 (3), pp. 3181–3188. External Links: [Document](https://dx.doi.org/10.1109/TPWRS.2017.2760011) Cited by: §V-B.

[40] B. Palmintier, C. Mateo Domingo, F. E. Postigo Marcos, T. Gomez San Roman, F. de Cuadra, N. Gensollen, T. Elgindy, and P. Duenas (2020) SMART-ds synthetic electrical network data opendss models for sfo, gso, and aus. Note: Open Energy Data Initiative (OEDI), National Renewable Energy Laboratory (NREL)Accessed: 2026-04-08 External Links: [Link](https://data.openei.org/submissions/2981) Cited by: §V-B.

[41] D. Montenegro and R. C. Dugan (2016) Quasi-static time-series simulation using OpenDSS. Technical report Electric Power Research Institute. Cited by: §V-C.

[42] IEEE Standards Association (2018) IEEE standard for interconnection and interoperability of distributed energy resources with associated electric power systems interfaces. IEEE. External Links: [Document](https://dx.doi.org/10.1109/IEEESTD.2018.8332112) Cited by: §VI-B.

[43] H. Cui, F. Li, and K. Tomsovic (2020) Hybrid symbolic-numeric framework for power system modeling and analysis. IEEE Transactions on Power Systems 36 (2), pp. 1373–1384. Cited by: §VII-A.
