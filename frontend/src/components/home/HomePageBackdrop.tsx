import { motion, useReducedMotion, useScroll, useTransform } from 'framer-motion';
import { useEffect, useRef } from 'react';
import heroVideo from '../../assets/home-hero-video.mp4';

/**
 * Page-level video backdrop. Renders inside an absolutely-positioned wrapper
 * that fills the home page only, with a sticky inner layer that follows the
 * viewport while the user scrolls through home content. Once the user reaches
 * the footer the wrapper ends naturally and the footer's own background takes
 * over — no more video bleed-through.
 */
export default function HomePageBackdrop() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const reduceMotion = useReducedMotion();
  const { scrollYProgress } = useScroll();

  // Subtle, unified parallax — keep the mood consistent across sections.
  const videoScale = useTransform(scrollYProgress, [0, 1], [1.02, 1.16]);
  const videoOpacity = useTransform(
    scrollYProgress,
    [0, 0.4, 0.85, 1],
    [1, 0.95, 0.78, 0.62],
  );
  const videoY = useTransform(scrollYProgress, [0, 1], ['0%', '-8%']);

  // Stays within a deep-navy palette throughout. Variations are temperature
  // (cooler / slightly warmer) rather than dark↔light flips, so the page
  // reads as one continuous cinematic surface.
  const tintBackground = useTransform(scrollYProgress, (p) => {
    if (p < 0.22) {
      // hero
      return 'linear-gradient(180deg, rgba(7,17,31,0.55) 0%, rgba(7,17,31,0.72) 100%)';
    }
    if (p < 0.55) {
      // value section — slight teal tilt to keep it visually distinct
      return 'linear-gradient(180deg, rgba(7,17,31,0.66) 0%, rgba(9,28,38,0.74) 100%)';
    }
    if (p < 0.85) {
      // workflow — slightly cooler / bluer
      return 'linear-gradient(180deg, rgba(8,19,33,0.74) 0%, rgba(10,22,40,0.82) 100%)';
    }
    // CTA / hand-off — gently warmer navy as a resolution
    return 'linear-gradient(180deg, rgba(10,22,40,0.78) 0%, rgba(14,26,42,0.86) 100%)';
  });

  const grainShift = useTransform(scrollYProgress, [0, 1], ['0px', '-180px']);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const tryPlay = () => v.play().catch(() => {});
    tryPlay();
    document.addEventListener('visibilitychange', tryPlay);
    return () => document.removeEventListener('visibilitychange', tryPlay);
  }, []);

  return (
    <div className="home-backdrop-wrap" aria-hidden="true">
      <div className="home-backdrop">
        <motion.div
          className="home-backdrop__media"
          style={
            reduceMotion
              ? undefined
              : { scale: videoScale, opacity: videoOpacity, y: videoY }
          }
        >
          <video
            ref={videoRef}
            className="home-backdrop__video"
            autoPlay
            muted
            loop
            playsInline
            preload="auto"
          >
            <source src={heroVideo} type="video/mp4" />
          </video>
        </motion.div>

        <motion.div
          className="home-backdrop__tint"
          style={reduceMotion ? undefined : { background: tintBackground }}
        />

        <motion.div
          className="home-backdrop__grain"
          style={reduceMotion ? undefined : { backgroundPositionX: grainShift }}
        />

        <div className="home-backdrop__edges" />
      </div>
    </div>
  );
}
