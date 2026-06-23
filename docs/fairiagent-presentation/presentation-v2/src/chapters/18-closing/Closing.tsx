import "./Closing.css";

export default function Closing() {
  return (
    <div className="cl-stage">
      <div className="cl-quote cl-quote-in">
        <div className="cl-quote-mark">"</div>
        <div className="cl-quote-text">
          Did the system reconstruct<br />
          a metadata object a curator<br />
          can <span className="cl-scale">inspect</span>?
        </div>
        <div className="cl-quote-mark">"</div>
      </div>

      <div className="cl-limits cl-limits-in">
        Open: completion rate · value fidelity · FAIR-DS dependency · semantic value evaluation
      </div>

      <div className="cl-info cl-info-in">
        <div className="cl-contact">
          Changlin Ke &middot; Changlin.ke@wur.nl<br />
          Systems &amp; Synthetic Biology, Wageningen U&amp;R
        </div>
        <div className="cl-thanks">Thank you</div>
      </div>
    </div>
  );
}
