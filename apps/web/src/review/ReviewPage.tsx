/**
 * Content review: turn proposed answers, levels and skills into decisions.
 *
 * Built for speed — 200 questions is an afternoon only if the keyboard does the work:
 * A-D sets the answer, 1-5 the level, S approves the skill, Enter approves the question,
 * J/K move through the queue.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  api,
  type Progress,
  type QueueItem,
  type QueueState,
  type QuestionDetail,
  type Reviewer,
  type Skill,
} from './api.js';

const QUEUES: { value: QueueState; label: string }[] = [
  { value: 'needs_review', label: 'Needs review' },
  { value: 'needs_answer', label: 'Answer unchecked' },
  { value: 'needs_level', label: 'Level unchecked' },
  { value: 'flagged', label: 'Flagged' },
  { value: 'ready', label: 'Ready to approve' },
  { value: 'approved', label: 'Approved' },
];

const REVIEWER_KEY = 'score-pilot.reviewer';

export function ReviewPage() {
  const [reviewers, setReviewers] = useState<Reviewer[]>([]);
  const [reviewerId, setReviewerId] = useState<string>('');
  const [queueState, setQueueState] = useState<QueueState>('needs_review');
  const [examYear, setExamYear] = useState<number | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<QuestionDetail | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const typingRef = useRef(false);

  useEffect(() => {
    api.reviewers().then((list) => {
      setReviewers(list);
      const saved = localStorage.getItem(REVIEWER_KEY);
      const known = saved && list.some((r) => r.id === saved) ? saved : list[0]?.id;
      if (known) setReviewerId(known);
    }, reportError);
  }, []);

  const loadQueue = useCallback(async () => {
    try {
      const [list, counts] = await Promise.all([
        api.queue(queueState, examYear),
        api.progress(examYear),
      ]);
      setItems(list);
      setProgress(counts);
      // Deliberately keep the current question selected even once it leaves the queue:
      // a decision must never move the page under the reviewer's next keystroke.
      setSelected((current) => current ?? list[0]?.question_id ?? null);
    } catch (cause) {
      reportError(cause);
    }
  }, [queueState, examYear]);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    api.question(selected).then(setDetail, reportError);
  }, [selected]);

  useEffect(() => {
    if (!detail?.syllabus_version_id) return;
    api.skills(detail.syllabus_version_id).then(setSkills, reportError);
  }, [detail?.syllabus_version_id]);

  function reportError(cause: unknown) {
    setError(cause instanceof Error ? cause.message : String(cause));
  }

  const act = useCallback(
    async (action: () => Promise<QuestionDetail>) => {
      if (!reviewerId || busy) return;
      setBusy(true);
      setError(null);
      try {
        setDetail(await action());
        await loadQueue();
      } catch (cause) {
        reportError(cause);
      } finally {
        setBusy(false);
      }
    },
    [reviewerId, busy, loadQueue],
  );

  const move = useCallback(
    (delta: number) => {
      if (items.length === 0) return;
      const index = items.findIndex((item) => item.question_id === selected);
      if (index === -1) {
        // The current question has left the queue; step into the list from the end nearest
        // the direction of travel.
        setSelected(items[delta > 0 ? 0 : items.length - 1]?.question_id ?? null);
        return;
      }
      const next = Math.min(items.length - 1, Math.max(0, index + delta));
      setSelected(items[next]?.question_id ?? null);
    },
    [items, selected],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (typingRef.current || event.metaKey || event.ctrlKey || event.altKey) return;
      if (!detail || detail.review_status === 'approved') return;
      const key = event.key.toUpperCase();

      if (['A', 'B', 'C', 'D', 'E', 'F'].includes(key) && detail.options.some((o) => o.option_key === key)) {
        event.preventDefault();
        void act(() => api.setAnswer(detail.question_id, reviewerId, key));
      } else if (['1', '2', '3', '4', '5'].includes(key)) {
        event.preventDefault();
        void act(() => api.setLevel(detail.question_id, reviewerId, Number(key)));
      } else if (key === 'S') {
        event.preventDefault();
        void act(() => api.decideSkill(detail.question_id, reviewerId));
      } else if (event.key === 'Enter') {
        event.preventDefault();
        void act(() => api.approve(detail.question_id, reviewerId));
      } else if (key === 'J') {
        move(1);
      } else if (key === 'K') {
        move(-1);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [detail, reviewerId, act, move]);

  const summary = useMemo(() => {
    if (!progress) return `${items.length} in queue`;
    return (
      `${items.length} in queue · answers ${progress.answer_checked}/${progress.total}` +
      ` · levels ${progress.level_checked}/${progress.total}` +
      ` · skills ${progress.skill_approved}/${progress.total}` +
      ` · approved ${progress.approved}` +
      (progress.flagged ? ` · ${progress.flagged} flagged` : '')
    );
  }, [progress, items.length]);

  return (
    <div className="review">
      <header className="review-bar">
        <strong>Question review</strong>
        <label>
          Reviewer
          <select
            value={reviewerId}
            onChange={(event) => {
              setReviewerId(event.target.value);
              localStorage.setItem(REVIEWER_KEY, event.target.value);
            }}
          >
            {reviewers.map((reviewer) => (
              <option key={reviewer.id} value={reviewer.id}>
                {reviewer.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Queue
          <select value={queueState} onChange={(event) => setQueueState(event.target.value as QueueState)}>
            {QUEUES.map((queue) => (
              <option key={queue.value} value={queue.value}>
                {queue.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Paper
          <select
            value={examYear ?? ''}
            onChange={(event) => setExamYear(event.target.value ? Number(event.target.value) : null)}
          >
            <option value="">All years</option>
            <option value="2011">2011</option>
            <option value="2013">2013</option>
          </select>
        </label>
        <span className="review-count">{summary}</span>
        <span className="review-keys">A–D answer · 1–5 level · S skill · ⏎ approve · J/K move</span>
      </header>

      {error && (
        <p className="review-error" role="alert">
          {error}
        </p>
      )}

      <div className="review-body">
        <ol className="review-queue">
          {items.map((item) => (
            <li key={item.question_id}>
              <button
                type="button"
                className={item.question_id === selected ? 'selected' : undefined}
                onClick={() => setSelected(item.question_id)}
              >
                <span className="q-id">
                  {item.exam_year} · Q{item.question_number}
                </span>
                <span className="q-stem">{item.stem}</span>
                <span className="q-flags">
                  <Flag on={item.answer_checked} label="answer" />
                  <Flag on={item.level_checked} label="level" />
                  <Flag on={item.has_approved_skill} label="skill" />
                  {item.open_reports > 0 && <em className="flagged">{item.open_reports} flag</em>}
                </span>
              </button>
            </li>
          ))}
          {items.length === 0 && <li className="empty">Nothing in this queue.</li>}
        </ol>

        {detail ? (
          <QuestionPanel
            detail={detail}
            skills={skills}
            reviewerId={reviewerId}
            busy={busy}
            onAct={act}
            onTyping={(value) => {
              typingRef.current = value;
            }}
          />
        ) : (
          <section className="review-detail empty">Select a question.</section>
        )}
      </div>
    </div>
  );
}

function Flag({ on, label }: { on: boolean; label: string }) {
  return <em className={on ? 'done' : 'todo'}>{on ? `${label} ✓` : label}</em>;
}

interface PanelProps {
  detail: QuestionDetail;
  skills: Skill[];
  reviewerId: string;
  busy: boolean;
  onAct: (action: () => Promise<QuestionDetail>) => Promise<void>;
  onTyping: (value: boolean) => void;
}

function QuestionPanel({ detail, skills, reviewerId, busy, onAct, onTyping }: PanelProps) {
  const [solution, setSolution] = useState('');
  const [hint, setHint] = useState('');

  useEffect(() => {
    setSolution(detail.solution_steps.join('\n'));
    setHint(detail.hints.join('\n'));
  }, [detail.question_version_id, detail.solution_steps, detail.hints]);

  const approved = detail.review_status === 'approved';
  const missing = [
    detail.answer_source === 'expert_verified' || detail.answer_source === 'official_key' ? null : 'answer check',
    detail.level_source === 'expert_verified' || detail.level_source === 'calibrated' ? null : 'level check',
    detail.classification_status === 'approved' ? null : 'skill approval',
    detail.solution_steps.length > 0 ? null : 'worked solution',
    detail.hints.length > 0 ? null : 'hint',
  ].filter(Boolean) as string[];

  return (
    <section className="review-detail">
      <div className="detail-head">
        <h2>
          {detail.exam_year} · Question {detail.question_number}
        </h2>
        <span className={`status ${approved ? 'approved' : 'draft'}`}>{detail.review_status}</span>
      </div>

      {detail.reports.length > 0 && (
        <ul className="reports">
          {detail.reports.map((report) => (
            <li key={report.id}>
              <strong>{report.reason}</strong> {report.detail}
            </li>
          ))}
        </ul>
      )}

      {detail.passage_body && (
        <details className="passage">
          <summary>{detail.passage_title ?? 'Passage'}</summary>
          <p>{detail.passage_body}</p>
        </details>
      )}

      {detail.instructions && <p className="instruction">{detail.instructions}</p>}
      <p className="stem">{detail.stem}</p>

      <ol className="options">
        {detail.options.map((option) => (
          <li key={option.id}>
            <button
              type="button"
              disabled={approved || busy}
              className={option.is_correct ? 'chosen' : undefined}
              onClick={() => onAct(() => api.setAnswer(detail.question_id, reviewerId, option.option_key))}
            >
              <span className="key">{option.option_key}</span>
              <span>{option.body}</span>
            </button>
          </li>
        ))}
      </ol>
      <p className="provenance">
        Answer: {label(detail.answer_source)}
        {detail.answer_confidence ? ` · proposed with ${detail.answer_confidence} confidence` : ''}
      </p>

      <div className="levels">
        {[1, 2, 3, 4, 5].map((level) => (
          <button
            key={level}
            type="button"
            disabled={approved || busy}
            className={detail.mastery_level_number === level ? 'chosen' : undefined}
            onClick={() => onAct(() => api.setLevel(detail.question_id, reviewerId, level))}
          >
            L{level}
          </button>
        ))}
        <span className="provenance">
          Level: {label(detail.level_source)}
          {detail.level_confidence ? ` · ${detail.level_confidence} confidence` : ''}
        </span>
      </div>

      <div className="skill">
        <label>
          Skill
          <select
            value={detail.primary_skill_id ?? ''}
            disabled={approved || busy}
            onChange={(event) =>
              onAct(() => api.decideSkill(detail.question_id, reviewerId, event.target.value))
            }
          >
            {skills.map((skill) => (
              <option key={skill.id} value={skill.id}>
                {skill.code} — {skill.name}
                {skill.topic ? ` (${skill.topic})` : ''}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={approved || busy || detail.classification_status === 'approved'}
          onClick={() => onAct(() => api.decideSkill(detail.question_id, reviewerId))}
        >
          {detail.classification_status === 'approved' ? 'Skill approved' : 'Approve skill (S)'}
        </button>
        {detail.classification_reason && <p className="provenance">{detail.classification_reason}</p>}
      </div>

      <div className="content-edit">
        <label>
          Worked solution — one step per line
          <textarea
            value={solution}
            disabled={approved || busy}
            rows={4}
            onFocus={() => onTyping(true)}
            onBlur={() => onTyping(false)}
            onChange={(event) => setSolution(event.target.value)}
          />
        </label>
        <label>
          Hints — one per line
          <textarea
            value={hint}
            disabled={approved || busy}
            rows={2}
            onFocus={() => onTyping(true)}
            onBlur={() => onTyping(false)}
            onChange={(event) => setHint(event.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={approved || busy}
          onClick={() =>
            onAct(() =>
              api.setContent(
                detail.question_id,
                reviewerId,
                solution.split('\n').filter((line) => line.trim()),
                hint.split('\n').filter((line) => line.trim()),
              ),
            )
          }
        >
          Save solution and hints
        </button>
      </div>

      <div className="approve">
        <button
          type="button"
          className="primary"
          disabled={approved || busy || missing.length > 0}
          onClick={() => onAct(() => api.approve(detail.question_id, reviewerId))}
        >
          Approve question (⏎)
        </button>
        {missing.length > 0 && <span className="provenance">Still needed: {missing.join(', ')}.</span>}
      </div>
    </section>
  );
}

function label(source: string): string {
  return source.replace(/_/g, ' ');
}
