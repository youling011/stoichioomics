# Stoichioomics：uWSGI / Nginx 生产适配

> 代码归档说明：本仓库不随附本机 `VALIDATION_REPORT.md`、`VALIDATION_MANIFEST.json` 或 `evidence/` 中的验收记录。下文保留部署方法和运行边界；历史验收数字与本机证据不属于本次发行内容。


本目录以当前唯一项目的 Django 5.2.18、原有接口和科学计算实现为基础。模板生成器只写配置文件，不安装软件、启动服务、迁移数据库或改写业务路径。本次验证证据见 `VALIDATION_REPORT.md`；测试通过不等于正式服务器已上线。

## 对应关系与改动边界

浏览器 → Nginx（HTTPS、Vue dist、Django staticfiles）→ 私有 Unix socket → uWSGI → 现有 WSGI → Django → PostgreSQL / 组学文件。

- `backend.config.settings_production` 是显式启用的生产覆盖模块，继承业务设置，保留时区、功能开关默认值、接口和数值算法。现有默认 settings / WSGI 入口继续可用。
- `settings.py` 仅增加 `DJANGO_ENV_FILE` 选择：未设置时仍加载原 `.env`；空字符串禁用加载；非空指定文件。生产模块默认禁用自动读取项目 `.env`，防止误用开发库和密钥。
- 新增 `/api/health/ready/`：只读检查数据库和配置目录的读/写权限；返回状态布尔值，不返回密码、目录或异常详情。现有 `/api/health/` 内容保持原样。
- 没有增加迁移、改变科学公式、修改已有业务数据，或引入新任务队列。
- 真实多进程联调暴露了旧清理函数会删除 RUNNING 序列任务输入的问题。本次修复任务生命周期：终态任务才清理输入，原有 TTL 策略保留；JSON 缓存按文件签名失效，序列状态和导出状态采用原子替换，避免其他 worker 读到旧状态或半写文件。特征提取与统计公式保持原样。
- 上传联调另发现 NumPy 对相邻浮点数范围无法构造多个有限分箱边界。仅在该明确异常时回退为一个分箱，保留全部观测；正常范围仍直接返回原 NumPy 输出。没有舍入、删改输入特征或变更统计公式，相关一致性和计数测试见证据。
- Linux 回归发现旧 HVG 产物路径检查未拒绝 `C:/outside`。现统一识别 Windows 盘符和两种分隔符，在 Linux/Windows 都拒绝绝对路径及上级目录跳转；不改动分析输入、公式或结果表。

## 先填写目标参数

复制 `config.example.json`，将所有 `__REQUIRED_...__` 替换为正式值。路径是 Linux 中的路径，不能直接填 `G:\...`。为减少路径推导差异，第一轮迁移优先保留 `stoichioomics/项目平台数据/平台版本/proj` 的层级。目录可含中文；模板生成器目前拒绝空白字符及配置/命令元字符。

`processes=2`、`threads=2`、请求体总量 512 MiB、读取间隔超时 300 秒、停机等待 3600 秒均为**初始测试参数**，不是已测容量承诺。应用默认单文件上限仍为 100 MiB；请求体总量包含多个文件和 multipart 开销。科学计算的 BLAS 线程默认不在生产模板中修改。

`config_root` 可指定生成配置最终安装的 Linux 目录，默认 `/etc/stoichioomics`。systemd 的 `ExecStart` 以及独立 Nginx 配置均引用该目录。生成目录可与安装目录不同，但必须将生成结果放到声明的 `config_root`。

`service_user` 是应用用户，`service_group` 是 socket 的共享组；独立 Nginx 主配置另用 `nginx_user/nginx_group`（默认 www-data）。按目标发行版调整账号，保持 Nginx 可以访问 socket，同时避免把应用用户的全部写权限授予 Nginx。

复制 `production.env.example` 到仓库外的私密环境文件，填写域名、密钥和 PostgreSQL 连接。建议权限 600。不要复制开发密钥、提交密码、使用 `postgres` 超级用户作为长期应用账号。跨机器 PostgreSQL 按实际网络和证书条件设置 TLS。

生产设置缺少必要参数、存在明确占位值、使用通配主机名、密钥过短或错误数据库类型时会拒绝启动。环境文件使用简单的 `KEY=value`，不要写命令、变量展开或多行值。systemd 加载该文件；手工命令使用下面的显式 `DJANGO_ENV_FILE`。

当前项目 `.env` 启用了 `HVG_RESEARCH_ENABLED=1`，示例显式保留。实际发布前核对现有全部功能开关，避免因为生产环境不再加载开发 `.env` 而改变功能。

## 生成与静态校验

在项目根目录：

```bash
python -m deploy.render --config /private/deployment.json --output /tmp/stoich-config
```

生成 `uwsgi.ini`、`stoichioomics.service`、`nginx-site.conf`、独立校验用 `nginx.conf` 和参数清单。生成过程不部署文件。

Linux 新环境使用 Python 3.11，并安装编译工具和 Python 开发头文件（uWSGI 需要编译）。先在独立环境验证：

```bash
python3.11 -m venv /目标项目/.venv
/目标项目/.venv/bin/python -m pip install -r deploy/requirements-production.txt
```

生产依赖继承主项目的科学依赖精确锁定，只额外固定 Linux uWSGI。不要用全局 Python 的 uWSGI 加载另一个版本 Python 的虚拟环境。Linux 的全部依赖可安装性与测试结果，以证据报告为准。

将生成配置放入声明的 `config_root` 后，可使用 `nginx -t -c /etc/stoichioomics/nginx.conf` 校验完整配置；或将 `nginx-site.conf` 纳入发行版已有 Nginx 主配置再运行 `nginx -t`。不要同时加载两份相同站点。配置中的证书文件必须先存在。

`systemd-analyze verify /etc/stoichioomics/stoichioomics.service` 仅验证 unit；不等于实际启动、开机恢复已通过。unit 的用户、组、虚拟环境、项目、环境文件和配置目录必须真实存在。

科学 Python 依赖在冷启动时需要导入时间。正式入口切换前应等待 `/api/health/ready/` 返回 200，再开放访问；不要将 socket 已存在或进程已启动视为应用已就绪。

## 应用、文件和数据库准备

1. 建立新服务用户及共享 Nginx 组。应用源码和科学源文件按需只读；现有 `proj/runtime`、`proj/workspace`、上传目录、产物目录须能由应用用户写入。Nginx 只需要读前端 dist、staticfiles，并能访问 socket；不要授予它整个组学目录的公开下载映射。
2. 前端在目标环境或构建环境执行 `npm ci`、`npm run build`，把 `frontend/dist` 发布到 `frontend_root`。不需要 Vite dev/preview 服务。前端 `/api` 地址无需修改。
3. 使用明确的生产配置执行检查和静态收集：

```bash
DJANGO_SETTINGS_MODULE=backend.config.settings_production DJANGO_ENV_FILE=/private/production.env python manage.py check --deploy
DJANGO_SETTINGS_MODULE=backend.config.settings_production DJANGO_ENV_FILE=/private/production.env python manage.py collectstatic --noinput
```

`STATIC_ROOT` 必须与 Nginx 的 `static_root` 一致。`collectstatic` 会写目标静态目录，只在新目标或独立环境操作。

4. 数据库采用备份、恢复、校验方案。新的目标库与当前业务库要明确区分。先检查迁移计划，再根据审批后的迁移策略运行迁移；本次不提供自动执行 `migrate` 的启动脚本。不要使用演示导入的 `--flush`。
5. 搜索迁移依赖 `pg_trgm` 扩展，扩展创建由有权限的迁移/DBA 账号负责。应用账号不必拥有长期超级用户权限。

## 路径迁移与只读预检

数据库不仅保存实体记录，还保存 `OmicsDataset.core_csv_path/full_csv_path`、`FeatureFile.path`、`AnalysisArtifact.path`、DataRelease 路径、StorageObject、JSON 元数据和历史任务/产物清单。只恢复 PostgreSQL 无法保证数据文件可读。

生产覆盖模块支持设置原有工作区/产物根目录，以及 `STOICH_FEATURE_ROOT`、`STOICH_PROJECT_ROOT`、`STOICHIOOMICS_ROOT` 等根目录别名。**别名不能自动修复所有旧 Windows 绝对路径。** 原代码仍有直接读取数据库路径和 `BASE_DIR/runtime` 的链路，因此本次不做不完整的全局字符串替换。

建议在数据库迁移副本中：盘点所有引用 → 制定前缀映射 → 校验映射后文件存在与校验和 → 转换数据库记录和可变清单 → 验证下载、比较、可视化、上传分析。包含源路径的签名/缓存可能失效，应使用现有重建及审计命令处理，不修改不可变来源记录来伪造一致。

```bash
DJANGO_SETTINGS_MODULE=backend.config.settings_production DJANGO_ENV_FILE=/private/production.env python -m deploy.preflight --database --sample-limit 20 --report /tmp/new-preflight.json
```

该工具在 PostgreSQL 只读事务中读取版本、扩展、迁移状态以及有限路径样本。不会迁移或改写路径；报告文件必须是新文件。样本检查不覆盖全部数据库/JSON/产物路径，也不替代全量迁移审计。

如要检查外部特征提取器，需设置 `STOICH_FEATURE_EXTRACTOR_ROOT` 并迁移原目录的三个提取器及其实际依赖。数据文件保持原值；不要为适配部署而修改科学输入。

## 后台任务与停机边界

现有 HVG、上传序列分析、Feature Hub 导出仍有进程内 daemon 线程；比较和部分可视化使用子进程。为保持行为，本次 uWSGI 显式启用线程、按 worker 加载应用、关闭子进程继承的监听描述符，并且不设置 harakiri、按请求数/内存回收或开发自动重载。

这能接入 uWSGI，但**不保证后台线程在崩溃、重启、强制回收后继续执行**。systemd 的停机等待也不是任务完成证明；默认 control-group 会在停机时处理所属子进程。计划重启前要停止接收新任务、等待活动任务结束、记录未结束任务，再检查恢复/重试状态。

任务脱离 Web 进程、统一持久队列和自动重试属于后续独立改造，本次没有以新增基础设施的方式扩大业务改动范围。要求无人值守任务跨重启可靠完成时，这一项必须完成后才能验收。

## Nginx 行为

- `/api`、`/admin` 交给 uWSGI，错误保持原状态码，不回退为前端 HTML，也不自动重试写请求。
- Vue history 路由回退 `index.html`；缺失的 `/assets/` 文件保持 404。
- Django `/static/` 由 `collectstatic` 目标提供；私有 `/media/` 不公开映射，沿用现有下载 API。
- HTTPS 在 Nginx 终止，覆盖转发协议头；应用只信任私有 socket 的入口。若再接入 CDN/负载均衡，应重新校准可信代理边界。
- HSTS 默认为 0，确认正式域名、证书续期和 HTTPS 稳定后再设置；`check --deploy` 可能因此报告 HSTS 建议。
- `http-test` 配置仅监听 `127.0.0.1:18080`；必须显式设置 `STOICH_ALLOW_HTTP_TEST=1`，不得作为公网 HTTPS 部署验收。

## 回归与验收

`deploy.validation_settings` 不读取项目 `.env`，要求所有临时 PostgreSQL 参数显式给出，并限定测试库前缀 `test_stoich_deploy_`。测试状态目录必须位于源码目录之外。应使用新建专用 PostgreSQL 实例，并在独立源码副本运行，避免原代码中固定 `BASE_DIR/runtime` 的缓存写入主项目。

```bash
DJANGO_SETTINGS_MODULE=deploy.validation_settings python -m deploy.run_regression --report /tmp/backend-tests.json
```

该命令另外需要 `STOICH_TEST_ROOT`、`STOICH_TEST_DB`、`STOICH_TEST_DB_HOST`、`STOICH_TEST_DB_PORT`、`STOICH_TEST_DB_USER`、`STOICH_TEST_DB_PASSWORD`。它会在专用实例中创建和删除指定测试库。测试代码和科学计算来源均为本项目；Windows 环境专用用例在 Linux 上应单独解释结果。

正式切换前的独立验收包括：真实数据的搜索/物种/特征表/比较/可视化；各类上传分析及导出；后台任务中断恢复；HTTPS 域名和证书续期；重启与开机启动；文件权限；资源与并发压力；备份恢复。服务器参数尚未确定的项目，不得标记为已通过。

## 回退

本次没有切换现有服务。生产适配通过显式 `DJANGO_SETTINGS_MODULE` 启用。未来切换应保留旧配置和上一份前端产物；出现问题时将入口切回旧服务。数据库和数据文件按独立备份恢复策略处理，不通过回滚代码覆盖业务数据。源码改动清单和原文件哈希见验证交付目录。

## 官方依据

- [Django 部署检查](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [Django uWSGI 接入](https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/uwsgi/)
- [uWSGI 线程、子进程描述符和运行注意事项](https://uwsgi-docs.readthedocs.io/en/latest/ThingsToKnow.html)
- [Nginx uwsgi 模块](https://nginx.org/en/docs/http/ngx_http_uwsgi_module.html)
