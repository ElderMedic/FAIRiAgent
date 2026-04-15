import { motion, useReducedMotion, type Variants } from 'framer-motion';
import type { HomeCard } from './content';

interface HomeValueSectionProps {
  cards: HomeCard[];
}

export default function HomeValueSection({ cards }: HomeValueSectionProps) {
  const reduceMotion = useReducedMotion();
  const stagger: Variants | undefined = reduceMotion
    ? undefined
    : {
        hidden: {},
        show: {
          transition: {
            staggerChildren: 0.1,
            delayChildren: 0.06,
          },
        },
      };
  const item: Variants | undefined = reduceMotion
    ? undefined
    : {
        hidden: { opacity: 0, y: 18 },
        show: {
          opacity: 1,
          y: 0,
          transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] },
        },
      };

  return (
    <section className="home-section home-section--light">
      <div className="home-shell home-section__layout">
        <motion.div
          className="home-section__intro"
          initial={reduceMotion ? undefined : 'hidden'}
          whileInView={reduceMotion ? undefined : 'show'}
          viewport={{ once: true, amount: 0.35 }}
          variants={item}
        >
          <p className="home-section__eyebrow">Why FAIRiAgent</p>
          <h2 className="home-section__title">Curation that scales with full papers.</h2>
          <p className="home-section__body">
            Manual MIxS-style metadata from a manuscript can take hours. This system targets the same job with
            inspectable, multi-agent runs—not a single opaque prompt.
          </p>
        </motion.div>

        <motion.div
          className="home-card-grid"
          initial={reduceMotion ? undefined : 'hidden'}
          whileInView={reduceMotion ? undefined : 'show'}
          viewport={{ once: true, amount: 0.18 }}
          variants={stagger}
        >
          {cards.map((card) => (
            <motion.article key={card.title} className="home-info-card" variants={item}>
              <div className="home-info-card__icon-wrap">
                <card.icon className="home-info-card__icon" aria-hidden="true" />
              </div>
              <h3 className="home-info-card__title">{card.title}</h3>
              <p className="home-info-card__body">{card.description}</p>
            </motion.article>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
