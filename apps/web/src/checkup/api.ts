/** Thin typed wrapper over the check-up endpoints, plus the developer student endpoints. */

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
  /** Where the topic weights came from; 'exam_structure' means the paper's own shape. */
  weights_source: string;
  question: CheckupQuestion | null;
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
  unassessed_topics: string[];
  priority_topics: string[];
  caveat: string;
}

export interface SandboxStudent {
  student_id: string;
  display_name: string;
  external_ref: string;
  consent_recorded: boolean;
}

export interface SandboxSubject {
  subject_id: string;
  subject_name: string;
  examination: string;
  deliverable_questions: number;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/v1${path}`, {
    headers: { 'content-type': 'application/json' },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status}: ${detail}`);
  }
  return (await response.json()) as T;
}

export const api = {
  /** A throwaway student with consent recorded — stands in for signing in. */
  createStudent: () => call<SandboxStudent>('/dev/students', { method: 'POST', body: '{}' }),
  subjects: () => call<SandboxSubject[]>('/dev/subjects'),
  start: (studentId: string, subjectId: string) =>
    call<CheckupState>('/checkup/start', {
      method: 'POST',
      body: JSON.stringify({ student_id: studentId, subject_id: subjectId }),
    }),
  answer: (
    sessionId: string,
    questionVersionId: string,
    optionKey: string,
    responseMs: number,
  ) =>
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
  report: (sessionId: string) => call<CheckupReport>(`/checkup/${sessionId}/report`),
};
