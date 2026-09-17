/**
 * The app currently opens straight into content review: until questions are verified,
 * there is nothing to show a student. Student-facing screens arrive with the practice
 * loop (see docs/roadmap.md).
 */

import { ReviewPage } from './review/ReviewPage.js';

export function App() {
  return <ReviewPage />;
}
