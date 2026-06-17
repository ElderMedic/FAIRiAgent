import "./LlmPromise.css";

export default function LlmPromise({ step }: { step: number }) {

  return (
    <div className="lp-stage">
      <h2 className="lp-title">"Outsource the Boring Work" — Can LLMs Help?</h2>

      <div className="lp-main">
        {/* Left: LLM vs Agent paradigm image */}
        <div className={`lp-img-wrap ${step >= 1 ? "lp-visible" : ""}`}>
          <img src="/figs/LLMvsAgent.png" alt="LLM vs Agent paradigm" className="lp-img" />
        </div>

        {/* Right: annotation */}
        {step >= 2 && (
          <div className="lp-annotations">
            <div className="lp-anno">
              <span className="lp-anno-label">LLM</span>
              <span className="lp-anno-text">One prompt → one answer</span>
            </div>
            <div className="lp-anno-arrow">↓</div>
            <div className="lp-anno">
              <span className="lp-anno-label lp-anno-accent">Agentic</span>
              <span className="lp-anno-text">Multi-step → auditable decisions</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
