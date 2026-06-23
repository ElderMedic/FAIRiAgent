import "./Takeaways.css";

const HIGHLIGHTS = [
  {
    icon: "①",
    head: "Auditable Multi-Agent Pipeline",
    desc: "Six roles plus Critic gates — failures surface per step, not buried in one JSON blob.",
  },
  {
    icon: "②",
    head: "Live FAIR-DS Grounding",
    desc: "Packages and terms from the authoritative API — fewer hallucinated vocabulary choices.",
  },
  {
    icon: "③",
    head: "Dual-Track Evaluation",
    desc: "Hierarchical-F1 for schema; row-aligned accuracy for values — always reported separately.",
  },
  {
    icon: "④",
    head: "Evidence-First Curation Drafts",
    desc: "Fields carry source spans and ISA row binding — assisted curation, not blind automation.",
  },
];

export default function Takeaways({ step }: { step: number }) {
  return (
    <div className="tk-stage">
      <h2 className="tk-title">Highlights — What FAIRiAgent Contributes</h2>

      <div className="tk-grid">
        {HIGHLIGHTS.map((t, i) => {
          const revealStep = i + 2;
          const isActive = step === revealStep;
          const isDone = step > revealStep;

          return (
            <div
              key={t.head}
              className={`tk-card ${step >= 1 ? "tk-reveal" : ""} ${isActive ? "tk-active" : ""} ${isDone ? "tk-done" : ""}`}
              style={{ transitionDelay: `${i * 0.16}s` }}
            >
              <div className="tk-card-icon">{t.icon}</div>
              <div className="tk-card-head">{t.head}</div>
              {step >= 2 + i && (
                <div className="tk-card-desc">{t.desc}</div>
              )}
            </div>
          );
        })}
      </div>

      <div className="tk-coda-slot">
        {step >= 5 && (
          <div className="tk-coda">
            Strong on structure and auditability today — value fidelity and completion are the next targets.
          </div>
        )}
      </div>
    </div>
  );
}
