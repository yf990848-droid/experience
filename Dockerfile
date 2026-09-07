FROM corecdimage.inhuawei.com/opentools/nuclio/python:3.10

RUN mkdir -p /agent-memory-service/app /agent-memory-service/repositories

#VARIABLE DEFINITION
MAINTAINER yezhiming  y30050958
LABEL name="agent-memory-service"
LABEL port=8080

# 设置工作目录
WORKDIR /agent-memory-service/app
COPY requirements.txt .
RUN pip install \
    --no-cache-dir \
    --progress-bar off \
    -r requirements.txt \
    -i http://cmc-cd-mirror.rnd.huawei.com/pypi/simple/ \
    --trusted-host cmc-cd-mirror.rnd.huawei.com
# 复制应用代码到镜像中
COPY . /agent-memory-service/app/

# 暴露应用端口
EXPOSE 8080

# 定义启动命令
CMD ["sh", "-c", "python3 server.py & python3 task_runner.py"]
