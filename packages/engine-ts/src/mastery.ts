/**
 * Elo-style mastery estimation — the offline mirror of packages/engine/mastery.py.
 *
 * Field names are snake_case to match the parity vectors and the wire format, so
 * fixtures can be applied without translation. Any change here must be made in
 * the Python engine first, then verified by `npm test` (ADR-0005).
 */

export type Band =
  | 'not_assessed'
  | 'weak'
  | 'developing'
  | 'exam_ready'
  | 'strong'
  | 'maintained';

export type Confidence = 'low' | 'medium' | 'high';

export interface SkillRating {
  theta: number;
  scored_attempts: number;
  levels_seen: number[];
}

export interface Attempt {
  is_correct: boolean;
  level: number;
  response_ms: number;
  expected_seconds: number;
  hint_used?: boolean;
  solution_viewed_before_answer?: boolean;
}

/**
 * Objective items carry between two and six options; the chance of guessing one
 * correctly is 1/option_count. Never assume four (ADR-0014).
 */
export const MIN_OPTIONS = 2;
export const MAX_OPTIONS = 6;

export function chanceLevelForOptions(optionCount: number): number {
  if (optionCount < MIN_OPTIONS || optionCount > MAX_OPTIONS) {
    throw new RangeError(`option_count must be ${MIN_OPTIONS}..${MAX_OPTIONS}, got ${optionCount}`);
  }
  return 1 / optionCount;
}

export const LEVEL_DIFFICULTY: Record<number, number> = {
  1: -1.5,
  2: -0.75,
  3: 0.0,
  4: 0.75,
  5: 1.5,
};

export const REFERENCE_LEVEL = 3;

export const K_INITIAL = 0.4;
export const K_DECAY = 0.1;
export const K_FLOOR = 0.08;

export const HINT_OUTCOME_CAP = 0.5;
export const GUESS_TIME_FRACTION = 0.25;
export const GUESS_K_FACTOR = 0.5;

export const MIN_SCORED_ATTEMPTS_FOR_BAND = 3;
export const HIGH_CONFIDENCE_ATTEMPTS = 8;

export function difficultyForLevel(level: number): number {
  const difficulty = LEVEL_DIFFICULTY[level];
  if (difficulty === undefined) {
    throw new RangeError(`level must be 1..5, got ${level}`);
  }
  return difficulty;
}

export function probabilityCorrect(theta: number, difficulty: number): number {
  return 1 / (1 + Math.exp(-(theta - difficulty)));
}

export function predictedProbability(rating: SkillRating, level: number): number {
  return probabilityCorrect(rating.theta, difficultyForLevel(level));
}

export function learningRate(scoredAttempts: number): number {
  return Math.max(K_FLOOR, K_INITIAL / (1 + K_DECAY * scoredAttempts));
}

export function isSuspectedGuess(attempt: Attempt): boolean {
  if (!attempt.is_correct) return false;
  return attempt.response_ms < GUESS_TIME_FRACTION * attempt.expected_seconds * 1000;
}

export function update(rating: SkillRating, attempt: Attempt): SkillRating {
  if (attempt.solution_viewed_before_answer) return rating;

  const expected = probabilityCorrect(rating.theta, difficultyForLevel(attempt.level));
  let outcome = attempt.is_correct ? 1 : 0;
  if (attempt.hint_used) outcome = Math.min(outcome, HINT_OUTCOME_CAP);

  let step = learningRate(rating.scored_attempts);
  if (isSuspectedGuess(attempt)) step *= GUESS_K_FACTOR;

  const levels = [...new Set([...rating.levels_seen, attempt.level])].sort((a, b) => a - b);

  return {
    theta: rating.theta + step * (outcome - expected),
    scored_attempts: rating.scored_attempts + 1,
    levels_seen: levels,
  };
}

/** Mastery as a fraction: the chance of answering an exam-level item. */
export function displayedMastery(rating: SkillRating): number {
  return predictedProbability(rating, REFERENCE_LEVEL);
}

export function band(rating: SkillRating): Band {
  if (rating.scored_attempts < MIN_SCORED_ATTEMPTS_FOR_BAND) return 'not_assessed';
  const mastery = displayedMastery(rating);
  if (mastery < 0.4) return 'weak';
  if (mastery < 0.65) return 'developing';
  if (mastery < 0.8) return 'exam_ready';
  if (mastery < 0.9) return 'strong';
  return 'maintained';
}

export function confidence(rating: SkillRating): Confidence {
  if (rating.scored_attempts < MIN_SCORED_ATTEMPTS_FOR_BAND) return 'low';
  if (rating.scored_attempts >= HIGH_CONFIDENCE_ATTEMPTS && rating.levels_seen.length >= 2) {
    return 'high';
  }
  return 'medium';
}

/** Mastery decayed towards the item's own chance level, for planning. */
export function retainedMastery(
  mastery: number,
  daysSinceSuccess: number,
  halfLifeDays: number,
  chanceLevel: number,
): number {
  if (halfLifeDays <= 0) throw new RangeError('halfLifeDays must be positive');
  if (daysSinceSuccess < 0) throw new RangeError('daysSinceSuccess cannot be negative');
  if (chanceLevel < 0 || chanceLevel >= 1) throw new RangeError('chanceLevel must be in [0, 1)');
  const retention = Math.pow(2, -daysSinceSuccess / halfLifeDays);
  return mastery * retention + chanceLevel * (1 - retention);
}
