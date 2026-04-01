import { useRef, useState, useCallback } from 'react';
import styles from './AttachmentButton.module.css';

interface AttachmentButtonProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  className?: string;
}

export default function AttachmentButton({ onFiles, disabled = false, className }: AttachmentButtonProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const acceptImages = 'image/*,.avif,image/avif';

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : [];
    if (files.length > 0) onFiles(files);
    e.target.value = '';
    setMenuOpen(false);
  }, [onFiles]);

  const handlePaste = useCallback(async () => {
    setMenuOpen(false);
    try {
      const items = await navigator.clipboard.read();
      const imageFiles: File[] = [];
      for (const item of items) {
        const imageType = item.types.find(t => t.startsWith('image/'));
        if (imageType) {
          const blob = await item.getType(imageType);
          const ext = imageType.split('/')[1] || 'png';
          imageFiles.push(new File([blob], `pasted-image.${ext}`, { type: imageType }));
        }
      }
      if (imageFiles.length > 0) onFiles(imageFiles);
    } catch {
      // Clipboard API not available or no image — silently ignore
    }
  }, [onFiles]);

  return (
    <div className={`${styles.wrapper} ${className || ''}`}>
      <button
        className={styles.attachBtn}
        onClick={() => setMenuOpen(prev => !prev)}
        disabled={disabled}
        type="button"
        title="Attach image"
        aria-label="Attach image"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      </button>
      {menuOpen && (
        <div className={styles.menu} role="menu">
          <button className={styles.menuItem} onClick={() => { cameraInputRef.current?.click(); }} role="menuitem">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
              <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
              <circle cx="12" cy="13" r="4" />
            </svg>
            Camera
          </button>
          <button className={styles.menuItem} onClick={() => { fileInputRef.current?.click(); }} role="menuitem">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            Upload File
          </button>
          <button className={styles.menuItem} onClick={handlePaste} role="menuitem">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            Paste from Clipboard
          </button>
        </div>
      )}
      <input ref={cameraInputRef} type="file" accept={acceptImages} capture="environment" multiple onChange={handleFileSelect} className={styles.hidden} />
      <input ref={fileInputRef} type="file" accept={acceptImages} multiple onChange={handleFileSelect} className={styles.hidden} />
    </div>
  );
}
