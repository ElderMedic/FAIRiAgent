# FAIRiAgent Academic Presentation — Speaker Script

## Slide 1 — Title

FAIRiAgent: Reconstructing FAIR Metadata Objects with Multi-Agent Workflows.

I'm going to talk about a problem that anyone who's ever tried to submit data to a public repository has felt: FAIR metadata is hard. And I'll show you how we're using agentic workflows to make it easier — not by building a bigger model, but by decomposing the problem.

---

## Slide 2 — FAIR by Design — But Difficult in Practice

Let's start with the reality that experimental biologists face.

FAIR principles tell us data should be Findable, Accessible, Interoperable, and Reusable. But actually producing FAIR-compliant metadata? That's a different story.

Think about what a researcher has to do. They need to plan what metadata to collect — ideally before the experiment starts. They need to fill in values across multiple layers of the ISA model. They need to learn community standards like MIxS or ENA checklists. And they need to do this while the paper deadline is approaching.

FAIR-DS — the FAIR Data Station — provides the standard packages and fields. But the tool itself has a learning curve. You still have to manually fill values. It's not a one-shot experience.

So the question becomes: **how can we make this easier?**

---

## Slide 3 — The Target: A 5-Layer ISA Metadata Object

To understand why this is hard, you need to see what we're actually asking people to produce.

FAIR metadata is not a flat table. It's a 5-layer hierarchical object following the ISA model.

At the top, Investigation captures project-level context. Study defines the research design. Then we have three multi-row layers: Observation Unit, Sample, and Assay — each can have multiple rows, and fields within the same layer must be bound to the correct row.

The first two layers are single-row — you fill them once. The bottom three are multi-row — for every sample, every assay, you need to get the row binding right.

**This is not a form-filling problem. This is a structured object reconstruction problem.**

---

## Slide 4 — "Outsource the Boring Work" — Can LLMs Help?

So here's a natural thought: LLMs can read papers and extract information. Why not outsource the boring metadata work to an LLM?

The promise is real. An LLM can read a scientific manuscript, identify the organism, the sequencing platform, the sampling location — all the things a curator would manually look up.

But there's a fundamental difference between asking an LLM to generate text, and asking it to reconstruct a structured metadata object that obeys a specific schema with row-level binding.

This is the paradigm shift: from a single prompt-response to a multi-step workflow where each step is auditable.

---

## Slide 5 — Why Raw LLM Falls Short

Here's what actually happens when you ask a single LLM call to produce FAIR metadata.

**First: hallucination.** The model invents package names that don't exist. It makes up accession numbers. It generates plausible-sounding but wrong field names. Let me show you an example: [LLM output snippet showing hallucinated package/accession]

**Second: context rot.** In a long document, the model forgets early information. By the time it's generating assay-level fields, it's already lost the sampling context from the methods section.

**Third: no ISA structure.** The output is flat. Fields are generated without sheet assignment, without row binding, without entity grouping. It looks like metadata in a JSON file, but it's not usable for submission.

---

## Slide 6 — Two Tasks That Fail Differently

This is where the core insight of our work comes in.

Metadata generation is actually two distinct tasks, and they fail in different ways.

**Metadata Schema** is about structure: which FAIR-DS package should I use? Which fields should exist? Which ISA sheet does each field belong to? Which row within that sheet?

**Value Extraction** is about content: what value goes into each field? Which row does it belong to? What evidence in the paper supports it?

A system can select the correct package and generate the right fields, but still fill incorrect values. And a system can extract locally plausible values while completely failing to reconstruct the ISA hierarchy.

These two tasks need to be designed for separately and evaluated separately.

---

## Slide 7 — Decomposing into Agent Roles

So here's our approach.

Instead of one massive prompt, we decompose the metadata reconstruction problem into a set of agent roles. Each agent addresses a specific failure mode.

Let me walk you through the architecture.

The Document Parser reads the paper and extracts structured study context.

The Planner analyzes the domain and generates agent-specific guidance — which packages to prioritize, which ISA sheets to focus on.

The Knowledge Retriever queries the FAIR-DS API in real time. It searches for relevant packages, retrieves field definitions, and reports what's available. This grounding step is critical: it constrains what the system can generate.

The JSON Generator maps extracted information to FAIR-compliant fields, with evidence, confidence, and ISA sheet assignment.

The Value Mapper fills values into the correct ISA rows with source evidence.

After every agent, a Critic evaluates the output and decides: ACCEPT and move on, RETRY with specific feedback, or ESCALATE for human review.

The point is not that we're using more LLM calls. The point is that each call has an auditable responsibility.

---

## Slide 8 — Grounding in Community Standards

Let me zoom in on grounding, because it's one of the most important pieces.

Without grounding, the LLM generates field names from its training data. Some are real, some are hallucinated. There's no way to tell which is which.

With FAIR-DS grounding, the agent actively queries the live terminology service. It asks: "What packages exist? What fields does the MIAPPE package require? What are the valid values for this enum field?"

Then it generates metadata constrained by what actually exists in the standard.

Here's a concrete example. Without grounding: the LLM invents a package called "GenomicsCore" — sounds plausible, doesn't exist. With grounding: the system correctly selects "Genome" from the FAIR-DS package registry.

The difference is not about model size. It's about giving the system access to authoritative sources.

---

## Slide 9 — Self-Correction: Critic + Rollback

Even with grounding, agents make mistakes. So we add a self-correction mechanism.

After each agent produces output, a Critic evaluates it against a rubric. The Critic checks: schema compliance, data type validity, confidence thresholds.

The decision is three-way. ACCEPT means the output is good — move to the next agent. RETRY means there are fixable issues — the Critic provides specific feedback, and the agent tries again. ESCALATE means critical problems — flag for human review.

But here's the important part: some errors can't be fixed by just trying again with feedback. Sometimes the system needs to go back to an earlier state — re-query the FAIR-DS API, re-read part of the document, regenerate from a better starting point.

That's rollback. It's the difference between "try harder" and "try differently."

---

## Slide 10 — Session Memory

There's one more challenge in multi-step workflows: context degradation.

By the time the Value Mapper is running — maybe the seventh or eighth LLM call in the workflow — the system has lost track of what was discovered earlier. Which packages were considered? Which fields were marked as uncertain? What evidence was already retrieved?

Session memory solves this. It preserves working context across steps. Early discoveries about the organism, the experimental design, the sequencing protocol — these persist and are available to later agents.

This is especially critical for local models, where the context window is smaller. But even with large-context models, explicit memory reduces inconsistency.

In our experiments, memory reduces runtime for local models and improves or maintains metadata breadth.

---

## Slide 11 — Evaluation Design

Now let me show you the evidence.

We evaluated on three scientific manuscripts — earthworm genomics, a biomedical study, and a bioremediation dataset. Each has a manually verified ground truth annotation.

Multiple model families: GPT, Claude, Qwen — different sizes and reasoning capabilities.

Each document-model pair runs 10 times to quantify variance.

We compare four configurations. B1: zero-shot, one LLM call. B2: adds RAG-style priors before generation. B3: adds a critic-like step with a flatter agent. And Full: the complete FAIRiAgent workflow with planning, live FAIR-DS lookup, ISA assembly, and critic-gated retries.

Two evaluation tracks. Track A: Metadata Schema — Hierarchical-F1, package selection, sheet coverage. Track B: Value Extraction — row-aligned value accuracy, per-sheet performance.

---

## Slide 12 — Experiment 1: Agentic Workflow vs Baselines

The first question: does the agentic workflow actually improve extraction?

Here's the answer. Across all baselines, the Full agentic design achieves the highest scores on both metrics.

But look at the gap. The improvement is largest on Hierarchical-F1 — the structural score. This makes sense: baselines don't do ISA row reconstruction. They generate flat fields. The Full system's decomposition, grounding, and critic loop directly address the structural challenge.

Value accuracy also improves, but the gap is smaller. This tells us something important: getting the structure right is where the agentic design adds the most value.

---

## Slide 13 — Inside One Run: MAS vs Baseline, Step by Step

Let me take you inside one concrete run to show you what's actually happening.

On the left: the FAIRiAgent trace. The Planner identifies this as a genomics study and prioritizes the Genome package. The Knowledge Retriever queries FAIR-DS and returns real field definitions. The Generator produces fields with ISA sheet assignments and confidence scores. The Critic evaluates — finds a missing required field, returns RETRY with specific feedback: "missing mandatory field 'collection date' in Study sheet." The Generator retries, adds the field with evidence from the methods section. The Critic accepts. The Value Mapper fills row-aligned values.

On the right: the baseline output. Single prompt. The model generates plausible-looking JSON. But the package is wrong — it chose something that doesn't exist in FAIR-DS. The fields are flat, no ISA sheets. A value is hallucinated — the accession number looks real but doesn't resolve. And there's no row binding.

The difference isn't that the agentic system uses more tokens. It's that each step is auditable. You can see where the mistake happened and why it was corrected.

---

## Slide 14 — Experiment 2: Ablation — Does Each Component Matter?

Someone might ask: do you really need all these pieces? Maybe just a good prompt and a big model is enough.

We tested this by systematically removing components.

Full system: highest Hierarchical-F1, lowest hallucination rate.

Remove the Critic: quality drops. Hallucination rises sharply. Without the critic, the system has no mechanism to catch its own errors.

Remove rollback: quality drops again. Some errors can't be repaired by moving forward — you need to go back and re-ground.

Each component contributes. The critic is quality control, not decoration. Rollback is recovery, not redundancy.

---

## Slide 15 — Experiment 3: Pass@k — Reliability Through Repair

The third experiment asks a reliability question: if you give the system multiple attempts, how often does it succeed?

This is Pass@k — the probability of at least one successful run in k attempts.

We define two thresholds. Moderate: some optional gaps allowed. Strict: all mandatory fields must be covered.

The curve rises as k increases. But this is not random sampling. The Critic and retry mechanism mean each attempt learns from the previous one. The system converges toward a valid output.

For metadata curation, this matters. One lucky first answer is less important than whether the workflow can reliably converge to a reviewable metadata object.

---

## Slide 16 — Synthesis: Three Dimensions of Quality

Bringing it together.

No single metric tells the full story. Reliability tells you whether the system consistently produces usable output. Extraction quality tells you whether the right values are in the right cells. Coverage tells you whether you're capturing enough of the required fields.

A system can be reliable but incomplete. It can extract correct values but miss required fields. It can cover many fields but assign them to the wrong row.

That's why the evaluation preserves the distinction between Schema and Values, and why we need multiple lenses.

---

## Slide 17 — FAIRiAgent Makes FAIR Easy

Let me leave you with four distilled themes from this work.

**First: Metadata Schema is a first-class task.** Package choice, field coverage, ISA sheet assignment, and row reconstruction are part of the scientific target — not implementation details. They need their own design attention and their own evaluation.

**Second: Values need their own evaluation.** Correct cell values require row binding and source evidence, not just string overlap with a reference answer. A field in the wrong row is a wrong field.

**Third: Agent decomposition makes failure visible.** When you decompose the problem into roles — grounding, generation, critique, memory — each component's contribution becomes auditable. You can see where the system is strong and where it still needs work.

**Fourth: Source-grounded, not source-free.** Real-time lookup against community standards reduces hallucination more reliably than hoping a larger model will magically know the right answer.

These mechanisms do not remove the need for human review. They make it clearer where to look.

---

## Slide 18 — Closing

The central question I want to leave you with is not: "Did the model find a value?"

The better question is: **"Did the system reconstruct a metadata object that a curator can inspect?"**

That's the scientific framing behind FAIRiAgent. Schema reconstruction, evidence provenance, reliability, and uncertainty are not supporting details. They are the research problem.

Current limitations include the dependency on FAIR-DS API availability, the need for further value-level semantic evaluation methods, and the variance across different LLM backbones.

Thank you.

[Contact information / links]
