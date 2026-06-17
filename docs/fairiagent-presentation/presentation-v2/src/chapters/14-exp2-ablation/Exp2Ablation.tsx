import "./Exp2Ablation.css";

const exp3Ablation = `${import.meta.env.BASE_URL}figs/exp3_ablation.png`;

export default function Exp2Ablation({ step }: { step: number }) {

  return (
    <div className="e2-stage">
      <h2 className="e2-title">Exp 2: Does Each Component Matter?</h2>

      <div className={`e2-chart-wrap ${step >= 1 ? "e2-visible" : ""}`}>
        <img
          src={exp3Ablation}
          alt="Ablation chart showing the effect of removing FAIRiAgent components"
          className="e2-chart-img"
        />
      </div>

      {step >= 2 && (
        <div className="e2-callouts">
          <div className="e2-co">
            <span className="e2-co-marker">Critic off</span>
            <span className="e2-co-text">Quality slips; hallucination rate (red line) ticks up</span>
          </div>
          <div className="e2-co">
            <span className="e2-co-marker">Rollback off</span>
            <span className="e2-co-text">Larger quality drop and a sharp jump in hallucination rate</span>
          </div>
        </div>
      )}
    </div>
  );
}
