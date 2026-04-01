import { useRef, useEffect, useCallback } from 'react';

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  color: string;
  alpha: number;
  pulsePhase: number;
  pulseSpeed: number;
  glowing: boolean;
}

interface BioBackgroundProps {
  reducedMode?: boolean;
  className?: string;
}

const COLORS = [
  { r: 0, g: 196, b: 140 },   // teal accent
  { r: 6, g: 104, b: 225 },   // primary blue
  { r: 100, g: 200, b: 255 }, // light cyan
  { r: 0, g: 160, b: 120 },   // deep teal
  { r: 60, g: 140, b: 220 },  // mid blue
];

function getParticleCount(reducedMode: boolean): number {
  if (reducedMode) return 20;
  if (typeof window !== 'undefined' && window.innerWidth < 768) return 40;
  return 80;
}

function createParticle(w: number, h: number): Particle {
  const colorDef = COLORS[Math.floor(Math.random() * COLORS.length)];
  const glowing = Math.random() < 0.3;
  return {
    x: Math.random() * w,
    y: Math.random() * h,
    vx: (Math.random() - 0.5) * 0.4,
    vy: (Math.random() - 0.5) * 0.4,
    radius: Math.random() * 2.5 + 1.5,
    color: `${colorDef.r}, ${colorDef.g}, ${colorDef.b}`,
    alpha: Math.random() * 0.5 + 0.3,
    pulsePhase: Math.random() * Math.PI * 2,
    pulseSpeed: Math.random() * 0.02 + 0.005,
    glowing,
  };
}

export default function BioBackground({ reducedMode = false, className = '' }: BioBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>([]);
  const mouseRef = useRef({ x: -1000, y: -1000 });
  const animRef = useRef<number>(0);
  const prefersReducedMotion = useRef(false);

  const initParticles = useCallback((w: number, h: number) => {
    const count = getParticleCount(reducedMode);
    particlesRef.current = Array.from({ length: count }, () => createParticle(w, h));
  }, [reducedMode]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const mql = window.matchMedia('(prefers-reduced-motion: reduce)');
    prefersReducedMotion.current = mql.matches;
    const motionHandler = (e: MediaQueryListEvent) => {
      prefersReducedMotion.current = e.matches;
    };
    mql.addEventListener('change', motionHandler);

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      initParticles(rect.width, rect.height);
    };

    resize();
    window.addEventListener('resize', resize);

    const handleMouse = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      mouseRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };
    const handleMouseLeave = () => {
      mouseRef.current = { x: -1000, y: -1000 };
    };
    canvas.addEventListener('mousemove', handleMouse);
    canvas.addEventListener('mouseleave', handleMouseLeave);

    const CONNECTION_DIST = 150;
    const MOUSE_RADIUS = 120;
    let time = 0;

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      time += 1;

      ctx.clearRect(0, 0, w, h);

      // Background gradient
      const bgGrad = ctx.createRadialGradient(w * 0.5, h * 0.4, 0, w * 0.5, h * 0.5, w * 0.8);
      bgGrad.addColorStop(0, '#0f1729');
      bgGrad.addColorStop(1, '#0A0E17');
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, w, h);

      const particles = particlesRef.current;
      const mouse = mouseRef.current;

      if (!prefersReducedMotion.current) {
        for (const p of particles) {
          // Mouse interaction: gentle attraction
          const dx = mouse.x - p.x;
          const dy = mouse.y - p.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < MOUSE_RADIUS && dist > 0) {
            const force = (MOUSE_RADIUS - dist) / MOUSE_RADIUS * 0.008;
            p.vx += dx / dist * force;
            p.vy += dy / dist * force;
          }

          // Damping
          p.vx *= 0.998;
          p.vy *= 0.998;

          p.x += p.vx;
          p.y += p.vy;

          // Wrap around edges
          if (p.x < -10) p.x = w + 10;
          if (p.x > w + 10) p.x = -10;
          if (p.y < -10) p.y = h + 10;
          if (p.y > h + 10) p.y = -10;

          // Update pulse
          p.pulsePhase += p.pulseSpeed;
        }
      }

      // Draw connections
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const a = particles[i];
          const b = particles[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < CONNECTION_DIST) {
            const opacity = (1 - dist / CONNECTION_DIST) * 0.25;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.strokeStyle = `rgba(6, 104, 225, ${opacity})`;
            ctx.lineWidth = 0.6;
            ctx.stroke();
          }
        }
      }

      // Draw particles
      for (const p of particles) {
        const pulse = p.glowing ? Math.sin(p.pulsePhase) * 0.3 + 0.7 : 1;
        const currentAlpha = p.alpha * pulse;
        const currentRadius = p.radius * (p.glowing ? (0.8 + Math.sin(p.pulsePhase) * 0.4) : 1);

        // Glow effect for glowing particles
        if (p.glowing) {
          const glowGrad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, currentRadius * 6);
          glowGrad.addColorStop(0, `rgba(${p.color}, ${currentAlpha * 0.3})`);
          glowGrad.addColorStop(1, `rgba(${p.color}, 0)`);
          ctx.beginPath();
          ctx.arc(p.x, p.y, currentRadius * 6, 0, Math.PI * 2);
          ctx.fillStyle = glowGrad;
          ctx.fill();
        }

        // Core particle
        ctx.beginPath();
        ctx.arc(p.x, p.y, currentRadius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${p.color}, ${currentAlpha})`;
        ctx.fill();
      }

      // Subtle DNA helix pattern in background
      ctx.globalAlpha = 0.04;
      const helixX = w * 0.75;
      for (let i = 0; i < h; i += 4) {
        const offset = Math.sin((i + time * 0.5) * 0.02) * 40;
        const offset2 = Math.sin((i + time * 0.5) * 0.02 + Math.PI) * 40;
        ctx.beginPath();
        ctx.arc(helixX + offset, i, 1.5, 0, Math.PI * 2);
        ctx.fillStyle = '#00C48C';
        ctx.fill();
        ctx.beginPath();
        ctx.arc(helixX + offset2, i, 1.5, 0, Math.PI * 2);
        ctx.fillStyle = '#0668E1';
        ctx.fill();

        // Cross-bars every ~30px
        if (i % 30 < 4) {
          ctx.beginPath();
          ctx.moveTo(helixX + offset, i);
          ctx.lineTo(helixX + offset2, i);
          ctx.strokeStyle = '#4A90D9';
          ctx.lineWidth = 0.8;
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;

      animRef.current = requestAnimationFrame(draw);
    };

    if (prefersReducedMotion.current) {
      // Draw once for static version
      draw();
      cancelAnimationFrame(animRef.current);
    } else {
      draw();
    }

    return () => {
      cancelAnimationFrame(animRef.current);
      window.removeEventListener('resize', resize);
      canvas.removeEventListener('mousemove', handleMouse);
      canvas.removeEventListener('mouseleave', handleMouseLeave);
      mql.removeEventListener('change', motionHandler);
    };
  }, [initParticles]);

  return (
    <canvas
      ref={canvasRef}
      className={`absolute inset-0 w-full h-full ${className}`}
      style={{ display: 'block' }}
    />
  );
}
