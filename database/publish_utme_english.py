#!/usr/bin/env python3
"""Walk UTME Use of English through the publishing chain, over the real API.

    make api            # in another terminal
    uv run python database/publish_utme_english.py --apply

WHY A SCRIPT AND NOT PSQL. Every step here is an endpoint a person will click, and the
order between the steps is enforced by database triggers rather than written down anywhere.
Driving the API proves both: that the endpoints work, and that this order is the one that
gets through. A direct SQL version would prove neither, and would leave no reviewer recorded.

THE ORDER, which is not the obvious one:

  1. License the documents. Nothing else is possible first: a citation cannot be approved
     against a document we have not decided we may use, and a syllabus version cannot be
     approved unless the document carries storage_permission specifically.
  2. Approve the citations — the lines of the PDF each syllabus item was read from.
  3. Publish the syllabus version. Items cannot be approved against a draft version.
  4. Approve the items, parents before children: topic, then subtopic, then skill.
  5. Switch the subject and its examination on. Until this, published_curriculum_scope is
     empty however much has been approved, which is a confusing way to find out that the
     catalogue is the thing in the way.
  6. License and approve the passages. Comprehension and cloze questions cannot be approved
     while the passage they hang off is not.

WHAT THIS DOES NOT DO, deliberately. It does not approve a single question. Approval needs
an answer and a difficulty level that a person has verified, and that person is not a script.
Everything here is the ground a question stands on; the questions themselves are still
waiting on review.
"""

from __future__ import annotations

import argparse
import sys

import httpx

#: The subject codes are not unique across examinations, so the examination is named too.
EXAMINATION = "UTME"
SUBJECT = "ENG"

#: Items import as 'uncertain' because the loader records what the document printed, not what
#: it means. These eight are the ones the seed's extraction notes mark as our inference rather
#: than a printed line — the paper sets these tasks, the syllabus does not name them. Every
#: other item is printed explicitly.
IMPLIED = {
    "ENG.A.4.i",
    "ENG.A.5.i",
    "ENG.A.6",
    "ENG.A.6.i",
    "ENG.B.4.i",
    "ENG.B.5.i",
    "ENG.C.4.i",
    "ENG.C.5.i",
}

#: Approve parents before children; the trigger refuses otherwise.
ORDER = {"topic": 0, "subtopic": 1, "skill": 2}


class Chain:
    def __init__(self, client: httpx.Client, reviewer: str, apply: bool) -> None:
        self.client = client
        self.reviewer = reviewer
        self.apply = apply

    def post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        if not self.apply:
            return {}
        response = self.client.post(path, json={"reviewer_id": self.reviewer, **body})
        if response.status_code >= 400:
            raise SystemExit(f"{path} refused: {response.status_code} {response.text}")
        result: dict[str, object] = response.json()
        return result

    def get(self, path: str, **params: object) -> list[dict[str, object]] | dict[str, object]:
        response = self.client.get(path, params=params)
        response.raise_for_status()
        payload: list[dict[str, object]] | dict[str, object] = response.json()
        return payload


def resolve_subject(client: httpx.Client) -> str:
    subjects = client.get("/v1/curriculum/subjects").json()
    for subject in subjects:
        if subject["code"] == SUBJECT and subject["examination"] == EXAMINATION:
            return str(subject["id"])
    raise SystemExit(f"no {EXAMINATION} subject with code {SUBJECT}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--reviewer", required=True, help="academic_reviewers.id making these calls"
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=30.0) as client:
        subject_id = resolve_subject(client)
        chain = Chain(client, args.reviewer, args.apply)

        # 1. Documents. Both UTME documents for this subject: the syllabus the curriculum was
        #    read from, and the past-question compilation the questions came from.
        documents = chain.get("/v1/publishing/documents", subject_id=subject_id)
        assert isinstance(documents, list)
        for document in documents:
            chain.post(
                f"/v1/publishing/documents/{document['document_id']}/licence",
                {
                    "licence_status": "verified",
                    "storage_permission": True,
                    "student_delivery_permission": True,
                    "model_context_permission": True,
                },
            )
            print(f"  licensed  {document['title']}")

        # 2. Citations.
        citations = chain.get("/v1/publishing/evidence", subject_id=subject_id, state="pending")
        assert isinstance(citations, list)
        for citation in citations:
            chain.post(f"/v1/publishing/evidence/{citation['evidence_id']}/approve", {})
        print(f"  approved  {len(citations)} citations")

        # 3. Syllabus version.
        # Read the version from this subject's own items. Resolving it any other way risks
        # publishing another subject's syllabus: two different subjects here are both coded
        # "ENG", and each has a 2027 version.
        items = chain.get("/v1/publishing/curriculum", subject_id=subject_id, state="all")
        assert isinstance(items, list)
        if not items:
            raise SystemExit("this subject has no curriculum items to publish")
        version_ids = {str(item["syllabus_version_id"]) for item in items}
        if len(version_ids) != 1:
            raise SystemExit(f"expected one syllabus version for this subject, found {version_ids}")
        version_id = version_ids.pop()
        chain.post(f"/v1/publishing/syllabus-versions/{version_id}/publish", {})
        print(f"  published syllabus version {version_id}")

        # 4. Items, parents first.
        items = chain.get("/v1/publishing/curriculum", subject_id=subject_id, state="draft")
        assert isinstance(items, list)
        for item in sorted(items, key=lambda i: (ORDER[str(i["item_type"])], str(i["code"]))):
            chain.post(
                f"/v1/publishing/curriculum/{item['curriculum_item_id']}/approve",
                {
                    "syllabus_status": "implied" if item["code"] in IMPLIED else "explicit",
                    "pilot_support_status": "supported",
                },
            )
        print(f"  approved  {len(items)} curriculum items")

        # 5. Catalogue.
        catalogue = chain.post(
            f"/v1/publishing/subjects/{subject_id}/activate", {"activate_examination": True}
        )
        if catalogue:
            print(f"  switched on: {catalogue['teachable_skills']} teachable skills")

        # 6. Passages.
        found = chain.get("/v1/publishing/passages", subject_id=subject_id, state="draft")
        assert isinstance(found, list)
        for passage in found:
            chain.post(
                f"/v1/publishing/passages/{passage['passage_id']}/decide",
                {"licence_status": "verified", "approve": True},
            )
        print(f"  approved  {len(found)} passages")

        if not args.apply:
            print("\nDry run; pass --apply to make these decisions.")
            return 0

        final = chain.get("/v1/publishing/catalogue", subject_id=subject_id)
        assert isinstance(final, dict)
        print(
            f"\n{final['subject_name']}: {final['teachable_skills']} teachable skills, "
            f"{final['deliverable_questions']} deliverable questions."
        )
        print(
            "Questions stay at zero until a person verifies each answer and level; that is "
            "the one thing a script must not do."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
