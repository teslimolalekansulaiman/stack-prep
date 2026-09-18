/**
 * Three surfaces so far, chosen by the URL rather than a router: the reviewer's queue, the
 * student's flow, and the bare check-up screen the flow grew out of. A real router arrives
 * when there are enough screens to need one; until then this keeps the dependency list short
 * and the intent obvious.
 *
 *   /            the review queue
 *   /student     the student's route in: sign in, choose, aim, sit, read the result
 *   /checkup     the check-up screen on its own, for trying a session id directly
 */

import { CheckupPage } from './checkup/CheckupPage.js';
import { ReviewPage } from './review/ReviewPage.js';
import { StudentApp } from './student/StudentApp.js';

export function App() {
  const path = window.location.pathname;
  if (path.startsWith('/student')) return <StudentApp />;
  if (path.startsWith('/checkup')) return <CheckupPage />;
  return <ReviewPage />;
}
