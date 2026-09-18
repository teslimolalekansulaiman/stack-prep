/**
 * Guided practice: the loop that runs after the check-up.
 *
 * Ask, and if the answer is wrong, help rather than mark. One hint and the same question
 * again; miss it again and the board writes the working out. A question that had to be
 * explained is counted as taught, not as known, and the screen says so — if a student leaves
 * thinking eight out of ten means they know eight, the number has taught them the wrong thing.
 *
 * The confidence question is asked between answering and being told. That order matters: it
 * is a question about what they thought, and once the screen has said "correct" nobody
 * remembers having guessed.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, type PracticeState } from './api.js';
import { Board } from './Board.js';
import './theme.css';

type Confidence = 'sure' | 'unsure' | 'guessed';

const CONFIDENCE: { value: Confidence; label: string }[] = [
  { value: 'sure', label: 'I knew it' },
  { value: 'unsure', label: 'I think so' },
  { value: 'guessed', label: 'I guessed' },
];

export function Practice({
  sessionId,
  subjectName,
  onFinished,
}: {
  sessionId: string;
  subjectName: string;
  onFinished: () => void;
}) {
  const [state, setState] = useState<PracticeState | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [issue, setIssue] = useState<string | null>(null);
  const askedAt = useRef<number>(Date.now());
  const finishRef = useRef(onFinished);

  useEffect(() => {
    finishRef.current = onFinished;
  }, [onFinished]);

  useEffect(() => {
    let cancelled = false;
    api
      .practiceCurrent(sessionId)
      .then((next) => {
        if (cancelled) return;
        setState(next);
        askedAt.current = Date.now();
      })
      .catch((error: Error) => !cancelled && setIssue(error.message));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const send = useCallback(
    async (confidence: Confidence | null) => {
      const question = state?.question;
      if (!question || !selected) return;
      setBusy(true);
      setAsking(false);
      setIssue(null);
      try {
        const next = await api.practiceAnswer(sessionId, {
          question_version_id: question.question_version_id,
          selected_option_key: selected,
          response_ms: Date.now() - askedAt.current,
          confidence,
        });
        setSelected(null);
        askedAt.current = Date.now();
        setState(next);
      } catch (error) {
        setIssue((error as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [selected, sessionId, state],
  );

  if (issue) {
    return (
      <Shell subjectName={subjectName}>
        <div className="sp-card pinkish">
          <h2>This session could not continue</h2>
          <p className="sp-small">{issue}</p>
        </div>
      </Shell>
    );
  }
  if (!state) {
    return (
      <Shell subjectName={subjectName}>
        <div className="sp-card">
          <p className="sp-small sp-muted" style={{ margin: 0 }}>
            Working out what to teach you…
          </p>
        </div>
      </Shell>
    );
  }

  if (state.stage === 'finished' || !state.question) {
    return (
      <Shell subjectName={subjectName}>
        <div className="sp-card dark hard">
          <span className="sp-eyebrow">Session done</span>
          <div className="sp-grid3" style={{ marginTop: 18 }}>
            <div className="sp-stat">
              <b style={{ color: '#85de4c' }}>{state.correct_unaided}</b>
              <small style={{ color: '#c9b8ea' }}>answered unaided</small>
            </div>
            <div className="sp-stat">
              <b style={{ color: '#f4fe6e' }}>{state.taught}</b>
              <small style={{ color: '#c9b8ea' }}>taught, not known</small>
            </div>
            <div className="sp-stat">
              <b>{state.answered}</b>
              <small style={{ color: '#c9b8ea' }}>questions</small>
            </div>
          </div>
          <p className="sp-small sp-muted" style={{ marginTop: 16, marginBottom: 0 }}>
            {state.closing_note}
          </p>
        </div>
        <button
          className="sp-btn primary"
          style={{ marginTop: 18 }}
          type="button"
          onClick={onFinished}
        >
          Back to my subjects
        </button>
      </Shell>
    );
  }

  const question = state.question;

  if (state.stage === 'explain') {
    return (
      <Board
        title={question.subtopic_name}
        subtitle={`${subjectName} · worked through`}
        steps={state.solution_steps ?? []}
        answerLine={`The answer is ${state.correct_option_key}.`}
        onDone={() => {
          setBusy(true);
          api
            .practiceTaught(sessionId)
            .then((next) => {
              setState(next);
              askedAt.current = Date.now();
            })
            .catch((error: Error) => setIssue(error.message))
            .finally(() => setBusy(false));
        }}
      />
    );
  }

  return (
    <Shell subjectName={subjectName}>
      <div style={{ maxWidth: 480, marginBottom: 14 }}>
        <div className="sp-bar">
          <i style={{ width: `${(state.answered / Math.max(1, state.length)) * 100}%` }} />
        </div>
        <div className="sp-tiny sp-muted" style={{ marginTop: 4 }}>
          {state.answered} of {state.length} · {question.topic_name} · {question.subtopic_name}
        </div>
      </div>

      {state.stage === 'hint' && state.hint ? (
        <div className="sp-notice warn" style={{ marginBottom: 14 }}>
          <b>Not that one.</b> {state.hint}
          {state.misconception ? (
            <div className="sp-tiny" style={{ marginTop: 6 }}>
              That option is the {state.misconception.name.toLowerCase()} mistake —{' '}
              {state.misconception.description}
            </div>
          ) : null}
          <div className="sp-tiny sp-muted" style={{ marginTop: 6 }}>
            Try the same question again. This one no longer counts towards what you know.
          </div>
        </div>
      ) : null}

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
            onClick={() => setSelected(option.option_key)}
            disabled={asking || busy}
          >
            <span className="letter">{option.option_key}</span>
            <span className="body">{option.body}</span>
          </button>
        ))}
      </div>

      {asking ? (
        <div className="sp-card lav" style={{ marginTop: 14 }}>
          <b className="sp-small">Before we mark it — how sure are you?</b>
          <p className="sp-tiny sp-muted" style={{ margin: '4px 0 0' }}>
            A right answer you guessed is not something we should plan around, so this is
            asked before you find out.
          </p>
          <div className="sp-conf">
            {CONFIDENCE.map((choice) => (
              <button key={choice.value} type="button" onClick={() => void send(choice.value)}>
                {choice.label}
              </button>
            ))}
            <button type="button" onClick={() => void send(null)} className="sp-muted">
              Rather not say
            </button>
          </div>
        </div>
      ) : (
        <div className="sp-row" style={{ marginTop: 18, justifyContent: 'flex-end' }}>
          <button
            className="sp-btn primary"
            type="button"
            disabled={!selected || busy}
            onClick={() => setAsking(true)}
          >
            {busy ? 'Sending…' : 'Answer'}
          </button>
        </div>
      )}
    </Shell>
  );
}

function Shell({ subjectName, children }: { subjectName: string; children: React.ReactNode }) {
  return (
    <div className="sp">
      <header className="sp-topbar">
        <div className="sp-title">
          <span className="sp-kicker">Training</span>
          <h1>{subjectName}</h1>
        </div>
      </header>
      <main className="sp-content">{children}</main>
    </div>
  );
}
