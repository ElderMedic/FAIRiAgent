import { ArrowRight } from 'lucide-react';

interface HomeCtaSectionProps {
  onStart: () => void;
  onAbout: () => void;
}

export default function HomeCtaSection({ onStart, onAbout }: HomeCtaSectionProps) {
  return (
    <section className="home-section home-section--light home-section--cta">
      <div className="home-shell">
        <div className="home-cta-card">
          <div className="home-cta-card__copy">
            <p className="home-section__eyebrow">Next step</p>
            <h2 className="home-section__title">
              Start with a real document, then tune the rest of the workflow inside the app.
            </h2>
            <p className="home-section__body">
              The same visual language should carry through the working screens next: upload,
              configuration, run status, and result review.
            </p>
          </div>

          <div className="home-actions home-actions--compact">
            <button type="button" onClick={onStart} className="home-button home-button--secondary">
              Open upload screen
              <ArrowRight className="home-button__icon" aria-hidden="true" />
            </button>
            <button type="button" onClick={onAbout} className="home-button home-button--subtle">
              Read project overview
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
