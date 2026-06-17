import "./EvalDesign.css";

const BASELINES = [
  {
    name: "B1",
    desc: "Zero-shot",
    tag: "Single prompt, no tools",
  },
  {
    name: "B2",
    desc: "+ RAG Priors",
    tag: "Pre-loaded domain knowledge, no live lookup",
  },
  {
    name: "B3",
    desc: "+ Critic Step",
    tag: "Self-evaluation added, flatter agent structure",
  },
  {
    name: "Full",
    desc: "FAIRiAgent",
    tag: "Planning + live FAIR-DS + ISA assembly + rollback + memory",
  },
];

export default function EvalDesign({ step }: { step: number }) {
  return (
    <div className="ed-stage">
      <h2 className="ed-title">Materials — Benchmark &amp; Metrics</h2>

      {/* Baseline progression */}
      <div className={`ed-baselines ${step >= 1 ? "ed-visible" : ""}`}>
        {BASELINES.map((b, i) => (
          <div key={b.name} className={`ed-bl ${i === 3 ? "ed-bl-full" : ""}`}>
            <div className="ed-bl-name">{b.name}</div>
            <div className="ed-bl-desc">{b.desc}</div>
            <div className="ed-bl-tag">{b.tag}</div>
            {i < 3 && <div className="ed-bl-arrow">→</div>}
          </div>
        ))}
      </div>

      {step >= 2 && (
        <div className="ed-benchmark">
          <span className="ed-benchmark-label">Phase-0 benchmark</span>
          <span className="ed-benchmark-detail">8 manuscripts + gold ISA-Tab · 5 local models · N=1 · 163/192 cells OK</span>
        </div>
      )}

      {/* Two-track metrics */}
      {step >= 2 && (
        <div className="ed-tracks">
          <div className="ed-track">
            <span className="ed-track-label">Track A · Metadata Schema</span>
            <span className="ed-track-metric">Hierarchical-F1</span>
            <span className="ed-track-desc">Field name + ISA position both correct</span>
          </div>
          <div className="ed-track">
            <span className="ed-track-label">Track B · Value Extraction</span>
            <span className="ed-track-metric">Row-aligned Accuracy</span>
            <span className="ed-track-desc">Value correct + bound to the right row</span>
          </div>
        </div>
      )}
    </div>
  );
}
