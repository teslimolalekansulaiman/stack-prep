/** Help ladder — the offline mirror of packages/engine/help.py. */

export type HelpAction = 'check_again' | 'hint' | 'worked_solution' | 'micro_lesson';

/** Above this mastery, one wrong answer reads as a slip rather than a gap. */
export const SLIP_MASTERY = 0.8;

/** Below this mastery, practice alone will not fix the gap. */
export const TEACHING_MASTERY = 0.4;

/** Wrong answers on one skill in a session before teaching is warranted. */
export const TEACHING_WRONG_COUNT = 3;

export interface HelpInput {
  /** Decayed mastery fraction for the item's skill. */
  mastery: number;
  /** Wrong answers on this skill this session, including this one. */
  wrong_in_session: number;
  /** Whether the student already saw a hint for this item. */
  hint_shown: boolean;
}

export function helpAction({ mastery, wrong_in_session, hint_shown }: HelpInput): HelpAction {
  if (wrong_in_session < 1) {
    throw new RangeError('helpAction is only called after a wrong answer');
  }
  if (mastery < TEACHING_MASTERY || wrong_in_session >= TEACHING_WRONG_COUNT) {
    return 'micro_lesson';
  }
  if (mastery >= SLIP_MASTERY && wrong_in_session === 1 && !hint_shown) {
    return 'check_again';
  }
  if (hint_shown || wrong_in_session >= 2) {
    return 'worked_solution';
  }
  return 'hint';
}
