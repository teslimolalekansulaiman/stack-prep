/**
 * What the check-up found, and what study could make of it.
 *
 * The screen is ordered the way a student reads it: the number first, then where the number
 * comes from, then what to do about it. The subtopic list is the part that earns its place —
 * "Lexis and Structure, 62%" is not something anyone can act on, while "Synonyms 80%,
 * Idiomatic usage 35%" decides what Saturday morning is for.
 *
 * Every number carries what stands behind it. A subtopic the sitting never reached shows as
 * "not checked" rather than as a low score, because silence is not evidence of weakness and
 * showing it as zero would invent a gap the student does not have.
 */

import { useEffect, useState } from 'react';

import { api, type CheckupReport, type PlanLine, type SubtopicReport } from './api.js';
import './theme.css';

const percent = (value: number) => `${Math.round(value * 100)}%`;

function bandFor(mastery: number | null): string {
  if (mastery === null) return 'grey';
  if (mastery >= 0.75) return 'green';
  if (mastery >= 0.5) return 'mint';
  return 'pink';
}

function labelFor(mastery: number | null): string {
  if (mastery === null) return 'not checked';
  if (mastery >= 0.75) return 'strong';
  if (mastery >= 0.5) return 'holding';
  if (mastery >= 0.3) return 'shaky';
  return 'needs teaching';
}

export function Result({
  sessionId,
  onRestart,
  onTrain,
}: {
  sessionId: string;
  onRestart: () => void;
  /** Absent until the subject is known; training starts where the plan says to start. */
  onTrain?: () => Promise<void>;
}) {
  const [report, setReport] = useState<CheckupReport | null>(null);
  const [issue, setIssue] = useState<string | null>(null);

  useEffect(() => {
    api.report(sessionId).then(setReport).catch((error: Error) => setIssue(error.message));
  }, [sessionId]);

  if (issue) {
    return (
      <div className="sp">
        <main className="sp-content">
          <div className="sp-card pinkish">
            <h2>Your result could not be loaded</h2>
            <p className="sp-small">{issue}</p>
          </div>
        </main>
      </div>
    );
  }
  if (!report) {
    return (
      <div className="sp">
        <main className="sp-content">
          <div className="sp-card">
            <p className="sp-small sp-muted" style={{ margin: 0 }}>
              Working out where you stand…
            </p>
          </div>
        </main>
      </div>
    );
  }

  const projection = report.projection;
  const byTopic = new Map<string, SubtopicReport[]>();
  for (const subtopic of report.subtopics) {
    byTopic.set(subtopic.topic_name, [...(byTopic.get(subtopic.topic_name) ?? []), subtopic]);
  }
  const worked = projection?.plan.filter((line) => line.sessions > 0) ?? [];

  return (
    <div className="sp">
      <header className="sp-topbar">
        <div className="sp-title">
          <span className="sp-kicker">Your check-up</span>
          <h1>Where you stand</h1>
        </div>
      </header>
      <main className="sp-content">
        <div className="sp-two">
          <div className="sp-card dark hard">
            <span className="sp-eyebrow">Estimated today</span>
            {projection ? (
              <>
                <div className="sp-hero-num" style={{ margin: '12px 0 6px' }}>
                  {projection.score_now}
                  <span style={{ fontSize: 20, color: '#d7bdff' }}> / 100</span>
                </div>
                <p className="sp-tiny sp-muted" style={{ margin: 0 }}>
                  likely between {projection.score_low} and {projection.score_high}, from{' '}
                  {report.answered} question{report.answered === 1 ? '' : 's'}
                </p>
                <div
                  className="sp-grid3"
                  style={{ marginTop: 18, borderTop: '1px solid #3a1a70', paddingTop: 16 }}
                >
                  <div className="sp-stat">
                    <b style={{ color: '#85de4c' }}>{projection.score_projected}</b>
                    <small style={{ color: '#c9b8ea' }}>after your plan</small>
                  </div>
                  <div className="sp-stat">
                    <b style={{ color: '#f4fe6e' }}>{projection.target_score ?? '—'}</b>
                    <small style={{ color: '#c9b8ea' }}>your target</small>
                  </div>
                  <div className="sp-stat">
                    <b>{projection.sessions_available}</b>
                    <small style={{ color: '#c9b8ea' }}>sessions left</small>
                  </div>
                </div>
              </>
            ) : (
              <p className="sp-small sp-muted" style={{ marginTop: 12 }}>
                Set a target score and an exam date and this becomes a projection you can plan
                against.
              </p>
            )}
          </div>
          <div className="sp-stack">
            {projection?.shortfall_note ? (
              <div className="sp-notice warn">{projection.shortfall_note}</div>
            ) : projection ? (
              <div className="sp-notice ok">
                On the hours you gave us, this plan reaches {projection.score_projected} — past
                your target of {projection.target_score}.
              </div>
            ) : null}
            <div className="sp-card lav">
              <b className="sp-small">How the score is worked out</b>
              <p className="sp-small" style={{ margin: '6px 0 0' }}>
                Each part of the syllabus is worth what the exam itself gives it, and your score
                is how much of each part you have. Nothing is curved.
              </p>
              <p className="sp-tiny sp-muted" style={{ margin: '8px 0 0' }}>
                Weights: {report.weights_source}.
              </p>
            </div>
          </div>
        </div>

        <h2 style={{ margin: '26px 0 12px', fontSize: 20 }}>Subtopic by subtopic</h2>
        <div className="sp-three">
          {[...byTopic.entries()].map(([topic, subtopics]) => (
            <div className="sp-card" key={topic}>
              <div className="sp-row between">
                <h3 style={{ margin: 0 }}>{topic}</h3>
                <span className="sp-tiny sp-muted">
                  {percent(subtopics.reduce((total, s) => total + s.share, 0))} of the paper
                </span>
              </div>
              <div style={{ marginTop: 10 }}>
                {subtopics.map((subtopic) => (
                  <div key={subtopic.subtopic_id} style={{ padding: '10px 0' }}>
                    <div className="sp-row between" style={{ marginBottom: 5 }}>
                      <b className="sp-small">{subtopic.name}</b>
                      <span className={`sp-pill ${bandFor(subtopic.mastery)}`}>
                        {labelFor(subtopic.mastery)}
                      </span>
                    </div>
                    <div className={`sp-bar thin ${bandFor(subtopic.mastery)}`}>
                      <i style={{ width: subtopic.mastery ? percent(subtopic.mastery) : '0%' }} />
                    </div>
                    <div className="sp-tiny sp-muted" style={{ marginTop: 4 }}>
                      {subtopic.answered > 0
                        ? `${subtopic.correct} of ${subtopic.answered} right · ${percent(subtopic.share)} of the paper`
                        : `no questions reached it · ${percent(subtopic.share)} of the paper`}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {projection ? (
          <>
            <h2 style={{ margin: '26px 0 4px', fontSize: 20 }}>Where your time goes</h2>
            <p className="sp-small sp-muted" style={{ margin: '0 0 12px' }}>
              Ordered by the marks each is expected to add — not by how weak it is. A subtopic
              worth one question of sixty pays back a sixtieth of the same hour spent on one
              worth ten.
            </p>
            <div className="sp-card">
              <ul className="sp-list">
                {worked.map((line: PlanLine) => (
                  <li key={line.subtopic_id}>
                    <span className="sp-mono" style={{ minWidth: 58, fontWeight: 700 }}>
                      +{line.marks_gained.toFixed(1)}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <b className="sp-small">{line.name}</b>
                      <div className="sp-tiny sp-muted">
                        {line.topic_name} · {percent(line.mastery_now)} →{' '}
                        {percent(line.mastery_projected)} · {line.reason}
                      </div>
                    </div>
                    <span className="sp-pill">{line.sessions} sessions</span>
                  </li>
                ))}
              </ul>
              {worked.length === 0 ? (
                <p className="sp-small sp-muted" style={{ margin: 0 }}>
                  There is no study time left before your exam date, so there is nothing to
                  plan. Moving the date gives the plan something to work with.
                </p>
              ) : null}
            </div>
            <div className="sp-notice" style={{ marginTop: 14 }}>
              {projection.caveat}
            </div>
          </>
        ) : null}

        {report.unassessed_topics.length > 0 ? (
          <div className="sp-notice warn" style={{ marginTop: 14 }}>
            <b>Not reached:</b> {report.unassessed_topics.join(', ')}. These were not sampled, so
            nothing here is a judgement about them.
          </div>
        ) : null}

        <div className="sp-row" style={{ marginTop: 22 }}>
          {onTrain ? (
            <button className="sp-btn primary" onClick={() => void onTrain()} type="button">
              Start training
            </button>
          ) : null}
          <button className="sp-btn light" onClick={onRestart} type="button">
            Back to my subjects
          </button>
        </div>
      </main>
    </div>
  );
}
