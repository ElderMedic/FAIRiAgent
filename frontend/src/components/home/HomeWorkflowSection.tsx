import { motion, useReducedMotion, type Variants } from 'framer-motion';
import { ClipboardCheck, FlaskConical } from 'lucide-react';
import type { HomeStep } from './content';

interface HomeWorkflowSectionProps {
  steps: HomeStep[];
}

export default function HomeWorkflowSection({ steps }: HomeWorkflowSectionProps) {
  const reduceMotion = useReducedMotion();
  const stagger: Variants | undefined = reduceMotion
    ? undefined
    : {
        hidden: {},
        show: {
          transition: {
            staggerChildren: 0.16,
            delayChildren: 0.1,
          },
        },
      };
  const item: Variants | undefined = reduceMotion
    ? undefined
    : {
        hidden: { opacity: 0, x: -32, scale: 0.97 },
        show: {
          opacity: 1,
          x: 0,
          scale: 1,
          transition: { duration: 0.75, ease: [0.16, 1, 0.3, 1] },
        },
      };

  return (
    <section className="home-section home-section--dark">
      <div className="home-shell home-system-layout">
        <motion.div
          className="home-system-column"
          initial={reduceMotion ? undefined : 'hidden'}
          whileInView={reduceMotion ? undefined : 'show'}
          viewport={{ once: true, amount: 0.24 }}
          variants={stagger}
        >
          <motion.div className="home-workflow__header" variants={item}>
            <div className="home-workflow__copy">
              <p className="home-section__eyebrow home-section__eyebrow--dark">System</p>
              <h2 className="home-section__title home-section__title--dark">
                Parse, ground, draft—then critique before you export.
              </h2>
            </div>
            <p className="home-workflow__lede">
              LangGraph orchestrates specialised agents through a Plan → Execute → Critique → Refine
              loop: structured document intake, FAIR Data Station grounding, and validation-aware
              retries that target genuinely weak fields.
            </p>
          </motion.div>

          <motion.div className="home-ops-panel" variants={item}>
            <div className="home-ops-panel__copy">
              <p className="home-section__eyebrow home-section__eyebrow--dark">Operating model</p>
              <h3 className="home-ops-panel__title">
                Transparent drafts—not a black-box answer.
              </h3>
            </div>

            <div className="home-ops-panel__grid">
              <article className="home-ops-card">
                <div className="home-ops-card__heading">
                  <FlaskConical className="home-ops-card__icon" aria-hidden="true" />
                  <span>Full documents only</span>
                </div>
                <p className="home-ops-card__body">
                  Methods, tables, and supplements are critical—biological metadata is rarely
                  contained in a single paragraph.
                </p>
              </article>

              <article className="home-ops-card">
                <div className="home-ops-card__heading">
                  <ClipboardCheck className="home-ops-card__icon" aria-hidden="true" />
                  <span>Demo uses the real pipeline</span>
                </div>
                <p className="home-ops-card__body">
                  The bundled sample paper runs through the same agents as your own uploads—no
                  simplified shortcut.
                </p>
              </article>
            </div>
          </motion.div>
        </motion.div>

        <motion.div
          className="home-system-rail"
          initial={reduceMotion ? undefined : 'hidden'}
          whileInView={reduceMotion ? undefined : 'show'}
          viewport={{ once: true, amount: 0.15 }}
          variants={stagger}
        >
          {steps.map((step, index) => (
            <motion.article key={step.title} className="home-step-card" variants={item}>
              <div className="home-step-card__track" aria-hidden="true">
                <span className="home-step-card__node" />
              </div>
              <div className="home-step-card__content">
                <div className="home-step-card__top">
                  <div className="home-step-card__icon-wrap">
                    <step.icon className="home-step-card__icon" aria-hidden="true" />
                  </div>
                  <span className="home-step-card__index">Module 0{index + 1}</span>
                </div>
                <h3 className="home-step-card__title">{step.title}</h3>
                <p className="home-step-card__body">{step.body}</p>
              </div>
            </motion.article>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
