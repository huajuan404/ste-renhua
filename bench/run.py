#!/usr/bin/env python3
"""ste-renhua 评测试点。只用标准库。

    python3 bench/run.py gen   --out runs/pilot --runs 3
    python3 bench/run.py judge --out runs/pilot
    python3 bench/run.py read  --out runs/pilot
    python3 bench/run.py score --out runs/pilot

每个中间结果一个文件。重跑时跳过已有文件，所以可以中断后继续。
模型通过本机已登录的 claude 和 codex 命令行调用，都不加载用户自己的全局指令。
"""
import argparse
import atexit
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BENCH = Path(__file__).resolve().parent
CACHE = BENCH.parent / ".cache"

GEN_MODEL = "sonnet"
JUDGES = ["codex", "opus"]
READERS = ["codex", "haiku"]
SKIM_READER = "haiku"
SKIM_CHARS = 80  # 扫读时读者能看到的非空白字符数
RULES = "v3"  # 判分规则版本。规则变了就升版本，旧结果留在原目录，不覆盖
JUDGE_DIR = f"judge-{RULES}"
ADD_TYPES = ("step", "claim", "advice", "next")

CLAUDE = ["claude", "-p", "--setting-sources", "", "--strict-mcp-config", "--tools", "",
          "--disable-slash-commands", "--no-session-persistence", "--output-format", "json"]

JUDGE_SYS = "你是严格的事实核对员。只输出一个 JSON 对象，不要输出任何其他文字。"
READ_SYS = "你是一位读者。只输出一个 JSON 对象，不要输出任何其他文字。"


# ---------- 模型调用 ----------

def call_claude(model, prompt, system=None, append=None, timeout=900):
    cmd = CLAUDE + ["--model", model]
    if system:
        cmd += ["--system-prompt", system]
    if append:
        cmd += ["--append-system-prompt", append]
    with tempfile.TemporaryDirectory() as cwd:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    try:
        result = [e for e in json.loads(p.stdout) if e.get("type") == "result"][-1]
    except Exception:
        raise RuntimeError(f"claude 输出无法解析: {p.stdout[:200]!r} {p.stderr[:200]!r}")
    if result.get("is_error") or not result.get("result"):
        raise RuntimeError(f"claude 调用失败: {str(result)[:300]}")
    return result["result"], {"models": sorted(result.get("modelUsage") or {}),
                              "cost_usd": result.get("total_cost_usd")}


_codex_home = None


def codex_home():
    """只含凭据链接的 CODEX_HOME，避开用户的 AGENTS.md 和 config.toml。"""
    global _codex_home
    if _codex_home is None:
        _codex_home = Path(tempfile.mkdtemp(prefix="codex-home-"))
        (_codex_home / "auth.json").symlink_to(Path.home() / ".codex" / "auth.json")
        atexit.register(shutil.rmtree, _codex_home, ignore_errors=True)
    return _codex_home


def call_codex(prompt, system=None, timeout=900):
    if system:
        prompt = system + "\n\n" + prompt
    with tempfile.TemporaryDirectory() as cwd:
        last = Path(cwd) / "last.txt"
        cmd = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
               "-C", cwd, "-o", str(last), prompt]
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=timeout, env={**os.environ, "CODEX_HOME": str(codex_home())})
        text = last.read_text(encoding="utf-8") if last.exists() else ""
    if p.returncode != 0 or not text.strip():
        raise RuntimeError(f"codex 调用失败: exit={p.returncode} {p.stderr[-300:]!r}")
    m = re.search(r"^model:\s*(\S+)", p.stdout + "\n" + p.stderr, re.M)
    return text, {"models": [m.group(1) if m else "codex-default"]}


def call(model, prompt, system=None, append=None):
    if model == "codex":
        return call_codex(prompt, system)
    return call_claude(model, prompt, system, append)


def retry(fn, n=2):
    for i in range(n):
        try:
            return fn()
        except Exception:
            if i == n - 1:
                raise
            time.sleep(3)


# ---------- 读写 ----------

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"回答里没有 JSON: {text[:120]!r}")
    return json.loads(m.group(0))


def load_cases(only=None):
    cases = []
    for d in sorted((BENCH / "cases").iterdir()):
        if not (d / "case.json").exists():
            continue
        case = load(d / "case.json")
        case["materials"] = (d / "materials.md").read_text(encoding="utf-8").strip()
        if not only or case["id"] in only:
            cases.append(case)
    return cases


def condition_text(cond):
    """返回追加到系统提示的文字。被测 skill 按固定 commit 拉取，不入库。"""
    if "repo" not in cond:
        return cond.get("append")
    src = CACHE / "systems" / cond["id"]
    if not src.exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", cond["repo"], str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "checkout", "-q", cond["commit"]], check=True)
    parts = [cond.get("preface", "")]
    for f in cond["files"]:
        text = (src / f["path"]).read_text(encoding="utf-8")
        if f.get("strip_frontmatter"):
            text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
        if f.get("start_at"):
            text = text[text.index(f["start_at"]):]
        parts.append(text.strip())
    return "\n\n".join(p for p in parts if p)


def run_pool(work, jobs, workers):
    if not jobs:
        print("没有待做的任务")
        return
    codex_home()
    done = failed = 0
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(work, job): job for job in jobs}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                failed += 1
                print(f"失败 {futures[fut][0].name}: {str(e)[:200]}", file=sys.stderr)
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f"进度 {done}/{len(jobs)}，失败 {failed}", flush=True)


# ---------- 提示 ----------

def judge_prompt(case, text):
    facts = "\n".join(f"{f['id']}. {f['text']}" for f in case["facts"])
    return f"""下面有三部分。【材料】是作者掌握的全部信息。【事实清单】是从材料里摘出的事实。【成稿】是作者写给读者的文字，读者看不到材料。

任务一：对事实清单的每一条，判断成稿怎样表达了它。status 只能取下面三个值之一。
- kept：成稿表达了这条事实，含义一致。措辞可以不同。成稿没有逐字写出、但读者不需要别的知识就能直接推出来的，也算 kept。
- distorted：成稿提到了这件事，但信息和材料不一样。包括：
  · 数值或单位变了，或者只写了参数名、没有写数值；
  · 限定语丢了（例：“默认”“不算抖动”“含人工审改时间”）；
  · 否定、范围、条件、例外变了或丢了；
  · 说重了或说轻了（例：“会”写成“可能”，“没有验证”写成“不需要”或“已确认”）。标题和小结里说重了也算，即使正文别处是对的；
  · 把某一次的情况写成了通常的情况；
  · 用“未验证”“未确认”这类笼统的词替换了材料里更具体的说法；
  · 一条事实有多个要点，成稿只表达了一部分。
- missing：成稿完全没有提到这条事实。
如果这条事实本身写对了，只是成稿另一处有话和它相抵，这条事实仍然判 kept，把相抵的那句话放进任务二。
status 是 kept 或 distorted 时，quote 必须是从成稿里逐字复制的一小段原文（不超过 60 个字），是你判断的依据。status 是 missing 时，quote 是空字符串。note 用一句话说明理由。

任务二：找出成稿里材料不支持的内容，放进 additions。能从材料直接推出来的话不算。措辞、标题、过渡语不算。每条给出：
- quote：成稿原文，逐字复制，不超过 60 个字。
- type：只能取下面四个值之一。
  · step：材料里没有的操作步骤、通知、联系人、检查方法、禁令或要求，并且写成了读者要照做的规定。
  · claim：材料里没有的事实性说法。例：把一两个例子说成普遍规律；给并列的事实加上因果；自己下结论；编出数值或时间；替读者做了决定，或者把还没定的事说成已经定了。
  · advice：作者自己多给的解决办法、排查思路或使用建议，读者可以不采纳。
  · next：作者提出自己接下来可以做什么，或者请读者去做某件事，并且把决定权留给读者。
- labeled：true 或 false。读者能不能从措辞明确看出，这句话是作者自己的建议或推断，不是材料里的事实。例：用了“建议”“可以考虑”“我的想法是”“我推断”。只有 advice 和 claim 可能是 true。
- note：一句话理由。
没有就给空数组。

输出格式：
{{"facts":[{{"id":"F1","status":"kept","quote":"...","note":"..."}}],"additions":[{{"quote":"...","type":"step","labeled":false,"note":"..."}}]}}

【材料】
{case['materials']}

【事实清单】
{facts}

【成稿】
{text}
"""


def read_prompt(questions, text, skim):
    scope = "你只看到了这段文字的开头，后面的内容你没有读。" if skim else ""
    qs = "\n\n".join(
        f"{q['id']}. {q['q']}\n" + "\n".join(f"{k}. {v}" for k, v in q["options"].items())
        for q in questions)
    return f"""你只能看到下面这段文字，没有其他任何背景。{scope}请只根据你看到的文字回答问题。每题选一个选项。文字里没有说明、或者你看到的部分不足以回答时，选“文中没有说明”或“文中没有提到”那一项。不要用常识猜测。

输出格式：
{{"answers":[{{"id":"Q1","choice":"A"}}]}}

【文字】
{text}

【问题】
{qs}
"""


def head(text, n):
    count = 0
    for i, ch in enumerate(text):
        if not ch.isspace():
            count += 1
            if count == n:
                return text[:i + 1]
    return text


def squash(text):
    return re.sub(r"\s", "", text)


# ---------- 子命令 ----------

def cmd_gen(a):
    out = Path(a.out)
    conds = load(a.conditions)
    texts = {c["id"]: condition_text(c) for c in conds}
    jobs = [(out / "gen" / f"{case['id']}__{cond['id']}__r{r}.json", case, cond["id"], r)
            for case in load_cases(a.cases) for cond in conds for r in range(1, a.runs + 1)]
    jobs = [j for j in jobs if not j[0].exists()]

    def work(job):
        path, case, cond_id, r = job
        t = time.time()
        text, meta = retry(lambda: call(GEN_MODEL, case["task"] + "\n\n" + case["materials"],
                                        append=texts[cond_id]))
        save(path, {"case": case["id"], "cond": cond_id, "run": r, "text": text.strip(),
                    "meta": meta, "secs": round(time.time() - t, 1)})

    run_pool(work, jobs, a.workers)


def cmd_judge(a):
    out = Path(a.out)
    cases = {c["id"]: c for c in load_cases()}
    jobs = [(out / JUDGE_DIR / f"{g.stem}__{j}.json", g, j)
            for g in sorted((out / "gen").glob("*.json")) for j in JUDGES]
    jobs = [j for j in jobs if not j[0].exists()]

    def work(job):
        path, g, judge = job
        gen = load(g)
        case = cases[gen["case"]]
        body = squash(gen["text"])

        def once():
            raw, meta = call(judge, judge_prompt(case, gen["text"]), system=JUDGE_SYS)
            data = parse_json(raw)
            by_id = {f["id"]: f for f in data["facts"]}
            facts = []
            for f in case["facts"]:
                got = by_id[f["id"]]
                if got["status"] not in ("kept", "distorted", "missing"):
                    raise ValueError(f"非法 status: {got['status']}")
                quote = got.get("quote") or ""
                facts.append({"id": f["id"], "status": got["status"], "quote": quote,
                              "note": got.get("note", ""), "quote_ok": squash(quote) in body})
            adds = [{"quote": x.get("quote") or "", "type": x["type"] if x.get("type") in ADD_TYPES else "claim",
                     "labeled": x.get("labeled") is True, "note": x.get("note", ""),
                     "quote_ok": squash(x.get("quote") or "") in body}
                    for x in data.get("additions", [])]
            return {"facts": facts, "additions": adds, "meta": meta}

        save(path, retry(once))

    run_pool(work, jobs, a.workers)


def cmd_read(a):
    out = Path(a.out)
    cases = {c["id"]: c for c in load_cases()}
    jobs = []
    for g in sorted((out / "gen").glob("*.json")):
        jobs += [(out / "read" / f"{g.stem}__{r}__full.json", g, r, "full") for r in READERS]
        jobs.append((out / "read" / f"{g.stem}__{SKIM_READER}__skim.json", g, SKIM_READER, "skim"))
    jobs = [j for j in jobs if not j[0].exists()]

    def work(job):
        path, g, reader, mode = job
        gen = load(g)
        case = cases[gen["case"]]
        skim = mode == "skim"
        questions = [q for q in case["questions"] if q.get("skim") or not skim]
        text = head(gen["text"], SKIM_CHARS) if skim else gen["text"]

        def once():
            raw, meta = call(reader, read_prompt(questions, text, skim), system=READ_SYS)
            by_id = {x["id"]: str(x["choice"]).strip()[:1].upper() for x in parse_json(raw)["answers"]}
            answers = [{"id": q["id"], "choice": by_id[q["id"]], "correct": by_id[q["id"]] == q["answer"]}
                       for q in questions]
            return {"mode": mode, "answers": answers, "meta": meta}

        save(path, retry(once))

    run_pool(work, jobs, a.workers)


def text_metrics(text):
    sents = [squash(s) for s in re.split(r"[。！？!?；;\n]+", text)]
    lens = [len(s) for s in sents if re.search(r"[一-鿿A-Za-z0-9]", s)]
    return {
        "chars": len(squash(text)),
        "sent_mean": round(statistics.mean(lens), 1) if lens else 0,
        "sent_max": max(lens, default=0),
        "headers": len(re.findall(r"^#{1,6}\s", text, re.M)),
        "bullets": len(re.findall(r"^\s*(?:[-*+]|\d+[.)])\s", text, re.M)),
        "bold": len(re.findall(r"\*\*[^*\n]+\*\*", text)),
    }


def share(items):
    return sum(items) / len(items) if items else None


def is_violation(add, family):
    """编出的步骤一律算加料。建议和推断写明了就不算。提议下一步只在回复里不算。"""
    if add["type"] == "step":
        return True
    if add["type"] == "next":
        return family != "reply"
    return not add["labeled"]


def fmt(vals, pct=False):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    f = (lambda v: f"{v * 100:.0f}%") if pct else (lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
    mean = f(statistics.mean(vals))
    return mean if min(vals) == max(vals) else f"{mean} [{f(min(vals))}–{f(max(vals))}]"


def cmd_score(a):
    out = Path(a.out)
    cases = {c["id"]: c for c in load_cases()}
    rows, queue = [], []
    fact_pairs = fact_agree = read_pairs = read_agree = bad_quotes = quotes = 0

    for g in sorted((out / "gen").glob("*.json")):
        gen = load(g)
        case = cases[gen["case"]]
        row = {"case": gen["case"], "cond": gen["cond"], "run": gen["run"], **text_metrics(gen["text"])}

        verdicts = {}
        for j in JUDGES:
            p = out / JUDGE_DIR / f"{g.stem}__{j}.json"
            if not p.exists():
                continue
            jd = load(p)
            verdicts[j] = {f["id"]: f for f in jd["facts"]}
            row[f"kept_{j}"] = share([f["status"] == "kept" for f in jd["facts"]])
            row[f"distorted_{j}"] = sum(f["status"] == "distorted" for f in jd["facts"])
            row[f"missing_{j}"] = sum(f["status"] == "missing" for f in jd["facts"])
            row[f"added_{j}"] = sum(is_violation(x, case["family"]) for x in jd["additions"])
            row[f"allowed_{j}"] = sum(not is_violation(x, case["family"]) for x in jd["additions"])
            for f in jd["facts"]:
                if f["status"] != "missing":
                    quotes += 1
                    bad_quotes += not f["quote_ok"]
            queue += [{"kind": "addition", "file": g.stem, "judge": j, **x} for x in jd["additions"]]
        if len(verdicts) == len(JUDGES):
            for f in case["facts"]:
                got = {j: verdicts[j][f["id"]] for j in JUDGES}
                fact_pairs += 1
                if len({v["status"] for v in got.values()}) == 1:
                    fact_agree += 1
                else:
                    queue.append({"kind": "fact", "file": g.stem, "fact": f, **got})

        choices = {}
        for r in READERS:
            p = out / "read" / f"{g.stem}__{r}__full.json"
            if p.exists():
                answers = load(p)["answers"]
                choices[r] = {x["id"]: x["choice"] for x in answers}
                row[f"read_{r}"] = share([x["correct"] for x in answers])
        if len(choices) == len(READERS):
            for q in case["questions"]:
                read_pairs += 1
                read_agree += len({choices[r][q["id"]] for r in READERS}) == 1
        p = out / "read" / f"{g.stem}__{SKIM_READER}__skim.json"
        if p.exists():
            row["skim"] = share([x["correct"] for x in load(p)["answers"]])
        rows.append(row)

    cols = [("字数", "chars", False), ("句均长", "sent_mean", False), ("标题", "headers", False),
            ("列表项", "bullets", False), ("加粗", "bold", False)]
    for j in JUDGES:
        cols += [(f"事实保留·{j}", f"kept_{j}", True), (f"歪曲·{j}", f"distorted_{j}", False),
                 (f"没写·{j}", f"missing_{j}", False), (f"加料·{j}", f"added_{j}", False),
                 (f"允许的补充·{j}", f"allowed_{j}", False)]
    cols += [(f"读者答对·{r}", f"read_{r}", True) for r in READERS] + [("扫读答对", "skim", True)]

    def table(title, key):
        print(f"\n### {title}\n")
        print("| " + " | ".join(["条件"] + [c[0] for c in cols]) + " |")
        print("|" + "---|" * (len(cols) + 1))
        for cond in dict.fromkeys(r["cond"] for r in rows):
            sel = [r for r in rows if r["cond"] == cond and key(r)]
            if sel:
                print("| " + " | ".join([cond] + [fmt([r.get(k) for r in sel], pct) for _, k, pct in cols]) + " |")

    for cid in dict.fromkeys(r["case"] for r in rows):
        table(cid, lambda r, cid=cid: r["case"] == cid)
    table("全部用例", lambda r: True)

    agreement = {
        "judge_fact_agreement": fact_agree / fact_pairs if fact_pairs else None,
        "reader_agreement": read_agree / read_pairs if read_pairs else None,
        "judge_quote_not_verbatim": bad_quotes / quotes if quotes else None,
    }
    print(f"\n判分模型逐条一致率: {fmt([agreement['judge_fact_agreement']], True)}（{fact_agree}/{fact_pairs}）")
    print(f"读者模型逐题一致率: {fmt([agreement['reader_agreement']], True)}（{read_agree}/{read_pairs}）")
    print(f"判分引文不是成稿原文的比例: {fmt([agreement['judge_quote_not_verbatim']], True)}（{bad_quotes}/{quotes}）")
    print(f"待人工裁决: 事实分歧 {sum(q['kind'] == 'fact' for q in queue)} 条，"
          f"新增内容 {sum(q['kind'] == 'addition' for q in queue)} 条")
    save(out / "summary.json", {"rows": rows, "agreement": agreement})
    save(out / "queue.json", queue)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("gen", cmd_gen), ("judge", cmd_judge), ("read", cmd_read), ("score", cmd_score)):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True, help="本次运行的目录")
        p.add_argument("--workers", type=int, default=4)
        if name == "gen":
            p.add_argument("--runs", type=int, default=3)
            p.add_argument("--cases", nargs="*", help="只跑这些用例 id")
            p.add_argument("--conditions", default=str(BENCH / "conditions.json"), help="写作指令清单")
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
