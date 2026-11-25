# Context Tree

[English](README.md)

Context Tree 研究**上下文树管理器（CTM）**：用户与执行工作的编码 agent 之间的一个助手。用户只和 CTM 说话，在一条连续的对话里同时推进
多项工作。CTM 为**工作本身**保存长期记忆，判断每条消息属于哪项工作，并给每次执行少而够用的上下文。

agent 的会话会遗忘、会被替换、会被压缩。CTM 在它们之外保持连续：

- **以工作为单位的记忆**：Goal 与 Task 组成的树，每项工作记着定下了什么、哪些规则成立、做到了哪里、与其他工作的关系。
  规则有作用范围（一项任务、一个目标、全部工作，或一个对象如某个模块），沿树向下继承。
- **用户的话为准**：每个条目保留时间和“被谁替换”，只有现行条目交给执行者；执行者的报告不能替换用户说过的话。
- **定位**：每条消息（或其中一部分）送到对的工作：接着做、在合适的目标下新建、旁问、控制某个执行者，或只是让 CTM 记住。
- **少而够用的上下文**：执行者的上下文由代码从记忆中拼装，有预算，而不是由模型自由书写。
- **分块度量**：每一类判断（送达、记忆、上下文、进度、控制、查询、维护、转述）用参照输入单独评估。

状态：研究原型，单用户，本地运行（在 Windows 上开发）。代码、提示与页面用英文；模型为你写的内容（工作标题、总结、回答）跟随你说话的语言；设计与评估文档用中文。许可为[MIT](LICENSE)。

## 运行方式

1. 消息到来：一次轻量调用读出它怎样指向工作（接续、指代、点名的对象、时间）。
2. 按这些指向找候选（最近的工作、碰过所点对象的工作、当前工作）。
3. 送达调用决定每部分送到哪里、以什么方式送。
4. 执行者随即开工（pi 编码 agent 会话，同一工作目录同时只有一个修改者），上下文从记忆拼装；接着用的会话只收到上次以来的变化。
5. 派发之后写记忆：约束、决定、事实与指导，每条与最相近的现行条目比对，记下它替换了什么。
6. 执行者的答复总结为进度；控制一步决定继续、停下还是问用户；遗留事项成为对话中带编号的待决事项。
7. 定期维护带着后来的信息重看树（合并、改挂、修正状态、上移共同的规则）。

完整设计见 [docs/ctm-concept-model.zh-CN.md](docs/ctm-concept-model.zh-CN.md)；实现了哪些、各部分怎样评估见
[docs/ctm-implementation-plan.zh-CN.md](docs/ctm-implementation-plan.zh-CN.md) 第 2 节。

## 依赖与运行

- Python 3.10+ 与 `requests`；模型经 GitHub Copilot 账号访问，用项目自带的设备登录（[docs/authentication.md](docs/authentication.md)）；
  执行者是 [pi 编码 agent](https://github.com/earendil-works/pi) 的命令行（`PATH` 上的 `pi`，或某个构建的 `cli.js`）；git。

```sh
python -m pip install -e .
context-tree-auth login --allow-network
context-tree --root <CTM目录> --open
```

CTM 目录保存运行数据（记忆、对话、执行者会话、日志），属于私人数据，放在 Git 之外。可配置的环境变量见 [README.md](README.md#configuration)。

## 检查

```sh
for f in tests/test_*.py; do PYTHONPATH=src python "$f" || exit 1; done
```

离线测试替换了所有模型调用；浏览器检查会改数据，只对 CTM 目录的副本运行，见 [docs/development.md](docs/development.md)。

## 文档

从 [docs/README.md](docs/README.md) 开始：概念模型、目标与方法（含未来方向与先后顺序）、实现规划、分块评估、相关工作与设计取舍的演进。
另见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [SECURITY.md](SECURITY.md)。
