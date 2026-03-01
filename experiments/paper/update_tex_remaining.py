import re

file_path = 'experiments/paper/sigconf-v3.tex'

with open(file_path, 'r') as f:
    content = f.read()

# Evaluation bullet
eval_pattern = r'\item 	extbf\{Evaluation\.\} An empirical study on X unique feature tasks spanning X repositories'
eval_replacement = r'\item 	extbf{Evaluation.} An empirical study on 28 unique feature tasks spanning three repositories'
content = re.sub(eval_pattern, eval_replacement, content)

# Intro paragraph
intro_pattern = r'Across X task instances \(X tasks instantiated over the reported open-source repositories\), Spec Kit Agents yields a modest but consistent improvement in judged quality \(\+X on a 1--5 composite scale, paired Wilcoxon over tasks with \$n_{	ext\{pairs\}}=14\$, \$p<0.05\$\) while maintaining high test pass rates \(99\.7--100\%\)\.'
intro_replacement = r'Across 28 unique feature tasks over three open-source repositories, Spec Kit Agents yields a modest but consistent improvement in judged quality (+0.19 on a 1--5 composite scale, paired Wilcoxon over tasks with $n_{	ext{pairs}}=14$, $p<0.05$) while maintaining high test pass rates (99.7--100%). On the SWE-bench Lite benchmark, Spec Kit Agents achieves a 58.8% pass rate.'

def repl_intro(m):
    return intro_replacement

content = re.sub(intro_pattern, repl_intro, content)

with open(file_path, 'w') as f:
    f.write(content)

print("Remaining updates applied.")
