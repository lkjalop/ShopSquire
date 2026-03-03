import styles from './DisambiguationButtons.module.css';

interface DisambiguationOption {
  id: string;
  text: string;
  goal: string;
}

interface DisambiguationButtonsProps {
  options: DisambiguationOption[];
  onSelect: (option: DisambiguationOption) => void;
  disabled?: boolean;
}

const ICONS: Record<string, string> = {
  visual_search: '\uD83D\uDD0D',  // 🔍
  cv_triage: '\uD83D\uDCE6',      // 📦
  freeform: '\uD83D\uDCAC',       // 💬
};

export default function DisambiguationButtons({ options, onSelect, disabled = false }: DisambiguationButtonsProps) {
  return (
    <div className={styles.container}>
      {options.map(opt => (
        <button
          key={opt.id}
          className={styles.btn}
          onClick={() => onSelect(opt)}
          disabled={disabled}
          type="button"
        >
          <span className={styles.icon}>{ICONS[opt.goal] || '\u2728'}</span>
          <span className={styles.label}>{opt.text}</span>
        </button>
      ))}
    </div>
  );
}
