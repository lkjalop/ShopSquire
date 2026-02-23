import React, { useEffect, useRef, useState } from 'react';
import { useDecisionTrace } from './hooks/useDecisionTrace';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8080/api/v1';
const API_KEY = import.meta.env.VITE_API_KEY || 'local-developer-key';

const fetchWithTimeout = async (url, options = {}, timeoutMs = 8000) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    return res;
  } finally {
    clearTimeout(timer);
  }
};
const MAX_UPLOAD_MB = 10;

// Client-side PII detection (heuristic patterns)
const PII_PATTERNS = {
  // Avoid false positives on normal numbers (prices, years). Keep these narrow.
  creditCard: /\b(?:\d[ -]*?){13,16}\b/,
  ssn: /\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b/,
  // Only treat CVV as sensitive when explicitly labeled.
  cvvLabeled: /\b(?:cvv|cvc)\s*[:#-]?\s*\d{3,4}\b/i,
};

const containsPII = (text) => {
  if (!text || typeof text !== 'string') return false;
  return Object.values(PII_PATTERNS).some((re) => re.test(text));
};

const Icons = {
  Menu: () => (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  ),
  Search: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
    </svg>
  ),
  Cart: () => (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z" />
    </svg>
  ),
  Bell: () => (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
    </svg>
  ),
  Send: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
    </svg>
  ),
  Mic: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
    </svg>
  ),
  Camera: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8a2 2 0 012-2h3l1-2h6l1 2h3a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V8z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 17a4 4 0 100-8 4 4 0 000 8z" />
    </svg>
  ),
  Close: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  ),
  Grid: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
    </svg>
  ),
  List: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  ),
  Compare: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 3H5a2 2 0 00-2 2v14a2 2 0 002 2h5V3zM19 3h-5v18h5a2 2 0 002-2V5a2 2 0 00-2-2z" />
    </svg>
  ),
  Gear: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11.983 13.983a2 2 0 110-3.966 2 2 0 010 3.966zM20 12a8.001 8.001 0 01-.6 3.03l2.01 1.55-2 3.464-2.41-1a8.04 8.04 0 01-2.43 1.41l-.37 2.6h-4l-.37-2.6A8.04 8.04 0 017.01 19.04l-2.41 1-2-3.465 2.01-1.55A8.001 8.001 0 014 12c0-1.06.21-2.07.6-3.03l-2.01-1.55 2-3.464 2.41 1A8.04 8.04 0 017.43 3.546l.37-2.6h4l.37 2.6A8.04 8.04 0 0116.99 4.96l2.41-1 2 3.465-2.01 1.55c.39.96.61 1.97.61 3.025z" />
    </svg>
  ),
  Check: () => (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  ),
  User: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
    </svg>
  ),
  Trash: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
    </svg>
  ),
  Shield: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    </svg>
  ),
  AlertTriangle: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
    </svg>
  ),
  Phone: () => (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
    </svg>
  ),
  Bot: () => (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
    </svg>
  ),
};

const FALLBACK_BASE = [
  {
    id: 'DEMO-BASE-1',
    name: 'ShopSquire Demo Laptop 14',
    price: 899,
    specs: '14-inch FHD display - 16GB RAM - 512GB SSD - Wi-Fi 6',
  },
  {
    id: 'DEMO-BASE-2',
    name: 'ShopSquire Demo Laptop 15 Pro',
    price: 1199,
    specs: '15.6-inch FHD display - 16GB RAM - 1TB SSD - RTX 4050',
  },
  {
    id: 'DEMO-BASE-3',
    name: 'ShopSquire Demo Laptop 13 Air',
    price: 999,
    specs: '13-inch WUXGA display - 16GB RAM - 512GB SSD - 12-hour battery',
  },
  {
    id: 'DEMO-BASE-4',
    name: 'ShopSquire Demo Creator 16',
    price: 1599,
    specs: '16-inch 2.5K display - 32GB RAM - 1TB SSD - RTX 4060',
  },
  {
    id: 'DEMO-BASE-5',
    name: 'ShopSquire Demo Workstation 17',
    price: 1899,
    specs: '17-inch UHD display - 32GB RAM - 2TB SSD - RTX 4070',
  },
  {
    id: 'DEMO-BASE-6',
    name: 'ShopSquire Demo Budget 15',
    price: 699,
    specs: '15.6-inch FHD display - 8GB RAM - 256GB SSD - Wi-Fi 6',
  },
];

const createImage = (name) =>
  `https://via.placeholder.com/300x200/2D3748/FFFFFF?text=${encodeURIComponent((name || 'Product').slice(0, 24))}`;

const formatPrice = (price) => {
  if (price === null || typeof price === 'undefined' || Number(price) <= 0) {
    return 'Price on request';
  }
  return `$${Number(price).toLocaleString()}`;
};

const splitSpecs = (specs) => {
  if (!specs) return [];
  if (Array.isArray(specs)) return specs.filter(Boolean);
  if (typeof specs === 'object') {
    return Object.values(specs).map((value) => String(value)).filter(Boolean);
  }
  return String(specs)
    .split(' - ')
    .map((item) => item.trim())
    .filter(Boolean);
};

const fillToMinimum = (items, minCount) => {
  const out = [...items];
  let idx = 1;
  while (out.length < minCount) {
    const base = FALLBACK_BASE[(idx - 1) % FALLBACK_BASE.length];
    out.push({
      ...base,
      id: `${base.id}-${idx}`,
      sku: `${base.id}-${idx}`,
      name: `${base.name} ${String(idx).padStart(2, '0')}`,
      price: base.price + (idx % 5) * 50,
      image: createImage(`${base.name} ${idx}`),
    });
    idx += 1;
  }
  return out;
};

const normalizeCatalog = (items) => {
  if (!Array.isArray(items)) return [];
  return items.map((item, idx) => ({
    id: item.sku || item.id || `SKU-${idx}`,
    sku: item.sku || item.id || `SKU-${idx}`,
    name: item.name || item.sku || `Product ${idx + 1}`,
    price: item.price || item.price_cents || null,
    specs: Array.isArray(item.features) ? item.features.join(' - ') : (item.specs || 'Specs on request'),
    image: createImage(item.name || item.sku || 'Product'),
  }));
};

const normalizeResults = (items) => {
  if (!Array.isArray(items)) return [];
  return items.map((item, idx) => {
    const name = item.name || item.sku || `Product ${idx + 1}`;
    return {
      id: item.id || item.sku || `result-${idx}`,
      sku: item.sku || item.id || `result-${idx}`,
      name,
      price: typeof item.price_cents === 'number' ? Math.round(item.price_cents) / 100 : (item.price || null),
      specs: typeof item.specs === 'string' ? item.specs : (item.specs ? Object.values(item.specs).join(', ') : 'Specs on request'),
      image: item.image || item.image_url || createImage(name),
      score: item.score,
      why_not: item.why_not,
    };
  });
};
const MobileMenu = ({ isOpen, onClose }) => {
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div className="fixed inset-0 bg-black bg-opacity-50" onClick={onClose}></div>
      <div className="fixed inset-y-0 left-0 w-64 bg-white shadow-xl">
        <div className="p-6">
          <div className="flex justify-between items-center mb-8">
            <h2 className="text-xl font-semibold">Menu</h2>
            <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded-lg">
              <Icons.Close />
            </button>
          </div>
          <nav style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <a href="#" className="block py-2 text-gray-700 hover:text-gray-900">Home</a>
            <a href="#" className="block py-2 text-gray-700 hover:text-gray-900">Shop by Category</a>
            <a href="#" className="block py-2 text-gray-700 hover:text-gray-900">My Orders</a>
            <a href="#" className="block py-2 text-gray-700 hover:text-gray-900">Live Chat</a>
            <a href="#" className="block py-2 text-gray-700 hover:text-gray-900">Help & FAQ</a>
            <a href="#" className="block py-2 text-gray-700 hover:text-gray-900">Settings</a>
            <div className="border-t pt-4 mt-4">
              <a href="#" className="block py-2 text-gray-700 hover:text-gray-900">Sign In</a>
            </div>
          </nav>
        </div>
      </div>
    </div>
  );
};

const ProductGrid = ({ products, viewMode, onAddToCart, onViewDetail, isLoading }) => {
  const items = Array.isArray(products) ? products : [];
  if (isLoading) {
    const skeletons = new Array(8).fill(0);
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
        {skeletons.map((_, idx) => (
          <div key={`sk-${idx}`} className="border border-gray-200 rounded-lg overflow-hidden">
            <div style={{ width: '100%', height: '120px', background: '#f3f4f6' }} />
            <div className="p-3">
              <div style={{ width: '80%', height: '14px', background: '#f3f4f6', borderRadius: '6px', marginBottom: '8px' }} />
              <div style={{ width: '60%', height: '12px', background: '#f3f4f6', borderRadius: '6px', marginBottom: '12px' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ width: '70px', height: '14px', background: '#f3f4f6', borderRadius: '6px' }} />
                <div style={{ display: 'flex', gap: '8px' }}>
                  <div style={{ width: '56px', height: '24px', background: '#f3f4f6', borderRadius: '6px' }} />
                  <div style={{ width: '56px', height: '24px', background: '#f3f4f6', borderRadius: '6px' }} />
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (!isLoading && viewMode !== 'compare' && items.length === 0) {
    return (
      <div className="text-sm text-gray-600">
        No results. Try adjusting budget or specs. If this seems wrong, open Decision Trace to review agent steps.
      </div>
    );
  }
  if (viewMode === 'compare') {
    const compareItems = items.slice(0, 3);
    return (
      <div className="flex flex-col gap-3">
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
            <h3 className="font-semibold text-gray-900">Comparison</h3>
            <small className="text-gray-500">Top {compareItems.length} matches</small>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th className="px-4 py-2 border-b">Product</th>
                  <th className="px-4 py-2 border-b">Price</th>
                  <th className="px-4 py-2 border-b">Key Specs</th>
                  <th className="px-4 py-2 border-b"></th>
                </tr>
              </thead>
              <tbody>
                {compareItems.map((product) => (
                  <tr key={product.id} className="border-b last:border-b-0">
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-900">{product.name}</div>
                    </td>
                    <td className="px-4 py-3">{formatPrice(product.price)}</td>
                    <td className="px-4 py-3 text-gray-600">{product.specs || 'Specs on request'}</td>
                    <td className="px-4 py-3 text-right">
                      <button onClick={() => onAddToCart(product)} className="px-3 py-2 bg-gray-900 text-white rounded-lg text-xs">
                        Add
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="border border-gray-200 rounded-lg p-4">
          <div className="font-semibold text-gray-900 mb-3">Comparison deep dive</div>
          <div className="flex flex-col gap-3">
            {compareItems.map((product) => (
              <div key={`deep-${product.id}`} className="border border-gray-200 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="font-semibold">{product.name}</div>
                  <div className="text-sm text-gray-600">{formatPrice(product.price)}</div>
                </div>
                <ul className="text-sm text-gray-600">
                  {splitSpecs(product.specs).slice(0, 6).map((spec, idx) => (
                    <li key={`${product.id}-spec-${idx}`}>- {spec}</li>
                  ))}
                </ul>
                <div className="mt-3 flex gap-2">
                  <button onClick={() => onViewDetail(product)} className="secondary">Details</button>
                  <button onClick={() => onAddToCart(product)} className="contrast">Add to cart</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }
  if (viewMode === 'list') {
    return (
      <div className="flex flex-col gap-3">
        {items.map((product) => (
          <div key={product.id} className="border border-gray-200 rounded-lg p-4">
            <div className="flex gap-4">
              <img
                src={product.image}
                alt={product.name}
                style={{ width: '72px', height: '72px', objectFit: 'cover', borderRadius: '10px', flex: '0 0 auto' }}
                onError={(e)=>{ e.currentTarget.src = createImage(product.name); }}
              />
              <div className="flex-1" style={{ minWidth: 0 }}>
                <h3 className="font-semibold text-gray-900 line-clamp-2">{product.name}</h3>
                <p className="text-sm text-gray-600 mt-1 line-clamp-2">{product.specs}</p>
                <div className="flex items-center justify-between mt-3">
                  <span className="text-lg font-semibold text-gray-900">{formatPrice(product.price)}</span>
                  <div className="flex gap-2">
                    <button onClick={() => onViewDetail(product)} className="secondary sm">Details</button>
                    <button onClick={() => onAddToCart(product)} className="contrast sm">Add</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
      {items.map((product) => (
        <div key={product.id} className="border border-gray-200 rounded-lg overflow-hidden">
          <img
            src={product.image}
            alt={product.name}
            className="panel-product-img"
            style={{ width: '100%', height: '120px', objectFit: 'contain', background: '#f9fafb', display: 'block' }}
            onError={(e)=>{ e.currentTarget.src = createImage(product.name); }}
          />
          <div className="p-3">
            <h3 className="font-semibold text-gray-900 mb-1 line-clamp-2">{product.name}</h3>
            <p className="text-sm text-gray-600 mb-3 line-clamp-2">{product.specs}</p>
            <div className="flex items-center justify-between">
              <span className="text-lg font-semibold text-gray-900">{formatPrice(product.price)}</span>
              <div className="flex gap-2">
                <button onClick={() => onViewDetail(product)} className="secondary sm">Details</button>
                <button onClick={() => onAddToCart(product)} className="contrast sm">Add</button>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};
const CheckoutSteps = ({ currentStep }) => {
  const steps = ['Cart', 'Shipping', 'Payment', 'Confirm'];
  return (
    <div className="checkout-steps">
      {steps.map((step, idx) => (
        <div
          key={step}
          className={`checkout-step ${idx < currentStep ? 'completed' : ''} ${idx === currentStep ? 'active' : ''}`}
        >
          <div className="step-number">{idx < currentStep ? <Icons.Check /> : idx + 1}</div>
          <div className="step-label">{step}</div>
        </div>
      ))}
    </div>
  );
};

const CVImageGallery = ({ images, onRemove }) => {
  if (!images || images.length === 0) return null;
  return (
    <div className="image-scroll" style={{ marginBottom: '16px' }}>
      {images.map((img, idx) => (
        <div key={idx} style={{ position: 'relative' }}>
          <img
            src={typeof img === 'string' ? img : URL.createObjectURL(img)}
            alt={`Upload ${idx + 1}`}
            className="cv-thumbnail"
          />
          {onRemove && (
            <button
              onClick={() => onRemove(idx)}
              style={{
                position: 'absolute',
                top: '-6px',
                right: '-6px',
                width: '20px',
                height: '20px',
                borderRadius: '50%',
                background: '#ef4444',
                color: 'white',
                border: 'none',
                padding: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
              }}
            >
              <Icons.Close />
            </button>
          )}
        </div>
      ))}
    </div>
  );
};

const buildIncidentPrefillMessage = (prefillContext) => {
  if (!prefillContext || typeof prefillContext !== 'object') return '';
  const lines = [];
  if (prefillContext.case_id) lines.push(`Case: ${prefillContext.case_id}`);
  if (prefillContext.trace_id) lines.push(`Trace: ${prefillContext.trace_id}`);
  if (prefillContext.decision_id) lines.push(`Decision: ${prefillContext.decision_id}`);
  if (prefillContext.severity) lines.push(`Severity: ${prefillContext.severity}`);
  if (Array.isArray(prefillContext.findings) && prefillContext.findings.length > 0) {
    lines.push(`Findings: ${prefillContext.findings.slice(0, 6).join(', ')}`);
  }
  if (prefillContext.reason) lines.push(`Reason: ${prefillContext.reason}`);
  if (lines.length === 0) return '';
  return `Auto-context for support:\n${lines.join('\n')}`;
};

const IncidentChatPanel = ({ incidentId, token, staffToken, prefillContext }) => {
  const [items, setItems] = useState([]);
  const [connected, setConnected] = useState(false);
  const [err, setErr] = useState(null);
  const [text, setText] = useState('');
  const [activeToken, setActiveToken] = useState(token || staffToken || null);
  const tokenAttemptedRef = useRef(false);
  const prefillSentRef = useRef(false);
  const endRef = useRef(null);

  const devMode = (() => {
    try {
      const qs = new URLSearchParams(window.location.search || '');
      if (qs.get('dev') === '1') return true;
      return localStorage.getItem('shopsquire_dev_mode') === '1';
    } catch (e) {
      return false;
    }
  })();

  const staffRoomLink = (() => {
    if (!devMode || !incidentId || !staffToken) return null;
    try {
      const base = String(API_BASE || '').split('/api/v1')[0].replace(/\/+$/, '');
      return `${base}/merchant/incident-room?incident_id=${encodeURIComponent(incidentId)}&token=${encodeURIComponent(staffToken)}`;
    } catch (e) {
      return null;
    }
  })();

  useEffect(() => {
    setActiveToken(token || staffToken || null);
    tokenAttemptedRef.current = false;
    prefillSentRef.current = false;
  }, [incidentId, token, staffToken]);

  useEffect(() => {
    if (!incidentId || activeToken || tokenAttemptedRef.current) return;
    tokenAttemptedRef.current = true;
    (async () => {
      try {
        const authKey = API_KEY || '';
        const res = await fetchWithTimeout(
          `${API_BASE}/admin/incidents/${encodeURIComponent(incidentId)}/room/token`,
          {
            method: 'POST',
            headers: { 'x-api-key': authKey },
          },
          6000
        );
        const body = await res.json().catch(() => ({}));
        const next = body?.staff_token || null;
        if (res.ok && next) {
          setActiveToken(next);
          return;
        }
        setErr('Unable to issue incident chat token. Please retry escalation.');
      } catch (e) {
        setErr('Unable to issue incident chat token. Please retry escalation.');
      }
    })();
  }, [incidentId, activeToken]);

  useEffect(() => {
    if (!incidentId || !activeToken) return;
    setItems([]);
    setErr(null);
    setConnected(false);

    const url = `${API_BASE}/incidents/${encodeURIComponent(incidentId)}/room/stream?token=${encodeURIComponent(activeToken)}`;
    const es = new EventSource(url);
    es.onopen = () => setConnected(true);
    es.onerror = () => {
      // Browser will auto-reconnect; keep UI calm.
      setConnected(false);
    };
    es.onmessage = (ev) => {
      try {
        const arr = JSON.parse(ev.data || '[]');
        if (!Array.isArray(arr)) return;
        setItems((prev) => {
          const next = [...prev];
          for (const rec of arr) {
            if (!rec || typeof rec !== 'object') continue;
            next.push(rec);
          }
          return next.slice(-200);
        });
      } catch (e) {
        // ignore
      }
    };
    return () => {
      try { es.close(); } catch (e) { /* ignore */ }
    };
  }, [incidentId, activeToken]);

  useEffect(() => {
    if (!incidentId || !activeToken || !prefillContext || prefillSentRef.current) return;
    const msg = buildIncidentPrefillMessage(prefillContext);
    if (!msg) return;
    const key = `shopsquire_incident_prefill:${incidentId}`;
    try {
      if (sessionStorage.getItem(key) === '1') {
        prefillSentRef.current = true;
        return;
      }
    } catch (e) {
      // ignore
    }
    (async () => {
      try {
        const res = await fetchWithTimeout(
          `${API_BASE}/incidents/${encodeURIComponent(incidentId)}/room/message`,
          {
            method: 'POST',
            headers: { 'content-type': 'application/json', 'x-incident-token': activeToken },
            body: JSON.stringify({ message: msg }),
          },
          6000
        );
        if (!res.ok) return;
        prefillSentRef.current = true;
        try { sessionStorage.setItem(key, '1'); } catch (e) { /* ignore */ }
      } catch (e) {
        // best-effort
      }
    })();
  }, [incidentId, activeToken, prefillContext]);

  useEffect(() => {
    try {
      if (endRef.current) endRef.current.scrollIntoView({ behavior: 'smooth' });
    } catch (e) {
      // ignore
    }
  }, [items.length]);

  const send = async () => {
    const msg = (text || '').trim();
    if (!msg) return;
    setText('');
    setErr(null);
    try {
      const res = await fetchWithTimeout(
        `${API_BASE}/incidents/${encodeURIComponent(incidentId)}/room/message`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json', 'x-incident-token': activeToken || '' },
          body: JSON.stringify({ message: msg }),
        },
        6000
      );
      if (!res.ok) throw new Error('send_failed');
    } catch (e) {
      setErr('Unable to send message. Please try again.');
    }
  };

  return (
    <div className="flex flex-col gap-3" style={{ height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
        <div>
          <div className="text-sm text-gray-700" style={{ fontWeight: 600 }}>Live support chat</div>
          <div className="text-xs text-gray-500">Incident: <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>{incidentId}</span></div>
        </div>
        <span className={`badge ${connected ? 'success' : 'warning'}`}>{connected ? 'Connected' : 'Reconnecting…'}</span>
      </div>

      {staffRoomLink && (
        <div style={{ padding: '10px 12px', border: '1px solid #fde68a', borderRadius: '12px', background: '#fffbeb', color: '#92400e' }}>
          <div style={{ fontWeight: 700, fontSize: '12px', marginBottom: '4px' }}>Demo (staff room link)</div>
          <div style={{ fontSize: '12px' }}>
            Open in the merchant window to reply in real time:
          </div>
          <div style={{ marginTop: '6px', display: 'flex', gap: '8px', alignItems: 'center' }}>
            <input readOnly value={staffRoomLink} style={{ flex: 1, padding: '8px 10px', borderRadius: '10px', border: '1px solid #fde68a', background: '#fff', color: '#111827' }} />
            <button
              className="secondary sm"
              onClick={() => {
                try {
                  navigator.clipboard.writeText(staffRoomLink);
                } catch (e) {
                  // ignore
                }
              }}
            >
              Copy
            </button>
          </div>
        </div>
      )}

      {prefillContext && (
        <div style={{ padding: '10px 12px', border: '1px solid #dbeafe', borderRadius: '12px', background: '#eff6ff', color: '#1e3a8a' }}>
          <div style={{ fontWeight: 700, fontSize: '12px', marginBottom: '4px' }}>Escalation context</div>
          <div style={{ fontSize: '12px', whiteSpace: 'pre-wrap' }}>{buildIncidentPrefillMessage(prefillContext) || 'Context attached.'}</div>
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', border: '1px solid #e5e7eb', borderRadius: '12px', padding: '12px', background: '#f9fafb' }}>
        {items.length === 0 && (
          <div className="text-sm text-gray-600">
            A human agent will join shortly. You can add extra details here (no payment details).
          </div>
        )}
        {items.map((rec, idx) => {
          const role = rec.role || 'system';
          const isBuyer = role === 'buyer';
          const ts = rec.ts ? new Date(rec.ts) : null;
          return (
            <div key={`m-${idx}`} style={{ display: 'flex', justifyContent: isBuyer ? 'flex-end' : 'flex-start', marginBottom: '8px' }}>
              <div style={{ maxWidth: '85%', padding: '10px 12px', borderRadius: '12px', border: '1px solid #e5e7eb', background: isBuyer ? '#111827' : '#fff', color: isBuyer ? '#fff' : '#111827' }}>
                <div style={{ fontSize: '11px', opacity: 0.75, marginBottom: '4px' }}>
                  {role}{ts ? ` • ${ts.toLocaleTimeString()}` : ''}
                </div>
                <div style={{ fontSize: '13px', whiteSpace: 'pre-wrap' }}>{String(rec.message || '')}</div>
              </div>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>

      {err && <div className="text-sm" style={{ color: '#dc2626' }}>{err}</div>}

      <div style={{ display: 'flex', gap: '8px' }}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') send(); }}
          placeholder="Type a message…"
          style={{ flex: 1, padding: '10px 12px', border: '1px solid #e5e7eb', borderRadius: '10px' }}
        />
        <button className="contrast" onClick={send} disabled={!text.trim()}>Send</button>
      </div>
    </div>
  );
};

const RightPanel = ({
  type,
  data,
  onClose,
  viewMode,
  viewModeReason,
  onViewModeChange,
  onAddToCart,
  onViewDetail,
  onCheckout,
  onApprovalAction,
  onEscalate,
  cvStatus,
  cvImages,
  uploadError,
  meta,
  onDemoTrace,
  checkoutStep,
  onCheckoutStepChange,
  shippingForm,
  onShippingChange,
  retentionConsent,
  onRetentionConsentChange,
  privacyPrefs,
  isLoading,
  uid,
}) => {
  if (!type) return null;

  const badgeLabel = viewMode === 'compare' ? 'Compare' : viewMode === 'list' ? 'Detailed' : 'Grid';
  const [upsells, setUpsells] = useState([]);
  const [upsellLoading, setUpsellLoading] = useState(false);
  const [upsellError, setUpsellError] = useState(null);
  const [upsellTraceId, setUpsellTraceId] = useState(null);
  const logUpsellInteraction = async (sku, action, extra = {}) => {
    try {
      if (!sku) return;
      await fetchWithTimeout(
        `${API_BASE}/recommend/interaction`,
        {
          method: 'POST',
          headers: { 'x-api-key': API_KEY, 'content-type': 'application/json' },
          body: JSON.stringify({
            uid: uid || 'guest_user',
            sku,
            action,
            surface: 'checkout_upsell',
            trace_id: upsellTraceId || undefined,
            context: extra || {},
          }),
        },
        4000
      );
    } catch (e) {
      return;
    }
  };
  const cartItemsKey = (() => {
    try {
      if (!(type === 'cart' && (checkoutStep || 0) === 0)) return '';
      const cartData = Array.isArray(data) ? { items: data } : (data || {});
      const cartItems = cartData.items || [];
      return cartItems
        .map((i) => i.sku || i.id || i.name || '')
        .filter(Boolean)
        .slice(0, 6)
        .join('|');
    } catch (e) {
      return '';
    }
  })();

  useEffect(() => {
    const isCart = type === 'cart' && (checkoutStep || 0) === 0;
    const cartData = Array.isArray(data) ? { items: data } : (data || {});
    const cartItems = cartData.items || [];
    if (!isCart || !cartItemsKey) {
      setUpsells([]);
      setUpsellTraceId(null);
      return;
    }

    let cancelled = false;
    (async () => {
      setUpsellLoading(true);
      setUpsellError(null);
      try {
        const skus = cartItems
          .map((i) => i.sku || i.id || i.name)
          .filter(Boolean)
          .slice(0, 8)
          .join(',');
        const url = `${API_BASE}/recommend/checkout_upsell?uid=${encodeURIComponent(uid || 'guest_user')}&cart_skus=${encodeURIComponent(skus)}&limit=4`;
        const res = await fetchWithTimeout(url, { headers: { 'x-api-key': API_KEY } }, 8000);
        if (!res.ok) throw new Error('upsell_fetch_failed');
        const payload = await res.json();
        const results = Array.isArray(payload.results) ? payload.results : [];
        const mapped = results.slice(0, 4).map((r) => ({
          id: r.id,
          sku: r.sku,
          name: r.name,
          price: r.price_cents ? Math.round(r.price_cents / 100) : r.price,
          image: r.image_url,
          specs: r.features || r.specs || [],
          tags: Array.isArray(r.tags) ? r.tags : [],
          reasons: Array.isArray(r.reasons) ? r.reasons : [],
          why: (Array.isArray(r.reasons) ? r.reasons : (r.factors?.positive || r.why || [])).slice(0, 3),
          lifecycle_segment: r.lifecycle_segment,
        }));
        if (cancelled) return;
        setUpsells(mapped);
        setUpsellTraceId(payload.trace_id || payload.decision_id || null);
      } catch (e) {
        if (!cancelled) setUpsellError('Upsell recommendations unavailable.');
      } finally {
        if (!cancelled) setUpsellLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [type, checkoutStep, cartItemsKey, uid]);

  return (
    <div style={{ borderLeft: '1px solid #e5e7eb', background: '#fff', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '1rem', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#fff', zIndex: 10 }}>
        <div className="flex items-center gap-2">
          <h2 className="font-semibold text-gray-900">
            {type === 'products' && 'Products'}
            {type === 'cart' && (checkoutStep === 0 ? 'Shopping Cart' : checkoutStep === 1 ? 'Shipping' : checkoutStep === 2 ? 'Payment' : 'Checkout')}
            {type === 'faq' && 'Help & FAQ'}
            {type === 'cv' && 'Complaint Analysis'}
            {type === 'product_detail' && 'Product Detail'}
            {type === 'checkout' && 'Order Confirmed'}
            {type === 'approval' && 'Human Review'}
            {type === 'incident_chat' && 'Support Chat'}
          </h2>
          {type === 'products' && Array.isArray(data) && (
            <span className="text-sm text-gray-500">({data.length})</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {type === 'products' && (
            <div style={{ display: 'flex', gap: '0.25rem', marginRight: '0.5rem', flexWrap: 'wrap' }}>
              <button onClick={() => onViewModeChange('grid', 'Manual view switch')} className={`panel-icon-btn ${viewMode === 'grid' ? 'contrast' : 'secondary'}`} title="Grid">
                <Icons.Grid />
              </button>
              <button onClick={() => onViewModeChange('list', 'Manual view switch')} className={`panel-icon-btn ${viewMode === 'list' ? 'contrast' : 'secondary'}`} title="Detailed list">
                <Icons.List />
              </button>
              <button onClick={() => onViewModeChange('compare', 'Manual compare mode')} className={`panel-icon-btn ${viewMode === 'compare' ? 'contrast' : 'secondary'}`} title="Compare">
                <Icons.Compare />
              </button>
            </div>
          )}
          {onDemoTrace && (
            <button className="secondary" onClick={onDemoTrace} title="Demo Trace + Playbook">
              Demo Trace
            </button>
          )}
          <button onClick={onClose} className="panel-icon-btn secondary" title="Close panel">
            <Icons.Close />
          </button>
        </div>
      </div>
      {type === 'products' && (meta?.view_reason || viewModeReason) && (
        <div style={{ padding: '0.5rem 1rem', borderBottom: '1px solid #e5e7eb', background: '#fbfbfb' }}>
          <small style={{ color: '#6b7280' }}>
            <span style={{ display: 'inline-block', padding: '2px 8px', border: '1px solid #e5e7eb', borderRadius: '999px', marginRight: '6px' }}>
              {badgeLabel}
            </span>
            {meta?.view_reason || viewModeReason}
          </small>
        </div>
      )}
      <div className="panel-scroll" style={{ padding: '1rem', flex: 1, minHeight: 0 }}>
        {type === 'products' && (
          <ProductGrid products={data} viewMode={viewMode} onAddToCart={onAddToCart} onViewDetail={onViewDetail} isLoading={!!isLoading} />
        )}
        {type === 'incident_chat' && (
          <IncidentChatPanel
            incidentId={data?.incident_id}
            token={data?.token}
            staffToken={data?.staff_token}
            prefillContext={data?.prefill_context || null}
          />
        )}
        {type === 'product_detail' && data && (
          <div className="flex flex-col gap-3">
            <button onClick={() => onViewDetail(null)} className="secondary">Back to results</button>
            <div className="border border-gray-200 rounded-lg overflow-hidden">
              <img
                src={data.image}
                alt={data.name}
                style={{ width: '100%', height: '160px', objectFit: 'contain', background: '#f9fafb', display: 'block' }}
                onError={(e)=>{ e.currentTarget.src = createImage(data.name); }}
              />
              <div className="p-4">
                <h3 className="text-xl font-semibold text-gray-900 mb-1">{data.name}</h3>
                <div className="text-gray-700 mb-3">{formatPrice(data.price)}</div>
                {data.availability && (
                  <div className="text-sm text-gray-600 mb-2">Availability: {data.availability}</div>
                )}
                {typeof data.stock === 'number' && (
                  <div className="text-sm text-gray-600 mb-3">Stock: {data.stock}</div>
                )}
                <div className="text-sm text-gray-600 mb-3">Specs</div>
                <ul className="text-sm text-gray-600" style={{ wordBreak: 'break-word' }}>
                  {splitSpecs(data.specs).map((spec, idx) => (
                    <li key={`detail-spec-${idx}`}>- {spec}</li>
                  ))}
                </ul>
                <div className="flex gap-2 mt-4">
                  <button onClick={() => onViewModeChange('compare', 'Compare this item with alternatives')} className="secondary">
                    Compare
                  </button>
                  <button onClick={() => onAddToCart(data)} className="contrast">Add to cart</button>
                </div>
              </div>
            </div>
          </div>
        )}
        {type === 'cart' && (
          <div className="flex flex-col gap-3">
            <CheckoutSteps currentStep={checkoutStep || 0} />
            {checkoutStep === 0 && (() => {
              const cartData = Array.isArray(data) ? { items: data } : (data || {});
              const cartItems = cartData.items || [];
              if (!cartItems.length) {
                return <div className="text-sm text-muted">Your cart is empty.</div>;
              }
              return (
                <>
                  {cartItems.map((item, index) => (
                    <div key={`${item.id}-${index}`} className="card">
                      <div className="card-body" style={{ padding: '12px' }}>
                        <div className="flex gap-3">
                          <img
                            src={item.image || createImage(item.name || item.sku)}
                            alt={item.name || item.sku}
                            style={{ width: '60px', height: '60px', borderRadius: '8px', objectFit: 'cover' }}
                          />
                          <div className="flex-1" style={{ minWidth: 0 }}>
                            <div className="font-medium text-sm line-clamp-2">{item.name || item.sku}</div>
                            <div className="text-muted text-xs mt-1">Qty: {item.quantity || 1}</div>
                          </div>
                          <div className="font-semibold">
                            {formatPrice(item.price ?? (item.price_cents ? Math.round(item.price_cents / 100) : null))}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}

                  <div className="divider" />
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ fontWeight: 800 }}>Recommended add-ons</div>
                    {upsellTraceId && (
                      <small className="mono" style={{ color: '#6b7280' }} title="Decision Trace ID">
                        {String(upsellTraceId).slice(0, 8)}…
                      </small>
                    )}
                  </div>
                  <div className="text-xs text-muted">
                    AI-generated, inventory-checked suggestions based on cart and sales trends.
                  </div>
                  {upsellLoading ? (
                    <div className="text-sm text-muted">Loading recommendations…</div>
                  ) : upsellError ? (
                    <div className="text-sm text-muted">{upsellError}</div>
                  ) : upsells.length === 0 ? (
                    <div className="text-sm text-muted">No upsell suggestions yet.</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      {upsells.map((u) => (
                        <div key={u.sku || u.id} className="card">
                          <div
                            className="card-body"
                            style={{ padding: '12px' }}
                            onMouseEnter={() => logUpsellInteraction(u.sku, 'hover', { lifecycle_segment: u.lifecycle_segment })}
                          >
                            <div style={{ display: 'flex', gap: '10px' }}>
                              <img
                                src={u.image || createImage(u.name || u.sku)}
                                alt={u.name || u.sku}
                                style={{ width: '56px', height: '56px', borderRadius: '8px', objectFit: 'cover', flex: '0 0 auto' }}
                              />
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontWeight: 700, fontSize: '13px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                  {u.name || u.sku}
                                </div>
                                <div className="text-muted text-xs" style={{ marginTop: '4px' }}>
                                  {u.sku}
                                </div>
                                {Array.isArray(u.why) && u.why.length > 0 && (
                                  <div style={{ marginTop: '6px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                    {u.why.slice(0, 2).map((w, idx) => (
                                      <span key={`${u.sku}-why-${idx}`} style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '999px', border: '1px solid #e5e7eb', background: '#fff' }}>
                                        {w}
                                      </span>
                                    ))}
                                  </div>
                                )}
                                {Array.isArray(u.tags) && u.tags.length > 0 && (
                                  <div style={{ marginTop: '6px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                    {u.tags.slice(0, 3).map((t, idx) => (
                                      <span key={`${u.sku}-tag-${idx}`} style={{ fontSize: '10px', padding: '2px 7px', borderRadius: '999px', border: '1px dashed #cbd5e1', color: '#334155', background: '#f8fafc' }}>
                                        {t}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
                                <div style={{ fontWeight: 800 }}>{formatPrice(u.price)}</div>
                                <button
                                  className="contrast sm"
                                  onClick={() => {
                                    logUpsellInteraction(u.sku, 'click', { lifecycle_segment: u.lifecycle_segment });
                                    logUpsellInteraction(u.sku, 'add_to_cart', { lifecycle_segment: u.lifecycle_segment });
                                    onAddToCart && onAddToCart(u);
                                  }}
                                  title="Add to cart"
                                >
                                  Add
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="divider" />
                  <div className="flex justify-between items-center">
                    <span className="text-muted">Subtotal</span>
                    <span className="font-semibold text-lg">
                      {cartData.subtotal_cents ? formatPrice(Math.round(cartData.subtotal_cents / 100)) : formatPrice(cartItems.reduce((sum, item) => sum + (Number(item.price) || 0) * (item.quantity || 1), 0))}
                    </span>
                  </div>
                  <button className="contrast w-full lg" onClick={() => onCheckoutStepChange && onCheckoutStepChange(1)}>
                    Proceed to Shipping
                  </button>
                </>
              );
            })()}
            {checkoutStep === 1 && (
              <div className="flex flex-col gap-4">
                <div className="text-lg font-semibold">Shipping Address</div>
                <div className="flex flex-col gap-3">
                  <input
                    type="text"
                    placeholder="Full Name"
                    value={shippingForm?.name || ''}
                    onChange={(e) => onShippingChange && onShippingChange({ ...shippingForm, name: e.target.value })}
                  />
                  <input
                    type="text"
                    placeholder="Street Address"
                    value={shippingForm?.street || ''}
                    onChange={(e) => onShippingChange && onShippingChange({ ...shippingForm, street: e.target.value })}
                  />
                  <div className="flex gap-3">
                    <input
                      type="text"
                      placeholder="City"
                      value={shippingForm?.city || ''}
                      onChange={(e) => onShippingChange && onShippingChange({ ...shippingForm, city: e.target.value })}
                      style={{ flex: 2 }}
                    />
                    <input
                      type="text"
                      placeholder="State"
                      value={shippingForm?.state || ''}
                      onChange={(e) => onShippingChange && onShippingChange({ ...shippingForm, state: e.target.value })}
                      style={{ flex: 1 }}
                    />
                  </div>
                  <input
                    type="text"
                    placeholder="ZIP Code"
                    value={shippingForm?.zip || ''}
                    onChange={(e) => onShippingChange && onShippingChange({ ...shippingForm, zip: e.target.value })}
                  />
                </div>
                <div className="flex gap-3 mt-2">
                  <button className="secondary flex-1" onClick={() => onCheckoutStepChange && onCheckoutStepChange(0)}>
                    Back
                  </button>
                  <button className="contrast flex-1" onClick={() => onCheckoutStepChange && onCheckoutStepChange(2)}>
                    Continue to Payment
                  </button>
                </div>
              </div>
            )}
            {checkoutStep === 2 && (
              <div className="flex flex-col gap-4">
                <div className="text-lg font-semibold">Payment</div>
                <div className="card">
                  <div className="card-body">
                    <div className="flex items-center gap-2 mb-3">
                      <Icons.Shield />
                      <span className="text-sm font-medium">Secure Payment via Stripe</span>
                    </div>
                    <div className="text-xs text-muted mb-4">
                      Your payment information is handled securely by Stripe. Our agents never have access to your card details (PCI-DSS compliant).
                    </div>
                    <div className="text-xs text-muted mb-4" style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '8px' }}>
                      AI notice: recommendations are data-informed, not guarantees. Personalization is {privacyPrefs?.personalization_opt_in ? 'enabled' : 'disabled'}.
                    </div>
                    <div className="border rounded-lg p-3 bg-subtle">
                      <div className="text-sm text-muted text-center">
                        Stripe Card Element would load here
                      </div>
                    </div>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '12px', fontSize: '12px', color: '#4b5563' }}>
                      <input
                        type="checkbox"
                        checked={!!retentionConsent}
                        onChange={(e) => onRetentionConsentChange && onRetentionConsentChange(e.target.checked)}
                      />
                      Keep my chat and support history beyond 2 hours to speed up support (optional).
                    </label>
                  </div>
                </div>
                <div className="flex gap-3 mt-2">
                  <button className="secondary flex-1" onClick={() => onCheckoutStepChange && onCheckoutStepChange(1)}>
                    Back
                  </button>
                  <button
                    className="contrast flex-1"
                    onClick={() => {
                      const cartData = Array.isArray(data) ? { items: data } : (data || {});
                      onCheckout && onCheckout(cartData);
                    }}
                  >
                    Place Order
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
        {type === 'faq' && (
          <div className="flex flex-col gap-3 text-sm text-gray-600">
            <div className="font-semibold text-gray-900">Quick help</div>
            <div>Ask for product recommendations, compare models, or submit a CV complaint with photos.</div>
            <div>Try: "Compare laptops with 16GB RAM", "Show me gaming laptops under $2000".</div>
            <button className="secondary">Contact Support</button>
          </div>
        )}
        {type === 'cv' && (
          <div className="flex flex-col gap-4">
            {cvImages && cvImages.length > 0 && (
              <div>
                <div className="text-sm font-medium text-gray-700 mb-2">Uploaded Images</div>
                <CVImageGallery images={cvImages} />
              </div>
            )}
            <div className="card">
              <div className="card-header" style={{ padding: '12px 16px' }}>
                <div className="flex items-center justify-between">
                  <div className="font-semibold text-gray-900">Agent Verdict</div>
                  <div className="status-indicator">
                    <span className={`status-dot ${cvStatus?.state || 'processing'}`}></span>
                    <span>
                      {cvStatus?.state === 'processing' && 'Analyzing'}
                      {cvStatus?.state === 'complete' && 'Complete'}
                      {cvStatus?.state === 'error' && 'Error'}
                      {!cvStatus?.state && 'Pending'}
                    </span>
                  </div>
                </div>
              </div>
              <div className="card-body">
                <div className="flex flex-col gap-3">
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">Case ID</span>
                    <span className="mono text-sm">{cvStatus?.caseId || 'pending'}</span>
                  </div>
                  {cvStatus?.decision && (
                    <div className="flex justify-between items-center">
                      <span className="text-sm text-gray-600">Decision</span>
                      <span className={`badge ${cvStatus.decision.includes('APPROVED') ? 'success' : cvStatus.decision.includes('DENIED') || cvStatus.decision.includes('FRAUD') ? 'danger' : 'warning'}`}>
                        {cvStatus.decision}
                      </span>
                    </div>
                  )}
                  {typeof cvStatus?.confidence !== 'undefined' && (
                    <div className="flex justify-between items-center">
                      <span className="text-sm text-gray-600">Confidence</span>
                      <span className="text-sm font-medium">{(cvStatus.confidence * 100).toFixed(0)}%</span>
                    </div>
                  )}
                  {cvStatus?.severity && (
                    <div className="flex justify-between items-center">
                      <span className="text-sm text-gray-600">Severity</span>
                      <span className={`badge ${cvStatus.severity === 'high' ? 'danger' : cvStatus.severity === 'medium' ? 'warning' : 'info'}`}>
                        {cvStatus.severity}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>
            {cvStatus?.policyApplied && (
              <div className="card">
                <div className="card-body">
                  <div className="text-sm font-medium text-gray-700 mb-2">Policy Applied</div>
                  <div className="text-sm text-gray-600">{cvStatus.policyApplied}</div>
                </div>
              </div>
            )}
            {cvStatus?.fraudSignals && cvStatus.fraudSignals.length > 0 && (
              <div className="card" style={{ borderColor: '#fecaca' }}>
                <div className="card-body">
                  <div className="flex items-center gap-2 mb-2">
                    <Icons.AlertTriangle />
                    <span className="text-sm font-medium text-danger">Fraud Signals Detected</span>
                  </div>
                  <ul className="text-sm text-gray-600" style={{ margin: 0, paddingLeft: '16px' }}>
                    {cvStatus.fraudSignals.map((signal, idx) => (
                      <li key={idx}>{signal}</li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
            {cvStatus?.message && (
              <div className="text-sm text-danger">{cvStatus.message}</div>
            )}
            {uploadError && (
              <div className="text-sm text-danger">{uploadError}</div>
            )}
            <div className="divider" />
            <button
              className="secondary w-full"
              disabled={cvStatus?.state === 'processing'}
              onClick={() => onEscalate && onEscalate(cvStatus?.caseId || cvStatus?.traceId || null)}
            >
              <Icons.Phone />
              Escalate to Human Agent
            </button>
            <div className="text-xs text-muted text-center">
              If you believe this verdict is incorrect, request human review.
            </div>
          </div>
        )}
        {type === 'checkout' && (
          <div className="flex flex-col gap-4">
            <CheckoutSteps currentStep={3} />
            {data?.order_id ? (
              <div className="card">
                <div className="card-body text-center" style={{ padding: '32px 24px' }}>
                  <div style={{ width: '64px', height: '64px', borderRadius: '50%', background: '#d1fae5', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px' }}>
                    <Icons.Check />
                  </div>
                  <div className="text-xl font-semibold mb-2">Order Confirmed</div>
                  <div className="text-muted mb-4">Thank you for your purchase!</div>
                  <div className="divider" />
                  <div className="flex flex-col gap-2 text-left">
                    <div className="flex justify-between">
                      <span className="text-muted text-sm">Order ID</span>
                      <span className="mono text-sm">{data.order_id}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted text-sm">Status</span>
                      <span className="badge success">{data.status || 'created'}</span>
                    </div>
                    {data.total_cents && (
                      <div className="flex justify-between">
                        <span className="text-muted text-sm">Total</span>
                        <span className="font-semibold">{formatPrice(Math.round(data.total_cents / 100))}</span>
                      </div>
                    )}
                  </div>
                  <div className="divider" />
                  <div className="text-xs text-muted">
                    A confirmation email has been sent to your registered email address.
                  </div>
                </div>
              </div>
            ) : data?.status === 'failed' ? (
              <div className="card" style={{ borderColor: '#fecaca' }}>
                <div className="card-body text-center">
                  <div style={{ width: '64px', height: '64px', borderRadius: '50%', background: '#fee2e2', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px' }}>
                    <Icons.AlertTriangle />
                  </div>
                  <div className="text-lg font-semibold text-danger mb-2">Payment Failed</div>
                  <div className="text-muted text-sm">There was an issue processing your payment. Please try again.</div>
                  <button className="contrast mt-4" onClick={() => onCheckoutStepChange && onCheckoutStepChange(2)}>
                    Try Again
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-muted text-center">Processing your order...</div>
            )}
            <button className="secondary w-full" onClick={onClose}>
              Continue Shopping
            </button>
          </div>
        )}
        {type === 'approval' && (
          <div className="flex flex-col gap-3">
            <div className="font-semibold text-gray-900">Human review pending</div>
            <div className="text-sm text-gray-600">Approval ID: <span className="mono">{data?.approval_id}</span></div>
            <div className="text-sm text-gray-600">Reason: {data?.reason || 'security_review'}</div>
            {data?.ticket_id && (
              <div className="text-sm text-gray-600">Ticket: <span className="mono">{data.ticket_id}</span></div>
            )}
            {data?.ticket_url && (
              <div className="text-sm text-gray-600">
                <a href={data.ticket_url} target="_blank" rel="noreferrer">Open ticket</a>
              </div>
            )}
            <div className="flex gap-2">
              <button className="secondary" onClick={() => onApprovalAction && onApprovalAction(data?.approval_id, 'approve')}>Approve</button>
              <button className="secondary" onClick={() => onApprovalAction && onApprovalAction(data?.approval_id, 'reject')}>Reject</button>
            </div>
            <div className="text-sm text-gray-600">
              <a href={`${window.location.origin}/ui/status`} target="_blank" rel="noreferrer">Open Live Ops</a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const OpsOverlay = ({ open, onClose }) => {
  const overlayRef = useRef(null);
  const headerRef = useRef(null);
  useEffect(() => {
    if (!open) return;
    const el = overlayRef.current;
    const hdr = headerRef.current;
    if (!el || !hdr) return;
    let dragging = false;
    let startX = 0;
    let startY = 0;
    let originX = 0;
    let originY = 0;
    const onMouseDown = (event) => {
      dragging = true;
      startX = event.clientX;
      startY = event.clientY;
      const rect = el.getBoundingClientRect();
      originX = rect.left;
      originY = rect.top;
      event.preventDefault();
    };
    const onMouseMove = (event) => {
      if (!dragging) return;
      const dx = event.clientX - startX;
      const dy = event.clientY - startY;
      el.style.left = `${originX + dx}px`;
      el.style.top = `${originY + dy}px`;
    };
    const onMouseUp = () => {
      dragging = false;
    };
    hdr.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      hdr.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [open]);
  if (!open) return null;
  return (
    <div ref={overlayRef} style={{ position: 'fixed', right: '24px', bottom: '80px', width: '800px', height: '500px', background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', boxShadow: '0 6px 24px rgba(0,0,0,0.15)', zIndex: 50 }}>
      <div ref={headerRef} style={{ padding: '8px 12px', background: '#15171b', color: '#fff', borderTopLeftRadius: '8px', borderTopRightRadius: '8px', cursor: 'move', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong>Live Ops</strong>
        <button className="secondary" onClick={onClose}>Close</button>
      </div>
      <iframe title="Live Ops" src={`${window.location.origin}/ui/status`} style={{ width: '100%', height: 'calc(100% - 40px)', border: '0' }} />
    </div>
  );
};

const ChatOverlay = ({ open, onClose, onOpenTrace, children }) => {
  const overlayRef = useRef(null);
  const headerRef = useRef(null);
  useEffect(() => {
    if (!open) return;
    const el = overlayRef.current;
    const hdr = headerRef.current;
    if (!el || !hdr) return;
    let dragging = false;
    let startX = 0;
    let startY = 0;
    let originX = 0;
    let originY = 0;
    const onMouseDown = (event) => {
      dragging = true;
      startX = event.clientX;
      startY = event.clientY;
      const rect = el.getBoundingClientRect();
      originX = rect.left;
      originY = rect.top;
      event.preventDefault();
    };
    const onMouseMove = (event) => {
      if (!dragging) return;
      const dx = event.clientX - startX;
      const dy = event.clientY - startY;
      el.style.left = `${originX + dx}px`;
      el.style.top = `${originY + dy}px`;
    };
    const onMouseUp = () => {
      dragging = false;
    };
    hdr.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      hdr.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [open]);
  if (!open) return null;
  return (
    <div
      ref={overlayRef}
      style={{
        position: 'fixed',
        right: '8vw',
        bottom: '8vh',
        width: '70vw',
        height: '78vh',
        background: '#fff',
        border: '1px solid #e5e7eb',
        borderRadius: '12px',
        boxShadow: '0 10px 28px rgba(0,0,0,0.18)',
        zIndex: 70,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        ref={headerRef}
        style={{
          padding: '10px 12px',
          background: '#111827',
          color: '#fff',
          borderTopLeftRadius: '12px',
          borderTopRightRadius: '12px',
          cursor: 'move',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <strong>ShopSquire Assistant</strong>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button className="secondary" onClick={onOpenTrace} title="Decision & Security Trace">
            <Icons.Gear />
          </button>
          <button className="secondary" onClick={onClose}>Close</button>
        </div>
      </div>
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>{children}</div>
    </div>
  );
};

const DevTracePanelLegacy = ({ open, onClose, trace, traceLog = [], expandedId = null, onToggle }) => {
  if (!open) return null;
  const panelRef = useRef(null);
  const headerRef = useRef(null);
  const [showPlaybook, setShowPlaybook] = useState(false);
  const [showSecurity, setShowSecurity] = useState(false);
  const [showModel, setShowModel] = useState(false);
  const [showPolicyNotes, setShowPolicyNotes] = useState(false);
  const [showQueueOnly, setShowQueueOnly] = useState(false);
  const decisionTrace = useDecisionTrace();
  useEffect(() => {
    if (!open) return;
    const id = trace?.trace_id || trace?.decision_id;
    if (!id) return;
    decisionTrace.subscribe(id);
    return () => decisionTrace.unsubscribe();
  }, [open, trace?.trace_id, trace?.decision_id]);
  useEffect(() => {
    const el = panelRef.current;
    const hdr = headerRef.current;
    if (!open || !el || !hdr) return;
    let dragging = false;
    let startX = 0;
    let startY = 0;
    let originX = 0;
    let originY = 0;
    const onMouseDown = (event) => {
      dragging = true;
      startX = event.clientX;
      startY = event.clientY;
      const rect = el.getBoundingClientRect();
      originX = rect.left;
      originY = rect.top;
      el.style.right = 'auto';
      event.preventDefault();
    };
    const onMouseMove = (event) => {
      if (!dragging) return;
      const dx = event.clientX - startX;
      const dy = event.clientY - startY;
      el.style.left = `${originX + dx}px`;
      el.style.top = `${originY + dy}px`;
    };
    const onMouseUp = () => {
      dragging = false;
    };
    hdr.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      hdr.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [open]);
  const sec = trace?.security || {};
  const mitre = Array.isArray(sec.mitre) ? sec.mitre.join(', ') : Array.isArray(sec.mitre_atlas) ? sec.mitre_atlas.join(', ') : '';
  const owasp = Array.isArray(sec.owasp) ? sec.owasp.join(', ') : Array.isArray(sec.owasp_llm_top10) ? sec.owasp_llm_top10.join(', ') : '';
  const dread = typeof sec.dread !== 'undefined' ? JSON.stringify(sec.dread) : '';
  const kev = typeof sec.kev !== 'undefined' ? JSON.stringify(sec.kev) : '';
  const cvss = typeof sec.cvss !== 'undefined' ? JSON.stringify(sec.cvss) : '';
  const pasta = typeof sec.pasta !== 'undefined' ? JSON.stringify(sec.pasta) : '';
  const intent = trace?.intent_analysis || trace?.intent || {};
  const evidence = trace?.rag_context || trace?.retrieved_context || {};
  const policyGates = trace?.policy_gates || trace?.policy || {};
  const modelInfo = trace?.llm || trace?.model || trace?.model_info || trace?.model_selection || {};
  const agentChain = Array.isArray(trace?.agent_chain) ? trace.agent_chain : [];
  const policyNotes = trace?.policy_notes || trace?.retrieved_context?.policy_notes || {};
  const retentionPolicy = policyNotes?.retention_policy || trace?.retrieved_context?.retention_policy || null;
  const complianceTags = Array.isArray(sec.compliance) ? sec.compliance : (sec.compliance_tags || []);
  const policyCompliance = Array.isArray(policyNotes?.compliance_tags) ? policyNotes.compliance_tags : [];
  const allCompliance = [...new Set([...(complianceTags || []), ...(policyCompliance || [])])];
  const playbook = trace?.playbook || trace?.evidence?.playbook || trace?.retrieved_context?.playbook || null;
  const raw = JSON.stringify(trace || {}, null, 2);
  const summarizeTraceItem = (item) => {
    const payload = item?.payload || {};
    if (payload.summary) return payload.summary;
    if (item.event_type === 'security_watch') return 'Safety check: potential sensitive info detected.';
    if (item.event_type === 'policy_gate') {
      const decision = payload?.decision || payload?.policy_gate?.decision || 'checked';
      return `Policy gate: ${decision}`;
    }
    if (item.event_type === 'model_selection') return 'Model routing updated.';
    if (item.event_type === 'next_questions') return 'Asked clarifying questions.';
    if (item.event_type === 'human_escalation') return 'Human review requested.';
    if (item.event_type === 'agent_handoff') return 'Agent handoff recorded.';
    if (item.status === 'review_required') return 'Human review required.';
    if (item.query) return `User request: ${String(item.query).slice(0, 80)}`;
    return 'Trace event recorded.';
  };
  const renderTraceDetails = (item) => {
    if (!item) return null;
    const payload = item.payload || {};
    const security = item.security || payload.security || {};
    const policy = payload.policy_gate || payload.policy || {};
    const decision = payload.decision || policy.decision || item.status;
    const intents = Array.isArray(payload.intent_chain) ? payload.intent_chain : [];
    const slots = payload.slots || payload.constraints || null;
    const signals = security.signals || {};
    const signalList = Object.entries(signals).filter(([, v]) => Boolean(v)).map(([k]) => k);
    const mitreTags = Array.isArray(security.mitre) ? security.mitre : [];
    const owaspTags = Array.isArray(security.owasp) ? security.owasp : [];
    const complianceTagsLocal = Array.isArray(security.compliance) ? security.compliance : [];
    const evidenceTags = [
      ...mitreTags.map((t) => `MITRE ${t}`),
      ...owaspTags.map((t) => `OWASP ${t}`),
      ...complianceTagsLocal.map((t) => `Compliance ${t}`),
    ];

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: '#111827' }}>
        {item.query && (
          <div>
            <strong>User request:</strong> {item.query}
          </div>
        )}
        {decision && (
          <div>
            <strong>Decision:</strong> {decision}
          </div>
        )}
        {item.error && (
          <div>
            <strong>Error:</strong> {item.error}
          </div>
        )}
        {payload.reason && (
          <div>
            <strong>Reason:</strong> {payload.reason}
          </div>
        )}
        {security.severity && (
          <div>
            <strong>Security severity:</strong> {security.severity}
          </div>
        )}
        {signalList.length > 0 && (
          <div>
            <strong>Signals:</strong> {signalList.join(', ')}
          </div>
        )}
        {intents.length > 0 && (
          <div>
            <strong>Intents:</strong> {intents.map((i) => `${i.intent || i.name} (${Math.round((i.confidence || 0) * 100)}%)`).join(', ')}
          </div>
        )}
        {slots && (
          <div>
            <strong>Constraints:</strong> {Object.entries(slots).map(([k, v]) => `${k}=${String(v)}`).join(', ')}
          </div>
        )}
        {evidenceTags.length > 0 && (
          <div>
            <strong>Tags:</strong> {evidenceTags.join(', ')}
          </div>
        )}
        {payload.summary && (
          <div>
            <strong>Summary:</strong> {payload.summary}
          </div>
        )}
      </div>
    );
  };
  const latestPolicyGate = (() => {
    if (Array.isArray(traceLog)) {
      const match = traceLog.find((item) => item.event_type === 'policy_gate');
      if (match) return match;
    }
    return null;
  })();
  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(raw);
    } catch (err) {
      return;
    }
  };
  return (
    <div ref={panelRef} style={{ position: 'fixed', right: '16px', top: '64px', width: '420px', maxHeight: '70vh', overflow: 'auto', background: '#fff', border: '1px solid #e5e7eb', borderRadius: '10px', boxShadow: '0 6px 24px rgba(0,0,0,0.15)', zIndex: 90 }}>
      <div ref={headerRef} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', borderBottom: '1px solid #e5e7eb', cursor: 'move' }}>
        <strong>Decision & Security Trace</strong>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="secondary" onClick={copyJson}>Copy JSON</button>
          <button className="secondary" onClick={onClose}>Close</button>
        </div>
      </div>
      <div style={{ padding: '12px' }}>
        {/* Live timeline */}
        <div style={{ marginBottom: '12px' }}>
          <div style={{ fontWeight: 600, marginBottom: '6px' }}>Live Timeline</div>
          {showQueueOnly ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {(!decisionTrace.filtered || decisionTrace.filtered.length === 0) ? (
                <small style={{ color: '#6b7280' }}>No queued events yet.</small>
              ) : (
                [...decisionTrace.filtered].reverse().map((item) => (
                  <div key={`qe-${item.id}`} style={{ borderLeft: '3px solid #7c3aed', paddingLeft: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <div style={{ fontWeight: 600, fontSize: '12px' }}>{item.type}</div>
                      <small>{new Date(item.time || Date.now()).toLocaleTimeString()}</small>
                    </div>
                    <div style={{ fontSize: '11px', color: '#6b7280' }}>
                      {(item.source || 'source')} → {(item.target || 'job')}
                    </div>
                    <div style={{ fontSize: '12px' }}>{String(item.payload?.job_id || '').slice(0, 24)}</div>
                  </div>
                ))
              )}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {(() => {
                const mappedHook = (Array.isArray(decisionTrace.events) ? decisionTrace.events : []).map((i) => ({
                  id: i.id,
                  time: i.time,
                  query: i.payload?.query || i.payload?.message || 'Trace event',
                  status: i.type || 'event',
                  event_type: i.type,
                  source_id: i.source,
                  target_id: i.target,
                  decision_id: i.trace_id,
                  trace_id: i.trace_id,
                  payload: i.payload || {},
                }));
                const base = Array.isArray(traceLog) ? traceLog : [];
                const combined = [...base, ...mappedHook];
                if (combined.length === 0) {
                  return <small style={{ color: '#6b7280' }}>No trace events yet.</small>;
                }
                return [...combined].reverse().slice(0, 25).map((item) => (
                <div key={`tl-${item.id}`} style={{ borderLeft: '3px solid #111827', paddingLeft: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <div style={{ fontWeight: 600, fontSize: '12px' }}>{item.status || item.event_type || 'event'}</div>
                    <small>{new Date(item.time || Date.now()).toLocaleTimeString()}</small>
                  </div>
                  <div style={{ fontSize: '11px', color: '#6b7280' }}>
                    {(item.source_id || 'source')} to {(item.target_id || 'target')}
                  </div>
                  <div style={{ fontSize: '12px' }}>{summarizeTraceItem(item)}</div>
                </div>
                ));
              })()}
            </div>
          )}
          <div style={{ marginTop: '6px' }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#4b5563' }}>
              <input type="checkbox" checked={showQueueOnly} onChange={(e) => setShowQueueOnly(e.target.checked)} />
              Show only queued job events (cv/fraud)
            </label>
          </div>
        </div>
        {/* Rolling trace log (most recent first) */}
        <div style={{ marginBottom: '12px' }}>
          <div style={{ fontWeight: 600, marginBottom: '6px' }}>Trace Log</div>
          {(!traceLog || traceLog.length === 0) ? (
            <small style={{ color: '#6b7280' }}>No trace events yet.</small>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {traceLog.map((item) => (
                <div key={item.id} style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <div style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                      {summarizeTraceItem(item)}
                      {(item.event_type === 'policy_gate' || item.payload?.decision || item.payload?.policy_gate?.decision) && (
                        <span style={{ fontSize: '10px', padding: '2px 6px', borderRadius: '999px', background: '#eef2ff', color: '#4338ca', fontWeight: 600 }}>
                          Policy Gate
                        </span>
                      )}
                    </div>
                    <small>{new Date(item.time || Date.now()).toLocaleTimeString()}</small>
                  </div>
                  <div style={{ fontSize: '12px', color: '#6b7280' }}>{item.status} - {item.decision_id || item.trace_id}</div>
                  <button className="secondary sm" onClick={() => onToggle && onToggle(item.id)} style={{ marginTop: '6px' }}>
                    {expandedId === item.id ? 'Hide details' : 'Show details'}
                  </button>
                  {expandedId === item.id && (
                    <div style={{ marginTop: '8px' }}>
                      {renderTraceDetails(item)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
{!trace ? (
          <small style={{ color: '#6b7280' }}>No trace yet. Ask a question to populate.</small>
        ) : (
          <div className="flex flex-col gap-2">
            {trace.status === 'offline' && (
              <div style={{ padding: '8px', border: '1px solid #e5e7eb', borderRadius: '8px', background: '#fef3c7', color: '#92400e' }}>
                Trace unavailable: recommendation service not reachable. Check API host.
              </div>
            )}
            {trace.decision_id && <div><small>Decision:</small> <span className="mono">{trace.decision_id}</span></div>}
            {trace.policy_version && <div><small>Policy:</small> <span>{trace.policy_version}</span></div>}
            {trace.trace_id && <div><small>Trace:</small> <span className="mono">{trace.trace_id}</span></div>}
            {typeof trace.risk_score !== 'undefined' && <div><small>Risk Score:</small> <span>{String(trace.risk_score)}</span></div>}
            {trace.approval_id && <div><small>Approval:</small> <span className="mono">{trace.approval_id}</span></div>}
            {trace.severity && <div><small>Severity:</small> <span>{trace.severity}</span></div>}
            {(modelInfo.model || modelInfo.name || trace?.llm_model || trace?.model_name || trace?.model_tier || trace?.complexity || trace?.complexity_signals) && (
              <div style={{ marginTop: '6px', padding: '8px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ fontWeight: 600 }}>Model Routing</div>
                  <button className="secondary sm" onClick={() => setShowModel(!showModel)}>
                    {showModel ? 'Hide Model' : 'Show Model'}
                  </button>
                </div>
                {showModel && (
                  <div style={{ marginTop: '6px' }}>
                    {modelInfo.model && <div><small>Model:</small> <span>{modelInfo.model}</span></div>}
                    {modelInfo.name && <div><small>Model:</small> <span>{modelInfo.name}</span></div>}
                    {trace?.llm_model && <div><small>Model:</small> <span>{trace.llm_model}</span></div>}
                    {trace?.model_name && <div><small>Model:</small> <span>{trace.model_name}</span></div>}
                    {trace?.model_tier && <div><small>Tier:</small> <span>{trace.model_tier}</span></div>}
                    {trace?.complexity && <div><small>Complexity:</small> <span>{String(trace.complexity)}</span></div>}
                    {trace?.complexity_signals && (
                      <div><small>Signals:</small> <span className="mono">{JSON.stringify(trace.complexity_signals)}</span></div>
                    )}
                  </div>
                )}
              </div>
            )}
            {Object.keys(intent || {}).length > 0 && (
              <div style={{ marginTop: '6px', padding: '8px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
                <div style={{ fontWeight: 600, marginBottom: '4px' }}>Intent</div>
                <pre style={{ margin: 0, fontSize: '11px', color: '#4b5563', whiteSpace: 'pre-wrap' }}>{JSON.stringify(intent, null, 2)}</pre>
              </div>
            )}
            {agentChain.length > 0 && (
              <div style={{ marginTop: '6px', padding: '8px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
                <div style={{ fontWeight: 600, marginBottom: '4px' }}>Agent Chain</div>
                <table style={{ width: '100%', fontSize: '11px' }}>
                  <thead>
                    <tr style={{ textAlign: 'left', color: '#6b7280' }}>
                      <th style={{ padding: '4px 0' }}>Agent</th>
                      <th style={{ padding: '4px 0' }}>Confidence</th>
                      <th style={{ padding: '4px 0' }}>ms</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agentChain.map((agent, idx) => (
                      <tr key={`${agent.agent || agent.name}-${idx}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                        <td style={{ padding: '4px 0' }}>{agent.agent || agent.name || `Agent ${idx + 1}`}</td>
                        <td style={{ padding: '4px 0' }}>{typeof agent.confidence !== 'undefined' ? String(agent.confidence) : '-'}</td>
                        <td style={{ padding: '4px 0' }}>{typeof agent.duration_ms !== 'undefined' ? String(agent.duration_ms) : '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {Object.keys(evidence || {}).length > 0 && (
              <div style={{ marginTop: '6px', padding: '8px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
                <div style={{ fontWeight: 600, marginBottom: '4px' }}>Evidence</div>
                <pre style={{ margin: 0, fontSize: '11px', color: '#4b5563', whiteSpace: 'pre-wrap' }}>{JSON.stringify(evidence, null, 2)}</pre>
              </div>
            )}
            {Object.keys(policyGates || {}).length > 0 && (
              <div style={{ marginTop: '6px', padding: '8px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
                <div style={{ fontWeight: 600, marginBottom: '4px' }}>Policy Gates</div>
                <pre style={{ margin: 0, fontSize: '11px', color: '#4b5563', whiteSpace: 'pre-wrap' }}>{JSON.stringify(policyGates, null, 2)}</pre>
              </div>
            )}
            {latestPolicyGate && (
              <div style={{ marginTop: '6px', padding: '8px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
                <div style={{ fontWeight: 600, marginBottom: '4px' }}>Policy Gate (Latest)</div>
                <div><small>Decision:</small> <span>{latestPolicyGate.payload?.decision || latestPolicyGate.payload?.policy_gate?.decision || 'unknown'}</span></div>
                {Array.isArray(latestPolicyGate.payload?.reasons) && (
                  <div style={{ marginTop: '4px' }}>
                    <small>Reasons:</small>
                    <ul style={{ margin: '4px 0 0 16px', fontSize: '11px', color: '#4b5563' }}>
                      {latestPolicyGate.payload.reasons.map((r, idx) => (
                        <li key={`pg-reason-${idx}`}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {latestPolicyGate.payload?.rule_hits && (
                  <div style={{ marginTop: '4px' }}>
                    <small>Rule hits:</small> <span className="mono">{JSON.stringify(latestPolicyGate.payload.rule_hits)}</span>
                  </div>
                )}
              </div>
            )}
            {playbook && (
              <div style={{ marginTop: '6px', padding: '8px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ fontWeight: 600 }}>Playbook</div>
                  <button className="secondary sm" onClick={() => setShowPlaybook(!showPlaybook)}>
                    {showPlaybook ? 'Hide Playbook' : 'Show Playbook'}
                  </button>
                </div>
                {showPlaybook && (
                <div>
                <div><small>ID:</small> <span className="mono">{playbook.id || playbook.playbook_id || 'unknown'}</span></div>
                {playbook.title && <div><small>Title:</small> <span>{playbook.title}</span></div>}
                {playbook.severity && <div><small>Severity:</small> <span>{playbook.severity}</span></div>}
                {Array.isArray(playbook.actions) && playbook.actions.length > 0 && (
                  <div style={{ marginTop: '6px' }}>
                    <div style={{ fontWeight: 600, marginBottom: '4px', fontSize: '12px' }}>Actions</div>
                    <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '11px', color: '#4b5563' }}>
                      {playbook.actions.map((item, idx) => (
                        <li key={`pb-action-${idx}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                </div>
                )}
              </div>
            )}
            {(policyNotes && Object.keys(policyNotes).length > 0) && (
              <div style={{ marginTop: '6px', padding: '8px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ fontWeight: 600 }}>Policy Notes</div>
                  <button className="secondary sm" onClick={() => setShowPolicyNotes(!showPolicyNotes)}>
                    {showPolicyNotes ? 'Hide Notes' : 'Show Notes'}
                  </button>
                </div>
                {showPolicyNotes && (
                  <div style={{ marginTop: '6px', fontSize: '11px', color: '#4b5563' }}>
                    {policyNotes.no_training_on_pii !== undefined && (
                      <div><small>No training on PII:</small> <span>{String(policyNotes.no_training_on_pii)}</span></div>
                    )}
                    {retentionPolicy && (
                      <div style={{ marginTop: '6px' }}>
                        <small>Retention:</small> <span className="mono">{JSON.stringify(retentionPolicy)}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
            {(mitre || owasp || dread || cvss || kev || pasta) && (
              <div style={{ marginTop: '6px', padding: '8px', border: '1px solid #e5e7eb', borderRadius: '8px', background: '#f9fafb' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ fontWeight: 600 }}>Security Signals</div>
                  <button className="secondary sm" onClick={() => setShowSecurity(!showSecurity)}>
                    {showSecurity ? 'Hide Security' : 'Show Security'}
                  </button>
                </div>
                {showSecurity && (
                  <>
                    {mitre && <div><small>MITRE:</small> <span>{mitre}</span></div>}
                    {owasp && <div><small>OWASP:</small> <span>{owasp}</span></div>}
                    {allCompliance && allCompliance.length > 0 && <div><small>Compliance:</small> <span>{allCompliance.join(', ')}</span></div>}
                    {(dread || cvss || pasta || kev) && (
                      <details style={{ marginTop: '6px' }}>
                        <summary>Risk scoring details</summary>
                        <div style={{ marginTop: '6px' }}>
                          {dread && <div><small>DREAD:</small> <span className="mono">{dread}</span></div>}
                          {cvss && <div><small>CVSS:</small> <span className="mono">{cvss}</span></div>}
                          {pasta && <div><small>PASTA:</small> <span className="mono">{pasta}</span></div>}
                          {kev && <div><small>KEV:</small> <span className="mono">{kev}</span></div>}
                        </div>
                      </details>
                    )}
                  </>
                )}
              </div>
            )}
            <details style={{ marginTop: '8px' }}>
              <summary>Signals & evidence (details)</summary>
              <pre style={{ background: '#f8f2ea', padding: '8px', borderRadius: '8px', overflow: 'auto' }}>{raw}</pre>
            </details>
            <div style={{ marginTop: '8px' }}>
              <a href={`${window.location.origin}/ui/status`} target="_blank" rel="noreferrer">Open Live Ops</a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const DevTracePanel = ({ open, onClose, trace }) => {
  if (!open) return null;

  const panelRef = useRef(null);
  const headerRef = useRef(null);
  const [tab, setTab] = useState('events'); // events | summary | security | raw
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [traceError, setTraceError] = useState('');
  const [showQueueOnly, setShowQueueOnly] = useState(false);

  const decisionTrace = useDecisionTrace();
  const traceId = trace?.trace_id || trace?.decision_id || null;

  useEffect(() => {
    if (!open || !traceId) return;
    if (!selectedId) setSelectedId('evt:user_query');
    decisionTrace.subscribe(traceId);
    return () => decisionTrace.unsubscribe();
  }, [open, traceId]);

  useEffect(() => {
    if (!open || !traceId) {
      setDetail(null);
      setTraceError('');
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/decisions/${encodeURIComponent(traceId)}/query?include_events=true`, {
          headers: { 'x-api-key': API_KEY },
        });
        if (!res.ok) {
          let detailMsg = '';
          try {
            const errBody = await res.json();
            detailMsg = errBody?.detail || errBody?.error || '';
          } catch (e) {
            detailMsg = '';
          }
          if (!cancelled) setTraceError(`Trace fetch failed (${res.status})${detailMsg ? `: ${detailMsg}` : ''}`);
          return;
        }
        const data = await res.json();
        if (!cancelled) {
          setTraceError('');
          setDetail(data);
        }
      } catch (e) {
        if (!cancelled) setTraceError(`Trace fetch failed: ${String(e?.message || e)}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, traceId]);

  useEffect(() => {
    const el = panelRef.current;
    const hdr = headerRef.current;
    if (!open || !el || !hdr) return;
    let dragging = false;
    let startX = 0;
    let startY = 0;
    let originX = 0;
    let originY = 0;
    const onMouseDown = (event) => {
      dragging = true;
      startX = event.clientX;
      startY = event.clientY;
      const rect = el.getBoundingClientRect();
      originX = rect.left;
      originY = rect.top;
      el.style.right = 'auto';
      event.preventDefault();
    };
    const onMouseMove = (event) => {
      if (!dragging) return;
      const dx = event.clientX - startX;
      const dy = event.clientY - startY;
      el.style.left = `${originX + dx}px`;
      el.style.top = `${originY + dy}px`;
    };
    const onMouseUp = () => {
      dragging = false;
    };
    hdr.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      hdr.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [open]);

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(detail || trace || {}, null, 2));
    } catch (e) {
      // ignore
    }
  };

  const mkBadge = (label) => (
    <span
      style={{
        fontSize: '10px',
        padding: '2px 8px',
        borderRadius: '999px',
        border: '1px solid #e5e7eb',
        color: '#374151',
        background: '#f9fafb',
        fontWeight: 700,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );

  const mkSuccess = () => (
    <span
      title="Success"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        fontSize: '10px',
        padding: '2px 6px',
        borderRadius: '999px',
        background: '#dcfce7',
        color: '#166534',
        border: '1px solid #86efac',
        fontWeight: 800,
      }}
    >
      ✓
    </span>
  );

  const isSuccessEvent = (e) => {
    const badge = (e.badge || '').toUpperCase();
    const p = e.payload || {};
    if (badge.includes('CANDIDATE') && (Array.isArray(p.candidates) ? p.candidates.length > 0 : (p.count || p.total || 0) > 0)) return true;
    if (badge.includes('POLICY') && typeof (p.decision || (p.policy_gate && p.policy_gate.decision)) !== 'undefined') {
      const d = String(p.decision || (p.policy_gate && p.policy_gate.decision) || '').toLowerCase();
      if (['allow', 'approved', 'pass', 'passed'].includes(d)) return true;
    }
    if (badge.includes('AGENT PROCESS') && ((p.result_count || 0) > 0 || (Array.isArray(p.results) ? p.results.length > 0 : false))) return true;
    if (badge.includes('RANKING') && ((p.top_k || 0) > 0 || (Array.isArray(p.ranked) ? p.ranked.length > 0 : false))) return true;
    return false;
  };

  const eventItems = (() => {
    const baseTs = detail?.timestamp || null;
    const out = [];

    const query = detail?.input_query || detail?.evidence?.query || trace?.query || null;
    if (query) out.push({ id: 'evt:user_query', ts: baseTs, title: 'Query', badge: 'USER QUERY', payload: { query } });

    const modelSel = detail?.model_selection || null;
    if (modelSel) out.push({ id: 'evt:model_selection', ts: baseTs, title: 'Model_Selector', badge: 'MODEL SELECTION', payload: modelSel });

    const chain = Array.isArray(detail?.agent_chain) ? detail.agent_chain : (Array.isArray(trace?.agent_chain) ? trace.agent_chain : []);
    chain.forEach((a, idx) => {
      const nm = a?.agent || a?.name || `Agent_${idx + 1}`;
      const badge = nm.toLowerCase().includes('candidate') ? 'CANDIDATE RETRIEVAL' : nm.toLowerCase().includes('price') ? 'AGENT PROCESS' : nm.toLowerCase().includes('ranking') ? 'AGENT PROCESS' : nm.toLowerCase().includes('model') ? 'MODEL SELECTION' : 'AGENT PROCESS';
      out.push({ id: `evt:agent:${idx}:${nm}`, ts: baseTs, title: nm, badge, payload: a || {} });
    });

    const hookEvents = Array.isArray(decisionTrace.events) ? decisionTrace.events : [];
    hookEvents.forEach((e, idx) => {
      const originalType = e?.payload?._original_event_type || e?.payload?.original_event_type || null;
      const shownType = String(originalType || e.type || e.event_type || 'event');
      const badge = shownType.replace(/_/g, ' ').toUpperCase();
      const titleBits = [shownType];
      if (e.source) titleBits.push(String(e.source));
      out.push({
        id: `evt:trace:${e.id || e.time || idx}`,
        ts: e.time || baseTs,
        title: titleBits.join(' · '),
        badge,
        payload: e.payload || {},
      });
    });

    const seen = new Set();
    const uniq = [];
    for (const i of out) {
      if (seen.has(i.id)) continue;
      seen.add(i.id);
      uniq.push(i);
    }
    return uniq;
  })();

  const selected = eventItems.find((e) => e.id === selectedId) || eventItems[0] || null;

  const toStrList = (value) => {
    if (!value) return [];
    if (Array.isArray(value)) return value.map((v) => String(v)).filter(Boolean);
    if (typeof value === 'string') return value ? [value] : [];
    return [];
  };

  const boolMapFrom = (...objs) => {
    const out = {};
    objs.forEach((obj) => {
      if (!obj || typeof obj !== 'object') return;
      Object.entries(obj).forEach(([k, v]) => {
        if (typeof v === 'boolean') out[k] = v;
      });
    });
    return out;
  };

  const extractSecuritySnapshot = (payload) => {
    const p = (payload && typeof payload === 'object') ? payload : {};
    const sec = p.security || p.security_analysis || (typeof p.details === 'object' ? p.details : null) || {};
    const signals = boolMapFrom(sec?.signals, p?.cv_signals, sec);
    const severityRaw = String(p.severity || sec.severity || 'info').toLowerCase();
    const severity = severityRaw === 'warning' ? 'warn' : severityRaw;
    const route = String(p.route || sec.route || '').toLowerCase() || (severity === 'error' || severity === 'high' ? 'escalate' : (severity === 'warn' ? 'review' : 'allow'));
    const thresholdVersion = p.threshold_version || sec.threshold_version || 'security-v1';
    const confidenceVal = (p.confidence ?? sec.confidence ?? null);
    const confidence = (confidenceVal === null || typeof confidenceVal === 'undefined') ? null : Number(confidenceVal);
    const mitre = [
      ...toStrList(sec.mitre_atlas),
      ...toStrList(sec.mitre),
      ...toStrList(sec.mitre_attack),
    ];
    const owasp = [
      ...toStrList(sec.owasp_llm_top10),
      ...toStrList(sec.owasp_llm),
      ...toStrList(sec.owasp_agentic_top10),
      ...toStrList(sec.owasp_api_top10),
    ];
    const stride = [
      ...toStrList(sec.stride_categories),
      ...toStrList(sec.stride),
    ];
    const evidence = (sec.evidence && typeof sec.evidence === 'object') ? sec.evidence : {};
    const containment = toStrList(sec.containment_actions || sec.actions);
    const bitemporal = (sec.bitemporal && typeof sec.bitemporal === 'object') ? sec.bitemporal : (p.bitemporal && typeof p.bitemporal === 'object' ? p.bitemporal : null);
    return { severity, route, thresholdVersion, confidence, signals, mitre, owasp, stride, evidence, containment, bitemporal };
  };

  const securitySnapshots = (() => {
    const snapshots = [];
    const add = (evt, idx, source) => {
      const eventType = String(evt?.event_type || evt?.type || '').toLowerCase();
      if (eventType !== 'security_scan') return;
      const snap = extractSecuritySnapshot(evt?.payload || {});
      snapshots.push({
        id: evt?.id || `${source}-${idx}`,
        ts: evt?.created_at || evt?.time || null,
        source,
        ...snap,
      });
    };
    const detailEvents = Array.isArray(detail?.events) ? detail.events : [];
    detailEvents.forEach((evt, idx) => add(evt, idx, 'trace_query'));
    const liveEvents = Array.isArray(decisionTrace.events) ? decisionTrace.events : [];
    liveEvents.forEach((evt, idx) => add(evt, idx, 'stream'));
    const seen = new Set();
    const deduped = [];
    for (const snap of snapshots) {
      const key = `${snap.id}:${snap.ts || ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      deduped.push(snap);
    }
    deduped.sort((a, b) => String(a.ts || '').localeCompare(String(b.ts || '')));
    return deduped;
  })();

  const fallbackSecurity = extractSecuritySnapshot(detail?.security || trace?.security || {});
  const securityCurrent = securitySnapshots[securitySnapshots.length - 1] || fallbackSecurity;
  const signals = securityCurrent?.signals || {};

  const renderEventsTab = () => (
    <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
      <div style={{ width: '42%', minWidth: '320px', borderRight: '1px solid #e5e7eb', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '10px 12px', fontWeight: 800, color: '#111827' }}>Events</div>
        <div style={{ padding: '0 12px 12px', flex: 1, overflowY: 'auto' }}>
          {showQueueOnly ? (
            (!decisionTrace.filtered || decisionTrace.filtered.length === 0) ? (
              <small style={{ color: '#6b7280' }}>No queued events yet.</small>
            ) : (
              [...decisionTrace.filtered].reverse().map((item) => (
                <button
                  key={`qe-${item.id}`}
                  onClick={() => setSelectedId(`evt:queue:${item.id}`)}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    background: '#fff',
                    border: '1px solid #e5e7eb',
                    borderRadius: '10px',
                    padding: '10px',
                    marginBottom: '8px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'center' }}>
                    <div style={{ fontWeight: 700, fontSize: '12px' }}>{String(item.type || 'queued')}</div>
                    <small style={{ color: '#6b7280' }}>{new Date(item.time || Date.now()).toLocaleTimeString()}</small>
                  </div>
                  <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '4px' }}>
                    {(item.source || 'source')} → {(item.target || 'job')}
                  </div>
                  <div style={{ fontSize: '12px', marginTop: '6px' }}>{String(item.payload?.job_id || '').slice(0, 36)}</div>
                </button>
              ))
            )
          ) : (
            eventItems.length === 0 ? (
              <small style={{ color: '#6b7280' }}>No trace events yet.</small>
            ) : (
              eventItems.map((e) => {
                const isSel = selected?.id === e.id;
                return (
                  <button
                    key={e.id}
                    onClick={() => setSelectedId(e.id)}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      background: isSel ? '#f8fafc' : '#fff',
                      border: isSel ? '1px solid #93c5fd' : '1px solid #e5e7eb',
                      borderRadius: '10px',
                      padding: '10px',
                      marginBottom: '8px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'center' }}>
                      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', minWidth: 0 }}>
                        <small style={{ width: '72px', color: '#6b7280' }}>
                          {e.ts ? new Date(e.ts).toLocaleTimeString() : '--:--:--'}
                        </small>
                        <div style={{ fontWeight: 800, fontSize: '12px', color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {e.title}
                        </div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        {mkBadge(e.badge || 'EVENT')}
                        {isSuccessEvent(e) && mkSuccess()}
                      </div>
                    </div>
                    {e.id === 'evt:user_query' && (
                      <div style={{ marginTop: '6px', fontSize: '12px', color: '#374151' }}>
                        {String(e.payload?.query || '').slice(0, 110)}{String(e.payload?.query || '').length > 110 ? '…' : ''}
                      </div>
                    )}
                  </button>
                );
              })
            )
          )}
        </div>
      </div>

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '10px 12px', fontWeight: 800, color: '#111827' }}>Event Details</div>
        <div style={{ padding: '0 12px 12px', overflowY: 'auto', flex: 1 }}>
          {!selected ? (
            <small style={{ color: '#6b7280' }}>Select an event to see details.</small>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ border: '1px solid #e5e7eb', borderRadius: '12px', padding: '12px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '8px', fontSize: '12px' }}>
                  <div style={{ color: '#6b7280' }}>Type</div>
                  <div style={{ fontWeight: 800 }}>{selected.badge || 'EVENT'}</div>
                  <div style={{ color: '#6b7280' }}>Timestamp</div>
                  <div style={{ fontWeight: 600 }}>{selected.ts ? new Date(selected.ts).toISOString() : '—'}</div>
                  <div style={{ color: '#6b7280' }}>Latency</div>
                  <div style={{ fontWeight: 600 }}>{typeof selected.payload?.duration_ms !== 'undefined' ? `${selected.payload.duration_ms}ms` : '—'}</div>
                </div>
              </div>
              <div style={{ border: '1px solid #e5e7eb', borderRadius: '12px', padding: '12px' }}>
                <div style={{ fontWeight: 900, fontSize: '12px', marginBottom: '8px', color: '#111827' }}>Payload</div>
                <pre style={{ margin: 0, fontSize: '11px', whiteSpace: 'pre-wrap', color: '#111827' }}>
                  {JSON.stringify(selected.payload || {}, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  const renderSummaryTab = () => (
    <div style={{ padding: '12px', overflowY: 'auto', width: '100%' }}>
      {!detail ? (
        <small style={{ color: '#6b7280' }}>No trace yet. Ask a question to populate.</small>
      ) : (
        <div className="flex flex-col gap-3">
          <div style={{ border: '1px solid #e5e7eb', borderRadius: '12px', padding: '12px' }}>
            <div style={{ fontWeight: 900, marginBottom: '6px' }}>Request</div>
            <div style={{ fontSize: '12px', color: '#111827' }}>{detail.input_query || detail.evidence?.query || trace?.query}</div>
            <div style={{ marginTop: '8px', display: 'flex', gap: '12px', flexWrap: 'wrap', fontSize: '12px', color: '#374151' }}>
              <div><small style={{ color: '#6b7280' }}>Decision:</small> <span className="mono">{detail.decision_id || traceId || '—'}</span></div>
              <div><small style={{ color: '#6b7280' }}>Tier:</small> <span>{detail.model_tier || '—'}</span></div>
              <div><small style={{ color: '#6b7280' }}>LLM:</small> <span>{detail.llm_model || '—'}</span></div>
              <div><small style={{ color: '#6b7280' }}>Risk:</small> <span>{detail.risk_quantification?.risk_band || '—'} ({detail.risk_quantification?.risk_score ?? '—'})</span></div>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  const renderSecurityTab = () => {
    const signalEntries = Object.entries(signals || {}).filter(([, v]) => Boolean(v));
    const hasMatrix = signalEntries.length > 0
      || (securityCurrent?.mitre || []).length > 0
      || (securityCurrent?.owasp || []).length > 0
      || (securityCurrent?.stride || []).length > 0
      || !!securityCurrent?.route;

    if (!hasMatrix) {
      return (
        <div style={{ padding: '12px', overflowY: 'auto', width: '100%' }}>
          {traceError && (
            <div style={{ border: '1px solid #fecaca', background: '#fff1f2', color: '#9f1239', borderRadius: '12px', padding: '12px', marginBottom: '10px', fontSize: '12px' }}>
              {traceError}
            </div>
          )}
          <div style={{ border: '1px dashed #d1d5db', borderRadius: '12px', padding: '16px', color: '#6b7280', fontSize: '13px' }}>
            No security analysis available for this trace yet.
          </div>
        </div>
      );
    }

    return (
      <div style={{ padding: '12px', overflowY: 'auto', width: '100%' }}>
        <div style={{ border: '1px solid #e5e7eb', borderRadius: '12px', padding: '12px', marginBottom: '10px' }}>
          <div style={{ fontWeight: 900, marginBottom: '6px' }}>Route</div>
          <div style={{ fontSize: '12px', color: '#374151', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            <span><small style={{ color: '#6b7280' }}>Route:</small> {securityCurrent?.route || '-'}</span>
            <span><small style={{ color: '#6b7280' }}>Severity:</small> {securityCurrent?.severity || '-'}</span>
            <span><small style={{ color: '#6b7280' }}>Threshold:</small> {securityCurrent?.thresholdVersion || '-'}</span>
            <span><small style={{ color: '#6b7280' }}>Confidence:</small> {typeof securityCurrent?.confidence === 'number' ? securityCurrent.confidence.toFixed(3) : '-'}</span>
          </div>
          {securityCurrent?.bitemporal && (
            <div style={{ marginTop: '8px', fontSize: '11px', color: '#6b7280' }}>
              valid_from: {securityCurrent.bitemporal.valid_from || '-'} | system_from: {securityCurrent.bitemporal.system_from || '-'}
            </div>
          )}
        </div>

        <div style={{ border: '1px solid #e5e7eb', borderRadius: '12px', padding: '12px', marginBottom: '10px' }}>
          <div style={{ fontWeight: 900, marginBottom: '6px' }}>Signals</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {signalEntries.map(([k]) => (
              <span key={k} style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '999px', background: '#fee2e2', color: '#991b1b', border: '1px solid #fecaca' }}>
                {k}
              </span>
            ))}
            {signalEntries.length === 0 && (
              <small style={{ color: '#6b7280' }}>No boolean signals flagged.</small>
            )}
          </div>
        </div>

        <div style={{ border: '1px solid #e5e7eb', borderRadius: '12px', padding: '12px', marginBottom: '10px' }}>
          <div style={{ fontWeight: 900, marginBottom: '6px' }}>MITRE / OWASP / STRIDE</div>
          <div style={{ fontSize: '12px', color: '#374151', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div><small style={{ color: '#6b7280' }}>MITRE:</small> <span>{(securityCurrent?.mitre || []).join(', ') || '-'}</span></div>
            <div><small style={{ color: '#6b7280' }}>OWASP:</small> <span>{(securityCurrent?.owasp || []).join(', ') || '-'}</span></div>
            <div><small style={{ color: '#6b7280' }}>STRIDE:</small> <span>{(securityCurrent?.stride || []).join(', ') || '-'}</span></div>
          </div>
        </div>

        <div style={{ border: '1px solid #e5e7eb', borderRadius: '12px', padding: '12px' }}>
          <div style={{ fontWeight: 900, marginBottom: '6px' }}>Evidence / Actions</div>
          <div style={{ fontSize: '12px', color: '#374151', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div><small style={{ color: '#6b7280' }}>Source:</small> <span>{securityCurrent?.evidence?.source || '-'}</span></div>
            <div><small style={{ color: '#6b7280' }}>Containment:</small> <span>{(securityCurrent?.containment || []).join(', ') || '-'}</span></div>
          </div>
        </div>
      </div>
    );
  };
  const renderRawTab = () => (
    <div style={{ padding: '12px', overflowY: 'auto', width: '100%' }}>
      <pre style={{ margin: 0, fontSize: '11px', whiteSpace: 'pre-wrap' }}>{JSON.stringify(detail || trace || {}, null, 2)}</pre>
    </div>
  );

  return (
    <div
      ref={panelRef}
      style={{
        position: 'fixed',
        right: '16px',
        top: '64px',
        width: 'min(860px, 92vw)',
        maxHeight: '72vh',
        background: '#fff',
        border: '1px solid #e5e7eb',
        borderRadius: '12px',
        boxShadow: '0 10px 30px rgba(0,0,0,0.18)',
        zIndex: 90,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <div
        ref={headerRef}
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '10px 12px',
          borderBottom: '1px solid #e5e7eb',
          cursor: 'move',
          background: '#0b2a52',
          color: '#fff',
        }}
      >
        <strong>Decision Trace</strong>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button className="secondary sm" onClick={copyJson} style={{ background: 'rgba(255,255,255,0.12)', color: '#fff', border: '1px solid rgba(255,255,255,0.18)' }}>
            Copy JSON
          </button>
          <button className="secondary sm" onClick={onClose} style={{ background: 'rgba(255,255,255,0.12)', color: '#fff', border: '1px solid rgba(255,255,255,0.18)' }}>
            Close
          </button>
        </div>
      </div>

      <div style={{ padding: '10px 12px', borderBottom: '1px solid #e5e7eb', display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
        {traceError && (
          <div style={{ width: '100%', border: '1px solid #fecaca', background: '#fff1f2', color: '#9f1239', borderRadius: '10px', padding: '8px 10px', fontSize: '12px' }}>
            {traceError}
          </div>
        )}
        <div style={{ display: 'flex', gap: '6px' }}>
          {[
            { k: 'events', label: 'Events' },
            { k: 'summary', label: 'Summary' },
            { k: 'security', label: 'Security Matrix' },
            { k: 'raw', label: 'Raw' },
          ].map(({ k, label }) => (
            <button key={k} className={tab === k ? 'contrast sm' : 'secondary sm'} onClick={() => setTab(k)} style={{ padding: '6px 10px' }}>
              {label}
            </button>
          ))}
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input type="checkbox" checked={showQueueOnly} onChange={(e) => setShowQueueOnly(e.target.checked)} />
            <small style={{ color: '#6b7280' }}>Queued jobs only</small>
          </label>
        </div>
      </div>
      <div style={{ padding: '6px 12px', borderBottom: '1px solid #e5e7eb', fontSize: '12px', color: '#6b7280' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '2px 6px', borderRadius: '999px', background: '#dcfce7', color: '#166534', border: '1px solid #86efac', fontWeight: 800 }}>✓</span>
          Green check indicates a successful agent stage.
        </span>
        Includes policy gate, model selection, candidate retrieval, ranking, and inventory checks.
      </div>

      {tab === 'events' && renderEventsTab()}
      {tab === 'summary' && renderSummaryTab()}
      {tab === 'security' && renderSecurityTab()}
      {tab === 'raw' && renderRawTab()}
    </div>
  );
};

const buildGreetingMessage = () => {
  let name = '';
  let tier = '';
  try {
    if (typeof window !== 'undefined') {
      name = localStorage.getItem('shopsquire_user_name') || '';
      tier = localStorage.getItem('shopsquire_user_tier') || '';
    }
  } catch (err) {
    name = '';
    tier = '';
  }
  const hello = name ? `Welcome back, ${name}!` : "Hi! I'm your shopping assistant.";
  const tierText = tier ? ` You're on the ${tier} tier.` : '';
  return {
    role: 'assistant',
    content: `${hello}${tierText} Try: "Show me gaming laptops under $2000" or "Compare laptops with 16GB RAM".`,
    timestamp: new Date(),
  };
};

const ShopSquireApp = () => {
  const screenshotMode = (typeof window !== 'undefined') && (
    (new URLSearchParams(window.location.search).get('screenshot') === '1') ||
    (localStorage.getItem('shopsquire_screenshot_mode') === '1')
  );
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [messages, setMessages] = useState(() => [buildGreetingMessage()]);
  const [inputValue, setInputValue] = useState('');
  const [catalogProducts, setCatalogProducts] = useState(() =>
    fillToMinimum(
      FALLBACK_BASE.map((item) => ({ ...item, sku: item.id, image: createImage(item.name) })),
      35
    )
  );
  const [rightPanel, setRightPanel] = useState({ type: 'products', data: catalogProducts, meta: { view_reason: 'Featured catalog loaded' } });
  const [viewMode, setViewMode] = useState('grid');
  const [viewModeReason, setViewModeReason] = useState('Featured catalog loaded');
  const [cartState, setCartState] = useState({ cart_id: null, items: [], subtotal_cents: 0, currency: 'USD' });
  const [isLoading, setIsLoading] = useState(false);
  const [opsOverlayOpen, setOpsOverlayOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [devTraceOpen, setDevTraceOpen] = useState(false);
  const [lastTrace, setLastTrace] = useState(null);
  const [traceLog, setTraceLog] = useState([]); // array of trace entries (most-recent-first)
  const [traceExpandedId, setTraceExpandedId] = useState(null);
  const [isPrivileged, setIsPrivileged] = useState(false);
  const [pendingUploads, setPendingUploads] = useState([]);
  const [cvStatus, setCvStatus] = useState(null);
  const [cvImages, setCvImages] = useState([]);
  const [uploadError, setUploadError] = useState('');
  const [lastProducts, setLastProducts] = useState(catalogProducts);
  const [checkoutStep, setCheckoutStep] = useState(0);
  const [retentionConsent, setRetentionConsent] = useState(false);
  const [privacyPanelOpen, setPrivacyPanelOpen] = useState(false);
  const [privacyPrefs, setPrivacyPrefs] = useState({
    personalization_opt_in: true,
    retention_opt_in: false,
    ai_disclosure_ack: true,
  });
  const [privacyNotice, setPrivacyNotice] = useState('');
  const [shippingForm, setShippingForm] = useState({ name: '', street: '', city: '', state: '', zip: '' });
  const uid = 'guest_user';
  const fileInputRef = useRef(null);
  const chatEndRef = useRef(null);

  const detectViewMode = (queryText) => {
    const q = (queryText || '').toLowerCase();
    if (q.includes('compare') || q.includes('vs') || q.includes('versus')) {
      return { mode: 'compare', reason: 'Comparison keywords detected' };
    }
    if (q.includes('detail') || q.includes('details') || q.includes('specs') || q.includes('list')) {
      return { mode: 'list', reason: 'Detailed request detected' };
    }
    if (
      q.includes('price') ||
      q.match(/\bbetween\s+\$?\d+\s+(?:to|and)\s+\$?\d+/) ||
      q.match(/\bfrom\s+\$?\d+\s+to\s+\$?\d+/) ||
      q.match(/\$?\d+\s*(?:-|to)\s*\$?\d+/) ||
      q.match(/under\s+\$?\d+/)
    ) {
      return { mode: 'grid', reason: 'Price range detected' };
    }
    return { mode: 'grid', reason: 'Default product layout' };
  };

  const handleViewModeChange = (mode, reason) => {
    setViewMode(mode);
    setViewModeReason(reason || 'Manual view switch');
  };

  const persistPrivacyConsent = async (prefs) => {
    try {
      const payload = {
        personalization_opt_in: !!prefs.personalization_opt_in,
        retention_opt_in: !!prefs.retention_opt_in,
        ai_disclosure_ack: !!prefs.ai_disclosure_ack,
        locale: 'en',
      };
      await fetchWithTimeout(
        `${API_BASE}/privacy/consent/${encodeURIComponent(uid)}`,
        {
          method: 'POST',
          headers: { 'x-api-key': API_KEY, 'content-type': 'application/json' },
          body: JSON.stringify(payload),
        },
        5000
      );
      try {
        localStorage.setItem('shopsquire_privacy_prefs', JSON.stringify(payload));
      } catch (e) {
        return;
      }
    } catch (e) {
      return;
    }
  };

  const createPrivacyRequest = async (requestType) => {
    try {
      const res = await fetchWithTimeout(
        `${API_BASE}/privacy/request/${encodeURIComponent(uid)}`,
        {
          method: 'POST',
          headers: { 'x-api-key': API_KEY, 'content-type': 'application/json' },
          body: JSON.stringify({ request_type: requestType, locale: 'en' }),
        },
        6000
      );
      if (!res.ok) throw new Error('privacy_request_failed');
      const body = await res.json();
      setPrivacyNotice(`Request received: ${requestType} (${body?.request?.id || 'queued'})`);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Privacy request received: ${requestType}. We logged this for review.`, timestamp: new Date() },
      ]);
    } catch (e) {
      setPrivacyNotice('Unable to submit privacy request right now.');
    }
  };

  useEffect(() => {
    if (!screenshotMode) return;
    setMessages([
      { role: 'assistant', content: 'Welcome! Here are curated picks based on your preferences.', timestamp: new Date() },
      { role: 'user', content: 'Compare laptops under $1500 with 16GB RAM.', timestamp: new Date() },
      { role: 'assistant', content: 'Showing top options with clear specs and price ranges.', timestamp: new Date() },
    ]);
    setRightPanel({ type: 'products', data: catalogProducts, meta: { view_reason: 'Screenshot demo mode' } });
    setViewMode('compare');
    setViewModeReason('Screenshot demo mode');
    setChatOpen(true);
  }, [screenshotMode, catalogProducts]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (!chatOpen) return;
    (async () => {
      try {
        let localPrefs = null;
        try {
          const raw = localStorage.getItem('shopsquire_privacy_prefs');
          if (raw) localPrefs = JSON.parse(raw);
        } catch (e) {
          localPrefs = null;
        }
        if (localPrefs && typeof localPrefs === 'object') {
          setPrivacyPrefs((prev) => ({ ...prev, ...localPrefs }));
          setRetentionConsent(!!localPrefs.retention_opt_in);
        }
        const res = await fetchWithTimeout(
          `${API_BASE}/privacy/consent/${encodeURIComponent(uid)}`,
          { headers: { 'x-api-key': API_KEY } },
          5000
        );
        if (!res.ok) return;
        const body = await res.json();
        const remote = body?.consent;
        if (remote && typeof remote === 'object') {
          setPrivacyPrefs((prev) => ({ ...prev, ...remote }));
          if (typeof remote.retention_opt_in !== 'undefined') {
            setRetentionConsent(!!remote.retention_opt_in);
          }
        }
      } catch (e) {
        return;
      }
    })();
  }, [chatOpen]);

  useEffect(() => {
    (async () => {
      try {
        const apiRoot = API_BASE.replace('/api/v1', '');
        const res = await fetch(`${apiRoot}/ui/products.json`);
        if (!res.ok) return;
        const data = await res.json();
        const normalized = normalizeCatalog(data);
        const filled = fillToMinimum(normalized, 35);
        setCatalogProducts(filled);
        setLastProducts(filled);
        setRightPanel((prev) => (prev.type === 'products' ? { ...prev, data: filled } : prev));
      } catch (err) {
        return;
      }
    })();
  }, []);

  useEffect(() => {
    fetchCart();
  }, []);

  useEffect(() => {
    try {
      if (typeof window !== 'undefined') window.__SS_IS_PRIV = !!isPrivileged;
    } catch (err) {
      return;
    }
  }, [isPrivileged]);

  useEffect(() => {
    (async () => {
      try {
        const apiRoot = API_BASE.replace('/api/v1', '');
        const res = await fetch(`${apiRoot}/api/v1/auth/me`, { credentials: 'include' });
        if (!res.ok) return;
        const me = await res.json();
        const roles = (Array.isArray(me.roles) ? me.roles.join(',') : (me.role || '')).toLowerCase();
        const allowed = ['merchant', 'owner', 'developer', 'admin'];
        const ok = allowed.some((role) => roles.includes(role));
        if (ok) setIsPrivileged(true);
      } catch (err) {
        return;
      }
    })();
  }, []);

  useEffect(() => {
    if (!cvStatus?.caseId || cvStatus.caseId === 'pending') return;
    if (cvStatus.state === 'complete' || cvStatus.state === 'error') return;
    let cancelled = false;
    const terminal = ['approved', 'blocked', 'denied', 'rejected'];
    let interval = null;
    let polls = 0;
    const MAX_POLLS = 15; // ~60s @ 4s interval
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE.replace('/api/v1', '')}/api/v1/support/complaints/${cvStatus.caseId}/status`, {
          headers: { 'x-api-key': API_KEY },
        });
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        const nextDecision = data.decision || data.status || cvStatus.decision;
        const isDone = terminal.includes(String(nextDecision || '').toLowerCase());
        const needsHuman = ['fraud_review_team', 'supervisor_review', 'manual_review', 'security_review'].includes(String(nextDecision || '').toLowerCase());
        setCvStatus((prev) => ({
          ...prev,
          decision: nextDecision,
          confidence: data.cv_analysis?.confidence ?? prev.confidence,
          severity: data.cv_analysis?.severity ?? prev.severity,
          state: isDone ? 'complete' : 'processing',
          message: needsHuman ? 'Human review required for this case.' : prev.message,
        }));
        if (isDone) {
          cancelled = true;
          if (interval) clearInterval(interval);
          return;
        }
        polls += 1;
        if (polls > MAX_POLLS) {
          cancelled = true;
          if (interval) clearInterval(interval);
          setCvStatus((prev) => ({ ...prev, state: 'error', message: 'Analysis timed out. Please escalate to a human agent.' }));
        }
      } catch (err) {
        return;
      }
    };
    interval = setInterval(poll, 4000);
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [cvStatus?.caseId, cvStatus?.state, cvStatus?.decision]);

  useEffect(() => {
    const traceKey = lastTrace?.trace_id || lastTrace?.decision_id;
    if (!devTraceOpen || !traceKey) return;
    let cancelled = false;
    let interval;
    const poll = async () => {
      try {
        const res = await fetchWithTimeout(`${API_BASE}/decisions/${traceKey}`, { headers: { 'x-api-key': API_KEY } }, 8000);
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        setLastTrace((prev) => ({ ...prev, ...data }));
      } catch (err) {
        // ignore
      }
    };
    // initial fetch + polling every 4s while panel is open
    poll();
    interval = setInterval(poll, 4000);
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [devTraceOpen, lastTrace?.trace_id, lastTrace?.decision_id]);

  // Legacy SSE removed in favor of useDecisionTrace within DevTracePanel

  const fetchCart = async () => {
    try {
      const res = await fetch(`${API_BASE}/cart?uid=${encodeURIComponent(uid)}`, {
        headers: { 'x-api-key': API_KEY },
      });
      if (!res.ok) return;
      const data = await res.json();
      setCartState(data);
    } catch (err) {
      return;
    }
  };

  const handleAddToCart = async (product) => {
    const sku = product?.sku || product?.id;
    if (!sku) return;
    try {
      const res = await fetch(`${API_BASE}/cart/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-api-key': API_KEY },
        body: JSON.stringify({ uid, sku, quantity: 1 }),
      });
      if (!res.ok) throw new Error('cart add failed');
      const data = await res.json();
      setCartState(data);
      setRightPanel({ type: 'cart', data });
    } catch (err) {
      const fallback = { ...cartState, items: [...(cartState.items || []), { sku, name: product?.name || sku, quantity: 1, price: product?.price }] };
      setCartState(fallback);
      setRightPanel({ type: 'cart', data: fallback });
    }
  };

  const handleCheckout = async (cartData) => {
    const items = (cartData?.items || []).map((item) => ({
      sku: item.sku,
      quantity: item.quantity || 1,
    }));
    if (!items.length) return;
    try {
      const res = await fetch(`${API_BASE}/orders/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-api-key': API_KEY },
        body: JSON.stringify({ uid, items }),
      });
      if (!res.ok) throw new Error('checkout failed');
      const data = await res.json();
      setRightPanel({ type: 'checkout', data });
      try {
        await fetch(`${API_BASE}/cart/clear?uid=${encodeURIComponent(uid)}`, {
          method: 'POST',
          headers: { 'x-api-key': API_KEY },
        });
        fetchCart();
      } catch (err) {
        return;
      }
    } catch (err) {
      setRightPanel({ type: 'checkout', data: { status: 'failed' } });
    }
  };

  const handleApprovalAction = async (approvalId, action) => {
    if (!approvalId) return;
    const endpoint = action === 'approve' ? 'approve' : 'reject';
    try {
      const res = await fetch(`${API_BASE.replace('/api/v1', '')}/api/v1/approvals/${approvalId}/${endpoint}`, {
        method: 'POST',
        headers: { 'x-api-key': API_KEY },
      });
      if (!res.ok) throw new Error('approval failed');
      const result = await res.json();
      setRightPanel({ type: 'approval', data: { approval_id: approvalId, status: result.approved ? 'approved' : 'rejected' } });
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Approval ${approvalId} ${result.approved ? 'approved' : 'rejected'}.`, timestamp: new Date() },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Approval action failed for ${approvalId}.`, timestamp: new Date(), action: 'warning' },
      ]);
    }
  };

  const handleViewDetail = async (product) => {
    if (!product) {
      setRightPanel({ type: 'products', data: lastProducts, meta: rightPanel.meta || {} });
      return;
    }
    const sku = product.sku || product.id;
    if (!sku) {
      setRightPanel({ type: 'product_detail', data: product, meta: rightPanel.meta || {} });
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/products/${encodeURIComponent(sku)}`, {
        headers: { 'x-api-key': API_KEY },
      });
      if (!res.ok) throw new Error('detail fetch failed');
      const data = await res.json();
      const detail = {
        ...product,
        sku: data.sku || sku,
        name: data.name || product.name,
        price: typeof data.price_cents === 'number' ? Math.round(data.price_cents / 100) : (product.price || null),
        specs: data.specs || product.specs,
        availability: data.availability || (data.stock > 0 ? 'in_stock' : 'out_of_stock'),
        stock: data.stock,
        image: data.image_url || product.image || product.image_url || createImage(product.name || sku),
      };
      setRightPanel({ type: 'product_detail', data: detail, meta: rightPanel.meta || {} });
    } catch (err) {
      setRightPanel({ type: 'product_detail', data: product, meta: rightPanel.meta || {} });
    }
  };

  const handleOpenFile = () => {
    if (fileInputRef.current) fileInputRef.current.click();
  };

  const handleFileChange = (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    const allowedTypes = ['image/jpeg', 'image/png', 'image/jpg', 'image/webp', 'video/mp4', 'video/webm'];
    const invalidType = files.find((file) => !allowedTypes.some((t) => file.type.startsWith(t.split('/')[0])));
    if (invalidType) {
      setUploadError('Unsupported format. Use JPG, PNG images or MP4 videos only.');
      setPendingUploads([]);
      setCvImages([]);
      return;
    }
    const maxBytes = MAX_UPLOAD_MB * 1024 * 1024;
    const tooLarge = files.find((file) => file.size > maxBytes);
    if (tooLarge) {
      setUploadError(`File too large. Max ${MAX_UPLOAD_MB}MB per file.`);
      setPendingUploads([]);
      setCvImages([]);
      return;
    }
    setUploadError('');
    setPendingUploads(files.map((file) => file.name));
    setCvImages(files);
  };

  const handleComplaintSubmit = async (message) => {
    if (!pendingUploads.length || !fileInputRef.current) return null;
    const files = Array.from(fileInputRef.current.files || []);
    if (!files.length) return null;
    const form = new FormData();
    // Best-effort extraction of order and issue type from message
    const detectIssueType = (text) => {
      const t = (text || '').toLowerCase();
      if (t.includes('damage') || t.includes('broken') || t.includes('cracked')) return 'damage';
      if (t.includes('refund') || t.includes('return') || t.includes('money back')) return 'refund';
      if (t.includes('wrong') || t.includes('incorrect') || t.includes('not what')) return 'wrong_item';
      if (t.includes('missing') || t.includes('not received')) return 'missing';
      if (t.includes('fake') || t.includes('counterfeit')) return 'fraud';
      return 'general';
    };
    const extractOrderId = (text) => {
      const m = (text || '').match(/\b(?:order|ord|#)\s*[:#-]?\s*([A-Z0-9\-]{4,20})/i);
      return m ? m[1] : '';
    };
    form.append('order_id', extractOrderId(message) || 'unspecified');
    form.append('issue_type', detectIssueType(message));
    form.append('description', message || 'Complaint submitted via chat');
    files.forEach((file) => form.append('images', file));
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const res = await fetch(`${API_BASE.replace('/api/v1', '')}/api/v1/support/complaints/submit`, {
        method: 'POST',
        headers: { 'x-api-key': API_KEY },
        body: form,
        signal: controller.signal,
      });
      if (!res.ok) throw new Error('Complaint upload failed');
      const data = await res.json();
      if (!data.case_id) {
        return { error: true, reason: 'missing_case_id', data };
      }
      return data;
    } catch (err) {
      if (err.name === 'AbortError') {
        return { error: true, reason: 'timeout' };
      }
      return { error: true };
    } finally {
      clearTimeout(timer);
    }
  };

  const handleSendMessage = async () => {
    if (!inputValue.trim()) return;
    // Client-side PII check: warn and block sending sensitive data
    if (containsPII(inputValue)) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '⚠️ Detected potentially sensitive information. Please do not enter card numbers or other PII in chat. Use secure checkout or contact support.', timestamp: new Date(), action: 'warning' },
      ]);
      setInputValue('');
      return;
    }
    const userMessage = { role: 'user', content: inputValue, timestamp: new Date() };
    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);
    try {
      const viewModeHint = detectViewMode(userMessage.content);
      handleViewModeChange(viewModeHint.mode, viewModeHint.reason);
      const complaintResult = await handleComplaintSubmit(userMessage.content);
      if (complaintResult) {
        if (complaintResult.error) {
          const reason = complaintResult.reason === 'timeout' ? 'CV upload timed out. Try again.' : 'CV upload failed. Check files and retry.';
          setCvStatus({ caseId: 'pending', state: 'error', message: reason });
          setUploadError(reason);
          setRightPanel({ type: 'cv', data: [], meta: {} });
        } else {
          const caseMsg = {
            role: 'assistant',
            content: `Complaint received. Case ID: ${complaintResult.case_id || 'pending'}. CV analysis is running.`,
            timestamp: new Date(),
          };
          setMessages((prev) => [...prev, caseMsg]);
          setPendingUploads([]);
          if (fileInputRef.current) fileInputRef.current.value = '';
          const decisionValue = complaintResult.decision || complaintResult.status || 'analysis_running';
          const cvTraceId = complaintResult.decision_id || complaintResult.case_id || null;
          const isDone = ['approved', 'blocked', 'denied', 'rejected'].includes(String(decisionValue).toLowerCase());
          const needsHuman = ['fraud_review_team', 'supervisor_review', 'manual_review', 'security_review'].includes(String(decisionValue || '').toLowerCase());
          setCvStatus({
            caseId: complaintResult.case_id || 'pending',
            traceId: cvTraceId,
            decision: decisionValue,
            confidence: complaintResult.cv_analysis?.confidence,
            severity: complaintResult.cv_analysis?.severity,
            state: isDone ? 'complete' : 'processing',
            message: needsHuman ? 'Human review required for this case.' : undefined,
          });
          setRightPanel({ type: 'cv', data: [], meta: {} });
          if (cvTraceId) {
            setLastTrace({
              decision_id: cvTraceId,
              trace_id: cvTraceId,
              severity: complaintResult.cv_analysis?.severity,
              risk_score: complaintResult.risk_quantification?.risk_score,
              agent_chain: complaintResult.agent_chain || [],
              query: userMessage.content,
            });
          }
          // append CV case to trace log
          try {
            const now = new Date();
              const cvEntry = {
              id: `cv-${complaintResult.case_id || 'pending'}-${now.getTime()}`,
              time: now.toISOString(),
              query: 'CV complaint analysis',
              status: decisionValue || 'processing',
              decision_id: cvTraceId,
              trace_id: cvTraceId,
              security: complaintResult.cv_analysis || {},
              agent_chain: complaintResult.agent_chain || [],
              human_review: needsHuman ? { status: 'pending', ticket_id: complaintResult.ticket_id } : undefined,
            };
            setTraceLog((prev) => [cvEntry, ...prev].slice(0, 25));
          } catch (err) {
            // ignore
          }
        }
      }
      const qs = new URLSearchParams({ uid, query: userMessage.content }).toString();
      const response = await fetchWithTimeout(`${API_BASE}/recommend/suggest?${qs}`, {
        method: 'GET',
        headers: { 'x-api-key': API_KEY, 'x-retention-consent': retentionConsent ? 'true' : 'false' },
      }, 10000);
      if (!response.ok) throw new Error('API request failed');
      const data = await response.json();
      if (data && (data.status === 'blocked' || data.status === 'review_required' || data.status === 'degraded')) {
        const warnMsg = {
          role: 'assistant',
          content: data.message || 'I cannot help with that. Try a safer phrasing or I can connect you with support.',
          timestamp: new Date(),
          action: 'human_handoff',
          approval_id: data.approval_id,
        };
        setMessages((prev) => [...prev, warnMsg]);
        setLastTrace({
          status: data.status,
          trace_id: data.trace_id || data.decision_id || null,
          decision_id: data.decision_id || data.trace_id || null,
          approval_id: data.approval_id,
          security: data.security,
          severity: data.severity,
          notice: data.notice,
          policy_notes: data.policy_notes,
          query: userMessage.content,
        });
        // append to rolling trace log
        try {
          const now = new Date();
          const entry = {
            id: data.trace_id || data.decision_id || `local-${now.getTime()}`,
            time: now.toISOString(),
            query: userMessage.content,
            status: data.status || 'ok',
            decision_id: data.decision_id,
            trace_id: data.trace_id,
            policy_version: data.policy_version,
            risk_score: data.risk_score,
            security: data.security,
            agent_chain: data.agent_chain,
            model_tier: data.model_tier,
            llm_model: data.llm_model,
            complexity_signals: data.complexity_signals,
            playbook: data.playbook,
            human_review: data.human_review || (data.approval_id ? { status: 'pending', approval_id: data.approval_id } : undefined),
          };
          setTraceLog((prev) => [entry, ...prev].slice(0, 25));
        } catch (err) {
          // ignore
        }
        if (data.approval_id) {
          setRightPanel({ type: 'approval', data: { approval_id: data.approval_id, reason: data.escalation?.reason || data.status } });
        } else {
          setRightPanel({ type: 'faq', data: [] });
        }
        setIsLoading(false);
        return;
      }
      const results = normalizeResults(data.results);
      const backendViewMode = data.view_mode || viewModeHint.mode;
      const backendViewReason = data.view_reason || viewModeHint.reason;
      const constraints = data.constraints_used || {};
      const budgetMin = constraints.budget_min;
      const budgetMax = constraints.budget_max;
      const budgetText = budgetMin && budgetMax
        ? `between $${budgetMin} and $${budgetMax}`
        : budgetMax
          ? `under $${budgetMax}`
          : budgetMin
            ? `over $${budgetMin}`
            : '';
      const viewLabel = backendViewMode === 'compare' ? 'comparison' : backendViewMode === 'list' ? 'detailed list' : 'grid';
      const assistantText =
        data.assistant_message ||
        data.message ||
        data.summary ||
        (results.length
          ? `For "${userMessage.content}", I found ${results.length} options${budgetText ? ` ${budgetText}` : ''}. Showing a ${viewLabel} view.`
          : `I couldn't find matches for "${userMessage.content}"${budgetText ? ` ${budgetText}` : ''}. Try adjusting budget or specs.`);
      const assistantMessage = {
        role: 'assistant',
        content: assistantText,
        timestamp: new Date(),
        action: 'show_products',
        products: results,
        llm_model: data.llm_model,
        model_tier: data.model_tier,
      };
      setMessages((prev) => [...prev, assistantMessage]);
      // Render clarifying questions when backend provides them
      if (Array.isArray(data.next_questions) && data.next_questions.length > 0) {
        const nqMessage = {
          role: 'assistant',
          content: 'Before I narrow this down, a few quick questions:',
          timestamp: new Date(),
          action: 'next_questions',
          questions: data.next_questions,
        };
        setMessages((prev) => [...prev, nqMessage]);
      }
      if (data.notice && !assistantText.includes(data.notice)) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.notice,
            timestamp: new Date(),
            action: 'warning',
          },
        ]);
      }
      const traceKey = data.trace_id || data.decision_id || null;
      setLastTrace({
        decision_id: data.decision_id || traceKey,
        policy_version: data.policy_version,
        trace_id: traceKey,
        approval_id: data.approval_id,
        risk_score: data.risk_score,
        security: data.security,
        why_not: data.why_not,
        degraded: data.degraded,
        eligible: data.eligible,
        agent_chain: data.agent_chain,
        llm_model: data.llm_model,
        model_tier: data.model_tier,
        complexity_signals: data.complexity_signals,
        intent_analysis: data.proposal?.nlp || data.constraints_used || {},
        retrieved_context: data.constraints_used,
        query: userMessage.content,
        policy_notes: data.policy_notes,
      });
      // append success result to trace log
      try {
        const now2 = new Date();
        const entry2 = {
          id: traceKey || `local-${now2.getTime()}`,
          time: now2.toISOString(),
          query: userMessage.content,
          status: 'ok',
          decision_id: data.decision_id,
          trace_id: traceKey,
          policy_version: data.policy_version,
          risk_score: data.risk_score,
          security: data.security,
          agent_chain: data.agent_chain,
          model_tier: data.model_tier,
          llm_model: data.llm_model,
          complexity_signals: data.complexity_signals,
          playbook: data.playbook,
          policy_notes: data.policy_notes,
          human_review: data.human_review || (data.approval_id ? { status: 'pending', approval_id: data.approval_id } : undefined),
        };
        setTraceLog((prev) => [entry2, ...prev].slice(0, 25));
      } catch (err) {
        // ignore
      }
      if (assistantMessage.products) {
        handleViewModeChange(backendViewMode, backendViewReason);
        setRightPanel({
          type: 'products',
          data: assistantMessage.products,
          meta: {
            why_not: data.why_not || [],
            policy_version: data.policy_version,
            decision_id: data.decision_id || null,
            view_reason: backendViewReason,
          },
        });
        setLastProducts(assistantMessage.products);
      }
    } catch (err) {
      const errMessage = {
        role: 'assistant',
        content: 'Unable to reach the recommendation service right now. Please try again in a moment.',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errMessage]);
      try {
        const now = new Date();
        const entry = {
          id: `error-${now.getTime()}`,
          time: now.toISOString(),
          query: userMessage.content,
          status: 'error',
          error: 'recommendation_unreachable',
        };
        setTraceLog((prev) => [entry, ...prev].slice(0, 25));
      } catch (err2) {
        // ignore
      }
    }
    setIsLoading(false);
  };
  return (
    <div className="flex flex-col h-screen">
      <header className="border-b border-gray-200 bg-white sticky top-0 z-40">
        <div className="px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button onClick={() => setMobileMenuOpen(true)} className="lg:hidden p-2 hover:bg-gray-100 rounded-lg">
              <Icons.Menu />
            </button>
            <h1 className="text-xl font-semibold text-gray-900">ShopSquire</h1>
          </div>
          <div className="hidden md:flex items-center flex-1 max-w-md mx-8">
            <div className="relative w-full">
              <input
                type="text"
                placeholder="Search products..."
                className="w-full px-4 py-2 pl-10 border border-gray-200 rounded-lg focus:outline-none focus:border-gray-400"
              />
              <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
                <Icons.Search />
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setRightPanel({ type: 'cart', data: cartState })} className="p-2 hover:bg-gray-100 rounded-lg relative">
              <Icons.Cart />
              {(cartState.items || []).length > 0 && (
                <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
                  {(cartState.items || []).length}
                </span>
              )}
            </button>
            <button className="p-2 hover:bg-gray-100 rounded-lg hidden sm:block" onClick={() => setDevTraceOpen(true)} title="View decision trace & alerts">
              <Icons.Bell />
            </button>
            {(lastTrace?.decision_id || lastTrace?.trace_id) && (
              <button className="p-2 hover:bg-gray-100 rounded-lg" onClick={() => setDevTraceOpen(true)} title="Decision & Security Trace">
                <Icons.Gear />
              </button>
            )}
            {/* Demo Trace removed to ensure only real traces are shown */}
          </div>
        </div>
      </header>

      <main style={{ background: '#f8fafc', flex: 1 }}>
        <section style={{ padding: '24px 24px 8px' }}>
          <div style={{ background: '#0f172a', color: '#fff', borderRadius: '16px', padding: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h2 style={{ margin: 0, fontSize: '24px' }}>Windows Laptops</h2>
              <p style={{ marginTop: '6px', color: '#cbd5f5' }}>Compare the latest work, gaming, and creator rigs.</p>
            </div>
            <button className="contrast" onClick={() => setChatOpen(true)}>Ask the Assistant</button>
          </div>
          <div style={{ marginTop: '10px', padding: '8px 12px', border: '1px solid #e5e7eb', borderRadius: '10px', background: '#f8fafc', color: '#475569', fontSize: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>AI recommendations are data-informed and inventory-checked. Manage consent in Assistant Privacy settings.</span>
            <button className="secondary sm" onClick={() => { setChatOpen(true); setPrivacyPanelOpen(true); }}>Privacy controls</button>
          </div>
        </section>
        <section style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: '20px', padding: '0 24px 32px' }}>
          <aside style={{ background: '#fff', borderRadius: '12px', padding: '16px', border: '1px solid #e5e7eb', height: 'fit-content' }}>
            <h3 style={{ marginTop: 0 }}>Filters</h3>
            <div className="text-sm text-gray-600" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <label><input type="checkbox" /> Under $1000</label>
              <label><input type="checkbox" /> 16GB RAM+</label>
              <label><input type="checkbox" /> RTX Graphics</label>
              <label><input type="checkbox" /> 1TB SSD+</label>
              <label><input type="checkbox" /> In stock</label>
            </div>
          </aside>
          <div style={{ background: '#fff', borderRadius: '12px', padding: '16px', border: '1px solid #e5e7eb' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div className="text-sm text-gray-600">Showing {catalogProducts.length} products</div>
              <button className="secondary" onClick={() => setChatOpen(true)}>Need help choosing?</button>
            </div>
            <ProductGrid products={catalogProducts} viewMode="grid" onAddToCart={handleAddToCart} onViewDetail={handleViewDetail} />
          </div>
        </section>
      </main>

      <button
        onClick={() => setChatOpen(true)}
        style={{ position: 'fixed', right: '24px', bottom: '24px', width: '60px', height: '60px', borderRadius: '999px', background: '#111827', color: '#fff', border: 'none', boxShadow: '0 12px 32px rgba(0,0,0,0.25)', zIndex: 65, transition: 'all 0.2s ease' }}
        title="Open assistant"
        className="transition-transform"
        onMouseEnter={(e) => { e.currentTarget.style.transform = 'scale(1.05)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
      >
        <Icons.Bot />
      </button>

      <ChatOverlay
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        onOpenTrace={() => setDevTraceOpen(true)}
      >
        <div className="chat-pane" style={{ width: '42.857%', flex: '0 0 42.857%', borderRight: '1px solid #e5e7eb', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div className="flex-1 overflow-y-auto chat-scroll" style={{ padding: '1.5rem', background: '#f9fafb' }}>
            <div style={{ maxWidth: '768px', margin: '0 auto' }}>
              {messages.map((message, index) => (
                <div key={index} className={`mb-4 flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`message-bubble ${message.role}`}>
                    <p style={{ margin: 0 }}>{message.content}</p>
                    {message.role === 'assistant' && (message.llm_model || message.model_tier) && (
                      <div className="mt-2" style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                        {message.llm_model && <span className="badge info">Model: {message.llm_model}</span>}
                        {message.model_tier && <span className="badge">Tier: {message.model_tier}</span>}
                      </div>
                    )}
                    {message.action === 'show_products' && (
                      <button
                        onClick={() => setRightPanel({ type: 'products', data: message.products || [], meta: {} })}
                        className="sm mt-2"
                        style={{ background: 'rgba(255,255,255,0.1)', color: 'inherit' }}
                      >
                        View {message.products?.length || 0} products
                      </button>
                    )}
                    {message.action === 'human_handoff' && (
                      <button
                        onClick={() =>
                          message.approval_id
                            ? setRightPanel({ type: 'approval', data: { approval_id: message.approval_id, reason: 'security_review' } })
                            : setRightPanel({ type: 'faq', data: [] })
                        }
                        className="sm mt-2"
                        style={{ background: 'rgba(255,255,255,0.1)', color: 'inherit' }}
                      >
                        <Icons.Phone />
                        Talk to human
                      </button>
                    )}
                    {message.action === 'warning' && (
                      <div className="flex items-center gap-2 mt-2" style={{ color: '#f59e0b' }}>
                        <Icons.AlertTriangle />
                        <span className="text-xs">Security notice</span>
                      </div>
                    )}
                    {message.action === 'next_questions' && Array.isArray(message.questions) && message.questions.length > 0 && (
                      <div className="flex flex-col gap-2 mt-2">
                        {message.questions.map((q, i) => (
                          <button
                            key={q.id || i}
                            className="secondary text-left text-sm"
                            onClick={() => {
                              setInputValue(q.text);
                            }}
                          >
                            {q.text}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {isLoading && (
                <div className="flex justify-start mb-4">
                  <div className="bg-white border border-gray-200 rounded-lg px-4 py-2">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
                    </div>
                  </div>
                </div>
              )}
              <div ref={chatEndRef}></div>
            </div>
          </div>
          <div style={{ borderTop: '1px solid #e5e7eb', padding: '1rem', background: '#fff' }}>
            <div style={{ maxWidth: '768px', margin: '0 auto' }}>
              <div style={{ marginBottom: '0.5rem', padding: '8px 10px', border: '1px solid #e5e7eb', borderRadius: '8px', background: '#f8fafc' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
                  <small style={{ color: '#6b7280' }}>
                    AI uses product and interaction signals for recommendations. You can control personalization and data rights.
                  </small>
                  <button className="secondary sm" onClick={() => setPrivacyPanelOpen((v) => !v)}>
                    {privacyPanelOpen ? 'Hide privacy' : 'Privacy'}
                  </button>
                </div>
                {privacyPanelOpen && (
                  <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#4b5563' }}>
                      <input
                        type="checkbox"
                        checked={!!privacyPrefs.personalization_opt_in}
                        onChange={(e) => {
                          const next = { ...privacyPrefs, personalization_opt_in: e.target.checked };
                          setPrivacyPrefs(next);
                          persistPrivacyConsent(next);
                        }}
                      />
                      Personalize recommendations using my interactions.
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#4b5563' }}>
                      <input
                        type="checkbox"
                        checked={!!privacyPrefs.ai_disclosure_ack}
                        onChange={(e) => {
                          const next = { ...privacyPrefs, ai_disclosure_ack: e.target.checked };
                          setPrivacyPrefs(next);
                          persistPrivacyConsent(next);
                        }}
                      />
                      I understand assistant responses are AI-generated and may require verification.
                    </label>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      <button className="secondary sm" onClick={() => createPrivacyRequest('export')}>Request data export</button>
                      <button className="secondary sm" onClick={() => createPrivacyRequest('delete')}>Request data deletion</button>
                      <button className="secondary sm" onClick={() => createPrivacyRequest('optout_automation')}>Opt out of automation</button>
                    </div>
                    {privacyNotice && <small style={{ color: '#475569' }}>{privacyNotice}</small>}
                  </div>
                )}
              </div>
              {pendingUploads.length > 0 && (
                <div style={{ marginBottom: '0.5rem' }}>
                  <small style={{ color: '#6b7280' }}>Attachments: {pendingUploads.join(', ')}</small>
                </div>
              )}
              {uploadError && (
                <div style={{ marginBottom: '0.5rem' }}>
                  <small style={{ color: '#dc2626' }}>{uploadError}</small>
                </div>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*,video/*"
                multiple
                style={{ display: 'none' }}
                onChange={handleFileChange}
              />
              <div className="flex gap-2" style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  className="secondary"
                  style={{ padding: '0.75rem', borderRadius: '8px' }}
                  onClick={handleOpenFile}
                  aria-label="Upload photo or video"
                  title="Upload photo or video"
                >
                  <Icons.Camera />
                </button>
                <input
                  type="text"
                  value={inputValue}
                  onChange={(event) => setInputValue(event.target.value)}
                  onKeyPress={(event) => event.key === 'Enter' && handleSendMessage()}
                  placeholder="Ask me anything about products, orders, or help..."
                  style={{ flex: 1, padding: '0.75rem', border: '1px solid #e5e7eb', borderRadius: '8px' }}
                />
                <button className="secondary" style={{ padding: '0.75rem', borderRadius: '8px', opacity: 0.6, cursor: 'not-allowed' }} aria-label="Start voice input" title="Voice input (coming soon)" disabled>
                  <Icons.Mic />
                </button>
                <button className="secondary" style={{ padding: '0.75rem', borderRadius: '8px' }} aria-label="Security & trace" title="Security & trace" onClick={() => setDevTraceOpen(true)}>
                  <Icons.Shield />
                </button>
                <button onClick={handleSendMessage} className="contrast" aria-label="Send message" title="Send message" disabled={!inputValue.trim()}>
                  <Icons.Send />
                </button>
              </div>
            </div>
          </div>
        </div>
        {rightPanel.type && (
          <div className="panel-pane" style={{ width: '57.143%', flex: '0 0 57.143%', minHeight: 0 }}>
            <RightPanel
              type={rightPanel.type}
              data={rightPanel.data}
              onClose={() => { setRightPanel({ type: null, data: [] }); setCheckoutStep(0); }}
              viewMode={viewMode}
              viewModeReason={viewModeReason}
              onViewModeChange={handleViewModeChange}
              onAddToCart={handleAddToCart}
              onViewDetail={handleViewDetail}
              onCheckout={(cartData) => { handleCheckout(cartData); setCheckoutStep(3); }}
              onApprovalAction={handleApprovalAction}
              onEscalate={(caseId) => {
                (async () => {
                  try {
                    const traceContext = {
                      case_id: caseId || cvStatus?.caseId || null,
                      trace_id: cvStatus?.traceId || lastTrace?.trace_id || lastTrace?.decision_id || null,
                      decision_id: lastTrace?.decision_id || null,
                      severity: cvStatus?.severity || lastTrace?.severity || null,
                      findings: Array.isArray(cvStatus?.fraudSignals) ? cvStatus.fraudSignals : [],
                      reason: 'cv_human_review',
                    };
                    const res = await fetchWithTimeout(
                      `${API_BASE}/incidents/escalate`,
                      {
                        method: 'POST',
                        headers: { 'content-type': 'application/json' },
                        body: JSON.stringify({
                          case_id: traceContext.case_id,
                          trace_id: traceContext.trace_id,
                          reason: 'cv_human_review',
                          context: {
                            surface: 'storefront',
                            uid: uid || 'guest_user',
                            trace: traceContext,
                          },
                        }),
                      },
                      8000
                    );
                    if (!res.ok) throw new Error('escalate_failed');
                    const j = await res.json();
                    if (!j?.incident_id) throw new Error('missing_incident_id');
                    setRightPanel({
                      type: 'incident_chat',
                      data: {
                        incident_id: j.incident_id,
                        token: j.buyer_token || j.staff_token || null,
                        staff_token: j.staff_token || null,
                        prefill_context: traceContext,
                      },
                      meta: {},
                    });
                    setMessages((prev) => [
                      ...prev,
                      { role: 'assistant', content: 'I have escalated this to a human support specialist. You can continue the conversation in the Support Chat panel.', timestamp: new Date() },
                    ]);
                  } catch (e) {
                    setRightPanel({ type: 'approval', data: { approval_id: `ESC-${caseId}`, reason: 'human_escalation', case_id: caseId } });
                    setMessages((prev) => [...prev, { role: 'assistant', content: 'Escalation is temporarily unavailable. Please try again or contact support.', timestamp: new Date() }]);
                  }
                })();
              }}
              cvStatus={cvStatus}
              cvImages={cvImages}
              uploadError={uploadError}
              meta={rightPanel.meta}
              onDemoTrace={null}
              checkoutStep={checkoutStep}
              onCheckoutStepChange={setCheckoutStep}
              shippingForm={shippingForm}
              onShippingChange={setShippingForm}
              retentionConsent={retentionConsent}
              onRetentionConsentChange={(checked) => {
                setRetentionConsent(checked);
                const next = { ...privacyPrefs, retention_opt_in: !!checked };
                setPrivacyPrefs(next);
                persistPrivacyConsent(next);
              }}
              privacyPrefs={privacyPrefs}
              isLoading={isLoading}
              uid={uid}
            />
          </div>
        )}
      </ChatOverlay>

      <MobileMenu isOpen={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />

      {(() => {
        const dev = (typeof window !== 'undefined') && ((localStorage.getItem('shopsquire_dev_mode') === '1') || (new URLSearchParams(window.location.search).get('dev') === '1'));
        return (dev || isPrivileged) && !screenshotMode;
      })() && (
        <>
          <div style={{ position: 'fixed', right: '12px', bottom: '12px', display: 'flex', gap: '8px' }}>
            <button className="secondary" onClick={() => window.open(`${window.location.origin}/ui/status`, '_blank', 'width=800,height=600')}>Live Ops</button>
            <button className="contrast" onClick={() => setOpsOverlayOpen(true)}>Ops Overlay</button>
          </div>
          <OpsOverlay open={opsOverlayOpen} onClose={() => setOpsOverlayOpen(false)} />
        </>
      )}

      {screenshotMode && (
        <div style={{ position: 'fixed', right: '16px', bottom: '16px', padding: '6px 10px', borderRadius: '6px', background: 'rgba(17,24,39,0.85)', color: '#fff', fontSize: '12px', zIndex: 80 }}>
          ShopSquire Demo • Screenshot Mode
        </div>
      )}

      <DevTracePanel
        open={devTraceOpen}
        onClose={() => setDevTraceOpen(false)}
        trace={lastTrace}
        traceLog={traceLog}
        expandedId={traceExpandedId}
        onToggle={(id) => setTraceExpandedId((prev) => (prev === id ? null : id))}
      />
    </div>
  );
};

export default ShopSquireApp;
