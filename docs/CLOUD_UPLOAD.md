# 百度/夸克网盘备份

## 官方接口结论

百度网盘开放平台提供正式的文件上传 API，但接入门槛较高：

- 必须创建百度开发者应用，完成实名认证和应用审核。
- 使用 OAuth 2.0 获取 `access_token`，并定期刷新。
- 文件只能上传到 `/apps/{应用名}` 对应的应用目录。
- 普通用户单文件上限 4 GB，会员 10 GB，超级会员 20 GB。
- 单个文件分片数不能超过 1024。

官方文档：

- 开放平台简介：<https://pan.baidu.com/union/doc/index.md>
- 上传能力说明：<https://pan.baidu.com/union/doc/%E5%9F%BA%E7%A1%80%E7%BD%91%E7%9B%98%E6%9C%8D%E5%8A%A1/%E4%B8%8A%E4%BC%A0/%E8%83%BD%E5%8A%9B%E8%AF%B4%E6%98%8E.md>
- 授权介绍：<https://pan.baidu.com/union/doc/%E4%BD%BF%E7%94%A8%E5%85%A5%E9%97%A8/%E6%8E%A5%E5%85%A5%E6%8E%88%E6%9D%83/%E6%8E%88%E6%9D%83%E4%BB%8B%E7%BB%8D.md>

夸克公开的 `open.quark.cn` 当前是“夸克小程序开发者平台”，不是面向个人网盘的公开上传 API。直接对接夸克个人网盘需要依赖未公开接口，稳定性和合规性都不适合作为正式产品能力。

因此，本应用保留两种网盘出口：

夸克备份优先使用**官方 macOS 客户端的“电脑备份”通道**。应用只负责把烧录后的最终 MP4 放入客户端正在备份的本地目录，再由官方客户端上传；`rclone` 只用于读取远端大小，确认官方客户端确实完成同步。OpenList 保留为未配置官方客户端时的回退方案。

其他 rclone 配置仍遵循下面的通用规则：

- 用户在本机配置 rclone remote。
- 百度网盘通过 OpenList 的 WebDAV 服务暴露给 rclone；夸克未配置官方电脑备份时也回退到该链路。
- 每个主播独立选择是否启用网盘备份。
- 每个主播独立填写 remote 路径，例如 `openlist:/baidu/DouyinBiliRecorder` 或 `openlist:/quark/DouyinBiliRecorder`。
- 应用自动按主播、日期、P 编号归档。

## 夸克官方客户端“电脑备份”

1. 安装并登录夸克官方 macOS 客户端（本机验证版本为 `7.4.0.818`）。
2. 在夸克客户端打开 `电脑备份`，把应用输出的视频根目录（或它的明确子目录）加入备份任务。
3. 在 rclone 中配置一个指向同一夸克账号的 `quark:` remote。该 remote 只用于读取/校验，不承担上传。
4. 在应用总览的“夸克电脑备份目录”填写第 2 步的本地目录；在“夸克校验远端”填写该目录对应、且 rclone 可读取的远端根路径。
5. 点击 `测试官方 VIP 通道`。测试会写入一个 256 KiB 探测文件，等待官方客户端同步，用 `rclone size` 核对远端大小，然后删除本地和远端探测文件。
6. 如果客户端里没有覆盖该目录的 `电脑备份` 任务，应用会立即报错，不会把文件复制进去后等待超时，也不会把 OpenList 上传标成“官方快速通道”。

只有“官方客户端完成备份 + rclone 能读到同路径”两项同时成立，才算真 VIP 通道验证成功。当前安装包已实现并测试诊断流程；端到端上传需要先在夸克客户端创建电脑备份任务。

## OpenList 回退配置


1. 安装 OpenList：<https://github.com/OpenListTeam/OpenList>
2. 在 OpenList 中添加百度网盘或夸克网盘存储。
3. 在 OpenList 中启用 WebDAV。
4. 安装 rclone：<https://rclone.org/install/>
5. 使用 `rclone config` 创建 WebDAV remote，例如：

```text
name: openlist
type: webdav
url: http://127.0.0.1:5244/dav
vendor: other
user: <OpenList 用户名>
pass: <rclone 加密后的密码>
```

上例的 `openlist:` 指向 OpenList WebDAV 根目录。应用里的 remote 路径需要包含存储挂载名，例如夸克填写 `openlist:/quark/DouyinBiliRecorder`，百度填写 `openlist:/baidu/DouyinBiliRecorder`。也可以为每个网盘单独创建指向 `/dav/quark` 或 `/dav/baidu` 的 remote；此时路径不要再重复挂载名。

如果每个网盘使用单独的 remote，URL 应直达对应挂载点，例如 `http://127.0.0.1:5244/dav/quark`，路径写作 `quark:/DouyinBiliRecorder`。两种配法二选一，不要混用。

6. 启动应用。应用会自动启动 `Application Support/DouyinBiliRecorder/tools/openlist/openlist`（如果存在），并确认左上角的 `rclone 可执行文件` 指向 `rclone` 或绝对路径。
7. 在主播卡片中选择百度/夸克并填写 remote 根路径；是否开启 `网盘备份` 不影响主播目录创建。
8. 点击 `测试网盘` 验证远端可访问。
9. 保存主播设置。
10. 保存和开播前会先检查 `主播名/` 是否存在；只有不存在时才创建。例如填写 `openlist:/quark/DouyinBiliRecorder` 后，“example-anchor”目录缺失时才会创建 `openlist:/quark/DouyinBiliRecorder/example-anchor/`。

## 归档规则

网盘目录示例：

```text
openlist:/quark/DouyinBiliRecorder/
  example-anchor/
    2026-09-30/
      1042_直播标题_P01.mp4
```

网盘只接收烧录后的最终 MP4，不上传 XML、FLV 或临时文件。

## 删除本地的安全规则

- B站上传和网盘备份分别使用独立上传线程，互不影响。
- B站限流或投稿失败不会停止网盘备份。
- 开启网盘备份后，只有 B站 BVID 和网盘文件都成功，才允许按全局设置删除本地文件。
- 网盘备份失败时，本地文件会保留，主播卡片会显示失败状态。
- 清除缓存不会删除尚待网盘备份或网盘备份失败的片段。
- 重启应用后会继续补传未完成的网盘备份。
