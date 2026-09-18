/**
 * Two screens so far, chosen by the URL rather than a router: the reviewer's queue, and the
 * student's check-up. A real router arrives when there are enough student screens to need
 * one; until then this keeps the dependency list short and the intent obvious.
 *
 *   /            the review queue
 *   /checkup     the check-up a student sits first
 */

import { ReviewPage } from './review/ReviewPage.js';
import { CheckupPage } from './checkup/CheckupPage.js';

export function App() {
  return window.location.pathname.startsWith('/checkup') ? <CheckupPage /> : <ReviewPage />;
}
