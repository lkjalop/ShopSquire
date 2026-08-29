import AffordabilityResolutionCard from './AffordabilityResolutionCard';
import BuyerClaimReconciliationCard from './BuyerClaimReconciliationCard';
import BuyerRequirementReviewCard from './BuyerRequirementReviewCard';
import DisambiguationButtons from './DisambiguationButtons';
import InlineMessageText from './InlineMessageText';
import PendingCartChangeCard from './PendingCartChangeCard';
import { isActionableBuyerQuestion, isResearchAuthorityQuestion } from '../lib/buyerQuestion';
import { citationChips } from '../lib/evidenceDisplay';
import type { ChatMessage } from '../conversationTypes';

type Props = {
  messages: ChatMessage[];
  classNames: Record<string, string>;
  showDebugBadges: boolean;
  cartItems: any[];
  onQuickAction: (text: string) => void;
  onNqeOption: (question: any, option: any) => void;
  onDisambiguation: (option: string) => void;
  onWebConsent: (message: ChatMessage, consent: boolean) => void;
  onOpenEvidence: (evidence: any) => void;
  onUndoClear: (message: ChatMessage) => void;
  onUndoServer: (message: ChatMessage) => void;
  onConfirmCart: (message: ChatMessage) => void;
  onDismissCart: (message: ChatMessage) => void;
  onAcceptRequirements: (message: ChatMessage, claimIds: string[], choice: any, corrections: any) => void;
  onAffordabilityChoice: (message: ChatMessage, choice: any) => void;
  onSourceFetch?: (message: ChatMessage) => void;
};

export default function ConversationTimeline(props: Props) {
  const { classNames: styles } = props;
  return <>{props.messages.map((msg, index) => <div key={index} className={`${styles.message} ${styles[msg.role]}`}>
    <div className={styles.messageContent}>
      {msg.images?.length ? <div className={styles.msgImageStrip}>{msg.images.map((source, imageIndex) => <img key={imageIndex} src={source} alt={`attachment ${imageIndex + 1}`} className={styles.msgThumb} />)}</div> : null}
      {msg.role === 'assistant'
        ? String(msg.content || '').split(/\n\n+/).filter(Boolean).map((paragraph, paragraphIndex) => <div key={paragraphIndex} className={/^\s*(⚠️|\[security\])/i.test(paragraph) ? styles.msgSecurity : styles.msgPara}><InlineMessageText text={paragraph.trim()} /></div>)
        : msg.content}
      {msg.role === 'assistant' && msg.responseProvenance?.label ? <div data-testid="response-provenance" style={{ marginTop: 5, fontSize: 11, fontStyle: 'italic', color: '#64748b' }}>{msg.responseProvenance.label}</div> : null}
      {msg.voiceUsed && <span className={styles.voiceBadge} title="Sent via voice">🎤</span>}
      {props.showDebugBadges && msg.complexity && <span className={styles.complexityBadge} title={`Complexity ${msg.complexity.score}/10 · Tier: ${msg.complexity.tier} · Model: ${msg.complexity.model}`} style={{ display: 'block', fontSize: '0.62em', opacity: 0.35, marginTop: 4, letterSpacing: '0.02em' }}>{msg.complexity.tier} · {msg.complexity.model?.split(':')[0]}</span>}
      {msg.agentStepsReadable?.length ? <details style={{ marginTop: 8, fontSize: '0.78em', opacity: 0.72 }}><summary style={{ cursor: 'pointer', userSelect: 'none' }}>How I answered this</summary><ul style={{ margin: '4px 0 0 16px', padding: 0 }}>{msg.agentStepsReadable.map((step, stepIndex) => <li key={stepIndex} style={{ marginBottom: 2 }}>{step}</li>)}</ul></details> : null}
      {index === props.messages.length - 1 && msg.nextQuestions?.some(question => isActionableBuyerQuestion(question) && !isResearchAuthorityQuestion(question)) && <div data-testid="nqe-card" style={{ marginTop: 10, border: '1px solid #e5e7eb', background: '#f9fafb', borderRadius: 10, padding: '10px 12px' }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#4f46e5', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6 }}>Help me narrow this down</div>
        {msg.nextQuestions.filter(question => isActionableBuyerQuestion(question) && !isResearchAuthorityQuestion(question)).slice(0, 2).map((question, questionIndex) => <div key={question.id} style={{ marginTop: questionIndex ? 8 : 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}><button type="button" onClick={() => props.onQuickAction(question.text)} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', font: 'inherit', fontSize: 13, fontWeight: 600, color: '#1f2937', textAlign: 'left' }}>{question.text}</button>{question.why_hint && <button type="button" className={styles.hintBtn} title={question.why_hint} style={{ fontSize: 11 }}>why?</button>}</div>
          {question.options?.length ? <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 5 }}>{question.options.slice(0, 3).map(option => <button key={`${question.id}:${option.id}`} type="button" className={styles.filterBtn} onClick={() => props.onNqeOption(question, option)}>{option.label}</button>)}</div> : null}
        </div>)}
      </div>}
    </div>
    {msg.disambiguation && msg.disambiguationOptions?.length ? <DisambiguationButtons options={msg.disambiguationOptions} onSelect={props.onDisambiguation} /> : null}
    {msg.sourceFetchPrompt && props.onSourceFetch && <div style={{ display: 'flex', gap: 8, marginTop: 8 }}><button type="button" className={styles.filterBtn} style={{ border: '1.5px solid #f59e0b' }} onClick={() => props.onSourceFetch?.(msg)}>Fetch reviewed canonical source</button></div>}
    {msg.webConsentPrompt && <div style={{ display: 'flex', gap: 8, marginTop: 8 }}><button type="button" className={styles.filterBtn} style={{ border: '1.5px solid #f59e0b' }} onClick={() => props.onWebConsent(msg, true)}>🌐 Check approved sources</button><button type="button" className={styles.filterBtn} onClick={() => props.onWebConsent(msg, false)}>Use store data only</button></div>}
    {msg.evidence?.citations?.length ? <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8, alignItems: 'center' }}><span style={{ fontSize: 11, color: '#6b7280' }}>Sources:</span>{citationChips(msg.evidence).map(chip => <button key={chip.key} type="button" className={styles.filterBtn} style={chip.trusted ? undefined : { border: '1.5px solid #f59e0b' }} title={chip.trusted ? 'Trusted store record — open the Evidence tab' : 'External evidence (verified, never authority) — open the Evidence tab'} onClick={() => props.onOpenEvidence(msg.evidence)}>{chip.icon} {chip.label}</button>)}</div> : null}
    {msg.undoClear?.items.length ? <div style={{ marginTop: 8 }}><button type="button" className={styles.filterBtn} onClick={() => props.onUndoClear(msg)} title="Put the cleared items back">↩️ Undo — restore {msg.undoClear.items.length} item(s)</button></div> : null}
    {msg.undoServer && <div style={{ marginTop: 8 }}><button type="button" className={styles.filterBtn} onClick={() => props.onUndoServer(msg)} title="Restore the cart from before that change (server snapshot)">↩️ Undo that cart change</button></div>}
    {msg.cartConfirm && <PendingCartChangeCard plan={msg.cartConfirm} cartItems={props.cartItems} onConfirm={() => props.onConfirmCart(msg)} onDismiss={() => props.onDismissCart(msg)} />}
    {msg.buyerRequirementClaims && <BuyerRequirementReviewCard claims={msg.buyerRequirementClaims} onAccept={msg.buyerRequirementProposal ? (claimIds, choice, corrections) => props.onAcceptRequirements(msg, claimIds, choice, corrections) : undefined} />}
    {msg.buyerClaimReconciliation && <BuyerClaimReconciliationCard rows={msg.buyerClaimReconciliation} />}
    {msg.cartPlanStatus && <div style={{ marginTop: 8, fontSize: 12, color: '#92400e' }}>{msg.cartPlanStatus}</div>}
    {msg.affordabilityResolution && <AffordabilityResolutionCard resolution={msg.affordabilityResolution} onChoose={choice => props.onAffordabilityChoice(msg, choice)} />}
  </div>)}</>;
}
