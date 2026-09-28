# PowerMCP Agentic Research Experiment System V2
## Detailed Specification & Execution Plan

> Status: **V2 MVP implemented; Agent research-loop extensions remain planned**  
> Baseline: PowerMCP Gateway v4 / 2026-09-28  
> Scope: Agent-based power-system research experiment workflow  

> Implementation note (2026-09-28): the repository now contains the V2 core domain model, proposal validation/preview, deterministic compiler, immutable commit artifacts, JSONL Observation Store, deterministic analysis, proposal/experiment query APIs, cancellation boundary, V1 compatibility reads, and a frontend proposal Review/Commit card. The remaining planned work is session-trace proposal generation, Agent context/query tools, follow-up proposal wiring, real artifact payload storage, result-table pivots, and experiment-level concurrency. See `docs/journal/handoff_2026-09-28_experiment-v2-research-loop.md` for the verified implementation boundary and test results.
> Primary goal: connect dynamic Agent exploration with reproducible, deterministic, batch experiment execution without putting the LLM inside the execution loop.

---

# 1. Executive Summary

The current experiment-matrix implementation is a solid deterministic batch executor and dataset builder, but it is not yet a complete agentic research workflow.

The V2 architecture keeps the existing deterministic execution substrate and adds explicit research-layer contracts:

```text
Agent Exploration
      │
      ▼
Experiment Proposal
      │
      ▼
Deterministic Validation
      │
      ▼
Experiment Compiler
      │
      ▼
Immutable Experiment
      │
      ▼
Deterministic Executor
      │
      ▼
Observation Store
      │
      ▼
Deterministic Analysis
      │
      ▼
Agent Interpretation
      │
      ▼
Next Experiment Proposal
```

The key design principle is:

> **The Agent may dynamically explore and design experiments, but once an experiment is committed, its execution definition is immutable and contains no LLM decision point.**

The existing matrix remains important, but its architectural role changes:

> **Experiment Matrix = deterministic execution representation, not the complete research model.**

The research-level object becomes:

```text
ResearchExperiment
├── Research Question
├── Hypothesis
├── Objective
├── Design
├── Execution Plan
├── Observables
├── Analysis Plan
└── Provenance
```

---

# 2. Design Goals

## 2.1 Primary goals

1. Connect Agent exploration to reproducible experiment execution.
2. Preserve deterministic execution after experiment commit.
3. Support parameter sweeps, scenario scans, N-1 studies, and similar batch workflows.
4. Preserve complete provenance.
5. Make results queryable by Agent without dumping an entire matrix into context.
6. Separate deterministic computation from LLM interpretation.
7. Support iterative research:
   - explore
   - formulate hypothesis
   - propose experiment
   - execute
   - analyze
   - revise hypothesis
   - propose next experiment.
8. Avoid claiming solver capabilities that are not actually verified.
9. Reuse PowerMCP/PowerIO typed operations where available rather than inventing unsupported solver semantics.
10. Maintain backward compatibility with the existing deterministic experiment executor during migration.

## 2.2 Non-goals

V2 does not attempt to:

- make the LLM part of the deterministic execution loop;
- automatically infer scientific causality from correlation;
- guarantee that an Agent-generated hypothesis is scientifically correct;
- hide solver limitations behind semantic abstractions;
- implement distributed execution before the single-process serial model is stable;
- make the Gateway itself a general-purpose statistical package;
- automatically publish scientific conclusions.

---

# 3. Existing Baseline to Preserve

The current implementation already has several important safety and reproducibility properties. These are V2 invariants, not disposable legacy behavior.

## 3.1 Deterministic execution

Execution must remain:

```text
No LLM
No dynamic replanning
No adaptive parameter changes
No hidden retries that alter experiment semantics
```

The executor consumes an immutable execution plan.

## 3.2 One cell = one isolated execution session

Each cell must have an isolated session so that state from one cell cannot contaminate another.

## 3.3 Failure isolation

A failure stops the remaining steps of the current cell but does not silently turn the whole experiment into success.

Other cells may continue.

## 3.4 Remount/reconnection failures are explicit failures

A remounted session must not be interpreted as a successful solver execution.

The result must distinguish:

```text
environment/session failure
```

from:

```text
solver non-convergence
```

from:

```text
physical constraint violation
```

## 3.5 Empty steps are invalid

An experiment with zero executable steps must not receive a successful execution status.

## 3.6 Static template semantics remain valid

Existing placeholders such as:

```text
{case_path}
{case_id}
{factor_name}
```

remain supported.

Unknown placeholders must fail validation before execution.

Whole-value placeholders must preserve their JSON type.

Example:

```json
{"load_scale": "{scale}"}
```

with:

```json
{"scale": 1.1}
```

must render to:

```json
{"load_scale": 1.1}
```

not:

```json
{"load_scale": "1.1"}
```

## 3.7 Cache identity remains content-addressed

The cache key must depend only on inputs that can be established deterministically.

The implementation must not introduce hidden mutable state into the cache identity.

---

# 4. Architectural Model

## 4.1 High-level architecture

```text
┌───────────────────────────────┐
│        Research Agent         │
│                               │
│ exploration                   │
│ tool use                      │
│ hypothesis formulation        │
│ interpretation                │
└───────────────┬───────────────┘
                │
                │ propose
                ▼
┌───────────────────────────────┐
│     Experiment Proposal       │
│                               │
│ question                      │
│ hypothesis                    │
│ variables                     │
│ design                        │
│ observables                   │
│ analysis intent               │
└───────────────┬───────────────┘
                │
                │ validate
                ▼
┌───────────────────────────────┐
│     Experiment Validator      │
│                               │
│ schema                        │
│ factor closure                │
│ tool validity                 │
│ case validity                 │
│ cardinality                   │
│ resource estimate             │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│      Experiment Compiler      │
│                               │
│ semantic DSL                  │
│ deterministic generators      │
│ static expansion              │
│ PowerMCP/PowerIO operations   │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│      Immutable Experiment     │
│                               │
│ compiled cells                │
│ execution steps               │
│ provenance                    │
│ analysis specification        │
└───────────────┬───────────────┘
                │
                │ deterministic
                ▼
┌───────────────────────────────┐
│     Experiment Executor       │
│                               │
│ serial execution              │
│ isolated sessions             │
│ cache/replay                  │
│ no LLM                        │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│       Observation Store       │
│                               │
│ inputs                        │
│ metrics                       │
│ diagnostics                   │
│ artifacts                     │
│ provenance                    │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│    Deterministic Analysis     │
│                               │
│ extrema                       │
│ boundaries                    │
│ representative cases          │
│ observed patterns             │
│ comparisons                   │
│ optional statistics           │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│        Research Agent         │
│                               │
│ interpretation                │
│ critique                      │
│ hypothesis revision           │
│ next experiment proposal      │
└───────────────────────────────┘
```

---

# 5. Core Domain Objects

V2 introduces six core objects.

```text
ResearchQuestion
Hypothesis
ExperimentProposal
Experiment
Cell
Observation
```

Artifacts and provenance are cross-cutting objects attached to observations and experiments.

---

# 6. Research Question

## 6.1 Schema

```json
{
  "id": "rq-001",
  "statement": "How does increasing system load affect N-1 branch loading?",
  "scope": {
    "cases": ["ieee39"],
    "phenomenon": "thermal_overload"
  }
}
```

## 6.2 Requirements

A research question:

- is human-readable;
- must not be required for execution;
- must be preserved for provenance;
- may be supplied by the user or Agent;
- must not be treated as scientifically validated merely because it exists.

---

# 7. Hypothesis

## 7.1 Schema

```json
{
  "id": "hyp-001",
  "statement": "Increasing total active load increases the maximum branch loading under N-1 contingencies.",
  "independent_variables": [
    "load_scale"
  ],
  "dependent_variables": [
    "max_branch_loading_pct"
  ],
  "controls": [
    "network_topology",
    "solver_settings"
  ],
  "expected_direction": {
    "load_scale": "increase",
    "max_branch_loading_pct": "increase"
  }
}
```

## 7.2 Principle

`hypothesis.statement` is a research claim or expectation, not a verified result.

The system must never silently convert:

```text
hypothesis
```

into:

```text
fact
```

---

# 8. Experiment Proposal

This is the most important new object.

The current `solidify_session_to_experiment` operation should not directly create an immutable experiment.

Instead:

```text
Agent Session
     ↓
ExperimentProposal
     ↓
Validation
     ↓
User/Policy Confirmation
     ↓
Commit
     ↓
Experiment
```

## 8.1 Schema

```json
{
  "proposal_id": "proposal-001",
  "title": "IEEE-39 load scaling N-1 scan",
  "research_question": {
    "id": "rq-001"
  },
  "hypothesis": {
    "id": "hyp-001"
  },
  "design": {
    "cases": ["ieee39"],
    "factors": [
      {
        "name": "load_scale",
        "type": "continuous",
        "values": [0.9, 1.0, 1.1, 1.2]
      },
      {
        "name": "outage_branch",
        "type": "categorical",
        "values": [
          "branches:0",
          "branches:1"
        ]
      }
    ]
  },
  "execution": {
    "steps": []
  },
  "observables": [
    "converged",
    "max_branch_loading_pct",
    "min_bus_voltage_pu"
  ],
  "analysis": {
    "requested": [
      "extreme_cases",
      "boundary_cases",
      "factor_comparison"
    ]
  },
  "origin": {
    "source": "agent_session",
    "session_id": "session-001"
  }
}
```

---

# 9. Experiment

An Experiment is the committed, immutable research execution object.

## 9.1 Principle

After commit:

```text
Experiment definition MUST NOT change.
```

If the research design changes:

```text
new proposal → new experiment
```

not:

```text
mutate existing experiment
```

## 9.2 Schema

```json
{
  "schema_version": "2.0",
  "eid": "exp-20260928-001",
  "title": "IEEE-39 load scaling N-1 scan",

  "research": {
    "question": {
      "id": "rq-001",
      "statement": "How does increasing system load affect N-1 branch loading?"
    },
    "hypothesis": {
      "id": "hyp-001",
      "statement": "Increasing total active load increases maximum branch loading."
    }
  },

  "design": {
    "cases": [
      {
        "case_id": "ieee39",
        "case_sha256": "..."
      }
    ],
    "factors": [
      {
        "name": "load_scale",
        "type": "number",
        "values": [0.9, 1.0, 1.1, 1.2]
      },
      {
        "name": "outage_branch",
        "type": "string",
        "values": [
          "branches:0",
          "branches:1"
        ]
      }
    ]
  },

  "execution": {
    "steps": [
      {
        "server": "powerio",
        "tool": "load_network",
        "args_template": {}
      }
    ]
  },

  "observables": {
    "metrics": [
      "converged",
      "max_branch_loading_pct",
      "min_bus_voltage_pu"
    ],
    "artifacts": [
      "solver_output",
      "violations"
    ]
  },

  "analysis": {
    "methods": [
      "summary",
      "extreme_cases",
      "boundary_cases",
      "factor_comparison"
    ]
  },

  "provenance": {
    "proposal_id": "proposal-001",
    "source_session_id": "session-001",
    "compiler_version": "..."
  },

  "status": "registered"
}
```

---

# 10. Cell

A Cell is one concrete experimental condition.

```text
case × factor_1 × factor_2 × ...
```

## 10.1 Example

```json
{
  "cell_id": "cell-0007",
  "eid": "exp-001",
  "bindings": {
    "case_id": "ieee39",
    "load_scale": 1.1,
    "outage_branch": "branches:1"
  },
  "steps": [
    {}
  ],
  "cache_key": "..."
}
```

## 10.2 Cell identity

Cell identity must be deterministic.

The identity must include:

- experiment execution definition;
- case content identity;
- factor bindings;
- relevant tool/compiler version information that affects execution semantics.

It must not depend on:

- LLM wording;
- timestamps;
- UI ordering;
- transient session IDs.

---

# 11. Observation

An Observation is the result of executing one Cell.

## 11.1 Schema

```json
{
  "observation_id": "obs-0007",
  "cell_id": "cell-0007",

  "inputs": {
    "case_id": "ieee39",
    "load_scale": 1.1,
    "outage_branch": "branches:1"
  },

  "execution": {
    "status": "completed",
    "duration_s": 1.82,
    "session_remounted": false
  },

  "metrics": {
    "converged": true,
    "max_branch_loading_pct": 118.2,
    "min_bus_voltage_pu": 0.942
  },

  "diagnostics": {
    "violations": [
      {
        "element": "branches:21",
        "quantity": "loading_pct",
        "value": 118.2,
        "limit": 100.0
      }
    ]
  },

  "artifacts": [
    {
      "artifact_id": "artifact-0007",
      "type": "solver_output",
      "sha256": "..."
    }
  ],

  "provenance": {
    "case_sha256": "...",
    "experiment_id": "exp-001",
    "cell_id": "cell-0007",
    "executor_version": "..."
  }
}
```

---

# 12. Execution Status Model

The system must distinguish at least:

```text
pending
running
completed
failed_environment
failed_execution
failed_validation
not_converged
cancelled
```

Do not collapse all failures into a single generic `failed`.

Examples:

```text
PowerMCP process disconnected
→ failed_environment

Unknown tool argument
→ failed_validation

Solver returned normally but did not converge
→ not_converged

Tool execution raised an exception
→ failed_execution
```

This distinction is required for Agent interpretation.

---

# 13. Artifact Model

Artifacts must be stored separately from compact metrics.

Recommended layout:

```text
~/.powermcp_gateway/experiments/<eid>/
├── proposal.json
├── definition.json
├── manifest.json
├── observations.jsonl
├── analysis.json
└── artifacts/
    ├── <artifact_sha256>.json
    ├── <artifact_sha256>.txt
    └── ...
```

## 13.1 Artifact requirements

Every artifact should have:

```json
{
  "artifact_id": "...",
  "type": "violations",
  "mime_type": "application/json",
  "sha256": "...",
  "cell_id": "...",
  "created_by": "executor",
  "size_bytes": 12345
}
```

Do not put huge solver payloads directly into the Agent context.

---

# 14. Provenance Model

Provenance is divided into four categories.

## 14.1 Research provenance

```json
{
  "session_id": "...",
  "proposal_id": "...",
  "hypothesis_id": "..."
}
```

## 14.2 Input provenance

```json
{
  "case_sha256": "...",
  "input_artifact_hash": "..."
}
```

## 14.3 Software provenance

```json
{
  "powermcp_version": "...",
  "powerio_version": "...",
  "executor_version": "...",
  "solver_version": null
}
```

If a version cannot be reliably determined:

```json
{
  "value": null,
  "status": "unknown",
  "reason": "not exposed by integration"
}
```

Never guess a version.

## 14.4 Execution provenance

```json
{
  "started_at": "...",
  "duration_s": 1.82,
  "session_id": "..."
}
```

---

# 15. Experiment Design DSL

The current factor model should remain as the lowest-level representation, but V2 introduces a compiler-level design language.

The critical principle is:

> **Semantic experiment concepts belong to the Experiment Compiler, not to the solver contract.**

Example:

```json
{
  "factor": {
    "name": "load_scale",
    "kind": "load_scaling",
    "values": [0.9, 1.0, 1.1, 1.2],
    "target": "all_loads",
    "quantity": "active_power"
  }
}
```

This does NOT imply that the solver exposes a native:

```text
load_scale
```

parameter.

The compiler translates the semantic design into deterministic concrete operations.

---

# 16. Compiler Architecture

```text
ExperimentProposal
       │
       ▼
Schema Validation
       │
       ▼
Design Validation
       │
       ▼
Semantic Generator Expansion
       │
       ▼
PowerMCP/PowerIO Operation Compilation
       │
       ▼
Static Cell Expansion
       │
       ▼
Immutable Experiment
```

The compiler must finish before execution starts.

---

# 17. Deterministic Generators

Generators are allowed only if they are:

1. deterministic;
2. side-effect free;
3. inspectable;
4. fully expanded before commit;
5. represented by their expanded output in the immutable execution definition.

Examples:

```text
linear_range
enumerate_case_branches
enumerate_case_generators
```

Potential future generators:

```text
enumerate_generators_by_type
enumerate_loads
enumerate_transformers
time_series_slice
scenario_set
```

---

# 18. Generator Rules

## 18.1 No hidden state

A generator must not depend on:

- current time;
- LLM state;
- network calls;
- random values without an explicit seed;
- mutable global state.

## 18.2 Expansion must be inspectable

Before commit:

```text
Generator
→ expanded factor values
→ cell count
```

must be visible to the user.

Example:

```text
IEEE-39
× 46 branches
× 4 load levels
= 184 cells
```

## 18.3 Expansion failure is a proposal/compiler error

Do not create a partially defined experiment.

---

# 19. PowerMCP / PowerIO Integration Principle

The Experiment Compiler should use the existing PowerMCP/PowerIO typed operations where they are available.

Examples include operations for:

```text
load active power
load reactive power
generator active/reactive power
generator voltage magnitude
generator status
branch status
transformer tap
transformer phase shift
switch state
thermal rating
bus load allocation
```

The architecture should therefore be:

```text
Scientific Experiment DSL
          ↓
Experiment Compiler
          ↓
PowerMCP / PowerIO typed operations
          ↓
Solver adapter
```

rather than:

```text
Scientific Experiment DSL
          ↓
Gateway invents undocumented solver semantics
          ↓
Solver
```

This preserves the existing honesty boundary.

---

# 20. Example: Load Scaling

High-level design:

```json
{
  "name": "load_scale",
  "kind": "load_scaling",
  "values": [0.9, 1.0, 1.1, 1.2],
  "target": "all_loads",
  "quantity": "p"
}
```

Compiler output must contain concrete deterministic operations.

For example:

```json
{
  "edits": [
    {
      "op": "set_bus_load_active_power",
      "bus": "bus:1",
      "mw": 91.5,
      "allocation": "proportional_to_current_active_power"
    }
  ]
}
```

The actual target operation depends on the PowerMCP/PowerIO capabilities available for the selected case and solver.

---

# 21. Example: N-1 Experiment

High-level design:

```json
{
  "factor": {
    "name": "outage_branch",
    "kind": "branch_outage",
    "source": {
      "type": "case_branches"
    }
  }
}
```

Compiler:

```text
case branch enumeration
        ↓
stable branch identities
        ↓
factor values
        ↓
static cells
        ↓
branch status edit
        ↓
solver
```

The final committed experiment contains the explicit branch identities.

It must not rely on re-enumerating branches during execution.

---

# 22. Experiment Validation

Validation occurs in three stages.

## 22.1 Schema validation

Validate:

- JSON structure;
- required fields;
- data types;
- enum values.

## 22.2 Semantic validation

Validate:

- factor references;
- step references;
- operation compatibility;
- case existence;
- generator arguments;
- observable definitions.

## 22.3 Execution feasibility validation

Validate:

- non-empty steps;
- valid server/tool;
- valid case paths;
- supported session model;
- estimated cell count;
- estimated execution cost;
- resource limits.

---

# 23. Resource Guardrails

Before commit, calculate:

```text
cell_count
estimated_steps
estimated_execution_time
estimated_artifact_size
```

Example:

```json
{
  "resource_estimate": {
    "cells": 184,
    "steps_per_cell": 3,
    "total_steps": 552,
    "estimated_duration_s": 840,
    "warning": "large experiment"
  }
}
```

Thresholds should be configurable.

Potential policies:

```text
< 100 cells
→ normal confirmation

100–1000
→ explicit confirmation

> 1000
→ require user confirmation + warning

very large
→ reject or require manual scheduling
```

These are product guardrails, not scientific conclusions.

---

# 24. Commit Semantics

A proposal becomes an experiment only after:

```text
proposal validated
+
compiler completed
+
resource estimate generated
+
confirmation policy satisfied
```

Commit creates:

```text
eid
definition.json
manifest.json
cell list
provenance
```

After commit:

```text
definition.json = immutable
```

---

# 25. Agent Tools

The Agent should receive a set of narrow, composable tools.

## 25.1 Exploration tools

Existing PowerMCP tools remain available.

## 25.2 Proposal tools

### `propose_experiment`

Purpose:

Create an ExperimentProposal.

Input:

```json
{
  "title": "...",
  "research_question": {},
  "hypothesis": {},
  "design": {},
  "execution": {},
  "observables": {},
  "analysis": {}
}
```

Output:

```json
{
  "proposal_id": "...",
  "validation": {},
  "resource_estimate": {},
  "preview": {}
}
```

### `validate_experiment_proposal`

Purpose:

Validate without committing.

### `commit_experiment`

Purpose:

Create an immutable experiment.

---

# 26. Replace Direct Solidification

The old tool:

```text
solidify_session_to_experiment
```

should become a compatibility wrapper or eventually be deprecated.

Preferred workflow:

```text
propose_experiment_from_session
```

This tool may inspect the session trace, but it must produce a proposal rather than immediately committing an experiment.

Example:

```json
{
  "source_session_id": "session-001",
  "target_turns": [3, 4],
  "parameterization": {
    "load_scale": [0.9, 1.0, 1.1]
  }
}
```

Output:

```json
{
  "proposal_id": "proposal-001",
  "status": "needs_confirmation"
}
```

The Agent must still explicitly provide or validate:

- research question;
- hypothesis;
- independent variables;
- dependent variables;
- controls;
- intended design.

Do not infer all of these from the trace.

---

# 27. Why Trace Inference Must Be Limited

A tool trace contains:

```text
what was executed
```

but does not necessarily contain:

```text
why it was executed
```

Therefore:

```text
Trace → execution skeleton
```

is safe.

But:

```text
Trace → scientific hypothesis
```

is not automatically safe.

The Agent may propose the missing scientific semantics, but those semantics must remain explicit proposal fields.

---

# 28. Result Query API

Do not expose only one giant `insight-digest`.

Provide layered access.

## 28.1 Experiment summary

```http
GET /experiments/{eid}/summary
```

Returns:

```json
{
  "total_cells": 184,
  "completed": 180,
  "failed_environment": 2,
  "failed_execution": 1,
  "not_converged": 1
}
```

## 28.2 Design

```http
GET /experiments/{eid}/design
```

## 28.3 Observation query

```http
GET /experiments/{eid}/observations
```

Supports filters:

```text
factor values
status
metric thresholds
case_id
```

Example:

```text
max_branch_loading_pct > 120
```

## 28.4 Cell detail

```http
GET /experiments/{eid}/cells/{cell_id}
```

## 28.5 Artifact

```http
GET /experiments/{eid}/cells/{cell_id}/artifacts/{artifact_id}
```

---

# 29. Deterministic Analysis Layer

The analysis layer produces structured facts for the Agent.

It should include:

```text
summary
extreme_cases
boundary_cases
representative_cases
observed_patterns
factor_comparisons
failure_summary
```

Avoid calling something a Pareto front unless actual multi-objective dominance analysis is performed.

---

# 30. Extreme Cases

Example:

```json
{
  "extreme_cases": [
    {
      "metric": "max_branch_loading_pct",
      "direction": "max",
      "cell_id": "cell-12",
      "value": 142.3
    }
  ]
}
```

---

# 31. Boundary Cases

Boundary cases include conditions near a transition, such as:

```text
converged → not_converged
no violation → violation
within limit → overload
```

The analysis layer should report the observed transition.

Example:

```json
{
  "factor": "load_scale",
  "transition": {
    "from": {
      "load_scale": 1.1,
      "status": "within_limit"
    },
    "to": {
      "load_scale": 1.2,
      "status": "overload"
    }
  }
}
```

Do not infer a continuous physical threshold if the experiment does not actually sample it.

---

# 32. Observed Patterns

Use neutral machine-readable patterns.

Example:

```json
{
  "pattern": {
    "type": "threshold_transition",
    "factor": "load_scale",
    "affected_metric": "max_branch_loading_pct",
    "observed_range": [1.1, 1.2]
  },
  "support": {
    "n_cells": 46,
    "n_affected": 10
  }
}
```

Do not generate phrases such as:

```text
statistically significant
strong causal relationship
```

unless the corresponding statistical/causal methodology has actually been executed.

---

# 33. Agent Interpretation

The Agent is responsible for:

```text
What does this mean?
Why might this happen?
What alternative explanations exist?
What should be tested next?
```

The Agent must distinguish:

```text
observed fact
inference
hypothesis
proposed intervention
```

Recommended language in internal structured output:

```json
{
  "claim_type": "hypothesis",
  "statement": "...",
  "evidence": [
    "cell-12",
    "cell-18"
  ],
  "alternative_explanations": [
    "..."
  ]
}
```

---

# 34. Follow-up Experiment

A follow-up study must be a new proposal.

Example:

```text
Observation:
branch 21-22 overloaded after branch 16-17 outage.

Agent hypothesis:
reactive support near bus X may reduce loading.

Next proposal:
Q compensation = [0, 10, 20, 30] Mvar
```

Flow:

```text
Observation
   ↓
Agent diagnosis
   ↓
Hypothesis
   ↓
ExperimentProposal
   ↓
Validation
   ↓
New Experiment
```

Do not mutate the previous experiment.

---

# 35. Cache Design

The existing content-addressed cache model should be retained.

The cache identity should represent the concrete execution condition.

Recommended conceptual input:

```text
H(
  case_sha256,
  compiled_execution_steps,
  cell_bindings,
  relevant_compiler_version,
  relevant execution-core version
)
```

Do not include:

```text
session_id
proposal_id
LLM wording
experiment title
timestamp
```

unless one of those values actually changes execution semantics.

---

# 36. Storage Model

Recommended:

```text
~/.powermcp_gateway/
└── experiments/
    └── <eid>/
        ├── proposal.json
        ├── definition.json
        ├── manifest.json
        ├── observations.jsonl
        ├── analysis.json
        └── artifacts/
            └── ...
```

## 36.1 `proposal.json`

Stores the pre-commit Agent/user proposal.

## 36.2 `definition.json`

Stores the immutable compiled execution definition.

## 36.3 `manifest.json`

Stores:

- schema version;
- compiler version;
- cell count;
- resource estimate;
- provenance;
- artifact index.

## 36.4 `observations.jsonl`

One observation per line.

This avoids repeatedly loading the entire experiment into memory.

---

# 37. REST API

## Existing APIs to preserve

```http
POST   /experiments
GET    /experiments
GET    /experiments/{eid}
POST   /experiments/{eid}/run
GET    /experiments/{eid}/results
GET    /experiments/{eid}/export
DELETE /experiments/{eid}
```

## New APIs

```http
POST /experiment-proposals
GET  /experiment-proposals/{proposal_id}
POST /experiment-proposals/{proposal_id}/validate
POST /experiment-proposals/{proposal_id}/commit

GET /experiments/{eid}/summary
GET /experiments/{eid}/design
GET /experiments/{eid}/observations
GET /experiments/{eid}/cells/{cell_id}
GET /experiments/{eid}/cells/{cell_id}/artifacts/{artifact_id}
GET /experiments/{eid}/analysis
```

---

# 38. Backward Compatibility

Existing Experiment V1 definitions should be accepted.

Migration:

```text
V1 Experiment
    ↓
V2 adapter
    ↓
ResearchExperiment with minimal research metadata
```

Example:

```json
{
  "research": {
    "question": null,
    "hypothesis": null
  },
  "design": {
    "cases": [],
    "factors": []
  }
}
```

Missing research metadata must be explicitly marked unknown rather than fabricated.

---

# 39. UI Specification

## 39.1 Agent conversation

When the Agent proposes an experiment, show:

```text
Experiment Proposal

Title:
IEEE-39 load scaling N-1 scan

Research question:
...

Hypothesis:
...

Cases:
IEEE-39

Factors:
load_scale: 0.9 / 1.0 / 1.1 / 1.2
outage_branch: 46 branches

Cells:
184

Estimated steps:
552

Estimated runtime:
~14 min

[Review] [Commit] [Cancel]
```

## 39.2 Experiment page

Tabs:

```text
Overview
Design
Execution
Observations
Analysis
Artifacts
Provenance
```

## 39.3 Analysis panel

Show:

```text
Execution summary
Extreme cases
Boundary cases
Observed patterns
Failures
```

Then provide:

```text
[Ask Agent]
```

The Agent should receive structured experiment context, not only a prose digest.

---

# 40. Agent Context Injection

When the user asks:

> “分析这个实验”

the Agent should receive:

```text
experiment metadata
+
research question
+
hypothesis
+
design summary
+
analysis summary
+
selected observations
```

It should not automatically receive:

```text
all raw artifacts
```

unless the Agent explicitly requests them.

---

# 41. Security / Safety Boundary

The experiment system must treat Agent-generated experiment definitions as untrusted input.

Validate:

- paths;
- tool names;
- server names;
- argument schema;
- resource limits;
- artifact destinations;
- shell/process-related inputs.

Do not allow a semantic generator to bypass existing PowerMCP tool validation.

---

# 42. Concurrency

V2 initial implementation remains serial.

Do not enable experiment-level parallel execution until:

1. session isolation is verified;
2. solver licensing/resource constraints are understood;
3. artifact writes are safe;
4. cache writes are atomic;
5. result ordering is deterministic.

Parallel execution should be a later executor capability, not part of the core research model.

---

# 43. Cancellation

Add:

```http
POST /experiments/{eid}/cancel
```

Cancellation must produce explicit statuses:

```text
cancelled
```

A cancelled cell must not be reported as:

```text
failed
```

unless an actual execution failure occurred.

---

# 44. Retry Semantics

Retries must not silently alter experiment semantics.

Recommended:

```text
same cell
same compiled steps
same inputs
same cache identity
```

If a retry occurs because of environment failure:

```json
{
  "attempt": 2,
  "reason": "failed_environment"
}
```

The final Observation must retain attempt metadata.

---

# 45. Export

Support:

```text
CSV
Markdown
JSON
```

CSV is for flat datasets.

JSON is the canonical machine-readable export.

Markdown is for human-readable reports.

PDF generation should remain outside the Gateway unless there is a strong product requirement.

---

# 46. Test Strategy

Testing must be organized around contracts.

## 46.1 Unit tests

### Compiler

- deterministic expansion;
- generator correctness;
- placeholder closure;
- type preservation;
- invalid generator rejection.

### Validator

- invalid cases;
- invalid tools;
- empty steps;
- excessive cardinality;
- unknown placeholders.

### Executor

- one session per cell;
- failure isolation;
- remount failure;
- no-LLM guarantee.

### Cache

- same inputs → same cache key;
- changed case → changed key;
- changed execution semantics → changed key.

---

# 47. Integration Tests

Required scenarios:

## Scenario A — Basic sweep

```text
1 case
×
3 factor values
=
3 cells
```

Verify all cells execute independently.

## Scenario B — N-1

```text
IEEE-39
×
all branches
```

Verify enumeration happens at compile time and committed definition contains explicit branch IDs.

## Scenario C — Load scaling

```text
0.9 / 1.0 / 1.1 / 1.2
```

Verify semantic factor is compiled into deterministic operations.

## Scenario D — Failure isolation

Cell 2 fails.

Expected:

```text
Cell 1 completed
Cell 2 failed
Cell 3 completed
```

## Scenario E — Remount

Verify the affected cell is reported as environment failure.

## Scenario F — Agent round trip

```text
Agent exploration
→ proposal
→ validation
→ commit
→ execution
→ analysis
→ Agent interpretation
→ follow-up proposal
```

---

# 48. Acceptance Criteria

V2 is considered functional when all of the following are true.

## AC-1

An Agent can convert a validated exploration into an ExperimentProposal without manually writing JSON.

## AC-2

A proposal can be validated without executing the experiment.

## AC-3

A committed experiment is immutable.

## AC-4

The executor never invokes an LLM during cell execution.

## AC-5

A semantic factor is completely expanded before execution.

## AC-6

The final committed definition contains enough concrete information to reproduce the experiment.

## AC-7

Every observation has cell identity and provenance.

## AC-8

Agent can query summaries and individual observations without loading the full dataset.

## AC-9

Failures distinguish environment, execution, and solver non-convergence.

## AC-10

Agent can use observations to propose a new experiment without mutating the previous one.

---

# 49. Execution Plan

The previous four-sprint plan should be expanded into six phases.

---

## Phase 0 — Contract Freeze

### Duration

1–2 days

### Goal

Define the V2 domain model before implementation changes.

### Deliverables

Create:

```text
schemas/
├── research_question.schema.json
├── hypothesis.schema.json
├── experiment_proposal.schema.json
├── experiment.schema.json
├── cell.schema.json
├── observation.schema.json
└── artifact.schema.json
```

Also define:

```text
ExperimentStatus
CellStatus
ObservationStatus
```

### Exit criteria

All objects and lifecycle transitions are documented.

---

# 50. Phase 1 — Proposal Layer

### Duration

2–3 days

### Goal

Add Agent → Proposal without changing the existing executor.

### Tasks

1. Implement proposal storage.
2. Implement proposal validation.
3. Implement `propose_experiment`.
4. Implement `propose_experiment_from_session`.
5. Add resource estimation.
6. Add proposal preview API.
7. Add frontend proposal card.

### Important constraint

Do not automatically commit proposals.

### Exit criteria

Agent can produce:

```text
proposal
→ validation
→ preview
```

without running cells.

---

# 51. Phase 2 — Compiler Layer

### Duration

3–5 days

### Goal

Compile proposals into immutable deterministic experiments.

### Tasks

1. Build compiler module.
2. Implement factor expansion.
3. Implement deterministic generators.
4. Implement placeholder resolution.
5. Implement semantic factor compilation.
6. Compile to PowerMCP/PowerIO concrete operations.
7. Generate cell IDs.
8. Generate cache keys.
9. Generate manifest.
10. Persist immutable definition.

### Exit criteria

Given the same proposal and same inputs:

```text
compiler output is byte-for-byte deterministic
```

or semantically equivalent under a documented canonical serialization.

---

# 52. Phase 3 — Observation Store

### Duration

3–4 days

### Goal

Upgrade results from flat metrics to structured observations.

### Tasks

1. Implement Observation schema.
2. Implement JSONL observation store.
3. Implement artifact manifest.
4. Store detailed solver/tool payloads.
5. Store diagnostics.
6. Store execution provenance.
7. Add observation query API.

### Exit criteria

A cell can be reconstructed from:

```text
Experiment definition
+
Observation
+
Referenced artifacts
```

---

# 53. Phase 4 — Deterministic Analysis

### Duration

2–4 days

### Goal

Replace the single `insight-digest` concept with structured analysis.

### Tasks

Implement:

```text
summary
extreme_cases
boundary_cases
representative_cases
observed_patterns
factor_comparisons
failure_summary
```

### Important

Do not implement unsupported causal conclusions.

### Exit criteria

For a completed experiment, the analysis API returns deterministic JSON.

---

# 54. Phase 5 — Agent Research Loop

### Duration

3–5 days

### Goal

Connect analysis back to the Agent.

### Tasks

Add tools:

```text
get_experiment
get_experiment_summary
get_experiment_design
query_observations
get_cell
get_artifact
get_experiment_analysis
propose_followup_experiment
```

Agent workflow:

```text
read summary
→ inspect pattern
→ query supporting cells
→ inspect artifacts if needed
→ formulate interpretation
→ formulate hypothesis
→ propose next experiment
```

### Exit criteria

Agent can complete one full research iteration without manual JSON editing.

---

# 55. Phase 6 — UI / End-to-End Hardening

### Duration

3–4 days

### Tasks

1. Proposal card.
2. Experiment preview.
3. Experiment detail tabs.
4. Observation table.
5. Analysis panel.
6. Artifact drill-down.
7. Provenance panel.
8. Ask Agent action.
9. Follow-up experiment action.
10. Error-state UX.

### Exit criteria

End-to-end scenario works through UI.

---

# 56. Suggested Implementation Order in Code

Recommended module structure:

```text
gateway/src/powermcp_gateway/
├── experiments/
│   ├── models.py
│   ├── schemas.py
│   ├── proposals.py
│   ├── compiler.py
│   ├── generators.py
│   ├── validator.py
│   ├── executor.py
│   ├── observations.py
│   ├── artifacts.py
│   ├── analysis.py
│   ├── provenance.py
│   ├── cache.py
│   └── api.py
│
├── agent/
│   ├── experiment_tools.py
│   └── context.py
│
└── ...
```

Avoid placing all V2 logic into the existing `experiments.py`.

---

# 57. Migration Strategy

## Step 1

Keep existing V1 API working.

## Step 2

Introduce V2 internal models.

## Step 3

Adapt V1 Experiment into V2 Experiment.

## Step 4

Switch new Agent-generated experiments to Proposal → Compiler.

## Step 5

Keep old `solidify_session_to_experiment` as a compatibility wrapper:

```text
old tool
→ proposal
→ validation
→ optional confirmation
→ commit
```

## Step 6

Deprecate direct automatic solidification after V2 adoption.

---

# 58. Recommended MVP Scope

Do not implement every semantic factor initially.

MVP should support:

```text
1. explicit numeric factor sweep
2. categorical factor
3. case enumeration
4. branch enumeration
5. load scaling
6. deterministic execution
7. observations
8. artifacts
9. summary/extreme/boundary analysis
10. Agent follow-up proposal
```

Do not start with:

```text
Monte Carlo
Bayesian optimization
adaptive experiment design
distributed execution
complex statistical inference
automatic causal discovery
```

Those should come later.

---

# 59. Example End-to-End Workflow

User:

> Investigate how increasing load affects N-1 thermal overloads on IEEE-39.

Agent explores the case through PowerMCP.

Agent proposes:

```text
Question:
How does load scaling affect N-1 thermal overload?

Hypothesis:
Higher load increases maximum branch loading.

Design:
load_scale = [0.9, 1.0, 1.1, 1.2]
outage_branch = all branches
case = IEEE-39
```

System validates:

```text
46 branches
×
4 load levels
=
184 cells
```

Compiler expands:

```text
semantic load scaling
→ concrete PowerIO/PowerMCP operations

branch enumeration
→ 46 explicit branch IDs
```

User commits.

Executor runs:

```text
184 cells
```

Observation store records:

```text
184 observations
```

Analysis returns:

```text
summary
extreme_cases
boundary_cases
observed_patterns
```

Agent inspects:

```text
summary
→ overload pattern
→ supporting cells
→ artifacts
```

Agent proposes:

```text
Hypothesis:
Reactive support near bus X may reduce overload.

Follow-up:
Q compensation = [0, 10, 20, 30] Mvar
```

This becomes:

```text
ExperimentProposal #2
```

not a mutation of Experiment #1.

---

# 60. Definition of Done

The V2 system is complete when:

```text
                 Agent
                   │
             ┌─────▼─────┐
             │  Proposal │
             └─────┬─────┘
                   │
             validation
                   │
             ┌─────▼─────┐
             │  Compiler │
             └─────┬─────┘
                   │
             immutable spec
                   │
             ┌─────▼─────┐
             │  Executor │
             └─────┬─────┘
                   │
             observations
                   │
             ┌─────▼─────┐
             │ Analysis  │
             └─────┬─────┘
                   │
             ┌─────▼─────┐
             │   Agent   │
             └───────────┘
```

is operational without manual JSON authoring.

The strongest invariant is:

> **Agentic research is dynamic before commit and interpretive after execution; the committed experiment itself is deterministic, immutable, replayable, and fully provenance-traceable.**

---

# 61. Final Design Decisions

The following decisions are normative for V2.

| Decision | V2 rule |
|---|---|
| Experiment execution | deterministic, no LLM |
| Experiment mutability | immutable after commit |
| Agent experiment design | Proposal first |
| Trace solidification | proposal generator, not direct commit |
| Matrix | compiled execution representation |
| Semantic factors | compiler-level DSL |
| Solver semantics | never invented by Gateway |
| PowerMCP integration | prefer verified typed operations |
| Generators | deterministic and fully expanded before execution |
| Result model | Observation, not only flat metrics |
| Artifacts | separate, hashed, queryable |
| Provenance | research + input + software + execution |
| Digest | deterministic analysis, not LLM conclusion |
| Pareto | only when actual multi-objective Pareto analysis exists |
| Scientific interpretation | Agent |
| Follow-up experiment | new Proposal |
| Execution concurrency | serial for MVP |
| Cache | content-addressed |
| Unknown version/capability | explicitly unknown, never guessed |

---

# 62. Relationship to the Existing V1 Design

The existing design does not need to be discarded.

The migration is:

```text
V1
──────────────────────────────
Experiment
├── case_ids
├── factors
└── steps
        │
        ▼
Deterministic Executor
        │
        ▼
Metrics / Artifacts


V2
──────────────────────────────
Research Question
        │
Hypothesis
        │
Experiment Proposal
        │
        ▼
Experiment Compiler
        │
        ▼
Immutable Experiment
├── compiled design
├── explicit cells
├── execution plan
└── provenance
        │
        ▼
Deterministic Executor
        │
        ▼
Observation Store
├── metrics
├── diagnostics
├── artifacts
└── provenance
        │
        ▼
Deterministic Analysis
        │
        ▼
Agent Interpretation
        │
        ▼
Next Experiment Proposal
```

The existing batch executor therefore becomes the stable computational core of the larger Agentic Research Workbench.

---

# 63. Repository Implementation Status (2026-09-28)

This specification is now partly implemented as a V2 MVP. The following acceptance items are verified in the repository:

| Area | Status | Evidence |
|---|---|---|
| V2 domain objects | ✅ | `gateway/src/powermcp_gateway/experiment_v2/models.py` |
| Proposal storage and validation | ✅ | `proposals.py`, `validator.py`, `ProposalStore` |
| Deterministic compiler | ✅ | `compiler.py`; fixed case identity, expanded cells, stable `cell_id` and `cache_key` |
| Immutable commit | ✅ | `definition.json`, `proposal.json`, `manifest.json`; conflicting re-commit rejected |
| Observation Store | ✅ MVP | `observations.jsonl`, structured status, inputs, diagnostics and provenance |
| Deterministic analysis | ✅ MVP | summary, extreme, boundary, representative, pattern, comparison and failure sections |
| V1 compatibility | ✅ | existing `/experiments*` endpoints remain available; V2 definitions have compatibility read views |
| Proposal frontend | ✅ MVP | `ExperimentProposalCard.tsx` with validate/preview/Review/Commit |
| Agent trace → proposal | ⏳ | not yet wired; current UI/API accepts explicit proposal payloads |
| Observation → Agent interpretation | ⏳ | query/analysis APIs exist; Agent context injection is not yet wired |
| Real artifact payload store | ⏳ | artifact endpoint is reserved; content manifest/payload write path remains |
| `result_tables` pivot | ⏳ | remains a P3/module responsibility |
| Experiment-level concurrency | ⏳ | execution remains serial; session-level prerequisites exist but switch is closed |

Verified test baseline for this implementation:

```text
gateway full suite: 651 passed
experiment V1/V2 focused suite: 106 passed
frontend TypeScript check: passed
frontend Vite build: passed
```

The implementation deliberately does not claim scientific causality, solver capability not exposed by a verified tool schema, or complete Agentic Research Workbench functionality until the remaining rows above are delivered.

