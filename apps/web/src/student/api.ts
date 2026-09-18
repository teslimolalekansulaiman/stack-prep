/**
 * The student side's typed client.
 *
 * Only the identity is held in the browser. Everything a student would be upset to lose —
 * the goal, the sitting, every answer — is written to the database as it happens, so closing
 * the tab loses nothing and reopening it finds the sitting where it stopped.
 */

export interface SubjectOffer {
  subject_id: string;
  code: string;
  name: string;
  deliverable_questions: number;
  teachable_skills: number;
  ready: boolean;
  blocked_reason: string | null;
}

export interface ExaminationOffer {
  examination_id: string;
  short_name: string;
  name: string;
  exam_body: string;
  subjects: SubjectOffer[];
}

export interface Goal {
  subject_id: string;
  subject_name: string;
  target_score: number | null;
  exam_date: string | null;
  minutes_per_day: number | null;
  study_days: number[] | null;
  sessions_before_exam: number | null;
}

export interface GoalIn {
  target_score: number;
  exam_date: string;
  minutes_per_day: number;
  study_days: number[];
}

export interface Sitting {
  session_id: string;
  subject_id: string;
  subject_name: string;
  answered: number;
  finished: boolean;
}

export interface CheckupOption {
  option_key: string;
  body: string;
}

export interface CheckupQuestion {
  position: number;
  of: number;
  topic_name: string;
  question_version_id: string;
  stem: string;
  instructions: string | null;
  passage_title: string | null;
  passage_body: string | null;
  options: CheckupOption[];
}

export interface CheckupState {
  session_id: string;
  answered: number;
  length: number;
  finished: boolean;
  weights_source: string;
  question: CheckupQuestion | null;
}

export interface SubtopicReport {
  subtopic_id: string;
  name: string;
  topic_name: string;
  share: number;
  answered: number;
  correct: number;
  mastery: number | null;
  confidence: string;
}

export interface PlanLine {
  subtopic_id: string;
  name: string;
  topic_name: string;
  share: number;
  mastery_now: number;
  mastery_projected: number;
  sessions: number;
  marks_gained: number;
  reason: string;
}

export interface ScoreProjection {
  score_now: number;
  score_low: number;
  score_high: number;
  score_projected: number;
  target_score: number | null;
  sessions_available: number;
  shortfall_note: string | null;
  unmeasured_share: number;
  plan: PlanLine[];
  caveat: string;
}

export interface TopicReport {
  topic_id: string;
  name: string;
  answered: number;
  correct: number;
  mastery: number | null;
  confidence: string;
  highest_level_correct: number | null;
  lowest_level_wrong: number | null;
  slow: boolean;
}

export interface CheckupReport {
  session_id: string;
  subject_id: string;
  answered: number;
  finished: boolean;
  topics: TopicReport[];
  subtopics: SubtopicReport[];
  weights_source: string;
  projection: ScoreProjection | null;
  unassessed_topics: string[];
  priority_topics: string[];
  caveat: string;
}

export interface PracticeOption {
  option_key: string;
  body: string;
}

export interface PracticeQuestion {
  question_version_id: string;
  subtopic_name: string;
  topic_name: string;
  stem: string;
  instructions: string | null;
  passage_title: string | null;
  passage_body: string | null;
  options: PracticeOption[];
  hints_used: number;
}

export interface Misconception {
  name: string;
  description: string;
  remediation_note: string | null;
}

export interface PracticeState {
  session_id: string;
  stage: 'asking' | 'hint' | 'explain' | 'finished';
  position: number;
  length: number;
  answered: number;
  correct_unaided: number;
  taught: number;
  question: PracticeQuestion | null;
  hint: string | null;
  solution_steps: string[] | null;
  correct_option_key: string | null;
  misconception: Misconception | null;
  closing_note: string | null;
}

export interface PracticeAnswerIn {
  question_version_id: string;
  selected_option_key: string;
  response_ms: number;
  confidence: 'sure' | 'unsure' | 'guessed' | null;
}

export interface StudentIdentity {
  student_id: string;
  display_name: string;
  external_ref: string;
  consent_recorded: boolean;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/v1${path}`, {
    headers: { 'content-type': 'application/json' },
    ...init,
  });
  if (!response.ok) {
    let detail = await response.text();
    try {
      detail = (JSON.parse(detail) as { detail?: string }).detail ?? detail;
    } catch {
      /* the body was not JSON; show it as it came */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  /** Stands in for signing in until ADR-0013 lands. The student row and its consent are real. */
  createStudent: (displayName?: string) =>
    call<StudentIdentity>('/dev/students', {
      method: 'POST',
      body: JSON.stringify(displayName ? { display_name: displayName } : {}),
    }),
  catalogue: () => call<ExaminationOffer[]>('/student/catalogue'),
  goals: (studentId: string) => call<Goal[]>(`/student/${studentId}/goals`),
  setGoal: (studentId: string, subjectId: string, goal: GoalIn) =>
    call<Goal>(`/student/${studentId}/goals/${subjectId}`, {
      method: 'PUT',
      body: JSON.stringify(goal),
    }),
  sittings: (studentId: string) => call<Sitting[]>(`/student/${studentId}/sittings`),
  start: (studentId: string, subjectId: string) =>
    call<CheckupState>('/checkup/start', {
      method: 'POST',
      body: JSON.stringify({ student_id: studentId, subject_id: subjectId }),
    }),
  answer: (sessionId: string, questionVersionId: string, optionKey: string, responseMs: number) =>
    call<CheckupState>(`/checkup/${sessionId}/answer`, {
      method: 'POST',
      body: JSON.stringify({
        // Generated here so a retried submission is stored once, not twice.
        attempt_id: crypto.randomUUID(),
        question_version_id: questionVersionId,
        selected_option_key: optionKey,
        response_ms: responseMs,
      }),
    }),
  /** Where an already-open sitting is, for a client that has just reloaded. */
  current: (sessionId: string) => call<CheckupState>(`/checkup/${sessionId}`),
  report: (sessionId: string) => call<CheckupReport>(`/checkup/${sessionId}/report`),
  startPractice: (studentId: string, subjectId: string, length = 10) =>
    call<PracticeState>('/practice/start', {
      method: 'POST',
      body: JSON.stringify({ student_id: studentId, subject_id: subjectId, length }),
    }),
  practiceCurrent: (sessionId: string) => call<PracticeState>(`/practice/${sessionId}`),
  practiceAnswer: (sessionId: string, body: PracticeAnswerIn) =>
    call<PracticeState>(`/practice/${sessionId}/answer`, {
      method: 'POST',
      body: JSON.stringify({ attempt_id: crypto.randomUUID(), ...body }),
    }),
  practiceTaught: (sessionId: string) =>
    call<PracticeState>(`/practice/${sessionId}/taught`, { method: 'POST' }),
};
