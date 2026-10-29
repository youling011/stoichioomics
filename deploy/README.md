# Nginx / uWSGI 部署

此版本以当前已运行的本地 Nginx/uWSGI 链路为依据，新增仓库内可移植的 Compose 部署入口。当前本机已有服务的控制目录和业务卷不需要为了本发布而搬动；仓库默认使用独立项目名 `stoichioomics-reproduction`，不会接管原 `stoich-local-*` 容器。

## 前提与边界

- Docker Engine/Compose，Linux 容器；Windows 服务器端需先准备可用的 Linux 容器运行环境。
- 外置数据须有合法可用副本，并遵循 `data-releases/README.md` 的完整相对目录布局。公共数据目前尚未发布。
- 私有 `.env`，充分的数据库、数据解包、依赖镜像及计算状态空间。默认 4 GiB/2 CPU、2 workers×2 threads 是当前本机初始参数，不是任意工作负载的容量保证。
- 用独立环境部署；不要对现有业务数据库直接执行新实例恢复命令。

本次发行已检查 Compose 配置、隔离容器中的 Nginx 语法及真实 uWSGI 就绪协议；当前业务源码也与已运行 Linux 副本核对。**新镜像的完整干净构建尚未验收完成**：本次在下载公开 Python 依赖阶段达到构建时间上限。该构建没有切换任何服务。目标机器仍需完成镜像构建和真实数据联调，不能把配置检查视为全新服务器全流程验收。

## 准备配置与数据

在仓库根目录（以下为 shell 示例）：

```bash
cp .env.example .env
mkdir -p var/downloads var/certificates
# 编辑 .env：真实密钥、数据库参数、绝对路径 STOICH_DATA_HOST_ROOT。
docker compose --env-file .env -f compose.yaml config --quiet
python scripts/data_release.py status
```

`.env` 不进仓库。生成 Django 密钥可使用 `python -c "import secrets; print(secrets.token_urlsafe(64))"`，将结果仅填写在本机私有配置中。

数据清单发布后才可以按数据文档 fetch / verify / extract。现有数据使用者也可自行准备目录；`STOICH_DATA_HOST_ROOT` 指原 `G:/stoichioomics` 的等价目录，而不是只指一个 Parquet 文件或 `proj/data`。容器只读挂载至 `/srv/stoichioomics`。新上传、任务和缓存由独立 `app-state` 卷保存；旧 Windows 私有工作区映射不自动复制到公共仓库。

## 新建独立 PostgreSQL 16

仅当没有已准备好的数据库时，显式启动此独立数据库服务：

```bash
docker compose --profile database up -d postgres
```

待匹配版本、已脱敏的 PostgreSQL custom-format 备份真实发布并通过校验后，将清单中的**实际文件名**代入：

```bash
docker compose --profile database exec -T -e STOICH_RESTORE_EMPTY_DATABASE=1 postgres \
  sh /usr/local/bin/stoich-restore /releases/实际校验过的数据库备份文件
```

恢复工具拒绝已有用户表/视图/序列的数据库，不带 `--clean`，不擦除现有数据。恢复操作是显式独立步骤，启动服务不会替用户执行。完整快照通常已有迁移历史；先使用新环境中的 `manage.py showmigrations --plan` 审核当前代码匹配情况，再制定独立迁移步骤，不把 `migrate` 写进自动启动。

只有想建立**空结构平台**时才自行在新空库执行 `manage.py migrate`；这不导入真实科学数据，不能替代完整内容复现。

已有 PostgreSQL 时不要启用 `database` profile。设置 `POSTGRES_HOST/PORT` 为容器真正可达的地址；已有 Docker 网络可用 `STOICH_NETWORK_EXTERNAL=true`、`STOICH_NETWORK_NAME=实际网络名`。不要把应用容器自身的 `localhost` 当另一台机器或另一容器的数据库地址。

## 构建和启动

```bash
docker compose build app nginx
docker compose run --rm app python manage.py collectstatic --noinput
docker compose up -d app nginx
docker compose ps
docker compose logs --tail 100 app nginx
```

默认浏览器地址为 `http://localhost:18080`，仅映射宿主回环地址。app 的健康检查通过私有 socket 请求真实 `/api/health/ready/`，检查数据库及配置目录，而不把 socket 存在当成就绪。缺少数据或配置时，服务保持未就绪；不生成虚构示例结果。Nginx 不公开映射私有 `/media`，下载继续走原 API。

Windows PowerShell 可使用仓库内 `deploy/local/platform.ps1 start/status/logs/build/stop/restart/readonly/clear-quality-cache`。这个导出副本中的入口调用当前仓库 Compose，不依赖原电脑的 C 盘控制目录。`readonly` 通过任务保护后将此副本的私有 `.env` 切换为 `STOICH_LOCAL_READ_ONLY=1` 并重新启动，保留状态卷；恢复写入需明确编辑为 0 再正常重启。它不会自动恢复数据或运行迁移。Linux 停机前可显式检查：

```bash
docker compose exec -T app python -B deploy/tools/task_guard.py
docker compose stop nginx app
```

先等待后台任务结束。PowerShell 包装入口会在 stop/restart 前执行该保护；直接调用 Docker stop 不会自动执行保护。原有进程内任务仍不能保证在断电或强制回收后继续。

## 公网 HTTPS

默认回环 HTTP 只用于本机使用，保持当前实际本地部署的访问方式。开放公网时，在 `var/certificates` 准备合法 `fullchain.pem` 和 `privkey.pem`，私钥不进 Git；在私有 `.env` 中明确设置：

```dotenv
STOICH_HTTP_BIND=0.0.0.0
STOICH_PUBLIC_PORT=443
STOICH_NGINX_PORT=443
STOICH_NGINX_SITE=./deploy/docker/nginx-https.conf
STOICH_ALLOW_HTTP_TEST=0
DJANGO_ALLOWED_HOSTS=你的正式域名
DJANGO_CSRF_TRUSTED_ORIGINS=https://你的正式域名
```

随后在任务空闲时应用配置并核验正式域名、证书和健康检查。这里不自动申请/续期证书，也不修改 DNS、防火墙或现有服务器站点。原有 `deploy/render.py` 与 `templates/` 仍可用于独立 Linux/systemd 方案，其路径和证书必须填写为目标实际值。

## 缓存与状态

公共质量页沿用有界共享缓存：16 MiB、1 小时，带 Cookie/Authorization/X-Job-Token 时绕过；任务、登录和写请求不缓存。数据版本变化后显式清除此缓存，避免继续展示旧公共响应：

```bash
docker compose exec -T nginx find /var/cache/nginx/stoich_quality -type f -delete
```

该命令只针对此独立 Compose 栈的 Nginx 缓存。数据库、应用状态、日志及卷备份需要部署者单独安排，仓库不自动删卷、覆盖数据或接管原服务。

依据：[Compose 启动顺序](https://docs.docker.com/compose/how-tos/startup-order/)、[PostgreSQL 16 pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html)、[pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html)。
