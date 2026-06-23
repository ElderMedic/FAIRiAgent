import "./TwoTasks.css";

export default function TwoTasks({ step }: { step: number }) {

  return (
    <div className="tt-stage">
      <h2 className="tt-title">Two Tasks That Fail Differently</h2>

      <div className="tt-cols">
        {/* Track A: Metadata Schema */}
        <div className={`tt-col ${step >= 1 ? "tt-visible" : ""}`}>
          <div className="tt-col-badge tt-badge-schema">Track A</div>
          <div className="tt-col-head">Metadata Schema</div>
          <div className="tt-col-sub">Structure</div>
          <ul className={`tt-list ${step >= 2 ? "tt-list-visible" : ""}`}>
            <li>Package selection</li>
            <li>Field generation</li>
            <li>ISA sheet assignment</li>
            <li>Row organization</li>
          </ul>
        </div>

        {/* Divider */}
        <div className={`tt-divider ${step >= 1 ? "tt-visible" : ""}`}>
          <div className="tt-divider-line" />
          <div className="tt-divider-word">vs</div>
          <div className="tt-divider-line" />
        </div>

        {/* Track B: Value Extraction */}
        <div className={`tt-col ${step >= 1 ? "tt-visible" : ""}`}>
          <div className="tt-col-badge tt-badge-value">Track B</div>
          <div className="tt-col-head">Value Extraction</div>
          <div className="tt-col-sub">Content</div>
          <ul className={`tt-list ${step >= 3 ? "tt-list-visible" : ""}`}>
            <li>Field values</li>
            <li>Row binding</li>
            <li>Source evidence</li>
            <li>Confidence estimation</li>
          </ul>
        </div>
      </div>

      {step >= 3 && (
        <div className="tt-bottom">
          They fail differently.&nbsp;
          <span className="tt-bottom-em">They must be evaluated separately.</span>
        </div>
      )}
    </div>
  );
}
