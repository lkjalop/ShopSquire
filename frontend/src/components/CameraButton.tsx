import { useRef } from 'react';
import styles from './CameraButton.module.css';

export default function CameraButton({
  onFiles,
  title = 'Take photo for product lookup or complaint',
  disabled = false,
  className,
}: {
  onFiles: (files: File[]) => void;
  title?: string;
  disabled?: boolean;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleClick = () => {
    if (disabled) return;
    inputRef.current?.click();
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : [];
    if (files.length > 0) onFiles(files);
    e.target.value = '';
  };

  return (
    <>
      <button
        className={`${styles.cameraBtn} ${className || ''}`}
        onClick={handleClick}
        title={title}
        disabled={disabled}
        type="button"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
          <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
          <circle cx="12" cy="13" r="4" />
        </svg>
      </button>
      <input
        ref={inputRef}
        className={styles.fileInput}
        type="file"
        accept="image/*"
        capture="environment"
        multiple
        onChange={handleChange}
      />
    </>
  );
}
