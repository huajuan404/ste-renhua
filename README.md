# STE 人话（ste-renhua）

让 AI 写给人看的中文说人话：短、准、顺。

AI 写的中文常常太长、太绕，读着费劲。本项目要做一份 AI 写中文时默认遵守的表达标准，以及配套的 Agent Skill。思路来自 ASD-STE100（Simplified Technical English，简化技术英语）：航空业为了让维修手册不被读错而制定的受控语言标准。

标准覆盖三类输出：

- 每一轮回复：汇报结果、解释问题、请人做决定。
- 技术文档：操作手册、说明、排查记录。
- 对外分享材料：给其他团队看的介绍和总结。

## 状态

建设中。现在仓库里只有评测基准的试点代码，还没有可以安装的 skill。

## 做法：先建评测，再写规则

受控语言能把句子写短、写规整，也容易把事实写丢。所以本项目先建评测，一条规则只有在评测证明有效后才加入。

评测量四件事：

| 指标 | 量什么 | 怎么量 |
|---|---|---|
| 保真 | 事实有没有丢、歪、多 | 每条用例配一份事实清单，两个不同厂商的判分模型逐条核对 |
| 读者结果 | 读者能不能得到正确结论 | 读者模型只看成稿，回答固定的选择题 |
| 扫读 | 只看开头能不能知道结论 | 读者模型只看开头一小段，回答结论类问题 |
| 阅读成本 | 读者要读多少字 | 字数、句长、标题和列表的数量 |

判分模型意见不一致的条目由人工裁决。

## 运行试点

需要本机已登录 `claude` 和 `codex` 命令行。脚本只用 Python 标准库。

```bash
python3 bench/run.py gen   --out runs/pilot --runs 3
python3 bench/run.py judge --out runs/pilot
python3 bench/run.py read  --out runs/pilot
python3 bench/run.py score --out runs/pilot
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
