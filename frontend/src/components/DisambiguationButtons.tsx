import { useEffect } from 'react';
import styles from './DisambiguationButtons.module.css';

export interface DisambiguationOption {
  id: string;
  text: string;
  goal?: string;
}

interface DisambiguationButtonsProps {
  options: (string | DisambiguationOption)[];
  onSelect: (text: string) => void;
  disabled?: boolean;
}

const ICONS: Record<string, string> = {
  visual_search: '🔍',  // 🔍
  cv_triage: '📦',      // 📦
  freeform: '💬',       // 💬
};

function normalize(opt: string | DisambiguationOption): DisambiguationOption {
  if (typeof opt === 'string') return { id: opt, text: opt, goal: 'freeform' };
  return { id: opt.id, text: opt.text, goal: opt.goal || 'freeform' };
}

export default function DisambiguationButtons({ options, onSelect, disabled = false }: DisambiguationButtonsProps) {
  const normalized = options.map(normalize);

  useEffect(() => {
    if (disabled) return;
    const handler = (e: KeyboardEvent) => {
      const n = parseInt(e.key, 10);
      if (n >= 1 && n <= 9 && normalized[n - 1]) {
        e.preventDefault();
        onSelect(normalized[n - 1].text);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [normalized, onSelect, disabled]);

  return (
    <div className={styles.container}>
      {normalized.map((opt, i) => (
        <button
          key={opt.id}
          className={styles.btn}
          onClick={() => onSelect(opt.text)}
          disabled={disabled}
          type="button"
          title={'Press ' + (i + 1)}
        >
          <span className={styles.shortcut}>{i + 1}</span>
          <span className={styles.icon}>{ICONS[opt.goal || ''] || '✨'}</span>
          <span className={styles.label}>{opt.text}</span>
        </button>
      ))}
    </div>
  );
}
