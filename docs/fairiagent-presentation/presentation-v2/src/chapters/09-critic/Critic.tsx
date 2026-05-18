import "./Critic.css";

export default function Critic({ step }: { step: number }) {

  return (
    <div className="cr-stage">
      <h2 className="cr-title">Self-Correction: Critic + Rollback</h2>

      <div className="cr-main">
        {/* State machine diagram */}
        <div className={`cr-diagram ${step >= 1 ? "cr-visible" : ""}`}>
          {/* Agent node */}
          <div className="cr-node cr-agent">Agent Output</div>
          <div className="cr-edge cr-edge-down" />

          {/* Critic node */}
          <div className="cr-node cr-critic">Critic Evaluates</div>

          {/* Three branches */}
          <div className="cr-branches">
            <div className="cr-branch">
              <div className="cr-edge cr-edge-left" />
              <div className="cr-node cr-accept">✓ ACCEPT</div>
            </div>
            <div className="cr-branch">
              <div className="cr-edge" />
              <div className="cr-node cr-retry">↻ RETRY</div>
              <div className="cr-note">with specific feedback</div>
            </div>
            <div className="cr-branch">
              <div className="cr-edge cr-edge-right" />
              <div className="cr-node cr-escalate">⚠ ESCALATE</div>
            </div>
          </div>
        </div>

        {/* Retry example */}
        {step >= 2 && (
          <div className="cr-example">
            <div className="cr-ex-head">Example: RETRY with Feedback</div>
            <div className="cr-ex-flow">
              <div className="cr-ex-msg cr-ex-critic">
                Critic: "Missing mandatory field 'collection date' in Study sheet"
              </div>
              <div className="cr-ex-arrow">→</div>
              <div className="cr-ex-msg cr-ex-agent">
                Agent retries, adds field with evidence from Methods §2.3
              </div>
              <div className="cr-ex-arrow">→</div>
              <div className="cr-ex-msg cr-ex-accept">Critic: ACCEPT ✓</div>
            </div>
          </div>
        )}

        {/* Rollback explanation */}
        {step >= 3 && (
          <div className="cr-rollback">
            <span className="cr-rb-label">Rollback</span>
            <span className="cr-rb-desc">
              Some errors can't be fixed by moving forward.
              System returns to earlier state, re-queries FAIR-DS, regenerates.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
