/**
 * The student's route into the product: sign in, choose what you are sitting, say what you
 * are aiming at, take the check-up, read what it found.
 *
 * Two rules decide where state lives. The identity sits in localStorage, because there is no
 * sign-in yet and something has to remember who this is between reloads. Everything else —
 * the goal, the sitting, every answer — goes to the database the moment it is made, so a
 * closed tab costs nothing and a reopened one resumes rather than restarts. Nothing here is
 * a mock: the rows it writes are the rows the real product reads.
 */

import { useCallback, useEffect, useState } from 'react';

import { api, type ExaminationOffer, type Goal, type Sitting, type SubjectOffer } from './api.js';
import { Diagnostic } from './Diagnostic.js';
import { Practice } from './Practice.js';
import { Result } from './Result.js';
import './theme.css';

const IDENTITY_KEY = 'scorepilot.student';
const PLACE_KEY = 'scorepilot.place';

export interface Identity {
  studentId: string;
  displayName: string;
}

interface Place {
  examinationId?: string;
  subjectId?: string;
  sessionId?: string;
  practiceId?: string;
}

type Step =
  | 'welcome'
  | 'exam'
  | 'subject'
  | 'goal'
  | 'intro'
  | 'sitting'
  | 'result'
  | 'training';

function readIdentity(): Identity | null {
  try {
    const raw = localStorage.getItem(IDENTITY_KEY);
    return raw ? (JSON.parse(raw) as Identity) : null;
  } catch {
    return null;
  }
}

function readPlace(): Place {
  try {
    return JSON.parse(localStorage.getItem(PLACE_KEY) ?? '{}') as Place;
  } catch {
    return {};
  }
}

function writePlace(place: Place) {
  try {
    localStorage.setItem(PLACE_KEY, JSON.stringify(place));
  } catch {
    /* a browser with storage disabled still works; it just forgets where it was */
  }
}

function Shell({
  kicker,
  title,
  onBack,
  children,
}: {
  kicker: string;
  title: string;
  onBack?: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="sp">
      <header className="sp-topbar">
        {onBack ? (
          <button className="sp-btn sm light" onClick={onBack} type="button">
            Back
          </button>
        ) : null}
        <div className="sp-title">
          <span className="sp-kicker">{kicker}</span>
          <h1>{title}</h1>
        </div>
      </header>
      <main className="sp-content">{children}</main>
    </div>
  );
}

export function StudentApp() {
  const [identity, setIdentity] = useState<Identity | null>(readIdentity);
  const [place, setPlace] = useState<Place>(readPlace);
  const [step, setStep] = useState<Step>(() => (readIdentity() ? 'exam' : 'welcome'));
  const [catalogue, setCatalogue] = useState<ExaminationOffer[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [sittings, setSittings] = useState<Sitting[]>([]);
  const [error, setError] = useState<string | null>(null);

  const remember = useCallback((next: Place) => {
    setPlace((current) => {
      const merged = { ...current, ...next };
      writePlace(merged);
      return merged;
    });
  }, []);

  useEffect(() => {
    api.catalogue().then(setCatalogue).catch((issue: Error) => setError(issue.message));
  }, []);

  useEffect(() => {
    if (!identity) return;
    api.goals(identity.studentId).then(setGoals).catch(() => setGoals([]));
    api.sittings(identity.studentId).then(setSittings).catch(() => setSittings([]));
  }, [identity, step]);

  const examination = catalogue.find((e) => e.examination_id === place.examinationId);
  const subject = examination?.subjects.find((s) => s.subject_id === place.subjectId);
  const goal = goals.find((g) => g.subject_id === place.subjectId);

  if (error) {
    return (
      <Shell kicker="Score Pilot" title="Something is not answering">
        <div className="sp-card pinkish">
          <h2>The app could not reach the server</h2>
          <p className="sp-small">{error}</p>
          <p className="sp-small sp-muted">
            Start it with <code>make api</code> and reload this page.
          </p>
        </div>
      </Shell>
    );
  }

  if (step === 'welcome' || !identity) {
    return <Welcome onSignedIn={(who) => { setIdentity(who); setStep('exam'); }} />;
  }

  if (step === 'exam') {
    return (
      <Shell kicker={`Signed in as ${identity.displayName}`} title="What are you sitting?">
        <ChooseExam
          catalogue={catalogue}
          onPick={(id) => {
            remember({ examinationId: id, subjectId: undefined, sessionId: undefined });
            setStep('subject');
          }}
          onSignOut={() => {
            localStorage.removeItem(IDENTITY_KEY);
            localStorage.removeItem(PLACE_KEY);
            setIdentity(null);
            setPlace({});
            setStep('welcome');
          }}
        />
      </Shell>
    );
  }

  if (step === 'subject' && examination) {
    const unfinished = sittings.find((s) => !s.finished);
    return (
      <Shell
        kicker={examination.short_name}
        title="Choose a subject"
        onBack={() => setStep('exam')}
      >
        <ChooseSubject
          examination={examination}
          goals={goals}
          unfinished={unfinished}
          onResume={(sitting) => {
            remember({ subjectId: sitting.subject_id, sessionId: sitting.session_id });
            setStep('sitting');
          }}
          onPick={(picked) => {
            remember({ subjectId: picked.subject_id, sessionId: undefined });
            setStep('goal');
          }}
          onTrain={async (picked) => {
            const started = await api.startPractice(identity.studentId, picked.subject_id);
            remember({ subjectId: picked.subject_id, practiceId: started.session_id });
            setStep('training');
          }}
          sat={new Set(sittings.filter((s) => s.finished).map((s) => s.subject_id))}
        />
      </Shell>
    );
  }

  if (step === 'goal' && subject) {
    return (
      <Shell kicker={subject.name} title="What are you aiming at?" onBack={() => setStep('subject')}>
        <GoalForm
          subject={subject}
          existing={goal}
          onSaved={() => setStep('intro')}
          studentId={identity.studentId}
        />
      </Shell>
    );
  }

  if (step === 'intro' && subject) {
    return (
      <Shell kicker={subject.name} title="Your check-up" onBack={() => setStep('goal')}>
        <Intro
          subject={subject}
          goal={goal}
          onStart={async () => {
            const state = await api.start(identity.studentId, subject.subject_id);
            remember({ sessionId: state.session_id });
            setStep('sitting');
          }}
        />
      </Shell>
    );
  }

  if (step === 'sitting' && place.sessionId && subject) {
    return (
      <Diagnostic
        sessionId={place.sessionId}
        subjectName={subject.name}
        onFinished={() => setStep('result')}
      />
    );
  }

  if (step === 'result' && place.sessionId) {
    return (
      <Result
        sessionId={place.sessionId}
        onRestart={() => {
          remember({ subjectId: undefined, sessionId: undefined });
          setStep('subject');
        }}
        onTrain={
          subject
            ? async () => {
                const started = await api.startPractice(identity.studentId, subject.subject_id);
                remember({ practiceId: started.session_id });
                setStep('training');
              }
            : undefined
        }
      />
    );
  }

  if (step === 'training' && place.practiceId && subject) {
    return (
      <Practice
        sessionId={place.practiceId}
        subjectName={subject.name}
        onFinished={() => {
          remember({ practiceId: undefined });
          setStep('subject');
        }}
      />
    );
  }

  // Any state the steps above do not cover means the remembered place no longer matches the
  // catalogue — a subject withdrawn, say. Start from the top rather than showing a blank.
  return (
    <Shell kicker="Score Pilot" title="Let's start again">
      <div className="sp-card">
        <p className="sp-small">That subject is no longer available.</p>
        <button className="sp-btn primary" onClick={() => setStep('exam')} type="button">
          Choose again
        </button>
      </div>
    </Shell>
  );
}

function Welcome({ onSignedIn }: { onSignedIn: (identity: Identity) => void }) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [issue, setIssue] = useState<string | null>(null);

  const signIn = async () => {
    setBusy(true);
    setIssue(null);
    try {
      const created = await api.createStudent(name.trim() || undefined);
      const identity = { studentId: created.student_id, displayName: created.display_name };
      localStorage.setItem(IDENTITY_KEY, JSON.stringify(identity));
      onSignedIn(identity);
    } catch (error) {
      setIssue((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sp">
      <div className="sp-auth">
        <div className="sp-brand">
          <span className="sp-mark">SP</span> Score Pilot
        </div>
        <div className="sp-card hard">
          <h2>Let&rsquo;s find out where you stand.</h2>
          <p className="sp-small sp-muted" style={{ marginTop: 6 }}>
            One short check-up per subject. There is no pass or fail — it decides where your
            teaching starts.
          </p>
          <label className="sp-field" style={{ marginTop: 18 }}>
            <span>Your name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Ada Okafor"
              onKeyDown={(event) => event.key === 'Enter' && void signIn()}
            />
          </label>
          <button className="sp-btn primary block" onClick={() => void signIn()} disabled={busy}>
            {busy ? 'Setting you up…' : 'Start'}
          </button>
          {issue ? (
            <p className="sp-small" style={{ color: '#b00020', marginBottom: 0 }}>
              {issue}
            </p>
          ) : null}
        </div>
        <p className="sp-tiny sp-muted" style={{ marginTop: 14 }}>
          There is no password yet. This creates a real student record with consent recorded,
          and your browser remembers it — so you can come back to an unfinished check-up.
        </p>
      </div>
    </div>
  );
}

function ChooseExam({
  catalogue,
  onPick,
  onSignOut,
}: {
  catalogue: ExaminationOffer[];
  onPick: (examinationId: string) => void;
  onSignOut: () => void;
}) {
  return (
    <>
      <p className="sp-small sp-muted" style={{ margin: '0 0 14px' }}>
        Pick the examination you are preparing for.
      </p>
      <div className="sp-stack">
        {catalogue.map((exam) => {
          const ready = exam.subjects.filter((s) => s.ready).length;
          return (
            <button
              key={exam.examination_id}
              className="sp-opt"
              onClick={() => onPick(exam.examination_id)}
              type="button"
            >
              <span className="letter">{exam.short_name.slice(0, 2)}</span>
              <span className="body">
                <b>{exam.short_name}</b>
                <small>
                  {exam.exam_body} · {exam.subjects.length} subject
                  {exam.subjects.length === 1 ? '' : 's'}
                  {ready ? `, ${ready} ready` : ', none ready yet'}
                </small>
              </span>
            </button>
          );
        })}
        {catalogue.length === 0 ? (
          <div className="sp-card lav">
            <p className="sp-small" style={{ margin: 0 }}>
              No examination is switched on yet.
            </p>
          </div>
        ) : null}
      </div>
      <button className="sp-btn sm light" style={{ marginTop: 18 }} onClick={onSignOut} type="button">
        Sign out
      </button>
    </>
  );
}

function ChooseSubject({
  examination,
  goals,
  unfinished,
  onPick,
  onResume,
  onTrain,
  sat,
}: {
  examination: ExaminationOffer;
  goals: Goal[];
  unfinished: Sitting | undefined;
  onPick: (subject: SubjectOffer) => void;
  onResume: (sitting: Sitting) => void;
  onTrain: (subject: SubjectOffer) => Promise<void>;
  sat: Set<string>;
}) {
  return (
    <>
      {unfinished ? (
        <div className="sp-card yellow" style={{ marginBottom: 16 }}>
          <h2>You have a check-up in progress</h2>
          <p className="sp-small" style={{ margin: '6px 0 12px' }}>
            {unfinished.subject_name} · {unfinished.answered} answered. Your answers are saved;
            carry on where you stopped.
          </p>
          <button className="sp-btn sm primary" onClick={() => onResume(unfinished)} type="button">
            Resume
          </button>
        </div>
      ) : null}
      <div className="sp-stack">
        {examination.subjects.map((subject) => {
          const goal = goals.find((g) => g.subject_id === subject.subject_id);
          return (
            <div key={subject.subject_id} className={`sp-card ${subject.ready ? '' : 'flat'}`}>
              <div className="sp-row between">
                <div>
                  <h3>{subject.name}</h3>
                  <p className="sp-tiny sp-muted" style={{ margin: '4px 0 0' }}>
                    {subject.teachable_skills} skills on the syllabus ·{' '}
                    {subject.deliverable_questions} questions ready
                  </p>
                </div>
                {subject.ready ? (
                  <span className="sp-pill green">ready</span>
                ) : (
                  <span className="sp-pill grey">not yet</span>
                )}
              </div>
              {goal?.target_score ? (
                <p className="sp-tiny sp-muted" style={{ margin: '8px 0 0' }}>
                  Aiming at {goal.target_score} by {goal.exam_date}.
                </p>
              ) : null}
              {subject.blocked_reason ? (
                <p className="sp-small sp-muted" style={{ margin: '10px 0 0' }}>
                  {subject.blocked_reason}
                </p>
              ) : (
                <div className="sp-row" style={{ marginTop: 12 }}>
                  <button
                    className="sp-btn primary sm"
                    onClick={() => onPick(subject)}
                    type="button"
                  >
                    {goal ? 'Continue' : 'Start here'}
                  </button>
                  {sat.has(subject.subject_id) ? (
                    <button
                      className="sp-btn sm light"
                      onClick={() => void onTrain(subject)}
                      type="button"
                    >
                      Train
                    </button>
                  ) : null}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function GoalForm({
  subject,
  existing,
  studentId,
  onSaved,
}: {
  subject: SubjectOffer;
  existing: Goal | undefined;
  studentId: string;
  onSaved: () => void;
}) {
  const [target, setTarget] = useState(String(existing?.target_score ?? 70));
  const [examDate, setExamDate] = useState(existing?.exam_date ?? '');
  const [minutes, setMinutes] = useState(String(existing?.minutes_per_day ?? 45));
  const [days, setDays] = useState<number[]>(existing?.study_days ?? [1, 2, 3, 4, 5]);
  const [busy, setBusy] = useState(false);
  const [issue, setIssue] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setIssue(null);
    try {
      await api.setGoal(studentId, subject.subject_id, {
        target_score: Number(target),
        exam_date: examDate,
        minutes_per_day: Number(minutes),
        study_days: days,
      });
      onSaved();
    } catch (error) {
      setIssue((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const complete = Number(target) > 0 && examDate !== '' && days.length > 0;

  return (
    <div className="sp-two">
      <div className="sp-card">
        <h2>Your goal for {subject.name}</h2>
        <p className="sp-small sp-muted" style={{ margin: '6px 0 16px' }}>
          This is what turns the check-up into a plan. Without a date there is nothing to count
          study towards, and without a target there is nothing to measure the plan against.
        </p>
        <label className="sp-field">
          <span>Score you are aiming for, out of 100</span>
          <input
            type="number"
            min={1}
            max={100}
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          />
        </label>
        <label className="sp-field">
          <span>When is the exam?</span>
          <input
            type="date"
            value={examDate}
            onChange={(event) => setExamDate(event.target.value)}
          />
        </label>
        <label className="sp-field">
          <span>Minutes you can study on a study day</span>
          <input
            type="number"
            min={5}
            max={600}
            step={15}
            value={minutes}
            onChange={(event) => setMinutes(event.target.value)}
          />
        </label>
        <div className="sp-field">
          <span>Which days?</span>
          <div className="sp-days">
            {DAY_NAMES.map((label, index) => {
              const day = index + 1;
              const on = days.includes(day);
              return (
                <button
                  key={label}
                  type="button"
                  className={on ? 'on' : ''}
                  onClick={() =>
                    setDays((current) =>
                      on ? current.filter((d) => d !== day) : [...current, day].sort(),
                    )
                  }
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
        <button
          className="sp-btn primary block"
          onClick={() => void save()}
          disabled={busy || !complete}
          type="button"
        >
          {busy ? 'Saving…' : 'Save and continue'}
        </button>
        {issue ? (
          <p className="sp-small" style={{ color: '#b00020', marginBottom: 0 }}>
            {issue}
          </p>
        ) : null}
      </div>
      <div className="sp-stack">
        <div className="sp-card lav">
          <b className="sp-small">Why we ask for the days</b>
          <p className="sp-small" style={{ margin: '6px 0 0' }}>
            The plan counts sessions, not good intentions. Telling us four evenings gives you a
            plan built on four evenings — and a projection you can hold us to.
          </p>
        </div>
        <div className="sp-card flat">
          <b className="sp-small">You can change this later</b>
          <p className="sp-small sp-muted" style={{ margin: '6px 0 0' }}>
            The goal is a current intention, not a contract. Moving the date or the hours
            re-plans everything.
          </p>
        </div>
      </div>
    </div>
  );
}

function Intro({
  subject,
  goal,
  onStart,
}: {
  subject: SubjectOffer;
  goal: Goal | undefined;
  onStart: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [issue, setIssue] = useState<string | null>(null);
  return (
    <div className="sp-two">
      <div className="sp-card">
        <h2>Before you start</h2>
        <ul className="sp-small" style={{ margin: '10px 0 0', paddingLeft: 18 }}>
          <li>About 15 questions, spread across the whole syllabus.</li>
          <li>
            The questions adapt: get one right and the next in that topic is harder, get one
            wrong and it is easier.
          </li>
          <li>Nothing here counts towards your score. It decides where your teaching starts.</li>
          <li>You can stop at any point — every answer is saved as you give it.</li>
        </ul>
        <button
          className="sp-btn primary block"
          style={{ marginTop: 18 }}
          disabled={busy}
          type="button"
          onClick={() => {
            setBusy(true);
            setIssue(null);
            onStart().catch((error: Error) => {
              setIssue(error.message);
              setBusy(false);
            });
          }}
        >
          {busy ? 'Setting up…' : 'Start the check-up'}
        </button>
        {issue ? (
          <p className="sp-small" style={{ color: '#b00020', marginBottom: 0 }}>
            {issue}
          </p>
        ) : null}
      </div>
      <div className="sp-stack">
        {goal?.sessions_before_exam != null ? (
          <div className="sp-card dark">
            <span className="sp-eyebrow">Your runway</span>
            <div className="sp-hero-num" style={{ margin: '12px 0 6px' }}>
              {goal.sessions_before_exam}
            </div>
            <p className="sp-small sp-muted" style={{ margin: 0 }}>
              study sessions before {goal.exam_date}, at {goal.minutes_per_day} minutes on each of
              your {goal.study_days?.length ?? 0} days.
            </p>
          </div>
        ) : null}
        <div className="sp-card lav">
          <b className="sp-small">What we look at</b>
          <p className="sp-small" style={{ margin: '6px 0 0' }}>
            Which subtopic each question belongs to, how hard it was, whether you got it right
            and how long you took. A right answer that took three times as long is a different
            result from a quick one.
          </p>
        </div>
        <div className="sp-card flat">
          <b className="sp-small">{subject.deliverable_questions} questions available</b>
          <p className="sp-tiny sp-muted" style={{ margin: '6px 0 0' }}>
            You will not be asked one you have already seen, so sitting this again gives you a
            different check-up.
          </p>
        </div>
      </div>
    </div>
  );
}
