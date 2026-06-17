import "./LlmFallsShort.css";

export default function LlmFallsShort({ step }: { step: number }) {

  return (
    <div className="lf-stage">
      <h2 className="lf-title">Why Raw LLM Falls Short</h2>

      <div className="lf-cards">
        <div className={`lf-card ${step >= 1 ? "lf-reveal" : ""}`} style={{ transitionDelay: "0s" }}>
          {step >= 2 && <div className="lf-card-active" />}
          <div className="lf-card-icon">⚠</div>
          <div className="lf-card-head">Hallucination</div>
          <div className="lf-card-body">
            Invents package names, accession numbers, terms that don't exist
          </div>
          {step >= 2 && (
            <div className="lf-card-snippet">
              "package": "GenomicsCore"<br />
              <span className="lf-err">← Not in FAIR-DS registry</span>
            </div>
          )}
        </div>

        <div className={`lf-card ${step >= 1 ? "lf-reveal" : ""}`} style={{ transitionDelay: "0.2s" }}>
          {step >= 3 && <div className="lf-card-active" />}
          <div className="lf-card-icon">⌛</div>
          <div className="lf-card-head">Context Rot</div>
          <div className="lf-card-body">
            Forgets early information as document length grows
          </div>
          {step >= 3 && (
            <div className="lf-card-diagram">
              <div className="lf-ctx-bar"><div className="lf-ctx-fill" /></div>
              <span className="lf-ctx-label">Document position → later = forgotten</span>
            </div>
          )}
        </div>

        <div className={`lf-card ${step >= 1 ? "lf-reveal" : ""}`} style={{ transitionDelay: "0.4s" }}>
          {step >= 4 && <div className="lf-card-active" />}
          <div className="lf-card-icon">📄</div>
          <div className="lf-card-head">No ISA Structure</div>
          <div className="lf-card-body">
            Flat fields with no clue which sample or assay they belong to
          </div>
          {step >= 4 && (
            <div className="lf-card-compare">
              <div className="lf-flat">Flat JSON — no sheets, no rows</div>
              <div className="lf-vs">vs</div>
              <div className="lf-structured">ISA-structured — Investigation → Study → Assay → Sample → ObservationUnit</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
