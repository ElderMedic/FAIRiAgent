import "./SessionMemory.css";
import memoryDesign from "../../../../figs/MemoryDesign.png";

export default function SessionMemory({ step }: { step: number }) {

  return (
    <div className="sm-stage">
      <h2 className="sm-title">Session Memory</h2>

      <div className={`sm-fig-wrap ${step >= 1 ? "sm-visible" : ""}`}>
        <img src={memoryDesign} alt="Session memory design" className="sm-fig" />
      </div>

      {step >= 2 && (
        <div className="sm-takeaway">
          Memory reduces runtime, preserves metadata breadth, improves confidence — especially for local models.
        </div>
      )}
    </div>
  );
}
