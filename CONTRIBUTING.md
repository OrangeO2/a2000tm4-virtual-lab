# 贡献指南

## 提交前

```bash
pip install -e .
pytest tests/ -v          # 参考模型测试必须全绿
```

改动 Renode 平台后，本地做一次语法冒烟（需安装 Renode）：

```bash
renode --console -e "mach create; machine LoadPlatformDescription @renode/a2000tm4.repl; quit"
```

## 约定

1. **模型常数必须有出处**：凡写入 `models/` 的数值（寄存器地址、协议常量、
   标定系数、时钟参数），在 docstring 中标注来源：数据手册章节、课程讲义页码，
   或 `docs/2-measured-board-facts.md` 中的实测记录编号。
2. **不要提交课程版权材料**（固件源码/二进制），见 `NOTICE.md`；
   本地放在 `firmware/local/`。
3. 实测新数据请同时更新 `docs/2-measured-board-facts.md`（记录测量条件与探针版本），
   再让模型/测试引用它。
4. 提交信息用中文或英文均可，一行主题 + 空行 + 说明。

## 报告问题

报 bug 时请附：Renode/python 版本、使用的固件（名字与来源，不必附文件）、
最小复现步骤、预期与实际输出。
