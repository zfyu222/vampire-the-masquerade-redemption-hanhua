# 占位符分析报告

- 文件：`vampire-the-masquerade-redemption_text.csv`
- 逻辑行：5163，物理行：5163

## square_bracket — 2 次出现
- 方括号标记（变量占位符/BBCode/富文本标签，如 [Player:Name] [i] [color="red"]）
- 建议禁翻正则：`\[[^\[\]\n]{1,60}\]`
- 高频样本：
  - `[not identified]` ×1
  - `[Cannot use yet]` ×1

## angle_tag — 1 次出现
- 尖括号标签（HTML/XML/Unity 富文本，如 <b> </color> <Tag:1>）
- 建议禁翻正则：`</?[A-Za-z][^<>\n]{0,50}>`
- 高频样本：
  - `<dialtone sound>` ×1

## printf — 22 次出现
- printf 格式化符（如 %s %d %.1f %1$s %%）
- 建议禁翻正则：`%(?:\d+\$)?[0-9.+#-]*[sdfoxXeEfgGcr]`
- 高频样本：
  - `%s` ×11
  - `%d` ×8
  - `%f` ×2
  - `%g` ×1
