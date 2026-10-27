# Stoichioomics

当前 Stoichioomics 平台的 Django/DRF、Vue 和科学计算源码，以及 **Nginx → Unix socket → uWSGI → Django → PostgreSQL/组学文件** 部署入口。发布快照：2026-10-27。

**科学数据库和数据文件尚未公开发布。** 已提供外置数据清单、下载/哈希校验/安全解包工具与数据库恢复入口；仓库目前不能仅凭一次 `git clone` 还原现有平台的全部真实数据、历史任务和所有页面内容。数据状态以 [`data-releases/release.example.json`](data-releases/release.example.json) 为准，未填写任何虚构下载地址或校验值。

## 仓库内容

| 目录/文件 | 内容 |
| --- | --- |
| `backend/` | 实际 API、模型和迁移、HVG、序列分析、比较、可视化、文件下载等；`backend/validation` 是运行期输入校验功能 |
| `frontend/` | 实际 Vue 页面、组件、样式与构建依赖锁文件 |
| `tools/feature_extractors/` | 平台实际调用的 genome/transcriptome/proteome 三个外部提取器源码 |
| `shared/schemas/` | 实际特征注册表、语义和展示契约 |
| `scripts/` | 平台数据导入/发布/构建工具；包含直接被业务模块引用的正式案例构建代码 |
| `compose.yaml`、`deploy/docker/` | 不依赖原电脑 C/G 盘控制目录的容器部署入口 |
| `deploy/templates/` | 原有 Linux Nginx/uWSGI/systemd 参数化模板 |
| `data-releases/` | 外置科学数据发布约定及状态，当前为 `not_published` |
| `SOURCE_MANIFEST.json` | 文件来源、SHA256 及仅在导出副本中进行的配置适配 |

原始唯一主体 `proj` 的业务代码和算法按原文件复制；不在原目录修改代码或部署。导出副本中仅做凭据脱敏、依赖/仓库配置整理和部署适配。测试、浏览器 E2E、日志、验收/讨论文档、Word 生成工具、探索性数据、虚拟环境与构建产物不随本发布分发。

## 依赖

- 当前平台使用 Python 3.11；本机 Linux 已运行版本为 **3.11.17**、Django **5.2.18**、uWSGI **2.0.31**、Nginx **1.30.6**、Node **22.23.4**、PostgreSQL **16.14**。
- `requirements.txt` 为最小应用依赖闭包：Windows 59 项、Linux 58 项；`deploy/requirements-production.txt` 在 Linux 额外安装固定版本 uWSGI。旧 Uvicorn 启动专用依赖已从发布清单移除，原项目依赖文件未被替换。
- 三个旧 requirements 入口及 Conda 配置均指向同一主清单。Python 精确版本和容器基础镜像固定信息见构建文件。
- 前端保留实际 5 项运行依赖、2 项构建依赖与 npm 锁文件；Playwright 及测试命令不在发行清单。
- 数据重建/离线建树属于单独的维护工作；必要的额外工具见 `requirements-data-tools.txt` 和 `tools/phylo-tools.Dockerfile`。不需要为 Web 日常运行安装所有候选工具。

原 `hvg_optional.py` 的候选工具探测表仍按原业务源码保留：最小环境可能显示 `degraded`，不等于真实算法缺包，现有 Run 入口不依赖这些候选全部存在。发布没有通过删除业务功能来规避依赖。

## 首次部署

1. 阅读 [`deploy/README.md`](deploy/README.md)，复制 `.env.example` 为私有 `.env`，填写新密钥、数据库连接及外部数据根目录。
2. 阅读 [`data-releases/README.md`](data-releases/README.md)。当前公共数据尚未发布；已有合法数据副本的部署者可按相同目录布局自行配置。
3. 数据就位后构建并启动 Nginx/uWSGI。启动不自动下载数据、恢复数据库、运行迁移、重建科学结果或生成演示数据。

完整命令、独立新数据库恢复、使用已有 PostgreSQL、TLS 和停机任务保护均见部署文档。当前所有容器和原业务数据库不会因本次 GitHub 上传被启动、停止或迁移。

## 复现范围

仓库保留当前已经实现的程序功能与算法；科学内容还要求相同版本的数据库、Core/Full 特征、注释、发布产物和公开案例。只有数据库备份而没有文件，或只有文件而没有匹配数据库，均不足以复现全部内容。数据库中的 G 盘路径通过现有 `host_paths` 适配到外部只读挂载，不做全库字符串替换。

私有用户、令牌、上传和个人历史任务不属于公共数据发布；不得直接把含这些内容的在线业务库当公共数据包。后台线程的跨崩溃恢复、任意规模数据的容量与性能，不由容器模板自动保证。没有自行添加原项目未明确授予的开源许可证，也没有替外部数据声明未经确认的许可。
