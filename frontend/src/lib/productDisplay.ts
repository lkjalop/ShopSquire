export function productDisplayName(product: any): string {
  const specs = product?.specs && typeof product.specs === 'object' ? product.specs : {};
  const displayName = String(
    product?.display_name ||
    specs?.display_name ||
    product?.name ||
    product?.title ||
    ''
  ).trim();
  return displayName || 'Product';
}

export function productSubtitle(product: any): string {
  const specs = product?.specs && typeof product.specs === 'object' ? product.specs : {};
  const subtitle = String(
    product?.subtitle ||
    specs?.subtitle ||
    product?.specs_summary ||
    ''
  ).trim();
  return subtitle;
}

export function productShortLabel(product: any): string {
  const title = productDisplayName(product);
  const subtitle = productSubtitle(product);
  if (!subtitle) return title;
  const storageChunk = subtitle.match(/\[[^\]]+\]/)?.[0] || '';
  return `${title} ${storageChunk}`.trim();
}
