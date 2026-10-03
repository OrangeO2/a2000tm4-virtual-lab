# NOTICE — 版权与材料边界

## 本仓库包含什么

- **原创代码**（MIT）：`models/`、`tests/`、`renode/`、`tools/hwprobe/`、CI 配置。
  这些是本项目的贡献者编写的，包括对真实硬件的实测工具与依据实测结果构建的仿真模型。
- **事实性数据**：TM4C1294NCPDT 寄存器地址、TM1638 指令码与段码、
  DAC6571 协议常量等，来自 TI / Titan Micro 公开数据手册以及课程公开讲义中的
  事实性技术参数（事实与参数不受版权保护，但感谢原机构的整理）。
- **实测数据档案**（docs/2）：来自贡献者对自己拥有的实验板卡进行的调试口测量。

## 本仓库刻意不包含什么

- **课程固件源码与编译产物**（demo.c / adc_demo.c / dac_demo.c / tm1638.c、
  *.axf / *.bin、driverlib 等）——版权归上海交通大学电子工程系实验教学中心 /
  课程教学组所有，仅在课程授权范围内向选课学生分发。

  使用者如已合法获得这些材料，可将其放置于本地 `firmware/local/` 目录
  （已被 .gitignore 排除），固件在环（FIL）测试即可直接运行；请勿提交或再分发。

- TivaWare 库本身：遵循 TI 的 BSD 许可单独获取（SW-EK-TM4C1294XL 安装包）。

## 商标

TM4C、Tiva、EK-TM4C1294XL 为 Texas Instruments 的商标；
Renode 为 Antmicro 的商标；本仓库与上述机构无隶属关系。
