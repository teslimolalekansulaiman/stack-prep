/**
 * The sitting itself: one question at a time, keyboard-first.
 *
 * Two things here are lessons from driving the earlier version in a browser rather than
 * guesses. The selected option is held in a ref as well as state, because a student who types
 * "B" and Enter faster than React re-renders would otherwise send the Enter against a stale
 * selection and lose the answer. And the phase moves to "sent" before the request is awaited,
 * because rendering an "asking" state with no question is what crashed the last question of
 * every sitting.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, type CheckupState } from './api.js';
import './theme.css';

const KEYS = ['A', 'B', 'C', 'D', 'E', 'F'];

export function Diagnostic({
  sessionId,
  subjectName,
  onFinished,
}: {
  sessionId: string;
  subjectName: string;
  onFinished: () => void;
}) {
  const [state, setState] = useState<CheckupState | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [issue, setIssue] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const selectedRef = useRef<string | null>(null);
  const askedAt = useRef<number>(Date.now());
  // The parent passes onFinished as an inline arrow, so its identity changes every render.
  // An effect depending on it would re-run for ever: fetch, setState, render, new arrow,
  // fetch. Keep it in a ref and depend on the session alone.
  const finishRef = useRef(onFinished);
  useEffect(() => {
    finishRef.current = onFinished;
  }, [onFinished]);

  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);

  useEffect(() => {
    const timer = setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // A reload leaves this screen with no question, because answers hand the next one back
  // and a fresh page has none. Ask where the sitting is.
  useEffect(() => {
    let cancelled = false;
    api
      .current(sessionId)
      .then((state) => {
        if (cancelled) return;
        if (state.finished || !state.question) finishRef.current();
        else {
          setState(state);
          askedAt.current = Date.now();
        }
      })
      .catch((error: Error) => !cancelled && setIssue(error.message));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const submit = useCallback(async () => {
    const question = state?.question;
    const pick = selectedRef.current;
    if (!question || !pick || sending) return;
    setSending(true);
    setIssue(null);
    try {
      const next = await api.answer(
        sessionId,
        question.question_version_id,
        pick,
        Date.now() - askedAt.current,
      );
      setSelected(null);
      selectedRef.current = null;
      askedAt.current = Date.now();
      if (next.finished || !next.question) {
        finishRef.current();
        return;
      }
      setState(next);
    } catch (error) {
      setIssue((error as Error).message);
    } finally {
      setSending(false);
    }
  }, [sending, sessionId, state]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const letter = event.key.toUpperCase();
      const available = state?.question?.options.map((o) => o.option_key) ?? [];
      if (available.includes(letter)) {
        setSelected(letter);
        selectedRef.current = letter;
        return;
      }
      if (event.key === 'Enter') void submit();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [state, submit]);

  if (!state) {
    return <Waiting subjectName={subjectName} issue={issue} />;
  }

  const question = state.question;
  if (!question) {
    return null;
  }

  const clock = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  const progress = (state.answered / Math.max(1, state.length)) * 100;

  return (
    <div className="sp">
      <header className="sp-topbar">
        <div className="sp-title">
          <span className="sp-kicker">Check-up</span>
          <h1>{subjectName}</h1>
        </div>
        <span className="sp-timer">{clock}</span>
      </header>
      <main className="sp-content">
        <div style={{ maxWidth: 480, marginBottom: 14 }}>
          <div className="sp-bar">
            <i style={{ width: `${progress}%` }} />
          </div>
          <div className="sp-tiny sp-muted" style={{ marginTop: 4 }}>
            Question {question.position} of {question.of} · {question.topic_name}
          </div>
        </div>

        {question.passage_body ? (
          <div className="sp-passage">
            {question.passage_title ? <b>{question.passage_title}</b> : null}
            <div>{question.passage_body}</div>
          </div>
        ) : null}

        <div className="sp-card">
          {question.instructions ? (
            <p className="sp-tiny sp-muted" style={{ margin: '0 0 8px' }}>
              {question.instructions}
            </p>
          ) : null}
          <h2 style={{ fontSize: 20, margin: '4px 0 16px' }}>{question.stem}</h2>
          {question.options.map((option) => (
            <button
              key={option.option_key}
              type="button"
              className={`sp-opt ${selected === option.option_key ? 'on' : ''}`}
              onClick={() => {
                setSelected(option.option_key);
                selectedRef.current = option.option_key;
              }}
            >
              <span className="letter">{option.option_key}</span>
              <span className="body">{option.body}</span>
            </button>
          ))}
        </div>

        <div className="sp-row between" style={{ marginTop: 18 }}>
          <span className="sp-tiny sp-muted">
            Press {KEYS.slice(0, question.options.length).join(' / ')} to choose, Enter to send.
          </span>
          <button
            className="sp-btn primary"
            onClick={() => void submit()}
            disabled={!selected || sending}
            type="button"
          >
            {sending ? 'Sending…' : state.answered + 1 >= state.length ? 'Finish' : 'Next question'}
          </button>
        </div>
        {issue ? (
          <p className="sp-small" style={{ color: '#b00020' }}>
            {issue}
          </p>
        ) : null}
      </main>
    </div>
  );
}

function Waiting({ subjectName, issue }: { subjectName: string; issue: string | null }) {
  return (
    <div className="sp">
      <header className="sp-topbar">
        <div className="sp-title">
          <span className="sp-kicker">Check-up</span>
          <h1>{subjectName}</h1>
        </div>
      </header>
      <main className="sp-content">
        <div className={`sp-card ${issue ? 'pinkish' : ''}`}>
          <p className="sp-small sp-muted" style={{ margin: 0 }}>
            {issue ?? 'Finding your place…'}
          </p>
        </div>
      </main>
    </div>
  );
}
