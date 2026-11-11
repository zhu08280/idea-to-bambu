# Idea to Bambu · 说出需求，做成打印件

在 Codex 里描述你想做的东西。技能会把用途和关键尺寸写进任务规格，生成可编辑模型，用 Blender 检查导出的 STL，再调用本机 Bambu Studio 切片。需要打印时，沿用官方 Studio，或在已配置的局域网设备上自动发送、跟踪作业。

> 做一枚空白挂线牌，30 × 20 × 3 mm，左侧开 5 mm 通孔。用 A1 mini 和 PLA，先切片。

<img src="docs/cable-tag.png" width="230" alt="示例切片包内的挂线牌预览，可见圆角及靠左的通孔">

上述示例在 Windows、Blender 4.4.3、Bambu Studio 2.9.1.70 下完成了真实切片。0.4 mm 喷嘴、0.20 mm 层高、纹理 PEI 板，15 层，预计 9 分 38 秒、1.55 g。示例停在切片阶段。

## 安装与第一单

准备 Python 3.10 或更高版本、Blender 4.x、Bambu Studio。首次运行 Studio，完成其初始设置；官方设备发送需要在 Studio 中连接自己的打印机。离线建模、切片无需设备账号或 LAN 访问码。

克隆仓库后，可直接在 Codex 中说“用这个仓库的 bambu-print 技能，做一个……”。要在别的项目或新聊天中使用，可把整个 skills/bambu-print 目录复制到自己的 Codex skills 目录，然后新开聊天。Windows PowerShell 示例：

~~~powershell
git clone https://github.com/zhu08280/idea-to-bambu.git
Set-Location idea-to-bambu
$skillsDir = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex/skills' }
New-Item -ItemType Directory -Force $skillsDir | Out-Null
Copy-Item -Recurse -LiteralPath skills/bambu-print -Destination $skillsDir
~~~

安装一次后，可用系统听写或键盘输入同一句需求。自然语言理解和新物件建模由宿主 AI 完成。脚本也可以独立运行；以下命令可复现挂线牌，无需 AI、API key 或打印机。输出目录须是新目录。

~~~shell
python skills/bambu-print/scripts/prepare.py demo jobs/tag-01
~~~

打开任务目录中的 plate.png 看摆放，report.json 看估时、耗材、首层件数和切片警告。目录还含 tag.blend、tag.stl、geometry.json 和可在 Studio 打开的 .gcode.3mf。

## 换成自己的设计

1. 说清用途与必须满足的尺寸。例如“给 2 mm 厚的板做个卡扣，单手可拆”。技能会追问决定配合的条件，或先做局部试件。桌面装饰、外壳和活动关节用不同的实物验收动作。[各环节审查要点](skills/bambu-print/references/review.md)
2. 保留 CAD 或 Blender 源文件，导出 mm 单位的 STL。把 job.json 放在模型旁边，填入零件尺寸、源文件、材料和机器预设。[可复制的任务规格](skills/bambu-print/examples/tag.json) · [字段说明和范围](skills/bambu-print/references/job.md)
3. 运行下列命令，照着原始需求检查外形、首层和关键高度。切片只接收通过数字检查的模型。修改尺寸、材料或摆放方向后，用新的目录生成下一版。

~~~shell
python skills/bambu-print/scripts/prepare.py job design/job.json jobs/revision-01
~~~

## 连接拓竹并打印

| 你的设备 | 入口 | 何时算完成 |
| --- | --- | --- |
| 使用官方 Bambu Studio，含云连接或外置料架 | device.py studio 打开已校验文件，在 Studio 选择并发送；可操作桌面的 AI 可接着处理界面 | 核对设备及本次任务，跟到设备完成，再按任务规格验收实物 |
| 已配置兼容的 LAN Only / Developer Mode 和 AMS | device.py check / send / watch；后端为 voska/bambu v0.3.0 | 预检、回读校验、同名任务状态，最后记录实物检验 |

按自己的设备选择路径。LAN 发送前要核实料槽、余量、盘面已清空。发送超时后可以继续查询原单。首次交接记录用于阻止同一作业重复开印。[配置、命令及故障恢复](skills/bambu-print/references/device.md)

## 验证范围

- 已实测 Windows 上的离线建模、网格检查、切片和 3MF 回读。自动化入口支持单盘、单料、一个或多个平放的独立 STL。其他机型可指定对应的 Studio 系统预设，换机、换材料后需重新验证。
- 测试覆盖尺寸及孔径错误、配置继承、文件被替换、设备预检失败、错单回执、重复发送、断线与恢复。设备侧测试使用模拟回执；本项目尚未用这版 LAN 代码在 A1 mini 上启动并完成一单实打。
- 现场验收依据盘面、线轴、首层观察和实物测量。机器完成时仍可能需要处理翘曲、孔紧、装配干涉或承力方向。每次修订都保留原始需求及上一版的测量结果。

~~~shell
python -m unittest discover -s tests -v
~~~

将 BAMBU_INTEGRATION 设为 1 会额外调用本机 Blender 和 Studio，实际切片并检查错误尺寸的拒绝路径。运行这些测试不会发送打印任务。

本项目采用 [MIT 许可](LICENSE)。Bambu Studio、设备固件及可选 LAN 客户端按各自许可使用。本项目由社区开发。
