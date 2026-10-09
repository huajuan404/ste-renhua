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

补全清单仍依赖模型，需要复核。上述生成评测比较的是不同指令下重新生成的成稿，不能证明同一篇文字经过改写后信息不变。另有下述固定原稿评测；人类读者验证尚未完成。

### 固定原稿的改写保真评测

`bench/rewrite.py` 单独验证“同一篇原稿，只加工表达”。它不沿用上述材料支持判分规则：

- 原稿是信息边界，不核查原稿本身是否真实。原有建议、意见、推断、下一步和未验证状态都要保留，轻重不变。
- 新增内容一律算加料，明确标为建议也不放行。重复信息可以合并，纯客套可以删除。
- 每种写法都改写同一篇原稿。`none` 仍收到基础改写任务和信息保留要求，只是不附加写法指令。`identity` 是逐字不变的原稿对照，不调用生成模型。
- 判分逐条核对冻结的信息清单，还阅读全文找清单漏掉的信息变化。清单可以由 Opus 提取，但未经人工复核时不能称为完整真值。
- 运行清单冻结原稿、信息清单、条件的实际文本、次数、判分器和提示版本。已有目录的配置变化会报错；成稿带文本哈希，改动后的成稿不能复用判分。汇总要求所有预期成稿及判分齐全，不把缺项当通过。

原稿输入是 JSON 数组，每项包含 `id`、`text` 和可选 `reader`、`provenance`。`prepare` 补入 `units`：每个信息单元包含唯一 `id`、`text`、原稿逐字 `quote`。已有清单的 JSON 数组可直接交给 `gen`；单个对象也可，用于公开的合成对照。

```bash
# 先检查判分器：原文、等义改写，以及七种预设信息变化
python3 bench/rewrite.py calibrate --out runs/rewrite-calibration
# 故意让清单漏掉“生产尚未验证”，检查全文核对是否仍能抓到删失
python3 bench/rewrite.py calibrate --omit-units U2 --out runs/rewrite-calibration-incomplete

# 公开合成原稿的完整运行，每种写法一次；另保留一份 identity
python3 bench/rewrite.py gen --dataset bench/rewrite-calibration.json --out runs/rewrite-public --runs 1
python3 bench/rewrite.py judge --out runs/rewrite-public
python3 bench/run.py express --out runs/rewrite-public
python3 bench/rewrite.py score --out runs/rewrite-public --express

# 私有原稿放在仓库外。下面的 /path/to/private 是示例，替换成自己的绝对路径。
python3 bench/rewrite.py prepare --sources /path/to/private/sources.json --out /path/to/private/prepared
python3 bench/rewrite.py gen --dataset /path/to/private/prepared/dataset.json --out /path/to/private/run --runs 1 --judges opus
python3 bench/rewrite.py judge --out /path/to/private/run
python3 bench/run.py express --out /path/to/private/run --judges opus
python3 bench/rewrite.py score --out /path/to/private/run --express
```

人工复核可用原稿/改写并排对照，保留全文、机器提取的信息单元和判分理由：

```bash
python3 bench/render_review.py --from /path/to/private/run --out /path/to/private/review
```

输出用于会话内展示的交互片段 `rewrite-adjudication.html` 和对应数据 `review-data.json`，都包含私有原文，只放在本地私有目录，不提交或公开发布。每处标记可裁决为“确有信息变化 / 信息没变 / 暂不确定”，也可选做原稿与实验提示的阅读感受对比。界面选择可在会话中暂存，但不会自动写入本地文件；用“把裁决发给 Codex”提交已选项目，或复制“汇总裁决”的 JSON 再交给 Codex 落盘。记录带运行和对照数据哈希，未选择的项仍待裁决，原模型判分保留。

`calibrate` 要求两个判分器逐单元的状态、清单外变化数、加料数全部符合预设答案，差异会以非零退出。公开对照包含删除建议、建议变命令、提高确定性、改单位、扩大条件、删除未验证状态、新增建议；这些有限例子不能证明复杂文本上没有漏报或误报。

原稿未附带此前对话，改写任务禁止猜测原稿中没有解释的代号。需要外部上下文才能解释的说法，不能靠这次评测证明已经解决。私有原稿及模型输出留在仓库外；本地试验只用 Claude 处理这些内容。

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

### 2026-10-09 固定原稿试验快照

判分器先做两组对抗检查：完整清单，以及故意漏掉“生产环境尚未验证”的清单。每组包括 2 个放行对照和 7 种信息变化；Codex 与 Opus 均为 9/9 与逐单元预期完全一致，共 36 次判分。漏项组中，两家模型都通过全文核对抓到了删掉未验证状态的问题。公开合成原稿另跑 4 种写法，每种 1 次，连同原稿共 5 篇；10 次信息判分和 10 次表达判分完成。两家判分器均标出 `ste-zh` 的一次排他限定丢失，其余三种写法通过；这不是第三方产品的总体质量结论。

真实试验从已完成表达判分的 60 条本地回复中，按非空白字数分成 500–999、1000–1999、2000–5999 三档。每档按 `SHA256("rewrite-pilot-v1:" + 原稿)` 排序取前 2 条，选样在生成改写稿前固定，没有按改写效果挑选。它只覆盖这批工程回复，不代表技术文档、分享材料或全部真实回复。

6 条原稿共提取 342 个信息单元，清单由 Opus 提取，未经人工复核。每种写法各跑 1 次，共 24 篇改写稿，加上 6 份原稿对照；30 次信息判分与 30 次表达判分完成。生成模型为 `claude-sonnet-5-5`，两种判分都只用 `claude-opus-5-5`。私有内容没有交给 Codex，也没有进入仓库。

| 写法 | 平均非空白字数 | 判为信息不变 | 难懂/千字 | 重复/千字 |
|---|---:|---:|---:|---:|
| 原稿 identity | 1790.7 | 6/6 | 6.89 | 1.02 |
| 基础改写 none | 1842.2 | 5/6 | 6.15 | 1.54 |
| 一句话 | 1880.0 | 1/6 | 6.56 | 1.68 |
| ste-zh | 1824.7 | 2/6 | 6.12 | 1.83 |
| 实验提示 probe-v1 | 1834.2 | 4/6 | 6.00 | 1.45 |

“信息不变”要求所有信息单元保留，且没有清单外丢失/歪曲或任何加料。一处变化就不通过。基础改写被标出 1 处加料；一句话被标出 4 处歪曲、2 处加料；`ste-zh` 被标出 8 处歪曲；实验提示被标出 2 处歪曲、1 处加料。均无整条信息完全缺失的模型标记。这些是模型判定，不是人工确认缺陷数。

四种改写平均都更长，重复率也均高于原稿。实验提示的难懂说法较少，但没有满足这批样本上“信息不变”的门槛；先前重新生成试验里少字的结果，不能迁移为改写同一原稿的结论。目前不据此发布可保证保真的 skill，也不据 6 条、每种 1 次的结果建立产品排名。下一步应先复核模型标出的变化，再用独立样本验证规则修改；人类理解效果仍未验证。

私有原稿、选择记录、清单、冻结运行配置和逐篇结果保存在本机 `ste-renhua-private/real/rewrite-v1/`，汇总为 `run/rewrite-summary.json`。公开对照在 `runs/rewrite-calibration/`、`runs/rewrite-calibration-incomplete/` 和 `runs/rewrite-public/`，全部结果目录不入库。

## 与 ASD-STE100 的关系

ASD-STE100 是 ASD（欧洲航空航天、安全与防务工业协会）发布的英文技术文档标准，只规定英文。本项目借用它的思路，为中文重新制定规则。本项目不是 ASD-STE100 的中文译本，不包含标准原文和词典，与 ASD 没有关联。标准原文可以在 [asd-ste100.org](https://www.asd-ste100.org) 免费申请。

## English

**ste-renhua** ("STE 人话", plain Chinese) is a work-in-progress writing standard and agent skill for the Chinese text that AI writes for people: replies, technical documents and shared write-ups. It applies the ideas of ASD-STE100 Simplified Technical English to Chinese. The benchmark comes first: it measures fact fidelity, reader comprehension and reading cost. No installable skill exists yet.

## 许可

[MIT](LICENSE)
