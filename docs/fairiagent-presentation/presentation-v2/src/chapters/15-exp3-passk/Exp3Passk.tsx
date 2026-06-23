import "./Exp3Passk.css";

const exp2PassAtK = `${import.meta.env.BASE_URL}figs/exp2_pass_at_k.png`;

export default function Exp3Passk({ step }: { step: number }) {

  return (
    <div className="e3-stage">
      <h2 className="e3-title">Exp 3: Pass@k — Reliability Through Repair</h2>

      <div className={`e3-chart-wrap ${step >= 1 ? "e3-visible" : ""}`}>
        <img
          src={exp2PassAtK}
          alt="Pass@k reliability curve across repeated repair attempts"
          className="e3-chart-img"
        />
      </div>

      {step >= 2 && (
        <div className="e3-insight">
          The more attempts, the higher the probability of producing a valid metadata object.
        </div>
      )}
    </div>
  );
}
