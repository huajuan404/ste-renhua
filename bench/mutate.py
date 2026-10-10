#!/usr/bin/env python3
"""故意改坏测试：检验判分能不能发现问题。

    # 信息类：删事实、说轻、说重、改数字、丢限定语、加料
    python3 bench/mutate.py make   --set info --from runs/pilot --cond none --out runs/mutants-info
    python3 bench/run.py    judge  --out runs/mutants-info
    python3 bench/mutate.py report --set info --out runs/mutants-info

    # 表达类：没解释的代号和缩写、要看上文的指代、比喻、绕、重复、空话
    python3 bench/mutate.py make    --set express --from runs/pilot --cond none --out runs/mutants-express
    python3 bench/run.py    express --out runs/mutants-express
    python3 bench/mutate.py report  --set express --out runs/mutants-express

make 取一批成稿当底稿，每份底稿各改坏一处，生成一批改坏稿。
每份改坏稿只动一个地方，并记下动了什么。
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

# 改法。mode：fact 是改一条指定的事实，swap 是替换一段原文，insert 是插入一句新话。
# ok=True 的是对照：这种改动不算问题，判分应当放行。
KINDS = [
    dict(id="del", set="info", mode="fact", n=2, expect="missing", name="删掉一条事实",
         desc="把表达这条事实的句子或分句整个删掉，让读者从成稿里完全得不到这条事实。after 写删掉以后留在原处的文字，通常是空字符串。"),
    dict(id="weak", set="info", mode="fact", n=1, expect="distorted", name="说轻了",
         desc="把这条事实说轻。例：把“会”改成“可能”，把“必须”改成“建议”，把“不得”改成“尽量不要”。"),
    dict(id="strong", set="info", mode="fact", n=1, expect="distorted", name="说重了",
         desc="把这条事实说重。例：把“可能”改成“会”，把“没有验证”改成“已经确认”，把“推断”改成“实测”，或者把范围说大。"),
    dict(id="num", set="info", mode="fact", n=2, expect="distorted", name="改了数字",
         desc="把这条事实里的一个数值或单位，改成另一个看起来合理的值。"),
    dict(id="qual", set="info", mode="fact", n=1, expect="distorted", name="丢了限定语",
         desc="删掉这条事实里的一个限定语、条件或例外，主体保留。例：删掉“默认”“不算抖动”，或者把“小于 30 秒才能继续”里的条件去掉。"),
    dict(id="step", set="info", mode="insert", n=1, name="加了一个步骤",
         desc="加一句材料里没有的操作步骤或要求，看起来合理。"),
    dict(id="claim", set="info", mode="insert", n=1, name="加了一个结论",
         desc="加一句材料里没有的事实性结论。例：把个别例子说成普遍规律，或者给两件事加上因果。"),
    dict(id="advice", set="info", mode="insert", n=1, name="加了没标明的建议",
         desc="加一句作者自己的解决办法或建议，写得像既定的做法，不说明这是建议。"),
    dict(id="advice-ok", set="info", mode="insert", n=1, ok=True, name="加了标明的建议",
         desc="加一句作者自己的解决办法或建议，并且明确写明这是作者自己的建议，材料里没有，没有验证过。"),

    dict(id="code", set="express", mode="swap", n=2, field="hard", name="换成没解释的代号",
         desc="从成稿里选一个说得很具体的东西（一个方案、一条规则、一个问题、一组数据），把这段具体的说法换成一个作者自己起的代号，例如“方案 B”“R2”“第二类”。全文不解释这个代号指什么。"),
    dict(id="abbr", set="express", mode="swap", n=1, field="hard", name="换成没解释的缩写",
         desc="把成稿里一个完整的名称换成一个作者自己缩出来的、读者没见过的缩写，全文不解释。例：把“订单明细表”换成“OD 表”。常见的缩写不要用。"),
    dict(id="ref", set="express", mode="swap", n=2, field="hard", name="换成要看上文的指代",
         desc="把成稿里一段说得很具体的内容，换成一个要看过之前的讨论才知道指什么的说法。例：“上次说的那个问题”“第二轮的结论”“按之前定的做法”。"),
    dict(id="metaphor", set="express", mode="swap", n=1, field="hard", name="换成比喻",
         desc="把成稿里一句平实的话换成比喻或口语化的说法，让读者要猜它的意思。例：把“先用小流量验证”换成“先放一只金丝雀下井”。"),
    dict(id="winding", set="express", mode="swap", n=1, field="winding", name="改成绕的句子",
         desc="选两到三句相邻的短句，合并成一句要读两遍才能懂的长句：从句套从句，或者把三件事塞进一句。信息不增不减。"),
    dict(id="repeat", set="express", mode="insert", n=1, field="repeats", name="加了一句重复",
         desc="加一句话，把前面已经说过的一件事换个说法再说一遍，不带任何新信息。"),
    dict(id="filler", set="express", mode="insert", n=1, field="fillers", name="加了一句空话",
         desc="加一句不带任何事实、条件、要求或决定的话，例如过渡语、铺垫或总结套话。"),
    dict(id="code-ok", set="express", mode="swap", n=1, field="hard", ok=True, name="换成解释过的代号",
         desc="从成稿里选一个说得很具体的东西，给它起一个代号，并且在同一句里把这个代号指什么说清楚。例：“把批大小调到 2000（下面叫方案 B）”。原来的具体说法要保留。"),
]
KIND = {k["id"]: k for k in KINDS}


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


def prompt_for(kind, case, text, used):
    avoid = f"不要再选这些：{'；'.join(sorted(used))}。" if used else ""
    if kind["mode"] == "fact":
        return header(case, text) + f"""
改法：{kind['desc']}

要求：
- 从事实清单里选一条适合这种改法的事实。成稿里必须确实写了这条事实，而且只在一处写了它。{avoid}
- before 是成稿里要被替换的原文片段，必须逐字复制，并且在成稿里只出现一次。片段尽量短，只包住要改的地方。
- after 是替换后的文字。改完读起来要自然，像作者自己写的。
- 除了这一处，不改任何别的地方。不要让别的事实受影响。

输出格式：{{"fact":"F3","before":"...","after":"..."}}
"""
    if kind["mode"] == "swap":
        return header(case, text) + f"""
改法：{kind['desc']}

要求：
- before 是成稿里要被替换的原文片段，必须逐字复制，并且在成稿里只出现一次。{avoid}
- after 是替换后的文字。改完读起来要自然，像作者自己写的。
- 除了这一处，不改任何别的地方。

输出格式：{{"before":"...","after":"..."}}
"""
    return header(case, text) + f"""
改法：{kind['desc']}

要求：
- anchor 是成稿里的一句原文，必须逐字复制，并且在成稿里只出现一次。新句子紧接在它后面。
- insert 是要加进去的新句子。读起来要自然，像作者自己写的。
- 不改任何别的地方。

输出格式：{{"anchor":"...","insert":"..."}}
"""


def apply(kind, case, text, m, used):
    """检查模型给的改法合不合格，合格就返回改坏稿和记录。"""
    if kind["mode"] == "insert":
        assert text.count(m["anchor"]) == 1, "anchor 在成稿里不是恰好出现一次"
        assert m["insert"].strip() and run.squash(m["insert"]) not in run.squash(text), "insert 不合格"
        return text.replace(m["anchor"], m["anchor"] + m["insert"], 1), {"anchor": m["anchor"], "insert": m["insert"]}
    assert text.count(m["before"]) == 1, "before 在成稿里不是恰好出现一次"
    assert m["after"] != m["before"] and m["before"] not in used, "没有改动，或者选了用过的地方"
    meta = {"before": m["before"], "after": m["after"]}
    if kind["mode"] == "fact":
        assert m["fact"] in {f["id"] for f in case["facts"]} and m["fact"] not in used, "事实编号不对"
        meta["fact"] = m["fact"]
        if kind["id"] == "del":
            assert len(m["after"]) <= len(m["before"]) // 2, "不是删除"
    else:
        assert m["after"].strip(), "after 不能为空"
    return text.replace(m["before"], m["after"], 1), meta


def cmd_make(a):
    src, out = Path(a.src), Path(a.out)
    cases = {c["id"]: c for c in run.load_cases()}
    kinds = [k for k in KINDS if k["set"] == a.set]
    gens = [run.load(g) for g in sorted((src / "gen").glob("*.json"))]
    bases = [g for g in gens if g["cond"] == a.cond and g["run"] in a.runs
             and (not a.cases or g["case"] in a.cases) and len(cases[g["case"]]["facts"]) >= MIN_FACTS]
    jobs = []
    for gen in bases:
        path = out / "gen" / f"{gen['case']}__orig__r{gen['run']}.json"
        if not path.exists():
            run.save(path, {"case": gen["case"], "cond": "orig", "run": gen["run"], "text": gen["text"],
                            "mutation": {"kind": "orig"}})
        for kind in kinds:
            for k in range(1, kind["n"] + 1):
                path = out / "gen" / f"{gen['case']}__{kind['id']}{k}__r{gen['run']}.json"
                if not path.exists():
                    jobs.append((path, gen, kind, k))

    def work(job):
        path, gen, kind, k = job
        case, text = cases[gen["case"]], gen["text"]
        # 同一份底稿、同一种改法的第 2 份，避开第 1 份改过的地方
        used = set()
        for i in range(1, k):
            p = out / "gen" / f"{gen['case']}__{kind['id']}{i}__r{gen['run']}.json"
            if p.exists():
                m = run.load(p)["mutation"]
                used.add(m.get("fact") or m.get("before") or m.get("anchor"))

        def once():
            raw, _ = run.call_claude("opus", prompt_for(kind, case, text, used), system=SYS)
            return apply(kind, case, text, run.parse_json(raw), used)

        mutant, meta = run.retry(once, n=3)
        run.save(path, {"case": gen["case"], "cond": f"{kind['id']}{k}", "run": gen["run"], "text": mutant,
                        "mutation": {"kind": kind["id"], **meta}})

    # 同一份底稿的同一种改法要串行，否则避不开改过的地方；所以按 k 分轮
    for k in (1, 2):
        run.run_pool(work, [j for j in jobs if j[3] == k], a.workers)


def bigrams(s):
    s = run.squash(s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def overlaps(quote, target):
    p, q = bigrams(quote), bigrams(target)
    return len(p & q) / max(1, min(len(p), len(q))) >= 0.5


def hit_info(kind, m, v, v0, family):
    """信息类：这个判分模型有没有发现。返回 None 表示这份改坏稿对它无效。"""
    if kind["mode"] == "fact":
        if next(f["status"] for f in v0["facts"] if f["id"] == m["fact"]) != "kept":
            return None  # 底稿里这条事实本来就没被判保留
        return next(f["status"] for f in v["facts"] if f["id"] == m["fact"]) != "kept"
    flagged = [x for x in v["additions"] if overlaps(x["quote"], m["insert"])]
    violation = any(run.is_violation(x, family) for x in flagged)
    return not violation if kind.get("ok") else violation


def hit_express(kind, m, v):
    target = m.get("insert") or m["after"]
    quotes = [q for x in v[kind["field"]] for q in (x.get("quote"), x.get("first"), x.get("again")) if q]
    if kind.get("ok"):
        # 解释过的代号保留原来的具体说法。原句已有的缩写被标出，
        # 不能归因为新增代号没解释；只统计改动引入的说法。
        before = run.squash(m.get("before", ""))
        quotes = [q for q in quotes if run.squash(q) not in before]
    found = any(overlaps(q, target) for q in quotes)
    return not found if kind.get("ok") else found


def cmd_report(a):
    out = Path(a.out)
    cases = {c["id"]: c for c in run.load_cases()}
    kinds = [k for k in KINDS if k["set"] == a.set]
    vdir = run.JUDGE_DIR if a.set == "info" else run.EXPRESS_DIR
    gens = {g.stem: run.load(g) for g in sorted((out / "gen").glob("*.json"))}
    verdict = {(stem, j): run.load(out / vdir / f"{stem}__{j}.json")
               for stem in gens for j in run.JUDGES if (out / vdir / f"{stem}__{j}.json").exists()}

    stats = collections.defaultdict(collections.Counter)
    misses, rows = [], []
    for stem, gen in gens.items():
        m = gen["mutation"]
        family = cases[gen["case"]]["family"]
        if m["kind"] == "orig":
            for j in run.JUDGES:
                v = verdict.get((stem, j))
                if not v:
                    continue
                stats["orig"][f"n_{j}"] += 1
                if a.set == "info":
                    stats["orig"][f"事实_{j}"] += sum(f["status"] != "kept" for f in v["facts"])
                    stats["orig"][f"加料_{j}"] += sum(run.is_violation(x, family) for x in v["additions"])
                else:
                    for field, name in (("hard", "难懂"), ("repeats", "重复"), ("fillers", "空话"), ("winding", "绕")):
                        stats["orig"][f"{name}_{j}"] += len(v[field])
            continue
        kind = KIND[m["kind"]]
        if kind["set"] != a.set:
            continue
        hit = {}
        for j in run.JUDGES:
            v = verdict.get((stem, j))
            v0 = verdict.get((f"{gen['case']}__orig__r{gen['run']}", j))
            if not v or not v0:
                continue
            h = hit_info(kind, m, v, v0, family) if a.set == "info" else hit_express(kind, m, v)
            if h is None:
                continue
            hit[j] = h
            stats[kind["id"]][f"n_{j}"] += 1
            stats[kind["id"]][f"hit_{j}"] += h
        if len(hit) == len(run.JUDGES):
            stats[kind["id"]]["n_both"] += 1
            stats[kind["id"]]["hit_all"] += all(hit.values())
            stats[kind["id"]]["hit_any"] += any(hit.values())
        rows.append({"file": stem, "kind": kind["id"], "mutation": m, "hit": hit})
        if hit and not all(hit.values()):
            misses.append((stem, kind, m, hit))

    def frac(n, d):
        return f"{n}/{d}" if d else "-"

    print("| 改法 | " + " | ".join(f"{j} 判对" for j in run.JUDGES) + " | 至少一个判对 | 两个都判对 |")
    print("|---|" + "---|" * (len(run.JUDGES) + 2))
    for kind in kinds:
        s = stats[kind["id"]]
        label = kind["name"] + ("（应当放行）" if kind.get("ok") else "")
        print(f"| {label} | " + " | ".join(frac(s[f"hit_{j}"], s[f"n_{j}"]) for j in run.JUDGES)
              + f" | {frac(s['hit_any'], s['n_both'])} | {frac(s['hit_all'], s['n_both'])} |")
    s = stats["orig"]
    names = ("事实", "加料") if a.set == "info" else ("难懂", "重复", "空话", "绕")
    print("\n没改过的底稿上被标出的数量："
          + "；".join(f"{j}（{s[f'n_{j}']} 份）" + "、".join(f"{n} {s[f'{n}_{j}']}" for n in names) for j in run.JUDGES))
    print(f"\n没有被两个判分模型都判对的改坏稿：{len(misses)} 份")
    for stem, kind, m, hit in misses:
        change = f"「{m.get('before', m.get('anchor', ''))[:36]}」→「{m.get('after', m.get('insert', ''))[:36]}」"
        print(f"- {stem} {kind['name']} {m.get('fact', '')}{change} {hit}")
    run.save(out / f"mutation-report-{a.set}.json", {"stats": {k: dict(v) for k, v in stats.items()}, "rows": rows})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("make")
    p.add_argument("--set", choices=("info", "express"), required=True, help="信息类还是表达类")
    p.add_argument("--from", dest="src", required=True, help="底稿所在的运行目录")
    p.add_argument("--cond", required=True, help="取哪种写法的成稿当底稿")
    p.add_argument("--runs", type=int, nargs="*", default=[1, 2], help="取哪几轮")
    p.add_argument("--cases", nargs="*", help="只取这些用例 id")
    p.add_argument("--out", required=True)
    p.add_argument("--workers", type=int, default=5)
    p.set_defaults(fn=cmd_make)
    p = sub.add_parser("report")
    p.add_argument("--set", choices=("info", "express"), required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
