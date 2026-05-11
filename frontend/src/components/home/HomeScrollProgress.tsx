import { motion, useScroll, useSpring } from 'framer-motion';

export default function HomeScrollProgress() {
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, {
    stiffness: 140,
    damping: 30,
    mass: 0.4,
  });
  return <motion.div className="home-progress" style={{ scaleX }} aria-hidden="true" />;
}
