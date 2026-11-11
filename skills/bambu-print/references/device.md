# 拓竹设备

以下命令从技能目录运行，JOB 指 prepare 生成的目录。每份成功的切片有独立的 print-… 任务名和 SHA-256。首次交接会在当前操作系统用户的本地状态目录记录尝试，避免同一作业重试或切换通道时重复开印。只有已获授权开印并准备交接时才使用 studio 或 send；平时可直接浏览 plate.png、报告和模型文件。

## 官方 Bambu Studio

    python scripts/device.py studio JOB --printer "目标设备在 Studio 的名字"

这条命令校验文件并打开 Studio。目标名用作操作记录；需要在官方界面选择同名设备。定位刚打开的已切片工程，核对任务名、机型、盘型、喷嘴、材料与实际料槽、警告和调平选项。按当前版本的“打印盘 / 打印”进入发送窗口，核对目标，再发送一次。若界面要求重切或切换预设，退回切片审查。记录设备接单、首层和最终状态。Studio 中用设备与任务详情核对，不用固定坐标自动点击。官方路径适用于原有云连接或 Studio 支持的局域网连接。[拓竹关于第三方连接的说明](https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect/)

## LAN 自动发送

可选依赖为 **voska/bambu v0.3.0**。从上游 release 下载对应系统的压缩包，比对该 release 的 SHA-256 后解压，将可执行文件放入 PATH 或用 BAMBU_CLI 指向它。局域网方式依赖兼容固件、已由机主启用的 LAN Only / Developer Mode 和可达的打印机。它会影响原有云连接，工作流不会自动切换。此客户端使用自签名设备证书及不校验服务端证书的 TLS，只在可信局域网使用。该版本的发送路径写入 use_ams=true，本项目仅对 AMS 槽开放 LAN 发送。外置料架使用官方 Studio。[v0.3.0 发布包](https://github.com/voska/bambu/releases/tag/v0.3.0) · [上游实机覆盖与设置](https://github.com/voska/bambu/tree/v0.3.0)

一次性配置示例，将尖括号和别名替换成本机值。访问码在交互式 auth set 提示中输入。设备地址、序列号、访问码、原始设备日志留在本地。

    bambu printer add workshop --host <设备局域网地址> --serial <设备序列号> --model A1M --nozzle 0.4 --plate textured_plate
    bambu auth set workshop
    bambu --printer workshop status

在可信局域网配置完成、确实使用 AMS A1 槽时：

    python scripts/device.py check JOB --printer workshop --slot A1
    python scripts/device.py send JOB --printer workshop --slot A1 --ready
    python scripts/device.py watch JOB --printer workshop --timeout 3600

check 读取设备并进行 FTPS 登录检查。核对其中的材料、余量、目标机型及全部 WARN；配置里的盘型仍需和实物对照。send 再做预检，交给上游上传并回读校验，然后核对设备上的唯一任务名。watch 可在断线后重新运行。不同任务、暂停、报警和超时会得到不同状态；设备报告 FINISH 后仍需冷却再验收。

发送结果不明时，保留本地凭据记录，在原设备查询任务名和历史，等待延迟回执。Studio 已打开但尚未点击发送时，可回到原窗口继续。只有明确查到原任务从未开始或确实需要另打一件，才对新的作业版本发起发送。BAMBU_PRINT_STATE 可指定本地持久状态目录；同一台操作电脑应保持目录固定。跨电脑交接时核对同一台打印机的任务历史。
