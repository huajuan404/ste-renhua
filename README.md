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

评测量五件事：

| 指标 | 量什么 | 怎么量 |
|---|---|---|
| 信息丢失 | 材料里的事实有没有被省掉 | 每条用例配一份事实清单，两个不同厂商的判分模型逐条核对 |
| 信息歪曲 | 事实的数值、条件、限定语、轻重有没有变 | 同上 |
| 加料 | 成稿里有没有材料不支持的内容 | 判分模型逐句找出，并分成步骤、结论、建议、下一步四类 |
| 读者结果 | 读者能不能得到正确结论 | 读者模型只看成稿，回答固定的选择题；另测只看开头一小段时的答对率 |
| 阅读成本 | 读者要读多少字 | 字数、句长、标题和列表的数量 |

### 判分规则

规则写在 `bench/run.py` 的判分提示里，现在是第 3 版。要点：

- 省掉任何一条事实都算丢失，不分“必要”和“非必要”。
- 限定语丢了、个例写成常规、说重或说轻、用笼统的词替换具体的说法，都算歪曲。标题里说重了也算。
- 没有逐字写出、但读者能直接推出来的，算保留。
- 编出材料里没有的步骤，一律算加料。
- 模型自己多给的建议或推断，读者能从措辞看出是建议或推断，就不算加料。写成事实才算。
- 作者提议下一步并把决定权留给读者，在回复里不算加料，在文档和分享材料里算。替读者做了决定，或者把没定的事说成已定，算加料。

### 检验判分本身：故意改坏测试

判分靠不靠得住，要单独验证。办法是取一批忠实的成稿，每份故意改坏一处：删一条事实、把话说轻、把话说重、改一个数字、去掉一个限定语、加一个步骤、加一个结论、加一条建议。每份改坏稿只动一个地方，并记下动了什么。然后看两个判分模型各自发现了多少。

## 运行

需要本机已登录 `claude` 和 `codex` 命令行。脚本只用 Python 标准库。

```bash
# 试点：生成、判分、读者答题、汇总
python3 bench/run.py gen   --out runs/pilot --runs 3
python3 bench/run.py judge --out runs/pilot
python3 bench/run.py read  --out runs/pilot
python3 bench/run.py score --out runs/pilot

# 故意改坏测试
python3 bench/mutate.py make   --from runs/pilot --cond none --out runs/mutants
python3 bench/run.py    judge  --out runs/mutants
python3 bench/mutate.py report --out runs/mutants
```

- `bench/cases/`：用例。每条用例有原始材料、事实清单和读者问题。
- `bench/conditions.json`：被比较的写作指令。第三方 skill 按固定 commit 拉取，不入库。
- `runs/`：运行结果，不入库。

## 与 ASD-STE100 的关系

ASD-STE100 是 ASD（欧洲航空航天、安全与防务工业协会）发布的英文技术文档标准，只规定英文。本项目借用它的思路，为中文重新制定规则。本项目不是 ASD-STE100 的中文译本，不包含标准原文和词典，与 ASD 没有关联。标准原文可以在 [asd-ste100.org](https://www.asd-ste100.org) 免费申请。

## English

**ste-renhua** ("STE 人话", plain Chinese) is a work-in-progress writing standard and agent skill for the Chinese text that AI writes for people: replies, technical documents and shared write-ups. It applies the ideas of ASD-STE100 Simplified Technical English to Chinese. The benchmark comes first: it measures fact fidelity, reader comprehension and reading cost. No installable skill exists yet.

## 许可

[MIT](LICENSE)
