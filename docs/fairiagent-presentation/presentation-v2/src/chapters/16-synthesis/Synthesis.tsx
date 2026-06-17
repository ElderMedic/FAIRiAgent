import "./Synthesis.css";

const WINS = [
  "ISA structure win rate 75%",
  "Evidence grounding 100%",
  "Multi-row depth 87.5%",
];

const CHALLENGES = [
  {
    title: "Completion rate",
    value: "~31%",
    note: "Full pipeline often fails before value mapping — benchmark coverage is uneven",
  },
  {
    title: "Value fidelity",
    value: "B1 > Full",
    note: "Zero-shot copies row values better on the 8-doc Phase-0 benchmark",
  },
  {
    title: "Dual metrics",
    value: "Both needed",
    note: "Structure & evidence wins do not imply value wins — one score misleads",
  },
  {
    title: "Evaluation rigor",
    value: "Phase-1/2",
    note: "N=1 cells, proxy ablation — need factorial reruns and more model families",
  },
];

export default function Synthesis({ step }: { step: number }) {
  return (
    <div className="sy-stage">
      <h2 className="sy-title">Current Problems &amp; Open Challenges</h2>

      {step >= 1 && (
        <p className="sy-lead">
          Phase-0 confirms gains on structure and evidence — but engineering gaps remain before we can claim end-to-end success.
        </p>
      )}

      {step >= 1 && (
        <div className="sy-wins">
          {WINS.map((w) => (
            <span key={w} className="sy-win">{w}</span>
          ))}
        </div>
      )}

      {step >= 2 && (
        <div className="sy-challenges">
          {CHALLENGES.map((c) => (
            <div key={c.title} className="sy-challenge">
              <div className="sy-challenge-value">{c.value}</div>
              <div className="sy-challenge-title">{c.title}</div>
              <div className="sy-challenge-note">{c.note}</div>
            </div>
          ))}
        </div>
      )}

      {step >= 3 && (
        <div className="sy-forward">
          Next focus: raise completion rate, close the value gap, and run Phase-1 with N&ge;3 and formal ablations.
        </div>
      )}
    </div>
  );
}
