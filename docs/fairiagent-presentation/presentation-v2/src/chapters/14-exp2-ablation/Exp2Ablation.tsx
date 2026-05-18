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
            <span className="e2-co-marker">−Critic</span>
            <span className="e2-co-text">Largest quality loss + strongest hallucination increase</span>
          </div>
          <div className="e2-co">
            <span className="e2-co-marker">−Rollback</span>
            <span className="e2-co-text">Smaller drop — repair path missing, but hallucination rises less</span>
          </div>
        </div>
      )}
    </div>
  );
}
