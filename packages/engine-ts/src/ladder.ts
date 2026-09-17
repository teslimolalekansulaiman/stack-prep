/** Item difficulty ladder — the offline mirror of packages/engine/ladder.py. */

import { predictedProbability, type SkillRating } from './mastery.js';

export const MIN_LEVEL = 1;
export const MAX_LEVEL = 5;

/** Aim just above a coin-flip: hard enough to teach, easy enough to keep going. */
export const TARGET_PROBABILITY = 0.7;

/** Consecutive answers at the current level before moving. */
export const STEP_THRESHOLD = 2;

/** The level whose predicted success sits closest to the target; ties go easier. */
export function startingLevel(rating: SkillRating): number {
  let bestLevel = MIN_LEVEL;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let level = MIN_LEVEL; level <= MAX_LEVEL; level += 1) {
    const distance = Math.abs(predictedProbability(rating, level) - TARGET_PROBABILITY);
    if (distance < bestDistance - 1e-12) {
      bestLevel = level;
      bestDistance = distance;
    }
  }
  return bestLevel;
}

function tailAll(outcomes: readonly boolean[], value: boolean): boolean {
  const tail = outcomes.slice(-STEP_THRESHOLD);
  return tail.length === STEP_THRESHOLD && tail.every((outcome) => outcome === value);
}

/**
 * Two correct in a row moves up; two wrong in a row moves down.
 * `recentOutcomes` is the run of answers at `currentLevel`, oldest first.
 */
export function nextLevel(currentLevel: number, recentOutcomes: readonly boolean[]): number {
  if (currentLevel < MIN_LEVEL || currentLevel > MAX_LEVEL) {
    throw new RangeError(`currentLevel must be 1..5, got ${currentLevel}`);
  }
  if (tailAll(recentOutcomes, true)) return Math.min(MAX_LEVEL, currentLevel + 1);
  if (tailAll(recentOutcomes, false)) return Math.max(MIN_LEVEL, currentLevel - 1);
  return currentLevel;
}

/** Two misses at the foundation level means the gap is probably a prerequisite. */
export function needsPrerequisiteProbe(
  currentLevel: number,
  recentOutcomes: readonly boolean[],
): boolean {
  return currentLevel === MIN_LEVEL && tailAll(recentOutcomes, false);
}
