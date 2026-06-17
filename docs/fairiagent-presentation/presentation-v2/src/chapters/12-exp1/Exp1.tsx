import "./Exp1.css";

const exp1HierarchicalF1 = `${import.meta.env.BASE_URL}figs/exp1_hierarchical_f1.png`;

export default function Exp1({ step }: { step: number }) {

  return (
    <div className="e1-stage">
      <h2 className="e1-title">Exp 1: Hierarchical-F1 (biosensor + earthworm subset)</h2>

      <div className={`e1-chart-wrap ${step >= 1 ? "e1-visible" : ""}`}>
        <img
          src={exp1HierarchicalF1}
          alt="Hierarchical-F1 comparison across baselines and FAIRiAgent"
          className="e1-chart-img"
        />
      </div>

      {step >= 2 && (
        <div className="e1-insight">
          <span className="e1-insight-em">Full 0.721</span>
          <span className="e1-insight-label"> beats B2 and B1 on this two-document slice — baselines skip ISA row reconstruction. On the full 8-doc benchmark, value accuracy still favours B1; see synthesis.</span>
        </div>
      )}
    </div>
  );
}
