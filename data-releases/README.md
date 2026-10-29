# 外置科学数据发布接口

**当前状态：未发布。** 用户本次确认没有可公开下载的地址或对象存储，范围为源码与外置数据接口；本发布没有执行大型数据复制、PostgreSQL dump、上传或数据库迁移。

## 存储布局

GitHub 保存源码、部署配置、清单格式和获取工具。数据库快照、Core/Full 特征、功能注释、已登记发布产物及公开案例放在独立、版本化的 HTTPS 对象存储，可采用 S3 兼容存储、OSS/COS 等。推荐每个数据版本不可变，例如 `releases/<data-release-id>/...`，公开清单中填稳定下载地址、实际字节数和 SHA256。不要把在线 PostgreSQL 的原始数据目录、Docker 数据卷或整个 G 盘提交到 Git，也不要用一个 Git LFS 指针假装数据已经可下载。

每个发布至少包括：

| 组件 | 需要覆盖的内容 |
| --- | --- |
| public-database | 匹配源码版本的 PostgreSQL 16 custom-format 备份；包含科学表、文件注册路径及迁移记录 |
| project-data | 原项目 `proj/data` 中当前运行使用的物种、树、注册信息和输入内容 |
| omics-features | `全组学特征数据` 中数据库当前引用的真实 Core/Full 特征文件 |
| functional-annotations | 当前功能注释发布，保留发布身份、文件结构和字段语义 |
| registered-model-artifacts | 当前模式生物发布的登记产物；包括 `项目平台数据/data` 下当前使用的版本 |
| published-case-artifacts | 正式案例、已公开预计算内容及公开案例注册表；不是个人用户任务或探索性测试数据 |

单个组件可以拆成多个独立 tar 档，每个档案都填写自己的 URL/字节数/哈希及解包后字节数。不要把 tar 的二进制分片误当多个独立 tar 文件。建议多个可单独下载校验的档案，便于大数据重试。下载程序支持服务器提供 Range 时续传；不提供时重新获取该档。

## 保留真实路径关系

文件档案中的路径必须相对于原 `G:/stoichioomics` 根，例如：

```text
数据根目录/
├── 全组学特征数据/...
└── 项目平台数据/
    ├── 功能注释下载/...
    ├── data/model_organism_release_hardening/...
    ├── data/mo_artifacts/...
    └── stoich_platform_postgres_open_search_v6_2_perf_fix/proj/
        ├── data/...
        └── workspace/公开案例与预计算内容...
```

设置 `STOICH_DATA_HOST_ROOT` 为上图根目录。容器路径 `/srv/stoichioomics` 与原 G 盘根前缀一一对应；当前源码已有 `backend.apps.common.host_paths` 做明确映射。已有数据库路径、文件内容和科学结果不通过全库字符串替换伪造一致。历史 Linux 私有任务路径还涉及原状态卷，不能由公共科学文件包自动恢复。

## 发布者后续需要落实的内容

1. 在隔离副本制作一致的数据发布。盘点数据库当前引用文件，不按“最近日期”猜测有效版本；确认当前发布、注释、树、Core/Full 特征和案例闭包齐全。
2. 建立专门的可公开数据库副本：排除用户密码、会话、令牌、个人上传和私有任务；不得改动保留科学数据的数值或语义。确认第三方数据许可及可再分发范围。
3. 为真实备份和档案测量 `bytes`、`sha256`，为 tar 测量 `unpacked_bytes`；上传到明确可访问的对象存储路径。
4. 将 `release.example.json` 复制为实际版本清单，填入所有真实 artifact 记录并改为 `published`。发布清单须对应同一源码/数据库版本，不得用零哈希、占位 URL 或伪造大小通过检查。
5. 在全新目标目录、全新 PostgreSQL 中完成下载、恢复、文件引用、API、上传分析和案例等验收，再发布“可完整数据复现”的结论。

未来 `artifacts` 的每项由 `manifest.schema.json` 约束，字段为 `id`、`component`（对应 `required_components` 中的组件 ID）、`kind`（`postgres-custom`/`tar`）、`filename`（下载目录内相对文件名）、`url`、`bytes`、`sha256`；tar 还要求 `unpacked_bytes`。所有值由真实文件计算，所有必需组件都有档案记录后才接受 `published` 状态。当前 `artifacts=[]` 是未发布状态的准确表达，不是待下载的空数据集。

## 获取和使用

```bash
python scripts/data_release.py status --manifest data-releases/release.example.json
# 仅实际 published 清单可执行以下步骤：
python scripts/data_release.py fetch --manifest /path/to/published-release.json
python scripts/data_release.py verify --manifest /path/to/published-release.json
python scripts/data_release.py extract --manifest /path/to/published-release.json --data-root /absolute/external/data-root
```

下载默认保存到 Git 排除的 `var/downloads`；未发布清单会明确拒绝 fetch。SHA256/大小不匹配会停止；解包拒绝路径跳转、链接、特殊文件与已有文件覆盖。数据库档不自动恢复，按部署文档在新空库显式执行恢复；工具不会连接业务库。大规模文件仍需提前预算下载和解包空间。

数据状态与下载接口能让他人知道还缺什么，并为真实数据上线提供可执行衔接；**在真实数据库和数据包发布之前，源码上传完成不能等同于全部平台内容已可复现。**

参考：[GitHub 大文件与 LFS](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage)、[PostgreSQL custom-format dump](https://www.postgresql.org/docs/16/app-pgdump.html)。

## 历史产物读取布局（2026-10-29）

当前代码增加不可变历史产物读取与兼容回执。公共数据发布还须提供经过审计的 `proj/runtime` 历史公开产物，组件名为 `historical-public-runtime`；仅公开冻结科学产物，不打包个人任务、锁文件、维护状态或临时缓存。Compose 将原项目对应目录作为 `DEPLOYMENT_HISTORICAL_ROOT` 只读来源，新状态仍写入独立卷。不能为通过兼容校验而重写旧 manifest 或科学身份。
