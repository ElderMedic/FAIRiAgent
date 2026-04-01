import type { HomeCard } from './content';

interface HomeValueSectionProps {
  cards: HomeCard[];
}

export default function HomeValueSection({ cards }: HomeValueSectionProps) {
  return (
    <section className="home-section home-section--light">
      <div className="home-shell home-section__layout">
        <div className="home-section__intro">
          <p className="home-section__eyebrow">Why this workflow</p>
          <h2 className="home-section__title">Built around the curation bottleneck in real biology papers.</h2>
          <p className="home-section__body">
            The hard part is not generating a plausible paragraph. It is recovering enough context from a
            complete paper to produce metadata another researcher, curator, or repository workflow can
            actually work with.
          </p>
        </div>

        <div className="home-card-grid">
          {cards.map((card) => (
            <article key={card.title} className="home-info-card">
              <div className="home-info-card__icon-wrap">
                <card.icon className="home-info-card__icon" aria-hidden="true" />
              </div>
              <h3 className="home-info-card__title">{card.title}</h3>
              <p className="home-info-card__body">{card.description}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
