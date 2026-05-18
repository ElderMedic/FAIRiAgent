import "./Grounding.css";

export default function Grounding({ step }: { step: number }) {

  return (
    <div className="gr-stage">
      <h2 className="gr-title">Grounding in Community Standards</h2>

      <div className="gr-main">
        {/* Without grounding */}
        <div className={`gr-panel ${step >= 1 ? "gr-visible" : ""}`}>
          <div className="gr-panel-label gr-label-bad">Without Grounding</div>
          <div className="gr-panel-body gr-body-bad">
            <div className="gr-llm-icon">LLM</div>
            <div className="gr-arrow">→</div>
            <div className="gr-output">
              <div className="gr-field gr-hallucinated">"BioSeqPipeline v3.1"</div>
              <div className="gr-note gr-note-err">Not in FAIR-DS registry</div>
            </div>
          </div>
        </div>

        {/* With grounding */}
        <div className={`gr-panel ${step >= 2 ? "gr-visible" : ""}`}>
          <div className="gr-panel-label gr-label-good">With Grounding</div>
          <div className="gr-panel-body gr-body-good">
            <div className="gr-agent-icon">Agent</div>
            <div className="gr-arrow">→</div>
            <div className="gr-fairds-box">FAIR-DS</div>
            <div className="gr-arrow">→</div>
            <div className="gr-output">
              <div className="gr-field gr-real">"Genome"</div>
              <div className="gr-note gr-note-ok">Verified package</div>
            </div>
          </div>
        </div>
      </div>

      {step >= 3 && (
        <div className="gr-bottom">
          The difference is not model size.<br />
          <span className="gr-bottom-em">It's access to authoritative sources.</span>
        </div>
      )}
    </div>
  );
}
