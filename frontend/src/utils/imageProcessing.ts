export type ImageMeta = {
  name: string;
  size: number;
  type: string;
  width?: number;
  height?: number;
  sha256?: string;
  phash?: string;
};

export async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const res = typeof reader.result === 'string' ? reader.result : '';
      const b64 = res.includes(',') ? res.split(',')[1] : res;
      resolve(b64);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export async function hashSha256(file: File): Promise<string | null> {
  try {
    const buf = await file.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', buf);
    const hashArray = Array.from(new Uint8Array(digest));
    return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
  } catch {
    return null;
  }
}

export async function extractImageMeta(file: File): Promise<ImageMeta> {
  const meta: ImageMeta = { name: file.name, size: file.size, type: file.type };
  try {
    const url = URL.createObjectURL(file);
    await new Promise<void>((resolve) => {
      const img = new Image();
      img.onload = () => {
        meta.width = img.width;
        meta.height = img.height;
        resolve();
      };
      img.onerror = () => resolve();
      img.src = url;
    });
    URL.revokeObjectURL(url);
  } catch {
    // ignore
  }
  try {
    meta.sha256 = await hashSha256(file);
  } catch {
    // ignore
  }
  try {
    meta.phash = await computePHash(file);
  } catch {
    // ignore
  }
  return meta;
}

/**
 * Compute a perceptual hash (aHash) for an image file using canvas.
 * Returns a hex string of 16 chars (64-bit).
 */
export async function computePHash(file: File): Promise<string> {
  const url = URL.createObjectURL(file);
  try {
    const img = await loadImage(url);
    const size = 8; // 8x8 grayscale gives 64-bit hash
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (!ctx) return '';
    ctx.drawImage(img, 0, 0, size, size);
    const { data } = ctx.getImageData(0, 0, size, size);
    const gray: number[] = [];
    for (let i = 0; i < data.length; i += 4) {
      const r = data[i], g = data[i + 1], b = data[i + 2];
      // luminance approximation
      gray.push(0.299 * r + 0.587 * g + 0.114 * b);
    }
    const avg = gray.reduce((a, b) => a + b, 0) / gray.length;
    // Build 64-bit string based on avg comparison
    let bits = '';
    for (let i = 0; i < gray.length; i++) {
      bits += gray[i] >= avg ? '1' : '0';
    }
    // Convert to hex
    let hex = '';
    for (let i = 0; i < 64; i += 4) {
      const nibble = bits.slice(i, i + 4);
      hex += parseInt(nibble, 2).toString(16);
    }
    return hex;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = (e) => reject(e);
    img.src = url;
  });
}

export async function buildSanitizedImages(files: File[]): Promise<Array<{ name: string; size: number; type: string; width?: number; height?: number; sha256?: string; phash?: string }>> {
  const out: Array<{ name: string; size: number; type: string; width?: number; height?: number; sha256?: string; phash?: string }> = [];
  for (const f of files) {
    const meta = await extractImageMeta(f);
    out.push({ name: meta.name, size: meta.size, type: meta.type, width: meta.width, height: meta.height, sha256: meta.sha256 || undefined, phash: meta.phash || undefined });
  }
  return out;
}
