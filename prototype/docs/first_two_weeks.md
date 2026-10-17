# The first two weeks on site

What a forward-deployed engineer does before writing production code. The aim is to replace every assumption in SOLUTION.md section 5 with the bank's own number, and to agree in advance what result would stop the POC.

## Week 1: listen and measure

| Who to interview | What to learn |
|---|---|
| 3 to 4 credit analysts (shadow a live case each) | Where the hours actually go; which documents are hardest; what they re-key |
| 1 to 2 RMs | How packs arrive; how many rounds of missing documents |
| Head of credit and a committee member | Which exceptions surface late; what makes a memo good; delegated authority in practice |
| Compliance (KYC, screening) | EDD triggers; screening tool and its API; who can clear what |
| Model risk | What they will validate; evidence they need; how they treat language models |
| InfoSec and data privacy | Data residency, masking rules, approved model endpoints |
| LOS owner / IT | Which LOS, which APIs, sandbox availability, document store |

**Measure:** time-and-motion on 10 live cases (hours by activity, rounds of missing documents, days waiting), and the current exception discovery point (intake vs. committee) from the last 50 committee packs.

## Week 2: replay 20 historical cases

Pick 20 closed cases with full documents and the final memo: 10 straightforward approvals, 5 approvals with exceptions, 3 declines, 2 that went wrong after approval. Encode the bank's top clauses and the DoA matrix, then run the agents on all 20 in replay.

| Measure | Compared with |
|---|---|
| Critical field accuracy and citation correctness | The analyst's spreading template |
| Exceptions found | Exceptions in the memo and committee minutes |
| Missing documents found | What the RM was actually asked for |
| Recommendation and route | What committee actually did |
| Tokens and cost per case | Analyst hours for the same case |

## Kill criteria (agreed with the sponsor before week 2)

Stop or re-scope the POC if, on the 20 replayed cases:
- critical field accuracy is below 85% after one round of fixes, **or**
- any case would have been recommended for approval when policy says otherwise, **or**
- data access for the pilot product cannot be approved, **or**
- analysts in shadow sessions say the citations do not save them checking time.

## Outputs at the end of week 2
- Signed-off baseline metrics.
- The 20-case replay report in the same format as `evals/results/REPORT.md`.
- Updated ADR 0004 (integration) with the real LOS and APIs.
- Go / re-scope / stop recommendation for weeks 3 to 8.
