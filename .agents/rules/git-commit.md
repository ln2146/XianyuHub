---
trigger: always_on
---

# 修改后必须提交

- 每完成一次代码修改（并通过类型检查 / 相关测试）后，立即执行 `git commit`。
- 只 `git add` 本次修改涉及的文件，不要把工作区里与本次任务无关的改动一起提交。
- 提交信息沿用仓库现有风格：英文 Conventional Commits，例如 `feat(goods): redesign publish page uploader`。
- 不要自动 `git push`，除非用户明确要求。
