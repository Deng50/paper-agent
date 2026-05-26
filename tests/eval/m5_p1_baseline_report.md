# 中文召回率评估报告（M4 task 7）

- 黄金集：`tests\eval\cn_recall_gold.yaml`
- 验收口径：top_3 ≥ 80%
- 主集判定：[FAIL]（paper 60% / session 0%）

## 主集（不含 F 警示项）

### 文献题（scope=papers）（5 题）

- 总分：Top-1 2/5=40%　Top-3 3/5=60%　Top-5 3/5=60%
- 按主题：
  - A_sulfide_solid_electrolyte（2 题）：Top-1 1/2　Top-3 2/2　Top-5 2/2
  - B_li_metal_anode_interface（2 题）：Top-1 1/2　Top-3 1/2　Top-5 1/2
  - D_polymer_composite_electrolyte（1 题）：Top-1 0/1　Top-3 0/1　Top-5 0/1

### 对话题（scope=sessions）（5 题）

- 总分：Top-1 0/5=0%　Top-3 0/5=0%　Top-5 0/5=0%
- 按主题：
  - A_sulfide_solid_electrolyte（2 题）：Top-1 0/2　Top-3 0/2　Top-5 0/2
  - B_li_metal_anode_interface（2 题）：Top-1 0/2　Top-3 0/2　Top-5 0/2
  - D_polymer_composite_electrolyte（1 题）：Top-1 0/1　Top-3 0/1　Top-5 0/1

## F 警示项（电池热管理，corpus 稀缺，单独算分不计主验收）

- corpus_count = 1
- expected_recall = near 0 due to corpus sparsity (not algorithmic failure)

### F 文献题（0 题）

（无题目）

### F 对话题（0 题）

（无题目）
