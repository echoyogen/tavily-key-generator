# ---- Builder Stage ----
# 使用完整的 Python 镜像，确保包含所有构建工具
FROM python:3.11 as builder

# 创建虚拟环境
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 配置 pip 使用国内源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 安装依赖
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ---- Final Stage ----
# 使用轻量的 slim 镜像作为最终的运行环境
FROM python:3.11-slim

WORKDIR /app

# 从 builder 阶段复制已安装的虚拟环境
COPY --from=builder /opt/venv /opt/venv

# 激活虚拟环境
ENV PATH="/opt/venv/bin:$PATH"

# 复制应用代码（.dockerignore 会排除不必要的文件）
COPY . .

# 启动命令将在 docker-compose.yml 中定义
