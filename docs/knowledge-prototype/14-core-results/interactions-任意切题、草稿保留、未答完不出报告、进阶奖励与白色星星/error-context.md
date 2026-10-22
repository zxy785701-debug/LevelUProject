# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: interactions.spec.ts >> 任意切题、草稿保留、未答完不出报告、进阶奖励与白色星星
- Location: e2e-accounts\interactions.spec.ts:26:5

# Error details

```
Test timeout of 60000ms exceeded.
```

# Page snapshot

```yaml
- generic [ref=f1e4]:
  - generic [ref=f1e5]: 9:41
  - generic [ref=f1e14]:
    - generic [ref=f1e15]: 本轮闯关
    - generic [ref=f1e20]: •••
  - generic [ref=f1e23]:
    - generic [ref=f1e24]:
      - generic [ref=f1e25]: 1 / 3
      - navigation "切换题目" [ref=f1e26]:
        - button "第 1 题" [ref=f1e27]:
          - generic [ref=f1e28]: "1"
        - button "第 2 题" [ref=f1e29]:
          - generic [ref=f1e30]: "2"
        - button "第 3 题" [ref=f1e31]:
          - generic [ref=f1e32]: "3"
      - generic [ref=f1e33]: 30 XP
    - generic [ref=f1e36]:
      - generic [ref=f1e37]: 单选题
      - generic [ref=f1e38]: HTTP 基础
    - generic [ref=f1e39]: 第 1 个问题？
    - generic [ref=f1e40]:
      - button "A 选项 A" [ref=f1e41]:
        - generic [ref=f1e42]: A
        - generic [ref=f1e43]: 选项 A
      - button "B 选项 B" [ref=f1e44]:
        - generic [ref=f1e45]: B
        - generic [ref=f1e46]: 选项 B
      - button "C 选项 C" [ref=f1e47]:
        - generic [ref=f1e48]: C
        - generic [ref=f1e49]: 选项 C
      - button "D 选项 D" [ref=f1e50]:
        - generic [ref=f1e51]: D
        - generic [ref=f1e52]: 选项 D
    - generic [ref=f1e53]: 选好后点击“确认本题”，确认前可以修改
  - generic [ref=f1e56]:
    - generic [ref=f1e57]:
      - button "上一题" [disabled] [ref=f1e58] [cursor=pointer]
      - button "确认本题" [disabled] [ref=f1e59] [cursor=pointer]
    - generic [ref=f1e60]: 已答 2 / 3 题，答完自动查看报告
```