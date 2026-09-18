/**
 * The check-up: the first sitting a student takes, which decides what to teach them.
 *
 * It is deliberately not exam-shaped. There is no timer on screen, no running score and no
 * "question 7 of 15 — 4 correct": a student who can see they are getting things wrong
 * starts guessing to protect the number, and guesses teach the engine nothing. What the
 * screen does show is progress and the topic, because knowing the sitting is short and
 * knowing what is being asked about are both reassuring.
 *
 * Answers are timed anyway — the engine treats a right answer that took three times as long
 * as expected differently from a quick one — but the student is never shown a clock.
 *
 * Until there is a sign-in (ADR-0013), the student comes from the developer endpoint: each
 * run creates a new one, which is also the honest way to re-test a first check-up, since a
 * first check-up means a student with no history.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  api,
  type CheckupReport,
  type CheckupState,
  type SandboxSubject,
} from './api.js';

type Phase = 'choosing' | 'asking' | 'finished' | 'failed';

export function CheckupPage() {
  const [phase, setPhase] = useState<Phase>('choosing');
  const [subjects, setSubjects] = useState<SandboxSubject[]>([]);
  const [studentName, setStudentName] = useState<string | null>(null);
  const [state, setState] = useState<CheckupState | null>(null);
  const [report, setReport] = useState<CheckupReport | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** When the current question appeared, so the answer can be timed. */
  const shownAt = useRef<number>(0);
  /**
   * The selection, mirrored where the key handler can always see the latest value. Reading
   * `selected` from the closure loses a fast "B then Enter": the second key can arrive
   * before React has re-registered the listener, and the Enter is silently dropped.
   */
  const selectedRef = useRef<string | null>(null);

  useEffect(() => {
    api
      .subjects()
      .then(setSubjects)
      .catch((cause: Error) => {
        setError(cause.message);
        setPhase('failed');
      });
  }, []);

  const begin = useCallback(async (subjectId: string) => {
    setBusy(true);
    setError(null);
    try {
      const student = await api.createStudent();
      setStudentName(student.display_name);
      const next = await api.start(student.student_id, subjectId);
      setSelected(null);
      selectedRef.current = null;
      shownAt.current = performance.now();
      setPhase(next.finished || !next.question ? 'finished' : 'asking');
      setState(next);
      if (next.finished || !next.question) setReport(await api.report(next.session_id));
    } catch (cause) {
      setError((cause as Error).message);
      setPhase('failed');
    } finally {
      setBusy(false);
    }
  }, []);

  const choose = useCallback((optionKey: string) => {
    setSelected(optionKey);
    selectedRef.current = optionKey;
  }, []);

  const submit = useCallback(async () => {
    const chosen = selectedRef.current;
    if (!state?.question || !chosen || busy) return;
    setBusy(true);
    setError(null);
    try {
      const elapsed = Math.round(performance.now() - shownAt.current);
      const next = await api.answer(
        state.session_id,
        state.question.question_version_id,
        chosen,
        elapsed,
      );
      setSelected(null);
      selectedRef.current = null;
      shownAt.current = performance.now();
      // The phase moves before the report is fetched, not after. Awaiting first would let
      // React paint one frame holding the last answer's state with no question in it, and
      // the question view would read position off null — which is exactly what it did.
      if (next.finished || !next.question) setPhase('finished');
      setState(next);
      if (next.finished || !next.question) {
        setReport(await api.report(next.session_id));
      }
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }, [state, busy]);

  // A, B, C, D to choose and Enter to submit: the same keyboard-first habit as the review
  // screen, and much faster than reaching for the mouse fifteen times.
  useEffect(() => {
    if (phase !== 'asking' || !state?.question) return;
    const onKey = (event: KeyboardEvent) => {
      const keys = state.question?.options.map((option) => option.option_key) ?? [];
      const pressed = event.key.toUpperCase();
      if (keys.includes(pressed)) {
        choose(pressed);
        event.preventDefault();
      } else if (event.key === 'Enter' && selectedRef.current) {
        void submit();
        event.preventDefault();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [phase, state, choose, submit]);

  if (phase === 'failed') {
    return (
      <main className="checkup">
        <h1>Check-up</h1>
        <p className="error">{error}</p>
        <p className="muted">
          A check-up needs a subject whose questions have passed review and licensing. If none
          is listed, that is the reason.
        </p>
      </main>
    );
  }

  if (phase === 'choosing') {
    return (
      <main className="checkup">
        <h1>Let us find out where you stand</h1>
        <p className="lede">
          A few questions, about fifteen minutes. It is not a test and there is no score to
          beat — the point is to work out what to teach you first.
        </p>
        {subjects.length === 0 ? (
          <p className="muted">No subject is ready yet: nothing has passed review.</p>
        ) : (
          <ul className="subject-list">
            {subjects.map((subject) => (
              <li key={subject.subject_id}>
                <button type="button" disabled={busy} onClick={() => void begin(subject.subject_id)}>
                  <span className="subject-name">{subject.subject_name}</span>
                  <span className="muted">{subject.examination}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </main>
    );
  }

  if (phase === 'finished') {
    return report ? (
      <Report report={report} studentName={studentName} onRestart={() => setPhase('choosing')} />
    ) : (
      <main className="checkup">
        <h1>Working out what we found…</h1>
      </main>
    );
  }

  // A sitting can also end because the bank ran dry mid-way: the engine returns no question
  // rather than repeating one. Either way there is nothing to render here.
  const question = state?.question;
  if (!question) {
    return (
      <main className="checkup">
        <h1>Working out what we found…</h1>
      </main>
    );
  }
  const progress = state ? (state.answered / state.length) * 100 : 0;

  return (
    <main className="checkup">
      <header className="checkup-header">
        <div className="progress" aria-label={`Question ${question.position} of ${question.of}`}>
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <p className="muted">
          Question {question.position} of {question.of} · {question.topic_name}
        </p>
      </header>

      {question.passage_body && (
        <section className="passage">
          {question.passage_title && <h2>{question.passage_title}</h2>}
          <p>{question.passage_body}</p>
        </section>
      )}
      {question.instructions && <p className="instructions">{question.instructions}</p>}

      <h1 className="stem">{question.stem}</h1>

      <ul className="options">
        {question.options.map((option) => (
          <li key={option.option_key}>
            <button
              type="button"
              className={selected === option.option_key ? 'option selected' : 'option'}
              aria-pressed={selected === option.option_key}
              onClick={() => choose(option.option_key)}
            >
              <span className="option-key">{option.option_key}</span>
              <span>{option.body}</span>
            </button>
          </li>
        ))}
      </ul>

      {error && <p className="error">{error}</p>}

      <footer className="checkup-footer">
        <button type="button" className="primary" disabled={!selected || busy} onClick={() => void submit()}>
          {busy ? 'Saving…' : 'Next'}
        </button>
        <p className="muted">Press A–D to choose, Enter to continue.</p>
      </footer>
    </main>
  );
}

function Report({
  report,
  studentName,
  onRestart,
}: {
  report: CheckupReport;
  studentName: string | null;
  onRestart: () => void;
}) {
  // priority_topics carries display names, not ids — the API resolves them for the reader.
  const assessed = report.topics.filter((topic) => topic.answered > 0);
  const priority = report.priority_topics
    .map((name) => assessed.find((topic) => topic.name === name))
    .filter((topic): topic is NonNullable<typeof topic> => Boolean(topic));

  return (
    <main className="checkup">
      <h1>Here is what we found</h1>
      {studentName && <p className="muted">{studentName}</p>}
      <p className="lede">{report.caveat}</p>

      {priority.length > 0 && (
        <section>
          <h2>Where to start</h2>
          <ol className="priority">
            {priority.slice(0, 3).map((topic) => (
              <li key={topic.topic_id}>
                <strong>{topic.name}</strong>{' '}
                <span className="muted">
                  {topic.correct} of {topic.answered} right
                  {topic.slow && ' · slower than expected'}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section>
        <h2>Every topic we looked at</h2>
        <table className="topics">
          <thead>
            <tr>
              <th>Topic</th>
              <th>Asked</th>
              <th>Right</th>
              <th>Reading</th>
              <th>How sure we are</th>
            </tr>
          </thead>
          <tbody>
            {report.topics.map((topic) => (
              <tr key={topic.topic_id}>
                <td>{topic.name}</td>
                <td>{topic.answered}</td>
                <td>{topic.answered > 0 ? topic.correct : '—'}</td>
                <td>{topic.mastery === null ? 'not looked at' : `${Math.round(topic.mastery * 100)}%`}</td>
                <td className="muted">{topic.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {report.unassessed_topics.length > 0 && (
        <p className="muted">
          {report.unassessed_topics.length} topic
          {report.unassessed_topics.length === 1 ? ' was' : 's were'} not reached. That is not a
          verdict on them — we simply did not ask.
        </p>
      )}

      <button type="button" className="primary" onClick={onRestart}>
        Start again as a new student
      </button>
    </main>
  );
}
