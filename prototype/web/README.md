# Web app

One entry point for the whole prototype: run any case, decide at the human gates, see the decision with its evidence and approval route, run the eval suite and the control demos.

## Start (Windows)

From the `prototype` folder, double-click `start_web.bat`, or:

```bat
cd "C:\Users\Alok Ranjan\Documents\loan-lifecycle\prototype"
python -m pip install -r web\requirements.txt
python web\app.py
```

Then open http://localhost:8000. To use Claude instead of the offline mock, set the key in the same window before starting (never put it in a file):

```bat
set ANTHROPIC_API_KEY=your-key-here
python web\app.py
```

## Screens

- **Home**: what the system does, the latest real-model eval headline, the golden set by category (real, corner, jailbreak) with per-category scores, and links into everything below.
- **Cases**: the 2 sample applications and the 39 golden cases, grouped as Real cases (18), Corner cases (13) and Jailbreak scenarios (8). Golden rows show the policy answer next to the system's result.
- **Case**: run the agents with "I decide at each gate" (you approve in the browser; try approving as the case's analyst or too junior a role to see the controls block it) or "Recorded approvers". Tabs show policy checks with clause text and clickable source lines, extracted fields with verified citations, findings and conditions, human decisions and blocked attempts, the documents, the hash-chained audit trail and the credit memo. Golden cases also show the comparison with ground truth.
- **Evals**: runs `evals/run_evals.py` and rebuilds the report; compares every saved run side by side, overall and by category.
- **Control demos**: prompt-injection red team, policy change v3.2 to v3.3, tamper-evident audit log, decision replay, and the unit tests.

Everything is served locally (Tailwind, Alpine and marked are in `static/vendor`), so it works without internet. The previous screen is kept at `/classic.html`.
