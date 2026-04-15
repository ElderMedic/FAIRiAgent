import { motion, useReducedMotion, type Variants } from 'framer-motion';
import { BadgeCheck, FlaskConical } from 'lucide-react';
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
            staggerChildren: 0.12,
            delayChildren: 0.08,
          },
        },
      };
  const item: Variants | undefined = reduceMotion
    ? undefined
    : {
        hidden: { opacity: 0, y: 24 },
        show: {
          opacity: 1,
          y: 0,
          transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] },
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
                Parse, ground, draft—then critique before export.
              </h2>
            </div>
            <p className="home-workflow__lede">
              LangGraph orchestrates specialised agents with a Plan → Execute → Critique → Refine loop:
              structured intake, FAIR Data Station grounding, and validation-aware retries.
            </p>
          </motion.div>

          <motion.div className="home-ops-panel" variants={item}>
            <div className="home-ops-panel__copy">
              <p className="home-section__eyebrow home-section__eyebrow--dark">Operating model</p>
              <h3 className="home-ops-panel__title">
                Drafts you can inspect—not a black-box answer.
              </h3>
            </div>

            <div className="home-ops-panel__grid">
              <article className="home-ops-card">
                <div className="home-ops-card__heading">
                  <FlaskConical className="home-ops-card__icon" aria-hidden="true" />
                  <span>Full documents</span>
                </div>
                <p className="home-ops-card__body">
                  Methods, tables, and supplements matter—metadata is rarely in one paragraph.
                </p>
              </article>

              <article className="home-ops-card">
                <div className="home-ops-card__heading">
                  <BadgeCheck className="home-ops-card__icon" aria-hidden="true" />
                  <span>Bundled sample = real path</span>
                </div>
                <p className="home-ops-card__body">
                  The demo manuscript uses the same pipeline as your uploads—no toy shortcut.
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
