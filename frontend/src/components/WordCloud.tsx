import { useMemo } from 'react';
import type { MemoryWord } from '../api/client';

// Agent category → color mapping
export const CATEGORY_COLORS: Record<string, string> = {
  DocumentParser:        '#3b82f6', // blue
  BioMetadataAgent:      '#059669', // emerald (darker)
  KnowledgeRetriever:    '#10b981', // emerald
  Planner:               '#8b5cf6', // violet
  MetadataJSONGenerator: '#f59e0b', // amber
  ValidationAgent:       '#ef4444', // red
  Critic:                '#ec4899', // pink
  JudgeAgent:            '#06b6d4', // cyan
  unknown:               '#94a3b8', // slate
};

function categoryColor(cat: string): string {
  return CATEGORY_COLORS[cat] ?? CATEGORY_COLORS['unknown'];
}

// Deterministic pseudo-random from a string seed
function seededRand(seed: string, index: number): number {
  let h = index * 2654435761;
  for (let i = 0; i < seed.length; i++) {
    h = Math.imul(h ^ seed.charCodeAt(i), 0x9e3779b9);
  }
  h = h ^ (h >>> 16);
  return (h >>> 0) / 0xffffffff;
}

interface Props {
  words: MemoryWord[];
  /** Container width in px (used to compute positions) */
  width?: number;
  height?: number;
  /** Optional map of word text to hex color for stable coloring across views */
  colorMap?: Record<string, string>;
}

export default function WordCloud({ words, width = 320, height = 260, colorMap }: Props) {
  const positioned = useMemo(() => {
    if (!words.length) return [];

    const maxVal = Math.max(...words.map((w) => w.value));
    const minVal = Math.min(...words.map((w) => w.value));
    const range = maxVal - minVal || 1;

    // Font size: 10px – 38px
    const fontSize = (v: number) => 10 + Math.round(((v - minVal) / range) * 28);

    // Simple spiral placement with collision avoidance
    const placed: Array<{
      word: MemoryWord;
      x: number;
      y: number;
      fs: number;
      rot: number;
      color: string;
      w: number;
      h: number;
    }> = [];

    const cx = width / 2;
    const cy = height / 2;

    for (let i = 0; i < words.length; i++) {
      const word = words[i];
      const fs = fontSize(word.value);
      // Approximate text bounds - refined for better density
      const tw = word.text.length * fs * 0.52;
      const th = fs * 0.95;
      const rot = seededRand(word.text, i) < 0.22 ? 90 : 0;
      const [bw, bh] = rot === 90 ? [th, tw] : [tw, th];

      // Archimedean spiral
      let angle = seededRand(word.text, i + 100) * Math.PI * 2;
      let r = 0;
      let x = cx - bw / 2;
      let y = cy - bh / 2;

      const maxIter = 600;
      for (let iter = 0; iter < maxIter; iter++) {
        x = cx + r * Math.cos(angle) - bw / 2;
        y = cy + r * Math.sin(angle) - bh / 2;

        // Clamp to bounds
        x = Math.max(2, Math.min(width - bw - 2, x));
        y = Math.max(2, Math.min(height - bh - 2, y));

        // Check overlap with already placed words
        const overlap = placed.some((p) => {
          return !(x + bw < p.x || x > p.x + p.w || y + bh < p.y || y > p.y + p.h);
        });

        if (!overlap) break;
        // Tighter spiral
        angle += 0.35;
        r += 0.85;
      }

      placed.push({
        word,
        x,
        y,
        fs,
        rot,
        color: colorMap?.[word.text] ?? categoryColor(word.category),
        w: bw,
        h: bh,
      });
    }

    return placed;
  }, [words, width, height, colorMap]);

  if (!words.length) {
    return (
      <p className="wc-empty">No memories recorded for this run yet.</p>
    );
  }

  const maxVal = Math.max(...words.map((w) => w.value)) || 1;

  return (
    <>
      <style>{`
        .wc-word {
          transition: all 0.2s ease-in-out;
          cursor: help;
          user-select: none;
        }
        .wc-word-group:hover .wc-word {
          fill-opacity: 1 !important;
          filter: brightness(1.2);
          transform-origin: center;
        }
      `}</style>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        style={{ display: 'block', overflow: 'visible' }}
        aria-label="Memory word cloud"
      >
        {positioned.map(({ word, x, y, fs, rot, color }) => (
          <g key={word.text} className="wc-word-group">
            <title>{`Category: ${word.category}`}</title>
            <text
              className="wc-word"
              x={x + (rot === 90 ? fs * 0.9 : 0)}
              y={y + fs}
              fontSize={fs}
              fill={color}
              fillOpacity={0.82 + (word.value / maxVal) * 0.18}
              fontWeight={word.value > 3 ? 600 : 400}
              fontFamily="'Inter', system-ui, -apple-system, sans-serif"
              transform={rot === 90 ? `rotate(90, ${x}, ${y + fs})` : undefined}
            >
              {word.text}
            </text>
          </g>
        ))}
      </svg>
    </>
  );
}
