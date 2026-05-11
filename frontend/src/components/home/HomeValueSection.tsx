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
            staggerChildren: 0.14,
            delayChildren: 0.08,
          },
        },
      };
  const item: Variants | undefined = reduceMotion
    ? undefined
    : {
        hidden: { opacity: 0, y: 36, scale: 0.96, rotateX: -6 },
        show: {
          opacity: 1,
          y: 0,
          scale: 1,
          rotateX: 0,
          transition: { duration: 0.7, ease: [0.16, 1, 0.3, 1] },
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
          <h2 className="home-section__title">Standards-aware curation at scale.</h2>
          <p className="home-section__body">
            Manual MIxS-style metadata from a single manuscript can take hours of expert time.
            FAIRiAgent targets the same task with structured, multi-agent runs—every step
            observable, every output traceable to the source document.
          </p>
        </motion.div>

        <motion.div
          className="home-card-grid"
          initial={reduceMotion ? undefined : 'hidden'}
          whileInView={reduceMotion ? undefined : 'show'}
          viewport={{ once: true, amount: 0.18 }}
          variants={stagger}
          style={reduceMotion ? undefined : { perspective: '1200px' }}
        >
          {cards.map((card) => (
            <motion.article
              key={card.title}
              className="home-info-card"
              variants={item}
              whileHover={reduceMotion ? undefined : { y: -6, rotateX: 2, rotateY: -2 }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              style={reduceMotion ? undefined : { transformStyle: 'preserve-3d' }}
            >
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
