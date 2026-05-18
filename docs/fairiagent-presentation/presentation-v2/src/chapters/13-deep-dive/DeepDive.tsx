import "./DeepDive.css";

const FAIR_STEPS = [
  { agent: "Planner", output: "Domain: genomics → prioritize 'Genome' package, focus on Study + Assay sheets" },
  { agent: "Knowledge Retriever", output: "Query FAIR-DS → found 42 fields in 'Genome' package, 12 mandatory" },
  { agent: "JSON Generator", output: "Generated 28 fields with ISA sheet assignments, confidence scores attached" },
  { agent: "Critic", output: "SCORE: 0.62 · RETRY — missing mandatory field 'collection date' in Study sheet" },
  { agent: "Generator (repair)", output: "Added 'collection date: 2023-06' with evidence from Methods §2.3", highlight: true },
  { agent: "Critic", output: "SCORE: 0.84 · ACCEPT — all mandatory fields present, ISA structure valid" },
];

const BASELINE_ERRORS = [
  { text: "\"package\": \"GenomicsCore\"", err: "Not in FAIR-DS registry" },
  { text: "\"sequencing_platform\": \"Illumina\"", err: "No ISA sheet assigned" },
  { text: "\"sample_id\": \"SRR12345678\"", err: "Hallucinated accession" },
  { text: "Flat JSON output", err: "No row binding, no entity grouping" },
];

export default function DeepDive({ step }: { step: number }) {
  return (
    <div className="dd-stage">
      <h2 className="dd-title">Inside One Run — MAS vs Baseline</h2>

      <div className={`dd-split ${step >= 1 ? "dd-visible" : ""}`}>
        <div className="dd-col dd-col-left">
          <div className="dd-col-head dd-head-good">FAIRiAgent Trace</div>
          <div className="dd-trace">
            {FAIR_STEPS.map((s, i) => (
              <div
                key={s.agent}
                className={`dd-step ${step >= 2 + Math.floor(i / 3) ? "dd-step-visible" : ""} ${s.highlight ? "dd-step-highlight" : ""}`}
                style={{ transitionDelay: `${(i % 3) * 0.15}s` }}
              >
                <div className="dd-step-agent">{s.agent}</div>
                <div className="dd-step-output">{s.output}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="dd-col dd-col-right">
          <div className="dd-col-head dd-head-bad">Baseline (Single Prompt)</div>
          <div className={`dd-baseline ${step >= 3 ? "dd-visible" : ""}`}>
            {BASELINE_ERRORS.map((be) => (
              <div key={be.err} className="dd-err">
                <div className="dd-err-text">{be.text}</div>
                <div className="dd-err-flag">{be.err}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {step >= 4 && (
        <div className="dd-bottom">
          Agentic: 6 auditable steps, 1 repair &rarr; valid output &nbsp;|&nbsp; Baseline: 1 step, invisible errors &rarr; unusable
        </div>
      )}
    </div>
  );
}
