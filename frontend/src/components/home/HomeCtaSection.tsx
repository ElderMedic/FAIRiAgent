import { motion, useReducedMotion } from 'framer-motion';
import { ArrowRight } from 'lucide-react';

interface HomeCtaSectionProps {
  onStart: () => void;
  onAbout: () => void;
}

export default function HomeCtaSection({ onStart, onAbout }: HomeCtaSectionProps) {
  const reduceMotion = useReducedMotion();

  return (
    <section className="home-section home-section--light home-section--cta">
      <div className="home-shell">
        <motion.div
          className="home-cta-card"
          initial={reduceMotion ? undefined : { opacity: 0, y: 22 }}
          whileInView={reduceMotion ? undefined : { opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.4 }}
          transition={reduceMotion ? undefined : { duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="home-cta-card__copy">
            <p className="home-section__eyebrow">Next step</p>
            <h2 className="home-section__title">Run a paper. Review the metadata bundle.</h2>
            <p className="home-section__body">
              Upload a PDF or try the bundled sample—then download JSON, validation, and reports from the
              results screen.
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
        </motion.div>
      </div>
    </section>
  );
}
