# Exact base images from the verified current local deployment.
ARG PYTHON_IMAGE=python@sha256:8f6593e62e991b818dc28750c0c67c340046a70ab5cf79df52116005ec9cbf56
ARG NGINX_IMAGE=nginx@sha256:a7675fcee220f59b4a99f7098c06a0d5d999c2c0ee37c0211efb780536e5cb20
FROM ${PYTHON_IMAGE} AS frontend
ARG TARGETARCH
ARG NODE_VERSION=22.23.4
COPY deploy/docker/install_node.py /tmp/install_node.py
RUN python -B /tmp/install_node.py --version "${NODE_VERSION}" --arch "${TARGETARCH}"
ENV PATH=/opt/node/bin:$PATH
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS app
WORKDIR /opt/local/project
COPY requirements.txt ./
COPY deploy/requirements-production.txt deploy/requirements-production.txt
RUN python -m venv /opt/venv && /opt/venv/bin/python -m pip install --no-cache-dir -r deploy/requirements-production.txt && /opt/venv/bin/python -m pip check
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN getent group 101 >/dev/null || groupadd --gid 101 stoichsocket
RUN useradd --uid 1001 --gid 101 --no-create-home --home-dir /opt/local/state/home --shell /usr/sbin/nologin stoichioomics
COPY --chown=1001:101 . .
RUN mkdir -p /opt/local/state/runtime /opt/local/state/workspace /opt/local/state/uploads /opt/local/run /opt/local/static && ln -s /opt/local/state/runtime runtime && ln -s /opt/local/state/workspace workspace && ln -s /opt/local/state/uploads uploads && ln -s /opt/venv .venv && ln -s /srv/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj/data data && chown -R 1001:101 /opt/local/state /opt/local/run /opt/local/static
USER 1001:101
ENTRYPOINT ["python","-B","deploy/docker/entrypoint.py"]
CMD ["uwsgi","--ini","/opt/local/project/deploy/docker/uwsgi.ini"]

FROM ${NGINX_IMAGE} AS gateway
COPY --from=frontend /build/frontend/dist /usr/share/nginx/html
COPY deploy/docker/nginx.conf /etc/nginx/nginx.conf
COPY deploy/docker/nginx-http.conf /etc/nginx/conf.d/default.conf
COPY deploy/docker/nginx-routes.conf /etc/nginx/stoich-routes.conf
RUN mkdir -p /var/cache/nginx/stoich_quality && chown -R nginx:nginx /var/cache/nginx
