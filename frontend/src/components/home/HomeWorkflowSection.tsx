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
              Follow the path from full paper to FAIR-ready metadata draft.
            </h2>
          </div>
          <p className="home-workflow__lede">
            FAIRiAgent parses the document, selects the right metadata structure, grounds the draft
            against FAIR Data Station context, then critiques and validates the result before export.
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
              Built for researchers who need a draft they can inspect, correct, and hand forward.
            </h3>
          </div>

          <div className="home-ops-panel__grid">
            <article className="home-ops-card">
              <div className="home-ops-card__heading">
                <FlaskConical className="home-ops-card__icon" aria-hidden="true" />
                <span>Complete papers, not snippets</span>
              </div>
              <p className="home-ops-card__body">
                The workflow is meant for long biological documents where key metadata are spread across
                methods, tables, and supporting sections.
              </p>
            </article>

            <article className="home-ops-card">
              <div className="home-ops-card__heading">
                <BadgeCheck className="home-ops-card__icon" aria-hidden="true" />
                <span>Same path as a real run</span>
              </div>
              <p className="home-ops-card__body">
                The bundled earthworm paper goes through the same backend path as an uploaded document, so
                the interface can be tested without switching into a toy mode.
              </p>
            </article>
          </div>
        </div>
      </div>
    </section>
  );
}
