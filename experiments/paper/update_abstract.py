import sys

file_path = 'experiments/paper/sigconf-v3.tex'
old_text = r"""\begin{abstract}
Spec-driven development (SDD) with AI coding agents provides a structured workflow, but agents often remain ``context blind'' in large, evolving repositories, leading to hallucinated APIs and violations of local architecture. We present 	extbf{Spec Kit Agents}, an orchestrated multi-agent SDD pipeline (PM/Developer roles) that adds phase-level tool-augmented guardrails.
Read-only probing hooks ground each stage (Specify, Plan, Tasks, Implement) in repository evidence, and validation hooks check intermediate artifacts against the local environment. We evaluate X task instances (X unique feature tasks across X  open-source popular repositories). Guardrails improve quality by +Y on a 5-point LLM-judge scale (paired Wilcoxon over tasks, n\_pairs=14, p<0.05) while maintaining 99.7--100\% test pass rates.
\end{abstract}"""

new_text = r"""\begin{abstract}
Spec-driven development (SDD) with AI coding agents provides a structured workflow, but agents often remain ``context blind'' in large, evolving repositories, leading to hallucinated APIs and violations of local architecture. We present 	extbf{Spec Kit Agents}, an orchestrated multi-agent SDD pipeline (PM/Developer roles) that adds phase-level tool-augmented guardrails.
Read-only probing hooks ground each stage (Specify, Plan, Tasks, Implement) in repository evidence, and validation hooks check intermediate artifacts against the local environment. We evaluate 28 unique feature tasks across three open-source popular repositories. Guardrails improve quality by +0.19 on a 5-point LLM-judge scale (paired Wilcoxon over tasks, $n_{	ext{pairs}}=14$, $p<0.05$) while maintaining 99.7--100\% test pass rates. On the SWE-bench Lite benchmark, Spec Kit Agents achieves a 58.8\% pass rate.
\end{abstract}"""

with open(file_path, 'r') as f:
    content = f.read()

if old_text in content:
    content = content.replace(old_text, new_text)
    with open(file_path, 'w') as f:
        f.write(content)
    print("Updated abstract successfully.")
else:
    print("Could not find the abstract text to replace.")
