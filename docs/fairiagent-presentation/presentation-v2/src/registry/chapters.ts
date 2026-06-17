import type { ChapterDef } from "./types";
import TitleChapter from "../chapters/01-title/Title";
import { narrations as titleNarrations } from "../chapters/01-title/narrations";
import FairPainChapter from "../chapters/02-fair-pain/FairPain";
import { narrations as fairPainNarrations } from "../chapters/02-fair-pain/narrations";
import IsaStructureChapter from "../chapters/03-isa-structure/IsaStructure";
import { narrations as isaStructureNarrations } from "../chapters/03-isa-structure/narrations";
import LlmPromiseChapter from "../chapters/04-llm-promise/LlmPromise";
import { narrations as llmPromiseNarrations } from "../chapters/04-llm-promise/narrations";
import LlmFallsShortChapter from "../chapters/05-llm-falls-short/LlmFallsShort";
import { narrations as llmFallsShortNarrations } from "../chapters/05-llm-falls-short/narrations";
import TwoTasksChapter from "../chapters/06-two-tasks/TwoTasks";
import { narrations as twoTasksNarrations } from "../chapters/06-two-tasks/narrations";
import AgentRolesChapter from "../chapters/07-agent-roles/AgentRoles";
import { narrations as agentRolesNarrations } from "../chapters/07-agent-roles/narrations";
import GroundingChapter from "../chapters/08-grounding/Grounding";
import { narrations as groundingNarrations } from "../chapters/08-grounding/narrations";
import CriticChapter from "../chapters/09-critic/Critic";
import { narrations as criticNarrations } from "../chapters/09-critic/narrations";
import SessionMemoryChapter from "../chapters/10-memory/SessionMemory";
import { narrations as sessionMemoryNarrations } from "../chapters/10-memory/narrations";
import EvalDesignChapter from "../chapters/11-eval-design/EvalDesign";
import { narrations as evalDesignNarrations } from "../chapters/11-eval-design/narrations";
import Exp1Chapter from "../chapters/12-exp1/Exp1";
import { narrations as exp1Narrations } from "../chapters/12-exp1/narrations";
import DeepDiveChapter from "../chapters/13-deep-dive/DeepDive";
import { narrations as deepDiveNarrations } from "../chapters/13-deep-dive/narrations";
import Exp2AblationChapter from "../chapters/14-exp2-ablation/Exp2Ablation";
import { narrations as exp2AblationNarrations } from "../chapters/14-exp2-ablation/narrations";
import Exp3PasskChapter from "../chapters/15-exp3-passk/Exp3Passk";
import { narrations as exp3PasskNarrations } from "../chapters/15-exp3-passk/narrations";
import SynthesisChapter from "../chapters/16-synthesis/Synthesis";
import { narrations as synthesisNarrations } from "../chapters/16-synthesis/narrations";
import TakeawaysChapter from "../chapters/17-takeaways/Takeaways";
import { narrations as takeawaysNarrations } from "../chapters/17-takeaways/narrations";
import ClosingChapter from "../chapters/18-closing/Closing";
import { narrations as closingNarrations } from "../chapters/18-closing/narrations";

export const CHAPTERS: ChapterDef[] = [
  { id: "title", title: "Title", narrations: titleNarrations, Component: TitleChapter },
  {
    id: "fair-pain",
    act: "Background",
    title: "FAIR — Hard in Practice",
    narrations: fairPainNarrations,
    Component: FairPainChapter,
  },
  {
    id: "isa-structure",
    act: "Background",
    title: "Target: 5-Layer ISA Object",
    narrations: isaStructureNarrations,
    Component: IsaStructureChapter,
  },
  {
    id: "llm-promise",
    act: "Problems",
    title: "Can LLMs Help?",
    narrations: llmPromiseNarrations,
    Component: LlmPromiseChapter,
  },
  {
    id: "llm-falls-short",
    act: "Problems",
    title: "Why Raw LLM Fails",
    narrations: llmFallsShortNarrations,
    Component: LlmFallsShortChapter,
  },
  {
    id: "two-tasks",
    act: "Problems",
    title: "Two Tasks, Two Failure Modes",
    narrations: twoTasksNarrations,
    Component: TwoTasksChapter,
  },
  {
    id: "agent-roles",
    act: "Method",
    title: "Multi-Agent Decomposition",
    narrations: agentRolesNarrations,
    Component: AgentRolesChapter,
  },
  {
    id: "grounding",
    act: "Method",
    title: "FAIR-DS Grounding",
    narrations: groundingNarrations,
    Component: GroundingChapter,
  },
  {
    id: "critic",
    act: "Method",
    title: "Critic + Rollback",
    narrations: criticNarrations,
    Component: CriticChapter,
  },
  {
    id: "memory",
    act: "Method",
    title: "Session Memory",
    narrations: sessionMemoryNarrations,
    Component: SessionMemoryChapter,
  },
  {
    id: "eval-design",
    act: "Materials",
    title: "Benchmark & Metrics",
    narrations: evalDesignNarrations,
    Component: EvalDesignChapter,
  },
  {
    id: "exp1",
    act: "Results",
    title: "Exp 1: Hierarchical-F1",
    narrations: exp1Narrations,
    Component: Exp1Chapter,
  },
  {
    id: "deep-dive",
    act: "Results",
    title: "Case Study: One Run",
    narrations: deepDiveNarrations,
    Component: DeepDiveChapter,
  },
  {
    id: "exp2-ablation",
    act: "Results",
    title: "Exp 2: Ablation (proxy)",
    narrations: exp2AblationNarrations,
    Component: Exp2AblationChapter,
  },
  {
    id: "exp3-passk",
    act: "Results",
    title: "Exp 3: Pass@k",
    narrations: exp3PasskNarrations,
    Component: Exp3PasskChapter,
  },
  {
    id: "synthesis",
    act: "Challenges",
    title: "Open Problems",
    narrations: synthesisNarrations,
    Component: SynthesisChapter,
  },
  {
    id: "takeaways",
    act: "Highlights",
    title: "What We Built",
    narrations: takeawaysNarrations,
    Component: TakeawaysChapter,
  },
  { id: "closing", title: "Closing", narrations: closingNarrations, Component: ClosingChapter },
];
