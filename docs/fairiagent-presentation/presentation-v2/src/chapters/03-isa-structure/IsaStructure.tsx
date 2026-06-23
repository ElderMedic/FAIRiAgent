import "./IsaStructure.css";

const LAYERS = [
  { name: "Investigation", type: "single", desc: "Project-level context" },
  { name: "Study", type: "single", desc: "Research design" },
  { name: "Observation Unit", type: "multi", desc: "Observation context" },
  { name: "Sample", type: "multi", desc: "Sample attributes" },
  { name: "Assay", type: "multi", desc: "Assay / analysis details" },
];

export default function IsaStructure({ step }: { step: number }) {

  return (
    <div className="is-stage">
      <h2 className="is-title">The Target: A 5-Layer ISA Metadata Object</h2>

      <div className="is-layers">
        {LAYERS.map((layer, i) => (
          <div
            key={layer.name}
            className={`is-layer ${step >= 1 ? "is-visible" : ""} ${layer.type === "multi" ? "is-multi" : "is-single"}`}
            style={{ transitionDelay: `${i * 0.18}s` }}
          >
            <div className="is-layer-num">{i + 1}</div>
            <div className="is-layer-body">
              <div className="is-layer-name">{layer.name}</div>
              <div className="is-layer-desc">{layer.desc}</div>
            </div>
            <div className={`is-layer-badge ${layer.type === "multi" ? "is-badge-multi" : "is-badge-single"}`}>
              {layer.type === "multi" ? "MULTI-ROW" : "SINGLE-ROW"}
            </div>
          </div>
        ))}
      </div>

      {step >= 2 && (
        <div className="is-bottom">
          <div className="is-highlight">
            <span className="is-highlight-label">Which sample / assay does each value belong to?</span>
            <span className="is-highlight-arrow">→</span>
            <span className="is-highlight-text">the central challenge</span>
          </div>
          <p className="is-tagline">
            Not a form-filling problem. A structured object reconstruction problem.
          </p>
        </div>
      )}
    </div>
  );
}
