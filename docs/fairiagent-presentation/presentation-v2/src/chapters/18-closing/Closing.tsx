import "./Closing.css";

export default function Closing() {
  return (
    <div className="cl-stage">
      <div className="cl-quote cl-quote-in">
        <div className="cl-quote-mark">"</div>
        <div className="cl-quote-text">
          FAIRiAgent does not replace<br />
          scientific expertise.<br />
          It <span className="cl-scale">Scales</span> it.
        </div>
        <div className="cl-quote-mark">"</div>
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
