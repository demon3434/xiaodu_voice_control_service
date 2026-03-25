# xiaodu_voice_control_service

`xiaodu_voice_control_service` 是一个独立 Docker 服务，用来对接小度智能家居技能，并把控制请求转发给 Home Assistant。

它负责：

- 小度 OAuth 授权
- access token / refresh token 管理
- 设备发现
- 设备控制
- 设备查询
- 接收 `xiaodu_voice_control` HA 集成同步过来的设备列表和运行参数

推荐部署顺序：

1. 先部署本服务容器
2. 再安装 Home Assistant 集成 `xiaodu_voice_control`
3. 最后在 HA 的“小度语音设备”页面里同步：
   - 小度技能 ID / botID
   - ClientSecret
   - openUid
   - 设备列表

## 目录结构

下载代码后，目录结构应类似：

```text
xiaodu_voice_control_service/
├─ Dockerfile
├─ docker-compose.yaml
├─ .env.example
├─ pyproject.toml
├─ src/
└─ data/
```

其中：

- `src/` 是服务代码
- `data/` 是持久化目录

## 第一步：准备 `.env`

先复制示例文件：

```bash
cp .env.example .env
```

最小可用示例：

```env
APP_BASE_URL=https://your-public-ha.example.com
HA_BASE_URL=http://192.168.6.10:8123
HA_REFRESH_TOKEN=replace_with_ha_refresh_token
HA_CLIENT_ID=https://xiaodu-dbp.baidu.com
INTERNAL_API_TOKEN=replace_with_random_internal_token
```

各参数含义：

- `APP_BASE_URL`
  小度平台从公网访问本服务时使用的地址，必须公网可达。
- `HA_BASE_URL`
  服务容器访问 Home Assistant API 的地址，建议用内网地址。
- `HA_REFRESH_TOKEN`
  服务容器换取 HA access token 用的刷新令牌。
- `HA_CLIENT_ID`
  推荐保持默认值 `https://xiaodu-dbp.baidu.com`。
- `INTERNAL_API_TOKEN`
  仅用于 HA 集成与本服务容器之间的内部鉴权，不填写给小度平台。

## 第二步：启动容器

默认推荐直接使用 Docker Hub 镜像，不需要本地构建。

直接执行：

```bash
docker compose up -d
```

## 如需本地构建镜像

如果你修改了源码，或希望自己构建镜像，再执行：

```bash
docker build -t xiaodu_voice_control_service:latest .
```

然后把 [docker-compose.yaml](E:\code\GitHub\xiaodu_voice_control_service\docker-compose.yaml) 里的镜像名改成你自己的本地 tag，或者临时这样运行：

```bash
docker run -d --name xiaodu-voice-control-service -p 8129:8129 --env-file .env -v $(pwd)/data:/data demon3434/xiaodu_voice_control_service:latest
```

查看状态：

```bash
docker ps | grep xiaodu-voice-control-service
```

查看日志：

```bash
docker logs -f xiaodu-voice-control-service
```

## 第四步：检查服务是否正常

健康检查：

```bash
curl http://127.0.0.1:8129/health
```

如果返回：

```json
{"status":"ok"}
```

说明服务已经可以正常运行。

## 第五步：打开服务管理页

假设宿主机IP是192.168.6.10  
启动后直接访问： `http://192.168.6.10:8129/`



这个页面支持：

- 图形化编辑服务参数
- 重新加载配置，不必手动重启容器
- 显示当前 `devices.yaml` 的设备数量
- 生成或重建公钥 / 私钥
- 复制或下载公钥

## `data/` 目录中的持久化文件

容器运行后，会在 `data/` 目录里维护这些文件：

```text
data/
├─ service.env
├─ token_store.json
├─ devices.yaml
├─ xiaodu_private_key.pem
└─ xiaodu_public_key.pem
```

说明：

- `service.env`
  管理页面保存后的运行参数文件。
- `token_store.json`
  保存 OAuth 授权码、access token、refresh token、openUid 绑定关系和运行时配置。
- `devices.yaml`
  保存当前服务容器使用的设备列表。
- `xiaodu_private_key.pem`
  小度云端设备同步签名所需的私钥。
- `xiaodu_public_key.pem`
  与私钥配对生成的公钥。

## 私钥文件需要手动准备吗

通常不需要。

当前程序会在首次启动时自动处理：

- 如果 `/data/xiaodu_private_key.pem` 不存在，会自动生成 RSA 私钥
- 同时自动生成 `/data/xiaodu_public_key.pem`

所以普通用户一般不需要手动创建密钥文件。

## `HA_REFRESH_TOKEN` 失效后怎么办

`HA_REFRESH_TOKEN` 一般不会按天自动失效，更常见的是以下情况导致不可用：

- 你在 HA 中撤销了相关授权
- 恢复备份后认证状态不一致
- 用户或认证数据被重建

如果它失效了，处理方式是：

1. 重新获取一个新的 HA refresh token
2. 打开服务管理页
3. 把新的 `HA_REFRESH_TOKEN` 粘贴进去
4. 保持 `HA_CLIENT_ID` 为默认值 `https://xiaodu-dbp.baidu.com`
5. 点击“保存配置”
6. 再点击“重新加载配置”

## 与 Home Assistant 集成的关系

本仓库只包含独立服务容器。

真正和 Home Assistant 图形界面打通时，还需要安装 `xiaodu_voice_control` 集成。安装后，HA 会把这些内容同步给本服务：

- 设备列表
- 小度技能 ID / botID
- 小度 ClientSecret
- 已捕获的 openUid 列表
- internal_api_token

因此，这个服务可以先单独启动，后续再由 HA 集成补齐小度运行参数。

## 两个 docker-compose 文件的区别

- `docker-compose.yaml`
  默认方案。直接拉取 Docker Hub 上已经发布好的镜像，适合普通用户直接部署。

- `docker-compose.build_by_self.yaml`
  自行构建方案。适合你修改过源码，或希望在本机重新构建镜像后再启动容器。
