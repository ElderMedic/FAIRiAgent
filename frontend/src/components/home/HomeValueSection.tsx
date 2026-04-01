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
          <h2 className="home-section__title">A research workflow that stays readable under real use.</h2>
          <p className="home-section__body">
            Researchers should be able to see where a draft came from, what context shaped it, and what
            still needs checking. The interface is designed to keep that chain visible without making the
            page feel technical for its own sake.
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
