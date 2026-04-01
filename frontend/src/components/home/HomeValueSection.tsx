import type { HomeCard } from './content';

interface HomeValueSectionProps {
  cards: HomeCard[];
}

export default function HomeValueSection({ cards }: HomeValueSectionProps) {
  return (
    <section className="home-section home-section--light">
      <div className="home-shell home-section__layout">
        <div className="home-section__intro">
          <p className="home-section__eyebrow">Design principles</p>
          <h2 className="home-section__title">Clarity at every stage of the workflow.</h2>
          <p className="home-section__body">
            Stable containers, consistent typography, predictable spacing, and restrained motion help the
            interface stay calm under real use. The structure follows the operator journey instead of
            competing with it.
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
