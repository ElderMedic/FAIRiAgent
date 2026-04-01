import { motion, useReducedMotion, useScroll, useTransform } from 'framer-motion';
import { ArrowRight, BadgeCheck, Database, FileSearch, Sparkles, Workflow } from 'lucide-react';
import { useRef } from 'react';
import HomeHeroBackdrop from './HomeHeroBackdrop';
import type { HomeSignal } from './content';

interface HomeHeroProps {
  onStart: () => void;
  onSample: () => void;
  signals: HomeSignal[];
  highlights: string[];
}

export default function HomeHero({
  onStart,
  onSample,
  signals,
  highlights,
}: HomeHeroProps) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const reduceMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ['start start', 'end start'],
  });
  const backdropOpacity = useTransform(scrollYProgress, [0, 0.72], [1, 0]);
  const backdropScale = useTransform(scrollYProgress, [0, 1], [1, 1.08]);
  const contentOpacity = useTransform(scrollYProgress, [0, 0.74], [1, 0.24]);
  const contentY = useTransform(scrollYProgress, [0, 1], [0, 88]);
  const consoleY = useTransform(scrollYProgress, [0, 1], [0, 116]);

  return (
    <motion.section
      ref={sectionRef}
      className="home-hero"
    >
      <motion.div
        className="home-hero__media"
        style={reduceMotion ? undefined : { opacity: backdropOpacity, scale: backdropScale }}
      >
        <HomeHeroBackdrop />
      </motion.div>
      <div className="home-hero__backdrop" aria-hidden="true" />
      <div className="home-hero__mesh" aria-hidden="true" />
      <div className="home-hero__fade" aria-hidden="true" />

      <div className="home-shell home-hero__layout">
        <motion.div
          className="home-hero__content"
          style={reduceMotion ? undefined : { y: contentY, opacity: contentOpacity }}
        >
          <div className="home-chip">
            <Sparkles className="home-chip__icon" aria-hidden="true" />
            Scientific metadata, shaped for focused operation
          </div>

          <div className="home-copy">
            <p className="home-eyebrow">Research documents in. FAIR metadata out.</p>
            <h1 className="home-title">
              A cleaner control surface for your FAIR metadata workflow.
            </h1>
            <p className="home-lede">
              FAIRiAgent turns research documents into structured FAIR metadata through a staged backend
              pipeline. The front end is built to make that process legible, stable, and easy to operate,
              with a quieter visual rhythm that supports careful work.
            </p>
          </div>

          <div className="home-actions">
            <button type="button" onClick={onStart} className="home-button home-button--primary">
              Launch workflow
              <ArrowRight className="home-button__icon" aria-hidden="true" />
            </button>
            <button type="button" onClick={onSample} className="home-button home-button--ghost">
              Run bundled sample
            </button>
          </div>

          <div className="home-signal-grid">
            {signals.map((signal) => (
              <article key={signal.label} className="home-signal-card">
                <h2 className="home-signal-card__title">{signal.label}</h2>
                <p className="home-signal-card__detail">{signal.detail}</p>
              </article>
            ))}
          </div>
        </motion.div>

        <motion.aside
          className="home-console"
          aria-label="Workflow overview"
          style={reduceMotion ? undefined : { y: consoleY, opacity: contentOpacity }}
        >
          <header className="home-console__header">
            <div>
              <p className="home-console__eyebrow">Workflow surface</p>
              <h2 className="home-console__title">Local operator console</h2>
            </div>
            <div className="home-status-pill">
              <BadgeCheck className="home-status-pill__icon" aria-hidden="true" />
              Ready for review
            </div>
          </header>

          <div className="home-console__panel">
            <div className="home-console__row">
              <div>
                <p className="home-console__eyebrow">Run architecture</p>
                <p className="home-console__summary">Upload, configure, stream, inspect, export.</p>
              </div>
              <div className="home-dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
            </div>

            <article className="home-console-card home-console-card--wide">
              <div>
                <h3 className="home-console-card__title">Document intake</h3>
                <p className="home-console-card__body">
                  PDF, TXT, and Markdown drop into the same backend pipeline.
                </p>
              </div>
              <FileSearch className="home-console-card__icon" aria-hidden="true" />
            </article>

            <div className="home-console__grid">
              <article className="home-console-card">
                <div className="home-console-card__heading">
                  <h3 className="home-console-card__title">Agent loop</h3>
                  <Workflow className="home-console-card__icon home-console-card__icon--secondary" aria-hidden="true" />
                </div>
                <p className="home-console-card__body">
                  Extraction, critique, and validation operate as distinct steps.
                </p>
              </article>

              <article className="home-console-card">
                <div className="home-console-card__heading">
                  <h3 className="home-console-card__title">Structured output</h3>
                  <Database className="home-console-card__icon home-console-card__icon--secondary" aria-hidden="true" />
                </div>
                <p className="home-console-card__body">
                  Reviewable metadata artifacts replace disposable chat output.
                </p>
              </article>
            </div>
          </div>

          <div className="home-console__highlights">
            {highlights.map((item) => (
              <div key={item} className="home-highlight">
                {item}
              </div>
            ))}
          </div>
        </motion.aside>
      </div>
    </motion.section>
  );
}
