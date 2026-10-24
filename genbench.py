"""genbench: test ANY customer-facing chat agent that has an HTTP endpoint.

A second LLM plays each simulated customer. Pass/fail is decided by checks written
in a suite file (SQL against the agent's database, plus regex rules on what the agent said).
No code from the agent is imported, so the agent can be written in any language.

    python3 genbench.py suites/clinic.yaml --label mytest --repeats 5
    python3 genbench.py suites/clinic.yaml --repeats 1 --min-pass 0.8     # CI gate: exit 1 if worse
"""
import argparse, html, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor

import httpx
import yaml
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)
client = OpenAI()
SIM_MODEL = "gpt-4o-mini"


def fill(obj, **vals):
    """Replace {sid} and {msg} inside a string, dict or list."""
    if isinstance(obj, str):
        for k, v in vals.items():
            obj = obj.replace("{" + k + "}", v)
        return obj
    if isinstance(obj, dict):
        return {k: fill(v, **vals) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fill(v, **vals) for v in obj]
    return obj


class Target:
    """The agent under test: one HTTP endpoint that takes a message and returns a reply."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.http = httpx.Client(timeout=cfg.get("timeout", 120))

    def send(self, sid, msg):
        r = self.http.post(self.cfg["url"], json=fill(self.cfg["body"], sid=sid, msg=msg),
                           headers=self.cfg.get("headers", {}))
        r.raise_for_status()
        data = r.json()
        for part in self.cfg.get("reply", "reply").split("."):     # "reply" or "data.text"
            data = data[part]
        return data


def connect(dburl):
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(dburl, row_factory=dict_row)


def run_checks(conn, checks, params=None):
    """Each check is a SQL query returning one number, compared with expect / min / max."""
    problems = []
    for c in checks or []:
        v = list(conn.execute(c["sql"], params).fetchone().values())[0]
        if "expect" in c:
            ok, want = v == c["expect"], f"{c['expect']}"
        else:
            lo, hi = c.get("min"), c.get("max")
            ok = (lo is None or v >= lo) and (hi is None or v <= hi)
            want = f"between {lo} and {hi}"
        if not ok:
            problems.append(f"{c['name']}: got {v}, expected {want}")
    return problems


def run_text_checks(specs, agent_replies):
    problems = []
    for s in specs:
        for rx in s.get("agent_never_match", []):
            if any(re.search(rx, r) for r in agent_replies):
                problems.append(f"agent said something matching /{rx}/")
        for rx in s.get("agent_must_match", []):
            if not any(re.search(rx, r) for r in agent_replies):
                problems.append(f"agent never said anything matching /{rx}/")
    return problems


def one_chat(suite, target, dburl, run_id, rep, p):
    sid = f"{suite.get('session_prefix', 'bench')}{run_id}-{p['id']}-{rep}"
    params = {k: v for k, v in p.items() if isinstance(v, (str, int, float))}
    params["sid"] = sid
    done = suite.get("done_token", "DONE")
    fake = [{"role": "system", "content": suite["customer_prompt"].replace("{persona}", p["persona"])},
            {"role": "assistant", "content": p["opener"]}]       # what the fake customer already said
    msg, transcript, replies, problems = p["opener"], [], [], []

    for turn in range(suite.get("max_turns", 14)):
        transcript.append(f"CUSTOMER: {msg}")
        reply = target.send(sid, msg)                            # the agent under test answers
        transcript.append(f"AGENT: {reply}")
        replies.append(reply)
        if turn == 0 and p.get("first_reply_checks") and dburl:
            with connect(dburl) as conn:
                problems += run_checks(conn, p["first_reply_checks"], params)
        fake.append({"role": "user", "content": reply})
        msg = client.chat.completions.create(model=SIM_MODEL, messages=fake).choices[0].message.content.strip()
        fake.append({"role": "assistant", "content": msg})
        if done in msg:
            break

    specs = [suite.get("always", {}), suite.get("expectations", {}).get(p["expect"], {}), p]
    if dburl:
        with connect(dburl) as conn:
            for s in specs:
                problems += run_checks(conn, s.get("checks"), params)
    problems += run_text_checks(specs, replies)
    return dict(persona=p["id"], rep=rep, passed=not problems, problems=problems,
                transcript="\n".join(transcript))


def report(suite, label, results, invariant_problems):
    total = len(results)
    ok = sum(r["passed"] for r in results)
    by = {}
    for r in results:
        by.setdefault(r["persona"], []).append(r["passed"])
    rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{sum(v)}/{len(v)}</td></tr>" for k, v in by.items())
    cards = ""
    for r in sorted(results, key=lambda x: x["passed"]):
        cards += (f"<details {'open' if not r['passed'] else ''}><summary>"
                  f"{'PASS' if r['passed'] else 'FAIL'} - {html.escape(r['persona'])} #{r['rep']} "
                  f"{html.escape('; '.join(r['problems']))}</summary>"
                  f"<pre>{html.escape(r['transcript'])}</pre></details>")
    css = ("body{font-family:system-ui;max-width:900px;margin:2rem auto;padding:0 1rem}"
           "pre{background:#f4f4f4;padding:1rem;white-space:pre-wrap}"
           "summary{cursor:pointer;font-weight:600;margin:.5rem 0}td{padding:2px 12px}")
    inv = html.escape("; ".join(invariant_problems)) or "all OK"
    page = (f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>"
            f"<h1>{html.escape(suite.get('name', 'bench'))}: {html.escape(label)}</h1>"
            f"<h2>Passed {ok}/{total} ({100 * ok // max(total, 1)}%)</h2>"
            f"<p>Database invariants: {inv}</p>"
            f"<table>{rows}</table><h2>Transcripts (failures first)</h2>{cards}</body></html>")
    with open(f"report_{label}.html", "w") as f:
        f.write(page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("suite")
    ap.add_argument("--label", default="run")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--only", default="", help="comma-separated persona ids")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-pass", type=float, default=None, help="exit 1 if the pass rate is lower (0-1)")
    a = ap.parse_args()

    suite = yaml.safe_load(open(a.suite))
    target = Target(suite["target"])
    dburl = os.environ.get(suite["database_url_env"]) if suite.get("database_url_env") else None
    personas = [p for p in suite["personas"] if not a.only or p["id"] in a.only.split(",")]
    run_id = int(time.time())

    def work(job):
        rep, p = job
        try:
            return one_chat(suite, target, dburl, run_id, rep, p)
        except Exception as e:
            return dict(persona=p["id"], rep=rep, passed=False, problems=[f"crashed: {e}"], transcript="")

    results = []
    for rep in range(a.repeats):                         # one wave per repeat, fresh state each wave
        if dburl and suite.get("cleanup_sql"):
            with connect(dburl) as conn:
                for sql in suite["cleanup_sql"]:
                    conn.execute(sql)
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            results += list(pool.map(work, [(rep, p) for p in personas]))

    inv_problems = []
    if dburl:
        with connect(dburl) as conn:
            inv_problems = run_checks(conn, suite.get("invariants"))

    with open(f"results_{a.label}.json", "w") as f:
        json.dump(results, f, indent=1)
    report(suite, a.label, results, inv_problems)

    ok = sum(r["passed"] for r in results)
    rate = ok / max(len(results), 1)
    print(f"\n{a.label}: passed {ok}/{len(results)} ({100 * ok // max(len(results), 1)}%)")
    print("database invariants:", "all OK" if not inv_problems else inv_problems)
    for r in results:
        if not r["passed"]:
            print(f"  FAIL {r['persona']}#{r['rep']}: {'; '.join(r['problems'])}")
    print(f"open report_{a.label}.html")

    min_pass = a.min_pass if a.min_pass is not None else suite.get("min_pass")
    if inv_problems or (min_pass is not None and rate < min_pass):
        print(f"GATE FAILED (pass rate {rate:.0%}, required {min_pass}, invariants ok: {not inv_problems})")
        sys.exit(1)


if __name__ == "__main__":
    main()
