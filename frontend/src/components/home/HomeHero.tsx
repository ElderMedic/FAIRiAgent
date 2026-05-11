import {
  AnimatePresence,
  motion,
  useReducedMotion,
  useScroll,
  useTransform,
  type Variants,
} from 'framer-motion';
import { ArrowRight, BadgeCheck, Microscope } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import HomeHeroBackdrop from './HomeHeroBackdrop';
import type { HomeConsoleSlide, HomeSignal } from './content';

const CONSOLE_AUTO_MS = 9000;
const CONSOLE_PAUSE_AFTER_MANUAL_MS = 20000;

interface HomeHeroProps {
  onStart: () => void;
  onSample: () => void;
  signals: HomeSignal[];
  consoleSlides: HomeConsoleSlide[];
}

export default function HomeHero({
  onStart,
  onSample,
  signals,
  consoleSlides,
}: HomeHeroProps) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const reduceMotion = useReducedMotion();
  const [activeConsoleIndex, setActiveConsoleIndex] = useState(0);
  const consolePauseUntilRef = useRef(0);

  const heroStagger: Variants | undefined = reduceMotion
    ? undefined
    : {
        hidden: {},
        show: {
          transition: {
            staggerChildren: 0.11,
            delayChildren: 0.06,
          },
        },
      };

  const heroItem: Variants | undefined = reduceMotion
    ? undefined
    : {
        hidden: { opacity: 0, y: 24 },
        show: {
          opacity: 1,
          y: 0,
          transition: { duration: 0.7, ease: [0.16, 1, 0.3, 1] },
        },
      };

  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ['start start', 'end start'],
  });
  const backdropOpacity = useTransform(scrollYProgress, [0, 0.72], [1, 0]);
  const backdropScale = useTransform(scrollYProgress, [0, 1], [1, 1.08]);
  const contentOpacity = useTransform(scrollYProgress, [0, 0.74], [1, 0.24]);
  const contentY = useTransform(scrollYProgress, [0, 1], [0, 88]);
  const consoleY = useTransform(scrollYProgress, [0, 1], [0, 116]);
  const activeConsoleSlide = consoleSlides[activeConsoleIndex];

  useEffect(() => {
    if (reduceMotion || consoleSlides.length < 2) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      if (Date.now() < consolePauseUntilRef.current) {
        return;
      }
      setActiveConsoleIndex((current) => (current + 1) % consoleSlides.length);
    }, CONSOLE_AUTO_MS);
    return () => window.clearInterval(timer);
  }, [consoleSlides.length, reduceMotion]);

  const selectConsoleSlide = (index: number, timeStamp: number) => {
    consolePauseUntilRef.current = timeStamp + CONSOLE_PAUSE_AFTER_MANUAL_MS;
    setActiveConsoleIndex(index);
  };

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
          initial={reduceMotion ? undefined : 'hidden'}
          animate={reduceMotion ? undefined : 'show'}
          variants={heroStagger}
          style={reduceMotion ? undefined : { y: contentY, opacity: contentOpacity }}
        >
          <motion.div className="home-chip" variants={heroItem}>
            <Microscope className="home-chip__icon" aria-hidden="true" />
            Multi-agent AI · Biological research
          </motion.div>

          <motion.div className="home-copy" variants={heroItem}>
            <p className="home-eyebrow">From manuscript to FAIR metadata — in one run.</p>
            <h1 className="home-title">
              FAIR metadata curation for biological research
            </h1>
            <p className="home-lede">
              FAIRiAgent reads your entire paper—methods, tables, and supplements—and produces
              structured, standards-grounded metadata drafts ready for curator review and
              FAIR Data Station submission.
            </p>
            <p className="home-keywords" aria-label="Highlights">
              <span className="home-keyword">Plan → Execute → Critique → Refine</span>
              <span className="home-keyword">MIxS / ISA-Tab</span>
              <span className="home-keyword">LangGraph · multi-agent</span>
            </p>
          </motion.div>

          <motion.div className="home-actions" variants={heroItem}>
            <button type="button" onClick={onStart} className="home-button home-button--primary">
              Start processing
              <ArrowRight className="home-button__icon" aria-hidden="true" />
            </button>
            <button type="button" onClick={onSample} className="home-button home-button--ghost">
              Try the demo paper
            </button>
          </motion.div>

          <motion.div className="home-signal-grid" variants={heroItem}>
            {signals.map((signal) => (
              <motion.article
                key={signal.label}
                className="home-signal-card"
                tabIndex={0}
                whileHover={reduceMotion ? undefined : { y: -3 }}
                transition={{ duration: 0.18, ease: 'easeOut' }}
              >
                <h2 className="home-signal-card__title">{signal.label}</h2>
                <p className="home-signal-card__detail">{signal.detail}</p>
              </motion.article>
            ))}
          </motion.div>
        </motion.div>

        <motion.aside
          className="home-console"
          aria-label="System overview"
          style={reduceMotion ? undefined : { y: consoleY, opacity: contentOpacity }}
        >
          <header className="home-console__header">
            <div>
              <p className="home-console__eyebrow">Pipeline run</p>
              <h2 className="home-console__title">Manuscript → FAIR metadata</h2>
            </div>
            <div className="home-status-pill home-status-pill--pulse">
              <BadgeCheck className="home-status-pill__icon" aria-hidden="true" />
              Review-ready
            </div>
          </header>

          <div className="home-console__panel">
            <div className="home-console__row">
              <div>
                <p className="home-console__eyebrow">{activeConsoleSlide.eyebrow}</p>
                <p className="home-console__summary">{activeConsoleSlide.summary}</p>
              </div>
              <div className="home-dots" role="tablist" aria-label="Console views">
                {consoleSlides.map((slide, index) => (
                  <button
                    key={slide.label}
                    type="button"
                    role="tab"
                    aria-selected={index === activeConsoleIndex ? 'true' : 'false'}
                    aria-label={`Show ${slide.label.toLowerCase()} view`}
                    className={`home-dots__button ${index === activeConsoleIndex ? 'is-active' : ''}`}
                    onClick={(event) => selectConsoleSlide(index, event.timeStamp)}
                  >
                    <span />
                  </button>
                ))}
              </div>
            </div>

            <AnimatePresence mode="wait">
              <motion.div
                key={activeConsoleSlide.label}
                className="home-console__view"
                initial={reduceMotion ? false : { opacity: 0, y: 12 }}
                animate={reduceMotion ? undefined : { opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -12 }}
                transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
              >
                <article className="home-console-card home-console-card--wide">
                  <div>
                    <h3 className="home-console-card__title">{activeConsoleSlide.wideCard.title}</h3>
                    <p className="home-console-card__body">
                      {activeConsoleSlide.wideCard.body}
                    </p>
                  </div>
                  <activeConsoleSlide.wideCard.icon className="home-console-card__icon" aria-hidden="true" />
                </article>

                <div className="home-console__grid">
                  {activeConsoleSlide.cards.map((card) => (
                    <article key={card.title} className="home-console-card">
                      <div className="home-console-card__heading">
                        <h3 className="home-console-card__title">{card.title}</h3>
                        <card.icon className="home-console-card__icon home-console-card__icon--secondary" aria-hidden="true" />
                      </div>
                      <p className="home-console-card__body">
                        {card.body}
                      </p>
                    </article>
                  ))}
                </div>
              </motion.div>
            </AnimatePresence>
          </div>

          <div className="home-console__highlights">
            {activeConsoleSlide.highlights.map((item) => (
              <motion.div
                key={item}
                className="home-highlight"
                initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                animate={reduceMotion ? undefined : { opacity: 1, y: 0 }}
                transition={{ duration: 0.28, ease: 'easeOut' }}
              >
                {item}
              </motion.div>
            ))}
          </div>
        </motion.aside>
      </div>
    </motion.section>
  );
}
