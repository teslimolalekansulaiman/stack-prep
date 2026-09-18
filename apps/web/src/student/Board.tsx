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
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import './theme.css';

const STEP_MS = 5200;

export function Board({
  title,
  subtitle,
  steps,
  answerLine,
  onDone,
}: {
  title: string;
  subtitle: string;
  steps: string[];
  /** Shown last, in green: what the answer actually was. */
  answerLine: string;
  onDone: () => void;
}) {
  const [shown, setShown] = useState(0);
  const [paused, setPaused] = useState(false);
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

  const finished = shown >= lines.length;
  const caption = finished
    ? 'That is the whole working. This one goes back in the pile — you will meet the same ground again, with a different question.'
    : (lines[Math.max(0, shown - 1)] ?? '');

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
              {paused
                ? 'Coach · paused — your place is kept'
                : finished
                  ? 'Coach · finished'
                  : `Coach · step ${shown} of ${lines.length}`}
            </div>
            <p>{caption}</p>
          </div>
        </div>
      </div>

      <div className="sp-dock">
        <span className="sp-soon">
          Voice explanation comes next — for now the coach writes rather than speaks.
        </span>
        <div className="ctl">
          <button
            type="button"
            title="Replay this step"
            onClick={() => setShown((current) => Math.max(0, current - 1))}
            disabled={shown === 0}
          >
            ↺
          </button>
          <button
            type="button"
            title={paused ? 'Resume' : 'Pause'}
            onClick={() => setPaused((value) => !value)}
            disabled={finished}
          >
            {paused ? '▶' : '❚❚'}
          </button>
          <button type="button" title="Next step" onClick={finished ? onDone : advance}>
            {finished ? '✓' : '→'}
          </button>
        </div>
      </div>
    </div>
  );
}
