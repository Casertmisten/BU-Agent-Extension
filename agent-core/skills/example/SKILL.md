---
name: example
description: 一个示例技能，演示如何编写和使用 Skill
---

# 示例技能

这是一个示例技能。当用户在输入框输入 `/skill example` 时，Agent 会通过内置的 `Skill` 工具读取本文件，然后按这里的指令操作。

## 使用方式

1. 确认用户的具体需求
2. 按需调用浏览器工具（parse_dom / click / input_text 等）完成任务
3. 完成后用 done 工具汇报结果

## 自定义技能

在 `agent-core/skills/<你的技能名>/SKILL.md` 创建新技能即可。frontmatter 必须包含 `name` 和 `description` 两个字段，正文是给 Agent 看的指令（markdown）。
