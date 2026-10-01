# Context Tree

**把海量历史整理成任务树，定位当前相关分支，排除无关信息，只给 agent 此刻所需的上下文。**

[English](README.md) · [项目目标](docs/goals.md) · [架构](docs/architecture.md) · [逐步骤运行](docs/stages.md)

本项目由 Companion C Python 原型独立整理而来。核心不是“让 agent 记住更多历史”，而是把历史保留在外部结构里，让 agent 不必持续携带、重读和重建全部会话。

## 核心思路

1. 按用户输入及其触发的回复、工具操作组织 turn。
2. 提取话语行为、约束和确认／否定引用，构建 Goal／Task／Subtask 树。
3. 做结构 review 与证据核验，再生成与来源关联的紧凑记忆。
4. 用语义、文件和 identifier 找到候选节点，依据树拓扑构造分支。
5. 在给定状态下决定展开、排除或停止；单独的 context 步骤整理必要证据。

树负责工作关系和上下文归属，embedding 负责候选查找。当前向量召回仍为平扫，不能宣称已实现 O(log n) 树检索；也没有自动接管外部 agent 的运行时上下文窗口。

## 当前状态

- 研究原型，不是生产就绪的记忆平台。
- 已支持 Claude Code JSONL；多 agent、多设备同步和自动 context paging 尚未完成。
- 模型传输为实验性 Copilot 适配，必须显式配置凭据和允许联网。
- **许可证待确认，目前没有授予开源许可。** 详见 [许可状态](LICENSE-STATUS.md)。
- 本仓库不包含真实会话、数据库、凭据或原始评测输出。

## 安装与离线验证

在仓库根目录，使用 Python 3.10+：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
context-tree --help
context-tree-check
context-tree-benchmark --offline-check
```

安装可能下载依赖；离线检查不调用模型、不需要认证，不读取你的会话。Windows 使用 `.venv\Scripts\Activate.ps1` 激活环境；Windows 上线传输尚未验证。

## 每一步独立运行和评估

```text
src/context_tree/
  common/         模型调用、数据契约、配置、存储、通用 CLI／评估工具
  stages/
    ingest/       来源解析
    extract/      L1 单元提取
    tree/         L2 建树与状态机
    review/       结构修正
    reflexion/    证据核验
    framing/      忠实压缩
    emit/         实体与关联生成
    resolve/      实体处理
    index/        向量／字面索引
    recall/       候选召回
    branches/     结构分支组织
    select/       给定状态下的检索动作
    context/      给定证据的上下文装配
  pipeline/       全流程编排
```

每个步骤均有 `processor.py`、`run.py`、`evaluate.py`。例如：

```sh
mkdir -p artifacts
python -m context_tree.stages.ingest.run --example --output artifacts/input.json
python -m context_tree.stages.ingest.run --input artifacts/input.json --output artifacts/turns.json
python -m context_tree.stages.ingest.evaluate --offline-check
python -m context_tree.stages.extract.run --example
python -m context_tree.stages.tree.evaluate --offline-check
```

真实模型调用需要 `--allow-network` 和显式环境凭据；`--example` 只输出合成输入，不执行该步骤。完整输入输出说明见 [阶段契约](docs/stages.md)。

## 模型选择原则

每一步目标不同，分别评估，不找“所有步骤的冠军”：

- L1 看信息、act 和引用是否完整；L2 看层级、归属、scope。
- Review 看修正和误改；Reflexion 看证据能否支持操作。
- Framing 看忠实度、标识符、数值、否定和压缩。
- Select 只评给定状态下的下一步动作；Context 在固定证据上评必要信息和无关内容。

端到端测试只验证集成，不能代替步骤模型排名。现有模型配置来自少量合成样本，最新独立评估未覆盖 Gemini 3.8，不能视为最优定论。详见 [评估方法](docs/evaluation.md)。

## 文档阅读顺序

先读 [目标](docs/goals.md)、[架构](docs/architecture.md)、[配置](docs/configuration.md)、[开发](docs/development.md) 和 [路线图](docs/roadmap.md)。

十份旧研发文档完整保留在 [历史档案](docs/history/README.md)，但旧草案、模型、指标及引用不代表当前事实。迁移及最近修改见 [开发记录](docs/development-log.md)；研究对照和引用纠错见 [research](docs/research.md)。

使用私有日志前请阅读 [安全说明](SECURITY.md)：文本和文件路径可能发送给模型，数据库和导出包含私人信息，不要公开。
