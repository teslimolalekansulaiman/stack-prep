/**
 * The coach's board: the worked solution written out a step at a time.
 *
 * It plays on its own — that is the point of a board rather than a page of text — and it can
 * be paused, replayed and stepped through. Nothing here is generated in the browser: the
 * steps are `solution_steps`, written when the question was imported, so what a student is
 * shown is the same text a reviewer can read and correct.
 *
 * The caption under the board stands in for the coach's voice, which is a later phase, so it
 * is written to be read as speech. When the voice arrives it narrates these same steps and
 * this caption becomes the transcript rather than being replaced.
 *
 * The board is no longer one-way: a student who loses a step can ask about it, and the coach
 * answers from these same steps. Asking pauses the writing, because a solution that keeps
 * marching on while you read the answer to your question is a solution you lose twice. What
 * comes back may be the tutor or may be the reviewed step again — the card says which, rather
 * than letting a student believe they were answered when they were not.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import type { TutorReply } from './api.js';
import './theme.css';

const STEP_MS = 5200;

/**
 * Matches the server's own cap, so a question that would be refused is stopped at the box
 * rather than after the student has finished typing it.
 */
const ASK_MAX_CHARS = 400;

/** Below this, the day's remaining questions are said out loud instead of running out silently. */
const LOW_ON_ASKS = 3;

export function Board({
  title,
  subtitle,
  steps,
  answerLine,
  onDone,
  onAsk,
}: {
  title: string;
  subtitle: string;
  steps: string[];
  /** Shown last, in green: what the answer actually was. */
  answerLine: string;
  onDone: () => void;
  /** `stepIndex` is null once the board has finished writing and the whole working is up. */
  onAsk: (asked: string, stepIndex: number | null) => Promise<TutorReply>;
}) {
  const [shown, setShown] = useState(0);
  const [paused, setPaused] = useState(false);
  const [draft, setDraft] = useState('');
  const [turn, setTurn] = useState<(TutorReply & { asked: string }) | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [askIssue, setAskIssue] = useState<string | null>(null);
  const lines = [...steps, answerLine];
  const inkRef = useRef<HTMLDivElement>(null);

  const advance = useCallback(() => {
    setShown((current) => Math.min(current + 1, lines.length));
  }, [lines.length]);

  useEffect(() => {
    if (paused || shown >= lines.length) return;
    const timer = setTimeout(advance, shown === 0 ? 500 : STEP_MS);
    return () => clearTimeout(timer);
  }, [advance, lines.length, paused, shown]);

  // Keep the newest line in view: a long solution should scroll itself rather than write
  // below the fold and wait to be found.
  useEffect(() => {
    inkRef.current?.scrollTo({ top: inkRef.current.scrollHeight, behavior: 'smooth' });
  }, [shown]);

  // Which line of the working the question is about. Null once the board has moved past the
  // steps onto the answer line, or before it has written anything.
  const stepIndex = shown > 0 && shown - 1 < steps.length ? shown - 1 : null;

  const send = useCallback(
    async (event: { preventDefault: () => void }) => {
      event.preventDefault();
      const asked = draft.trim();
      if (!asked || waiting) return;
      setWaiting(true);
      setAskIssue(null);
      // The working stops while they are being answered, and their place is kept.
      setPaused(true);
      try {
        const reply = await onAsk(asked, stepIndex);
        setTurn({ ...reply, asked });
        setDraft('');
      } catch (error) {
        setAskIssue((error as Error).message);
      } finally {
        setWaiting(false);
      }
    },
    [draft, onAsk, stepIndex, waiting],
  );

  // Reading an answer and watching the next step appear are different things, so the reply
  // stays up until the student moves the board themselves.
  const resume = useCallback(() => {
    setTurn(null);
    setAskIssue(null);
  }, []);

  const finished = shown >= lines.length;
  const caption = finished
    ? 'That is the whole working. This one goes back in the pile — you will meet the same ground again, with a different question.'
    : (lines[Math.max(0, shown - 1)] ?? '');

  // A student has to be able to tell being answered from being handed the same step again,
  // so the card says which of the two just happened rather than sounding the same either way.
  const status = waiting
    ? 'Coach · reading your question'
    : turn
      ? turn.source === 'model'
        ? 'Coach · answering you'
        : 'Coach · cannot talk this through — here is the reviewed step'
      : paused
        ? 'Coach · paused — your place is kept'
        : finished
          ? 'Coach · finished'
          : `Coach · step ${shown} of ${lines.length}`;

  return (
    <div className="sp sp-coach">
      <div className="sp-cbar">
        <button className="sp-btn sm light" type="button" onClick={onDone}>
          Close
        </button>
        <div className="sp-lesson">
          <span>
            <small>{subtitle}</small>
            <strong>{title}</strong>
          </span>
        </div>
        <div className="sp-steps-mini">
          {lines.map((line, index) => (
            <i key={line + String(index)} className={index < shown ? 'on' : ''} />
          ))}
        </div>
      </div>

      <div className={`sp-board ${paused ? 'dim' : ''}`}>
        <div className="sp-ink" ref={inkRef}>
          {lines.map((line, index) => (
            <span
              key={line + String(index)}
              className={`sp-hl ${index < shown ? 'show' : ''} ${
                index === lines.length - 1 ? 'answer' : ''
              }`}
            >
              <span className="n">
                {index === lines.length - 1 ? 'answer' : `step ${index + 1}`}
              </span>
              {line}
            </span>
          ))}
        </div>

        <div className={`sp-tutorcard ${paused ? 'paused' : ''}`}>
          <span className="sp-mark">SP</span>
          <div>
            <div className="who">
              <span className="dot" />
              {status}
            </div>
            {turn ? (
              <>
                <p className="asked">“{turn.asked}”</p>
                <p>{turn.reply}</p>
              </>
            ) : (
              <p>{waiting ? 'Let me look at that with you…' : caption}</p>
            )}
          </div>
        </div>
      </div>

      <div className="sp-dock">
        <form className="sp-ask" onSubmit={send}>
          <div className="row">
            <input
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                // A student typing a question is no longer reading the board, and a step that
                // scrolls past mid-sentence is the step they were about to ask about.
                if (event.target.value !== '') setPaused(true);
              }}
              onKeyDown={(event) => {
                // Submitted here rather than left to the form, because this box is mostly
                // used on a phone, where sending is the keyboard's own Go key and not a tap
                // on the button beside it.
                if (event.key === 'Enter') void send(event);
              }}
              placeholder={
                stepIndex === null
                  ? 'Ask the coach about the working…'
                  : `Ask about step ${stepIndex + 1}…`
              }
              aria-label="Ask the coach about this working"
              maxLength={ASK_MAX_CHARS}
              disabled={waiting}
            />
            <button
              className="sp-btn sm"
              type="submit"
              disabled={waiting || draft.trim() === ''}
            >
              {waiting ? '…' : 'Ask'}
            </button>
          </div>
          <span className="note">
            {askIssue
              ? askIssue
              : turn && turn.asks_left <= LOW_ON_ASKS
                ? `${turn.asks_left} more question${turn.asks_left === 1 ? '' : 's'} today.`
                : 'Lost a step? Ask about it — the coach answers from this working.'}
          </span>
        </form>
        <div className="ctl">
          <button
            type="button"
            title="Replay this step"
            onClick={() => {
              resume();
              setShown((current) => Math.max(0, current - 1));
            }}
            disabled={shown === 0}
          >
            ↺
          </button>
          <button
            type="button"
            title={paused ? 'Resume' : 'Pause'}
            onClick={() => {
              resume();
              setPaused((value) => !value);
            }}
            disabled={finished}
          >
            {paused ? '▶' : '❚❚'}
          </button>
          <button
            type="button"
            title="Next step"
            onClick={() => {
              resume();
              if (finished) onDone();
              else advance();
            }}
          >
            {finished ? '✓' : '→'}
          </button>
        </div>
      </div>
    </div>
  );
}
