# job.json

参考 [挂线牌](../examples/tag.json)。request 保留需求，design 记录选择和依据，acceptance 写能在实物上执行的验收动作。machine、process、filament 要填写本机 Bambu Studio 系统预设的完整名称。bed 填 Studio CLI 接受的盘型名称，例如 Textured PEI Plate。换料或喷嘴时一起核对这四项。

parts 每项包括同目录下的 stl 文件名、摆放后的 size_mm 三轴尺寸，以及可选的 vertical_bores。孔中心按 STL 坐标填写，diameter_mm 是标称直径。该项验证中心线贯穿，并在 3 个高度、每层 16 个方向采样内壁，适用于贯穿整件高度的直孔。横孔、沉头孔、斜孔或局部凹槽应单独做截面或间隙检查。复杂装配每件单独导出，件数等于 parts 长度。

可选 source_files 按文件名列出需要随单交付的同目录设计源文件，例如 ["washer.blend","make_washer.py"]。脚本将这些文件复制到成品目录。涉及外部依赖时可把源工程打成 ZIP。复制的建模脚本不会自动执行。

可选 process_settings 接受与 Bambu Studio 对应的字符串值。例如 {"enable_support":"1","wall_loops":"3"}。支持 enable_support、support_type、wall_loops、brim_type、brim_width、sparse_infill_density、sparse_infill_pattern、top_shell_layers、bottom_shell_layers。切片后会对照导出值，仍需检查相关层的形状。

首版处理单盘、单料、每件单连通表面且有平面着床的 STL。自动切片读取本机 Studio 的系统预设，解析继承与模板，并复核导出的启停 G-code、首层和文件摘要。版本间元数据格式可能不同；遇到无法识别的格式会中止。若需封闭内腔的独立内壳、筏板悬空、手绘多色或多盘，使用 Studio 的相应功能并单独记录人工复核结果。

环境变量 BLENDER_BIN、BAMBU_STUDIO_BIN 可指定可执行文件。BAMBU_PROFILES 指向安装目录中包含 machine、process、filament 的 profiles/BBL。脚本的运行时依赖为 Python 3.10+、有 wm.stl_import/export 的 Blender 4.x 和 Bambu Studio；本项目不分发厂商预设和网络插件。[拓竹 CLI 参数](https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage)
