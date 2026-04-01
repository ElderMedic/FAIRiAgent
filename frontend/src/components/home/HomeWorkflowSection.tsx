import { BadgeCheck, FlaskConical } from 'lucide-react';
import type { HomeStep } from './content';

interface HomeWorkflowSectionProps {
  steps: HomeStep[];
}

export default function HomeWorkflowSection({ steps }: HomeWorkflowSectionProps) {
  return (
    <section className="home-section home-section--dark">
      <div className="home-shell">
        <div className="home-workflow__header">
          <div className="home-workflow__copy">
            <p className="home-section__eyebrow home-section__eyebrow--dark">Workflow</p>
            <h2 className="home-section__title home-section__title--dark">
              Explain the system as a sequence, not a collage.
            </h2>
          </div>
          <p className="home-workflow__lede">
            The goal is not to clone another site pixel-for-pixel. The goal is to reach the same standard
            of restraint: fewer visual decisions, stronger hierarchy, and panels that feel intentional.
          </p>
        </div>

        <div className="home-step-grid">
          {steps.map((step, index) => (
            <article key={step.title} className="home-step-card">
              <div className="home-step-card__top">
                <div className="home-step-card__icon-wrap">
                  <step.icon className="home-step-card__icon" aria-hidden="true" />
                </div>
                <span className="home-step-card__index">0{index + 1}</span>
              </div>
              <h3 className="home-step-card__title">{step.title}</h3>
              <p className="home-step-card__body">{step.body}</p>
            </article>
          ))}
        </div>

        <div className="home-ops-panel">
          <div className="home-ops-panel__copy">
            <p className="home-section__eyebrow home-section__eyebrow--dark">Operating model</p>
            <h3 className="home-ops-panel__title">
              Built for local labs and internal teams, not public sign-up funnels.
            </h3>
          </div>

          <div className="home-ops-panel__grid">
            <article className="home-ops-card">
              <div className="home-ops-card__heading">
                <FlaskConical className="home-ops-card__icon" aria-hidden="true" />
                <span>Research-first UX</span>
              </div>
              <p className="home-ops-card__body">
                Emphasis stays on process state, evidence, and reviewability rather than decorative churn.
              </p>
            </article>

            <article className="home-ops-card">
              <div className="home-ops-card__heading">
                <BadgeCheck className="home-ops-card__icon" aria-hidden="true" />
                <span>Demo without fakery</span>
              </div>
              <p className="home-ops-card__body">
                The bundled sample still exercises the actual backend flow, just with a smaller document.
              </p>
            </article>
          </div>
        </div>
      </div>
    </section>
  );
}
