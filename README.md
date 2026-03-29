# xiaodu_voice_control_service

`xiaodu_voice_control_service` 是一个独立的 Docker 服务，用来承接小度智能家居技能的请求，并把控制、查询、发现设备等操作转发给 Home Assistant。

它通常与另一个 HA 集成项目 `xiaodu_voice_control` 搭配使用：

- 这个服务负责对接小度云端
- HA 集成负责把设备列表、运行参数和内部鉴权信息同步到这个服务

服务启动后，会提供一个 `8129` 端口的管理页面，用于：

- 编辑运行配置
- 读取 HA 配置目录中的可用 `HA_REFRESH_TOKEN`
- 重新加载配置
- 生成或查看密钥

## 部署方式

下面分别介绍三种常见部署方式。

## 方法 1：直接使用 Docker Hub 镜像

这是最简单的方式，适合直接部署。

你的 `compose` 可以写成下面这样：

```yaml
services:
  xiaodu-voice-control-service:
    image: demon3434/xiaodu_voice_control_service:latest
    container_name: xiaodu-voice-control-service
    restart: unless-stopped
    ports:
      - "8129:8129"
    environment:
      - TZ=Asia/Shanghai
      - HA_CONFIG_PATH=/ha_conf
    volumes:
      - ./data:/data
      - /path/to/your/ha/config:/ha_conf
      - /etc/localtime:/etc/localtime:ro
      - /etc/timezone:/etc/timezone:ro
```

启动：

```bash
docker compose up -d
```

说明：

- `./data:/data`
  持久化本服务的配置、密钥和运行数据
- `/path/to/your/ha/config:/ha_conf`
  把 HA 配置目录挂载进容器，便于管理页面读取 `.storage/auth`
- `HA_CONFIG_PATH=/ha_conf`
  告诉程序去容器内哪个目录读取 HA 配置

启动后访问：

```text
http://你的主机IP:8129/
```

## 方法 2：自己编译构建镜像后运行

如果你修改了源码，或者想自己构建镜像，可以在项目根目录执行：

```bash
docker build -t xiaodu_voice_control_service:latest .
```

然后用 `compose` 运行：

```yaml
services:
  xiaodu-voice-control-service:
    image: xiaodu_voice_control_service:latest
    container_name: xiaodu-voice-control-service
    restart: unless-stopped
    ports:
      - "8129:8129"
    environment:
      - TZ=Asia/Shanghai
      - HA_CONFIG_PATH=/ha_conf
    volumes:
      - ./data:/data
      - /path/to/your/ha/config:/ha_conf
      - /etc/localtime:/etc/localtime:ro
      - /etc/timezone:/etc/timezone:ro
```

启动：

```bash
docker compose up -d
```

## 方法 3：使用 docker run 运行

如果你不想写 `compose`，也可以直接运行：

```bash
docker run -d \
  --name xiaodu-voice-control-service \
  --restart unless-stopped \
  -p 8129:8129 \
  -e TZ=Asia/Shanghai \
  -e HA_CONFIG_PATH=/ha_conf \
  -v $(pwd)/data:/data \
  -v /path/to/your/ha/config:/ha_conf \
  -v /etc/localtime:/etc/localtime:ro \
  -v /etc/timezone:/etc/timezone:ro \
  demon3434/xiaodu_voice_control_service:latest
```

如果你是自己本地构建的镜像，就把最后一行镜像名替换成你自己的 tag。

## 服务配置方法

启动后，打开：

```text
http://你的主机IP:8129/
```

页面里主要配置这几项：

- `HA_PUBLIC_BASE_URL`
  填 Home Assistant 的公网 HTTPS 地址，例如 `https://ha.example.com:port`
- `HA_INTERNAL_BASE_URL`
  填服务容器访问 HA API 使用的内网地址，例如 `http://192.168.6.10:8123`
- `HA_REFRESH_TOKEN`
  本服务控制 HA 时使用的 refresh token
- `INTERNAL_API_TOKEN`
  只用于 HA 集成与本服务容器之间的内部鉴权，建议填写足够长的随机字符串

### HA_REFRESH_TOKEN 的配置方式

有两种方式：

1. 手工填写
2. 从 HA 配置目录读取后，在下拉框中选择

如果你已经像上面的示例一样挂载了：

```yaml
- /path/to/your/ha/config:/ha_conf
```

并且设置了：

```yaml
- HA_CONFIG_PATH=/ha_conf
```

那么 8129 页面里就可以直接点击：

```text
从 HA 配置读取可用授权
```

程序会读取：

```text
/ha_conf/.storage/auth
```

然后列出可选的 `HA_REFRESH_TOKEN` 供你选择。

### 配置保存在哪里

页面保存后，运行配置会写入容器内：

```text
/data/service.env
```

如果你的宿主机挂载是：

```yaml
- ./data:/data
```

那么宿主机上的实际文件路径就是：

```text
./data/service.env
```

如果你是在我当前这套服务器目录结构下部署，则常见路径是：

```text
/opt/docker/xiaodu_voice_control_service/data/service.env
```

## 常用运维命令

查看容器状态：

```bash
docker ps | grep xiaodu-voice-control-service
```

查看日志：

```bash
docker logs -f xiaodu-voice-control-service
```

重启容器：

```bash
docker restart xiaodu-voice-control-service
```

## 数据目录说明

服务运行后，`data` 目录里通常会出现这些文件：

```text
data/
├── service.env
├── token_store.json
├── devices.yaml
├── xiaodu_private_key.pem
└── xiaodu_public_key.pem
```

说明：

- `service.env`
  管理页面保存后的运行参数
- `token_store.json`
  服务运行时保存的 token 和绑定关系
- `devices.yaml`
  当前同步到服务里的设备列表
- `xiaodu_private_key.pem`
  小度云端设备同步签名所需私钥
- `xiaodu_public_key.pem`
  与私钥配套的公钥
