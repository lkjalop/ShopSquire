import { Fragment } from 'react';

export default function InlineMessageText({ text }: { text: string }) {
  const parts = String(text || '').split(/(\*\*[^*\n]+\*\*)/g);
  return (
    <>
      {parts.map((part, index) => {
        const emphasized = part.startsWith('**') && part.endsWith('**') && part.length > 4;
        return emphasized
          ? <strong key={index}>{part.slice(2, -2)}</strong>
          : <Fragment key={index}>{part}</Fragment>;
      })}
    </>
  );
}
