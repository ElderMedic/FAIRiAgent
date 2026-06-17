import "./Title.css";

export default function Title() {
  return (
    <div className="ti-stage">
      {/* Floating particles */}
      <div className="ti-particles">
        {Array.from({ length: 7 }).map((_, i) => (
          <div key={i} className="ti-particle" />
        ))}
      </div>

      {/* Top-left event badge */}
      <div className="ti-event">SSB Seminar 2026</div>

      {/* Top decorative rule */}
      <div className="ti-rule-top" />

      {/* Title with clip-path reveal */}
      <h1 className="ti-title">
        FAIR<span className="ti-title-accent">i</span>Agent
      </h1>

      {/* Subtitle */}
      <p className="ti-subtitle">
        Reconstructing FAIR Metadata Objects with Multi-Agent Systems
      </p>

      {/* Author / institution */}
      <div className="ti-meta">
        <div className="ti-meta-author">Changlin Ke</div>
        <div className="ti-meta-affil">Systems &amp; Synthetic Biology, Wageningen U&amp;R</div>
        <div className="ti-meta-email">Changlin.ke@wur.nl</div>
      </div>

      {/* Bottom-right date & location */}
      <div className="ti-locale">May 12, 2026 &middot; Helix</div>

      {/* Vignette overlay */}
      <div className="ti-vignette" />
    </div>
  );
}
