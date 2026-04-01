import {
  AnimatePresence,
  motion,
  useReducedMotion,
  useScroll,
  useTransform,
  type Variants,
} from 'framer-motion';
import { ArrowRight, BadgeCheck, Sparkles } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import HomeHeroBackdrop from './HomeHeroBackdrop';
import type { HomeConsoleSlide, HomeSignal } from './content';

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
  const heroStagger: Variants | undefined = reduceMotion
    ? undefined
    : {
        hidden: {},
        show: {
          transition: {
            staggerChildren: 0.1,
            delayChildren: 0.08,
          },
        },
      };
  const heroItem: Variants | undefined = reduceMotion
    ? undefined
    : {
        hidden: { opacity: 0, y: 20 },
        show: {
          opacity: 1,
          y: 0,
          transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] },
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
      setActiveConsoleIndex((current) => (current + 1) % consoleSlides.length);
    }, 4200);
    return () => window.clearInterval(timer);
  }, [consoleSlides.length, reduceMotion]);

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
            <Sparkles className="home-chip__icon" aria-hidden="true" />
            Agentic FAIR metadata generation for biological research
          </motion.div>

          <motion.div className="home-copy" variants={heroItem}>
            <p className="home-eyebrow">Full papers in. FAIR metadata drafts out.</p>
            <h1 className="home-title">
              Context Engineering of Your Project For Autonomous Research
            </h1>
            <p className="home-lede">
              FAIRiAgent is a multi-agent system for the part of curation that usually takes hours:
              reading a full paper, recovering methods and sample context, selecting the right MIxS-style
              checklist, grounding terms against FAIR Data Station resources, and producing structured
              metadata drafts that can be reviewed before reuse or submission.
            </p>
          </motion.div>

          <motion.div className="home-actions" variants={heroItem}>
            <button type="button" onClick={onStart} className="home-button home-button--primary">
              Start a run
              <ArrowRight className="home-button__icon" aria-hidden="true" />
            </button>
            <button type="button" onClick={onSample} className="home-button home-button--ghost">
              Run bundled sample
            </button>
          </motion.div>

          <motion.div className="home-signal-grid" variants={heroItem}>
            {signals.map((signal) => (
              <motion.article
                key={signal.label}
                className="home-signal-card"
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
              <p className="home-console__eyebrow">Run overview</p>
              <h2 className="home-console__title">Paper-to-metadata system</h2>
            </div>
            <div className="home-status-pill">
              <BadgeCheck className="home-status-pill__icon" aria-hidden="true" />
              Ready for review
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
                    aria-selected={index === activeConsoleIndex}
                    aria-label={`Show ${slide.label.toLowerCase()} view`}
                    className={`home-dots__button ${index === activeConsoleIndex ? 'is-active' : ''}`}
                    onClick={() => setActiveConsoleIndex(index)}
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
                initial={reduceMotion ? false : { opacity: 0, y: 10 }}
                animate={reduceMotion ? undefined : { opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -10 }}
                transition={{ duration: 0.28, ease: 'easeOut' }}
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
                transition={{ duration: 0.26, ease: 'easeOut' }}
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
