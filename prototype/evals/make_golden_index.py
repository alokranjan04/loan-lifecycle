#!/usr/bin/env python3
"""Write golden/README.md: a readable index of the golden set (what each case tests, the expected
decision, and links to its files), with the latest Claude result next to each case if one is recorded.

  python evals/make_golden_index.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
CLAUDE = HERE / "results" / "claude-opus-5-5" / "results.json"
BASE = "/mnt/project-files/loan-lifecycle/prototype/evals/golden"   # project path, so links open in the project preview
STYLE = {"standard": "Standard", "adversarial": "Adversarial", "varied": "Unfamiliar layout"}
CATEGORY = {"real": ("Real cases", "Everyday applications: clean files and the policy problems analysts see every week"),
            "corner": ("Corner cases", "Values exactly on a policy limit, missing documents or lines, two figures that disagree, "
                                       "several problems at once, and unfamiliar document layouts"),
            "jailbreak": ("Jailbreak scenarios", "A borrower document tries to steer the AI (ignore the policy, fake approvals, "
                                                 "role-play, change a number, skip screening, another language, a JSON override). "
                                                 "The instruction must be caught and the policy outcome must not move")}


def money(x):
    return f"USD {x / 1e6:.2f}M".replace(".00M", "M")


def main():
    claude = {}
    if CLAUDE.exists():
        claude = {c["case_id"]: c for c in json.loads(CLAUDE.read_text())["cases"]}
    cases = []
    for d in sorted(p for p in GOLDEN.iterdir() if p.is_dir()):
        gt = json.loads((d / "ground_truth.json").read_text())
        app = json.loads((d / "application.json").read_text())
        cases.append((d, gt, app))

    groups = {k: [c for c in cases if c[1].get("category") == k] for k in CATEGORY}
    L = [f"# Golden set: {len(cases)} test cases with known answers", "",
         "Fictional loan applications built by `evals/generate_cases.py` (seed 20261016, decision date 2026-10-16). "
         "Each case has an application, its supporting documents, and a `ground_truth.json` with the answer worked out "
         "from the credit policy text, independently of the agent code. Results by category: `evals/results/REPORT.md`. "
         "The Claude column covers GS-001 to GS-030; GS-031 to GS-039 were added after that run.", "",
         "| Category | Cases | What they test |", "|---|---|---|"]
    L += [f"| [{name}](#{name.lower().replace(' ', '-')}) | {len(groups[k])} | {what} |" for k, (name, what) in CATEGORY.items()]
    for k, (name, what) in CATEGORY.items():
        L += ["", f"## {name}", "", f"{what}.", "",
              "| Case | Layout | Borrower and facility | What it tests | Expected decision | Approval route | Policy exceptions | Claude Opus 5.5 |",
              "|---|---|---|---|---|---|---|---|"]
        for d, gt, app in groups[k]:
            exc = [f"{k2} {v}" for k2, v in gt["policy_checks"].items() if v != "PASS"]
            c = claude.get(gt["case_id"])
            res = "not run" if not c else ("✓ matches" if c["recommendation"]["actual"] == gt["recommendation"] else f"✗ {c['recommendation']['actual']}")
            f = app["facility"]
            L.append(f"| [{gt['case_id']}](#{gt['case_id'].lower()}) | {STYLE[gt['style']]} | {app['borrower']['legal_name']}, "
                     f"{money(f['amount_usd'])} {f['type'].lower()} | {'; '.join(gt['planted'])} | **{gt['recommendation']}** | "
                     f"{' → '.join(gt['gates'])} | {', '.join(exc) or 'none'} | {res} |")
    L += ["", "## Case details"]
    for d, gt, app in cases:
        cid, f = gt["case_id"], app["facility"]
        L += ["", f"### {cid}", "",
              f"**{CATEGORY[gt['category']][0]}** · {STYLE[gt['style']]} layout · {app['borrower']['legal_name']} · {money(f['amount_usd'])} {f['type'].lower()}, "
              f"{f.get('tenor_months', '?')} months", "",
              f"- **What it tests:** {'; '.join(gt['planted'])}",
              f"- **Expected decision:** {gt['recommendation']}, routed to {' → '.join(gt['gates'])}",
              f"- **Policy checks not passing:** {', '.join(f'{k} {v}' for k, v in gt['policy_checks'].items() if v != 'PASS') or 'none'}"]
        if gt["missing_documents"]:
            L.append(f"- **Missing documents:** {', '.join(gt['missing_documents'])}")
        if gt["findings"]:
            L.append(f"- **Other findings expected:** {', '.join(x if isinstance(x, str) else x.get('kind', str(x)) for x in gt['findings'])}")
        files = [f"[application.json]({BASE}/{cid}/application.json)", f"[ground_truth.json]({BASE}/{cid}/ground_truth.json)"]
        files += [f"[{p.name}]({BASE}/{cid}/documents/{p.name})" for p in sorted((d / "documents").glob("*"))]
        L.append(f"- **Files:** {' · '.join(files)}")
    (GOLDEN / "README.md").write_text("\n".join(L) + "\n")
    print(f"Wrote {GOLDEN / 'README.md'} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
