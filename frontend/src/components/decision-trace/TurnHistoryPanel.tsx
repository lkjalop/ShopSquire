import { useState } from 'react';

type TurnRecord = {
  commit_id: string;
  known_at: string;
  valid_at: string;
  read_model: {
    case_revision: number;
    operation_id?: string;
    objective?: string;
    catalog_authority?: string;
    commerce_authority?: string;
  };
};

export default function TurnHistoryPanel({ history }: { history: TurnRecord[] }) {
  const [selected, setSelected] = useState('');
  if (!history.length) return null;
  const record = history.find(row => row.commit_id === selected) || history[history.length - 1];
  const model = record.read_model;
  return <section data-testid="recorded-turn-history">
    <h3>Recorded shopping-turn history</h3>
    <label>Recorded turn revision{' '}
      <select value={record.commit_id} onChange={event => setSelected(event.target.value)}>
        {history.map(row => <option key={row.commit_id} value={row.commit_id}>Revision {row.read_model.case_revision}</option>)}
      </select>
    </label>
    <p>{model.objective || 'Objective not recorded'}</p>
    <p>Operation: {model.operation_id || 'not recorded'}</p>
    <p>Known at <time>{record.known_at}</time>; effective at <time>{record.valid_at}</time>.</p>
    <p>Catalog authority: {model.catalog_authority || 'not recorded'}; commerce authority: {model.commerce_authority || 'not recorded'}.</p>
    <p>This is the persisted turn projection, not a reconstruction from today's catalog or a procurement execution certificate.</p>
  </section>;
}
