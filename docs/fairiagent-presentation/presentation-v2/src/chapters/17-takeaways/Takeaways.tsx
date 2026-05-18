import "./Takeaways.css";

const THEMES = [
  {
    icon: "①",
    head: "Metadata Is More Than Extracted Values",
    desc: "FAIR metadata is a structured study object. The job is to rebuild that object, not just summarize a paper.",
  },
  {
    icon: "②",
    head: "Community Standards Should Guide the Workflow",
    desc: "FAIR-DS packages and fields should constrain proposals during generation, not only be checked at the end.",
  },
  {
    icon: "③",
    head: "Curation Needs Evidence, Not Just Answers",
    desc: "A reviewable draft must show source spans, ISA row alignment, and which parts are still uncertain.",
  },
  {
    icon: "④",
    head: "The Goal Is Assisted Curation",
    desc: "The agent should remove repetitive work while leaving interpretation, correction, and release with the scientist.",
  },
];

export default function Takeaways({ step }: { step: number }) {
  return (
    <div className="tk-stage">
      <h2 className="tk-title">What FAIRiAgent Teaches Us About Curation</h2>

      <div className="tk-grid">
        {THEMES.map((t, i) => {
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
            The question is not whether an LLM can fill a form. It is whether it can produce a reviewable draft.
          </div>
        )}
      </div>
    </div>
  );
}
