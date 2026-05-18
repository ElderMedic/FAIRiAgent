import "./Exp1.css";

const exp1HierarchicalF1 = `${import.meta.env.BASE_URL}figs/exp1_hierarchical_f1.png`;

export default function Exp1({ step }: { step: number }) {

  return (
    <div className="e1-stage">
      <h2 className="e1-title">Exp 1: Agentic Workflow vs Baselines</h2>

      <div className={`e1-chart-wrap ${step >= 1 ? "e1-visible" : ""}`}>
        <img
          src={exp1HierarchicalF1}
          alt="Hierarchical-F1 comparison across baselines and FAIRiAgent"
          className="e1-chart-img"
        />
      </div>

      {step >= 2 && (
        <div className="e1-insight">
          <span className="e1-insight-label">Largest gain on</span>
          <span className="e1-insight-em">Hierarchical-F1</span>
          <span className="e1-insight-label">— because baselines don't reconstruct ISA rows.</span>
        </div>
      )}
    </div>
  );
}
