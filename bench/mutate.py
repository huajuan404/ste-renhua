#!/usr/bin/env python3
"""故意改坏测试：检验判分能不能发现信息变化。

    python3 bench/mutate.py make   --from runs/pilot --cond none --out runs/mutants
    python3 bench/run.py    judge  --out runs/mutants
    python3 bench/mutate.py report --out runs/mutants

make 取一批成稿当底稿，每份底稿各改坏一处，生成一批改坏稿。
每份改坏稿只动一个地方，并记下动了哪条事实、怎么动的。
report 统计两个判分模型各自发现了多少。
"""
import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run  # noqa: E402

SYS = "你在帮忙构造测试数据。只输出一个 JSON 对象，不要输出任何其他文字。"
MIN_FACTS = 5  # 事实太少的用例不当底稿

# 改法：(编号, 名称, 每份底稿做几份, 说明)
FACT_KINDS = [
    ("del", "删掉一条事实", 2, "把表达这条事实的句子或分句整个删掉，让读者从成稿里完全得不到这条事实。after 写删掉以后留在原处的文字，通常是空字符串。"),
    ("weak", "说轻了", 1, "把这条事实说轻。例：把“会”改成“可能”，把“必须”改成“建议”，把“不得”改成“尽量不要”。"),
    ("strong", "说重了", 1, "把这条事实说重。例：把“可能”改成“会”，把“没有验证”改成“已经确认”，把“推断”改成“实测”，或者把范围说大。"),
    ("num", "改了数字", 2, "把这条事实里的一个数值或单位，改成另一个看起来合理的值。"),
    ("qual", "丢了限定语", 1, "删掉这条事实里的一个限定语、条件或例外，主体保留。例：删掉“默认”“不算抖动”，或者把“小于 30 秒才能继续”里的条件去掉。"),
]
ADD_KINDS = [
    ("step", "加了一个步骤", 1, "加一句材料里没有的操作步骤或要求，看起来合理。"),
    ("claim", "加了一个结论", 1, "加一句材料里没有的事实性结论。例：把个别例子说成普遍规律，或者给两件事加上因果。"),
    ("advice", "加了没标明的建议", 1, "加一句作者自己的解决办法或建议，写得像既定的做法，不说明这是建议。"),
    ("advice-ok", "加了标明的建议", 1, "加一句作者自己的解决办法或建议，并且明确写明这是作者自己的建议，材料里没有，没有验证过。"),
]
NAMES = {k: name for k, name, _, _ in FACT_KINDS + ADD_KINDS}
EXPECT = {"del": "missing", "weak": "distorted", "strong": "distorted", "num": "distorted", "qual": "distorted"}


def header(case, text):
    facts = "\n".join(f"{f['id']}. {f['text']}" for f in case["facts"])
    return f"""下面是【材料】、从材料里摘出的【事实清单】，和一篇忠实于材料的【成稿】。
我在测试审校能不能发现成稿里的问题，需要你把成稿改坏一处。

【材料】
{case['materials']}

【事实清单】
{facts}

【成稿】
{text}
"""


def fact_prompt(case, text, desc, used):
    exclude = f"不要选这些事实：{'、'.join(sorted(used))}。" if used else ""
    return header(case, text) + f"""
改法：{desc}

要求：
- 从事实清单里选一条适合这种改法的事实。成稿里必须确实写了这条事实，而且只在一处写了它。{exclude}
- before 是成稿里要被替换的原文片段，必须逐字复制，并且在成稿里只出现一次。片段尽量短，只包住要改的地方。
- after 是替换后的文字。改完读起来要自然，像作者自己写的。
- 除了这一处，不改任何别的地方。不要让别的事实受影响。

输出格式：{{"fact":"F3","before":"...","after":"..."}}
"""


def add_prompt(case, text, desc):
    return header(case, text) + f"""
改法：{desc}

要求：
- anchor 是成稿里的一句原文，必须逐字复制，并且在成稿里只出现一次。新句子紧接在它后面。
- insert 是要加进去的新句子。内容必须是材料里没有、也不能从材料直接推出来的。读起来要自然，像作者自己写的。
- 不改任何别的地方。

输出格式：{{"anchor":"...","insert":"..."}}
"""


def cmd_make(a):
    src, out = Path(a.src), Path(a.out)
    cases = {c["id"]: c for c in run.load_cases()}
    bases = [g for g in sorted((src / "gen").glob("*.json"))
             if run.load(g)["cond"] == a.cond and run.load(g)["run"] in a.runs
             and len(cases[run.load(g)["case"]]["facts"]) >= MIN_FACTS]
    jobs = []
    for g in bases:
        gen = run.load(g)
        path = out / "gen" / f"{gen['case']}__orig__r{gen['run']}.json"
        if not path.exists():
            run.save(path, {"case": gen["case"], "cond": "orig", "run": gen["run"], "text": gen["text"],
                            "mutation": {"kind": "orig", "base": g.stem}})
        for kind, _, count, desc in FACT_KINDS + ADD_KINDS:
            for k in range(1, count + 1):
                path = out / "gen" / f"{gen['case']}__{kind}{k}__r{gen['run']}.json"
                if not path.exists():
                    jobs.append((path, gen, kind, k, desc))

    def work(job):
        path, gen, kind, k, desc = job
        case, text = cases[gen["case"]], gen["text"]
        fact_ids = {f["id"] for f in case["facts"]}
        # 同一份底稿、同一种改法的第 2 份，避开第 1 份用过的事实
        used = set()
        for p in (out / "gen").glob(f"{gen['case']}__{kind}*__r{gen['run']}.json"):
            used.add(run.load(p)["mutation"].get("fact"))
        used.discard(None)

        def once():
            if kind in EXPECT:
                raw, _ = run.call_claude("opus", fact_prompt(case, text, desc, used), system=SYS)
                m = run.parse_json(raw)
                assert m["fact"] in fact_ids and m["fact"] not in used, "事实编号不对"
                assert text.count(m["before"]) == 1, "before 在成稿里不是恰好出现一次"
                assert m["after"] != m["before"], "没有改动"
                if kind == "del":
                    assert len(m["after"]) <= len(m["before"]) // 2, "不是删除"
                return text.replace(m["before"], m["after"], 1), {"fact": m["fact"], "before": m["before"], "after": m["after"]}
            raw, _ = run.call_claude("opus", add_prompt(case, text, desc), system=SYS)
            m = run.parse_json(raw)
            assert text.count(m["anchor"]) == 1, "anchor 在成稿里不是恰好出现一次"
            assert m["insert"].strip() and run.squash(m["insert"]) not in run.squash(text), "insert 不合格"
            return text.replace(m["anchor"], m["anchor"] + m["insert"], 1), {"anchor": m["anchor"], "insert": m["insert"]}

        mutant, meta = run.retry(once, n=3)
        run.save(path, {"case": gen["case"], "cond": f"{kind}{k}", "run": gen["run"], "text": mutant,
                        "mutation": {"kind": kind, **meta}})

    # 同一份底稿的同一种改法要串行，否则避不开用过的事实；所以按 k 分两轮
    for k in (1, 2):
        run.run_pool(work, [j for j in jobs if j[3] == k], a.workers)


def bigrams(s):
    s = run.squash(s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def overlaps(quote, insert):
    p, q = bigrams(quote), bigrams(insert)
    return len(p & q) / max(1, min(len(p), len(q))) >= 0.5


def cmd_report(a):
    out = Path(a.out)
    cases = {c["id"]: c for c in run.load_cases()}
    gens = {g.stem: run.load(g) for g in sorted((out / "gen").glob("*.json"))}
    verdict = {}
    for stem in gens:
        for j in run.JUDGES:
            p = out / run.JUDGE_DIR / f"{stem}__{j}.json"
            if p.exists():
                verdict[(stem, j)] = run.load(p)

    def base_of(gen):
        return f"{gen['case']}__orig__r{gen['run']}"

    stats = collections.defaultdict(lambda: collections.Counter())
    misses, rows = [], []
    for stem, gen in gens.items():
        m = gen["mutation"]
        kind = m["kind"]
        family = cases[gen["case"]]["family"]
        if kind == "orig":
            for j in run.JUDGES:
                v = verdict.get((stem, j))
                if v:
                    stats["orig"][f"n_{j}"] += 1
                    stats["orig"][f"facts_{j}"] += sum(f["status"] != "kept" for f in v["facts"])
                    stats["orig"][f"adds_{j}"] += sum(run.is_violation(x, family) for x in v["additions"])
            continue
        hit = {}
        for j in run.JUDGES:
            v, v0 = verdict.get((stem, j)), verdict.get((base_of(gen), j))
            if not v or not v0:
                continue
            if kind in EXPECT:
                s0 = next(f["status"] for f in v0["facts"] if f["id"] == m["fact"])
                if s0 != "kept":
                    continue  # 底稿里这条事实本来就没被判保留，这份改坏稿对这个判分无效
                s = next(f["status"] for f in v["facts"] if f["id"] == m["fact"])
                hit[j] = s != "kept"
                stats[kind][f"exact_{j}"] += s == EXPECT[kind]
                base_status = {f["id"]: f["status"] for f in v0["facts"]}
                stats[kind][f"collateral_{j}"] += sum(f["status"] != base_status[f["id"]] for f in v["facts"] if f["id"] != m["fact"])
            else:
                flagged = [x for x in v["additions"] if overlaps(x["quote"], m["insert"])]
                violation = any(run.is_violation(x, family) for x in flagged)
                hit[j] = (not violation) if kind == "advice-ok" else violation
            stats[kind][f"n_{j}"] += 1
            stats[kind][f"hit_{j}"] += hit[j]
        if len(hit) == len(run.JUDGES):
            stats[kind]["n_both"] += 1
            stats[kind]["hit_all"] += all(hit.values())
            stats[kind]["hit_any"] += any(hit.values())
        rows.append({"file": stem, "kind": kind, "mutation": m, "hit": hit})
        if hit and not all(hit.values()):
            misses.append((stem, kind, m, hit))

    def pct(n, d):
        return f"{n}/{d}" if d else "-"

    print("| 改法 | " + " | ".join(f"{j} 发现" for j in run.JUDGES) + " | 至少一个发现 | 两个都发现 |")
    print("|---|" + "---|" * (len(run.JUDGES) + 2))
    for kind, name, _, _ in FACT_KINDS + ADD_KINDS:
        s = stats[kind]
        label = name + ("（应当放行）" if kind == "advice-ok" else "")
        print(f"| {label} | " + " | ".join(pct(s[f"hit_{j}"], s[f"n_{j}"]) for j in run.JUDGES)
              + f" | {pct(s['hit_any'], s['n_both'])} | {pct(s['hit_all'], s['n_both'])} |")
    s = stats["orig"]
    print("\n没改过的底稿被误报的次数："
          + "；".join(f"{j}：{s[f'facts_{j}']} 条事实、{s[f'adds_{j}']} 处加料（共 {s[f'n_{j}']} 份）" for j in run.JUDGES))
    print("改坏一处时，别的事实被连带改判的次数："
          + "；".join(f"{j}：{sum(stats[k][f'collateral_{j}'] for k in EXPECT)}" for j in run.JUDGES))
    print(f"\n没有被两个判分模型都发现的改坏稿：{len(misses)} 份")
    for stem, kind, m, hit in misses:
        change = f"{m.get('fact', '')}「{m.get('before', m.get('anchor', ''))[:40]}」→「{m.get('after', m.get('insert', ''))[:40]}」"
        print(f"- {stem} {NAMES[kind]} {change} {hit}")
    run.save(out / "mutation-report.json", {"stats": {k: dict(v) for k, v in stats.items()}, "rows": rows})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("make")
    p.add_argument("--from", dest="src", required=True, help="底稿所在的运行目录")
    p.add_argument("--cond", required=True, help="取哪种写法的成稿当底稿")
    p.add_argument("--runs", type=int, nargs="*", default=[1, 2], help="取哪几轮")
    p.add_argument("--out", required=True)
    p.add_argument("--workers", type=int, default=5)
    p.set_defaults(fn=cmd_make)
    p = sub.add_parser("report")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
