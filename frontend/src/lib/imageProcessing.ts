/**
 * Client-side image processing utilities for ShopSquire.
 *
 * Resizes, compresses, and converts uploaded product images to WebP
 * before sending to the backend, reducing bandwidth and upload latency.
 */

export interface ProcessedImage {
  blob: Blob;
  width: number;
  height: number;
  originalSize: number;
  compressedSize: number;
}

const MAX_DIMENSION = 1920;
const QUALITY = 0.82;
const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5 MB hard limit after compression

/**
 * Resize an image to fit within {@link MAX_DIMENSION} on its longest side,
 * convert to WebP (with JPEG fallback), and compress.
 */
export async function processImage(file: File): Promise<ProcessedImage> {
  const originalSize = file.size;
  const bitmap = await createImageBitmap(file);
  const { width: origW, height: origH } = bitmap;

  let width = origW;
  let height = origH;

  if (width > MAX_DIMENSION || height > MAX_DIMENSION) {
    const ratio = Math.min(MAX_DIMENSION / width, MAX_DIMENSION / height);
    width = Math.round(width * ratio);
    height = Math.round(height * ratio);
  }

  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas 2D context unavailable');
  ctx.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();

  // Prefer WebP; fall back to JPEG if the browser doesn't support WebP encoding
  let blob: Blob;
  try {
    blob = await canvas.convertToBlob({ type: 'image/webp', quality: QUALITY });
  } catch {
    blob = await canvas.convertToBlob({ type: 'image/jpeg', quality: QUALITY });
  }

  if (blob.size > MAX_FILE_SIZE) {
    // Re-encode at lower quality
    try {
      blob = await canvas.convertToBlob({ type: 'image/webp', quality: 0.6 });
    } catch {
      blob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.6 });
    }
  }

  return {
    blob,
    width,
    height,
    originalSize,
    compressedSize: blob.size,
  };
}

/**
 * Convert a File to a data-URL thumbnail (max 256px, low quality) for
 * instant preview while the full upload proceeds.
 */
export async function createThumbnailDataUrl(file: File, maxPx = 256): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const ratio = Math.min(maxPx / bitmap.width, maxPx / bitmap.height, 1);
  const w = Math.round(bitmap.width * ratio);
  const h = Math.round(bitmap.height * ratio);
  const canvas = new OffscreenCanvas(w, h);
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas 2D context unavailable');
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();

  let blob: Blob;
  try {
    blob = await canvas.convertToBlob({ type: 'image/webp', quality: 0.5 });
  } catch {
    blob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.5 });
  }
  return URL.createObjectURL(blob);
}
