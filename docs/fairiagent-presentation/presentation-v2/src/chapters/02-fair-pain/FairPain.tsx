import "./FairPain.css";
import fairdsScreenshot from "../../../../figs/fairds_screenshot.png";

export default function FairPain({ step }: { step: number }) {

  return (
    <div className="fp-stage">
      <h2 className="fp-title">FAIR by Design — But Difficult in Practice</h2>

      {/* Pain points flow */}
      <div className="fp-flow">
        <div className={`fp-flow-node ${step >= 1 ? "fp-visible" : ""}`}>
          <span className="fp-node-icon">1</span>
          <span className="fp-node-label">Plan what<br />to collect</span>
        </div>
        <div className={`fp-flow-arrow ${step >= 1 ? "fp-visible" : ""}`} />
        <div className={`fp-flow-node ${step >= 1 ? "fp-visible" : ""}`}>
          <span className="fp-node-icon">2</span>
          <span className="fp-node-label">Fill values<br />across layers</span>
        </div>
        <div className={`fp-flow-arrow ${step >= 1 ? "fp-visible" : ""}`} />
        <div className={`fp-flow-node ${step >= 1 ? "fp-visible" : ""}`}>
          <span className="fp-node-icon">3</span>
          <span className="fp-node-label">Learn<br />standards</span>
        </div>
      </div>

      {/* FAIR-DS callout */}
      {step >= 2 && (
        <div className="fp-fairds">
          <div className="fp-fairds-label">FAIR-DS</div>
          <div className="fp-fairds-crop">
            <img
              src={fairdsScreenshot}
              alt="FAIR-DS interface screenshot"
              className="fp-fairds-shot"
            />
          </div>
          <div className="fp-fairds-tags">
            <span className="fp-tag">Learning curve</span>
            <span className="fp-tag">Manual work</span>
            <span className="fp-tag">Not one-shot</span>
          </div>
        </div>
      )}

      {/* Core question */}
      {step >= 3 && (
        <div className="fp-question">
          How can we make this easier?
        </div>
      )}
    </div>
  );
}
