# STE 人话（ste-renhua）

让 AI 写给人看的中文说人话：短、准、顺。

AI 写的中文常常太长、太绕，读着费劲。本项目要做一份 AI 写中文时默认遵守的表达标准，以及配套的 Agent Skill。思路来自 ASD-STE100（Simplified Technical English，简化技术英语）：航空业为了让维修手册不被读错而制定的受控语言标准。

标准覆盖三类输出：

- 每一轮回复：汇报结果、解释问题、请人做决定。
- 技术文档：操作手册、说明、排查记录。
- 对外分享材料：给其他团队看的介绍和总结。

## 状态

建设中。现在仓库里只有评测基准的试点代码，还没有可以安装的 skill。

## 原则：信息不变，只加工表达

这份标准只管怎么说，不管说什么。模型要告诉读者的信息，一条不多，一条不少，轻重不变。能动的只有表达：

- 同一件事只说一遍。
- 不写不带信息的话。
- 把难懂的说法换成好懂的。

## 做法：先建评测，再写规则

受控语言能把句子写短、写规整，也容易把事实写丢。所以本项目先建评测，一条规则只有在评测证明有效后才加入。

评测量六件事：

| 指标 | 量什么 | 怎么量 |
|---|---|---|
| 信息丢失 | 材料里的事实有没有被省掉 | 每条用例配一份事实清单，两个不同厂商的判分模型逐条核对 |
| 信息歪曲 | 事实的数值、条件、限定语、轻重有没有变 | 同上 |
| 加料 | 成稿里有没有材料不支持的内容 | 判分模型逐句找出，并分成步骤、结论、建议、下一步四类 |
| 表达问题 | 难懂的说法、重复、空话和绕句 | 两个判分模型只看成稿，摘出原文；另查临时代号是否在成稿中解释 |
| 读者结果 | 读者能不能得到正确结论 | 读者模型只看成稿，回答固定的选择题；另测只看开头一小段时的答对率 |
| 阅读成本 | 读者要读多少字 | 字数、句长、标题和列表的数量 |

### 判分规则

规则写在 `bench/run.py` 的判分提示里，现在是第 4 版。要点：

- 省掉任何一条事实都算丢失，不分“必要”和“非必要”。
- 限定语丢了、个例写成常规、说重或说轻、用笼统的词替换具体的说法，都算歪曲。标题里说重了也算。
- 没有逐字写出、但读者能直接推出来的，算保留。
- 编出材料里没有的步骤，一律算加料。
- 模型自己多给的建议或推断，读者能从措辞看出是建议或推断，就不算加料。写成事实才算。
- 作者提议下一步并把决定权留给读者，在回复里不算加料，在文档和分享材料里算。替读者做了决定，或者把没定的事说成已定，算加料。

### 检验判分本身：故意改坏测试

判分靠不靠得住，要单独验证。信息类测试删事实、说轻、说重、改数字、丢限定语和加料；表达类测试未解释的代号与缩写、依赖上文的指代、比喻、重复、空话和绕句。每份只改一处，并保存改动记录。另有“明确标明的建议”和“解释过的代号”两种应当放行的对照。

这些测试测的是发现所植入问题的能力。底稿未经人工确认完全无问题，底稿上标出的问题数量不能直接当作误报数；两个模型都判对也不等于人类读者验证通过。

### 补全事实清单

先单独生成无附加指令的基线成稿，再用 `facts` 找出“基线说了、材料支持、清单没写”的事实，合并进清单。这批基线不参与后面的对比。清单定稿后，重新生成比较用的成稿并判分；修改清单或材料时必须换运行目录，否则已有判分会被跳过。

补全清单仍依赖模型，需要复核。它不能证明一篇文字经过改写后信息完全不变：当前试点比较的是不同指令下重新生成的成稿，逐篇改写保真和人类读者验证尚未完成。

## 运行

需要本机已登录 `claude` 和 `codex` 命令行。脚本只用 Python 标准库。

```bash
# 试点：四种写法，每格 3 次
python3 bench/run.py gen   --out runs/pilot --runs 3
python3 bench/run.py judge --out runs/pilot
python3 bench/run.py express --out runs/pilot
python3 bench/run.py read  --out runs/pilot
python3 bench/run.py score --out runs/pilot

# 信息类故意改坏测试
python3 bench/mutate.py make --set info --from runs/pilot --cond none --out runs/mutants
python3 bench/run.py    judge  --out runs/mutants
python3 bench/mutate.py report --set info --out runs/mutants

# 表达类故意改坏测试
python3 bench/mutate.py make --set express --from runs/pilot --cond none --out runs/mutants-express
python3 bench/run.py express --out runs/mutants-express
python3 bench/mutate.py report --set express --out runs/mutants-express

# 长会话：先补清单，再开始独立的对比运行
python3 bench/run.py gen --out runs/long-session-facts --runs 1 --conds none --cases session-report-02 session-doc-02 session-share-02
python3 bench/run.py facts --from runs/long-session-facts --cases session-report-02 session-doc-02 session-share-02
python3 bench/run.py gen --out runs/long-session --runs 3 --cases session-report-02 session-doc-02 session-share-02
python3 bench/run.py judge --out runs/long-session
python3 bench/run.py express --out runs/long-session
python3 bench/run.py read --out runs/long-session
python3 bench/run.py score --out runs/long-session

# 运行器对抗检查，不调用模型
python3 -m unittest discover -s bench -p 'test_*.py'
```

- `bench/cases/`：用例。每条用例有原始材料、事实清单和读者问题。
- `bench/conditions.json`：无附加指令、一句话提示、固定提交的 `ste-zh` 和实验提示 `probe-v1`。实验提示不是已发布的产品规则；第三方 skill 不入库。
- `runs/`：运行结果，不入库。

`session-*-01` 是短会话，`session-*-02` 是长会话，分别覆盖回复、文档和分享。长会话保留早期起的代号，中间多轮追问数字、条件、例外与未验证状态，最后一问不提示代号。是否重现真实回复中的表达问题，需要用无附加指令的结果核验。

各步骤跳过已经落盘的文件。模型调用失败时命令以非零退出，成功文件保留；重跑同一命令只补失败项。未知写法、空指令清单、没有成稿就判分或汇总，也会以非零退出。事实和表达问题的引文必须非空并匹配成稿原文（忽略空白），不合格的结果会重试，不会落盘为成功结果。

结果记录实际模型标识。汇总允许缺项，缺项显示 `-`，因此应先核对判分和读者文件数量，再解释分数。`score` 表格按篇求平均，方括号是样本最小值与最大值，不是置信区间。

当前有 11 条 AI 构造的用例，尚未形成封存集，也未完成判分器的人工校准。小样本的模型判分不能作为产品领先或人类读者效果的证据。

### 2026-10-09 长会话试验快照

3 条长会话用例，每种写法各跑 3 次，共 36 篇成稿。生成模型为 `claude-sonnet-5-5`，判分模型为 `gpt-6.1-sol` 和 `claude-opus-5-5`，读者模型为 `gpt-6.1-sol` 和 `claude-haiku-5-5`。72 次信息判分、72 次表达判分、108 次读者答题均完成。3 份引文不合格的长会话判分保留在本地 `rejected-quotes/`，重判后引文检查通过。输出存放在 `runs/long-session/`，不入库；重跑会有波动。

下表字数为非空白字符数，字数和事实保留率按篇平均；表达问题按总次数除以总字数，再乘以 1000。

| 写法 | 字数 | 事实保留·Codex | 事实保留·Opus | 难懂/千字·Opus | 重复/千字·Opus |
|---|---:|---:|---:|---:|---:|
| 无指令 | 991.9 | 92.0% | 96.1% | 2.58 | 1.57 |
| 一句话 | 893.1 | 85.6% | 92.4% | 1.87 | 1.99 |
| ste-zh | 900.8 | 85.8% | 94.5% | 2.10 | 3.08 |
| 实验提示 probe-v1 | 815.1 | 92.3% | 96.0% | 1.91 | 0.82 |

实验提示平均少约 18% 的字，重复减少，事实保留率与无指令接近。它仍是方向探针，不能据此宣称逐篇信息不变或产品领先。全文答题接近满分，扫读每种写法只有 9 道题，尚不足以证明读者效果改善。

长会话无指令成稿中，两个模型均标出 2 处未解释代号；这是模型判断，尚未由人类裁决。其难懂说法为每千字 2.58 处，仍低于本地抽样的 60 条真实回复（同一 Opus 判分约 6.13 处）。核心痛点还未充分覆盖，真实会话素材仅保留在本地。

## 与 ASD-STE100 的关系

ASD-STE100 是 ASD（欧洲航空航天、安全与防务工业协会）发布的英文技术文档标准，只规定英文。本项目借用它的思路，为中文重新制定规则。本项目不是 ASD-STE100 的中文译本，不包含标准原文和词典，与 ASD 没有关联。标准原文可以在 [asd-ste100.org](https://www.asd-ste100.org) 免费申请。

## English

**ste-renhua** ("STE 人话", plain Chinese) is a work-in-progress writing standard and agent skill for the Chinese text that AI writes for people: replies, technical documents and shared write-ups. It applies the ideas of ASD-STE100 Simplified Technical English to Chinese. The benchmark comes first: it measures fact fidelity, reader comprehension and reading cost. No installable skill exists yet.

## 许可

[MIT](LICENSE)
