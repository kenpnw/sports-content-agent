# Chapter 2  Related Work

This chapter conducts a focused literature review across five directions closely related to the work in this thesis: (1) large language models and text generation; (2) retrieval-augmented generation; (3) hallucination in LLMs and its suppression; (4) multi-agent LLM systems; and (5) automatic sports content generation. For each direction, the review highlights representative works, their core ideas, the inspiration they provide for this thesis, and the specific extensions or differences in our approach.

## 2.1 Large Language Models and Text Generation

### 2.1.1 The Transformer and the GPT Family

The foundation of modern large language models is the Transformer architecture introduced by Vaswani et al. [Vaswani 2017]. By replacing recurrent computation with self-attention, the Transformer enables parallel processing of long sequences and effective capture of long-range dependencies. The GPT family [Radford 2018; Radford 2019; Brown 2020; OpenAI 2023] inherits the Transformer decoder backbone and applies autoregressive language modeling on large-scale unlabeled text, scaling parameter counts from GPT-1's 117 million through GPT-3's 175 billion to the (undisclosed) larger scale of GPT-4. Generation quality exhibits "emergent abilities" as model scale grows [Wei 2022b]. Encoder-based bidirectional pretraining models such as BERT [Devlin 2019] meanwhile dominate discriminative tasks.

The "in-context learning" (ICL) capability demonstrated by GPT-3 — learning new tasks from a handful of in-prompt examples — opened the research direction of "prompt engineering" [Liu 2023]. Chain-of-thought (CoT) prompting [Wei 2022a] further demonstrated that requiring explicit reasoning steps in the prompt can substantially improve performance on complex reasoning tasks.

### 2.1.2 Instruction Tuning and Human-Preference Alignment

Pretrained foundation models are not natively suited for dialogue or instruction-following. Instruction tuning [Wei 2022; Sanh 2022; Chung 2024] supervises the model to learn the "instruction → response" format, substantially improving instruction-following ability. Reinforcement learning from human feedback (RLHF) [Ouyang 2022] further leverages human preference annotations to train a reward model, then uses reinforcement learning algorithms (such as PPO) to optimize the language model along three dimensions: helpfulness, honesty, and harmlessness. Direct Preference Optimization (DPO) [Rafailov 2024] provides a simplified path that bypasses the need to train a separate reward model and has been adopted by several open-source models.

### 2.1.3 The Chinese LLM Ecosystem

The open-source ecosystem for Chinese-language models has matured rapidly. The Qwen series [Bai 2023; Bai 2024] (Alibaba), the ChatGLM series [Zeng 2023] (Zhipu AI), the Baichuan series [Yang 2023] (Baichuan Inc.), and the DeepSeek series [DeepSeek-AI 2024] (DeepSeek) all achieve Chinese-scenario performance comparable to GPT-4-equivalent classes. This thesis selects DeepSeek-V2 as the underlying model for three reasons: (1) DeepSeek-V2 demonstrates strong understanding of Chinese basketball terminology — "pick-and-roll," "backdoor cut," "drag screen" — with accurate semantic capture; (2) DeepSeek provides an OpenAI-compatible API surface, lowering integration cost; (3) DeepSeek's per-token pricing is substantially lower than GPT-4, enabling cost-effective production deployment.

### 2.1.4 Relationship to This Thesis

This thesis uses DeepSeek-V2 as a foundation language model layer and does not modify LLM architectures or training methods. The contribution is positioned **above** the LLM, in the form of coordination and constraint mechanisms — multi-agent protocols, prompt contracts, dual-layer knowledge architectures — that bound the LLM's output to be trustworthy and controllable in the sports-content-generation scenario. This line of work is complementary to, rather than substitutive of, the research program of "improving LLM intrinsic capability through larger-scale training or finer-grained tuning."

## 2.2 Retrieval-Augmented Generation (RAG)

### 2.2.1 The Classic RAG Paradigm

The RAG framework introduced by Lewis et al. [Lewis 2020] is the most influential "knowledge + LLM" integration paradigm. Its core idea is: for each user query, first retrieve top-K relevant text chunks from an external (typically vector-indexed) knowledge base, concatenate them into the LLM input as context, and have the LLM generate the final response. This paradigm offers two clear advantages: (1) it decouples "knowledge" from "generation" — updating the knowledge base does not require model retraining; (2) generated output can cite concrete sources, lowering hallucination risk. RAG has become the de facto standard architecture for enterprise LLM applications.

### 2.2.2 Improvement Trajectories

The limitations of RAG manifest in three areas: (1) retrieval quality is limited by the vector index algorithm; (2) the LLM may ignore retrieved chunks and "free-associate"; (3) a single vector store struggles to carry structured knowledge. Subsequent work improves along these three axes:

- **Retrieval quality.** HyDE [Gao 2023] generates a "hypothetical document" first, then uses it as the query for retrieval, improving recall. ColBERT [Khattab 2020] and its successors employ fine-grained late-interaction encoding to improve relevance. GraphRAG [Edge 2024] captures entity relationships through graph-structured knowledge representation.
- **LLM-retriever coordination.** Self-RAG [Asai 2023] teaches the LLM to dynamically decide whether to retrieve, what to retrieve, and whether to cite retrieved results during generation. CRAG [Yan 2024] introduces a lightweight retrieval-quality evaluator that triggers fallback strategies on low-quality retrieval. RAFT [Zhang 2024] fine-tunes the LLM to distinguish "relevant vs. distractor" retrieved chunks.
- **Multimodal and structured-knowledge extensions.** MuRAG [Chen 2022] extends RAG to image-text mixed knowledge bases. KG-RAG [Yang 2024] introduces knowledge graphs as supplementary retrieval sources. Table-RAG [Wang 2024] designs specialized retrieval and alignment mechanisms for tabular structured data.

### 2.2.3 The Numeric-Recall Bottleneck

Despite RAG's success on text-style questions ("describe player X's career"), it still hits a clear ceiling on numeric questions ("what was player X's shooting percentage last season"). Two reasons: (1) vector retrieval is based on semantic similarity, which is unfriendly to precise numeric recall — "42%" and "43%" have very close vector similarity but starkly different semantics; (2) when the LLM sees multiple close numeric values in context, it is prone to "numeric crosstalk," conflating data from one entity with another.

The Dual-Layer Knowledge Architecture proposed in this thesis directly addresses this gap: by extracting structured numeric knowledge from the vector store into a precision-query-friendly SQLite Fact Store, accompanied by explicit routing policy, numeric assertions must clear Fact Store verification. This design is conceptually related to Table-RAG [Wang 2024] but more explicit in formalizing the routing policy.

## 2.3 LLM Hallucination and Factuality

### 2.3.1 Categorization and Evaluation of Hallucination

Ji et al. [Ji 2023], in their ACM Computing Surveys review, systematically categorize LLM hallucinations into "intrinsic hallucinations" (conflicting with input) and "extrinsic hallucinations" (conflicting with established facts). Huang et al. [Huang 2024] further subdivide into "factuality hallucination" and "faithfulness hallucination." In this thesis's sports-content scenario, the focus is on the former — whether generated content is consistent with real game data.

For hallucination evaluation, FActScore [Min 2023] decomposes generated text into atomic facts and verifies each against a reference knowledge base. SelfCheckGPT [Manakul 2023] generates multiple answers to the same question and estimates hallucination risk based on inter-answer consistency. TruthfulQA [Lin 2022] provides a multiple-choice dataset targeting common misconceptions to specifically test the model's resistance to false beliefs. This thesis adopts the "atomic-fact" idea from FActScore in the Chapter 5 experimental design, decomposing each generated segment into atomic units of "player-action-number-time" for individual verification.

### 2.3.2 Three Approaches to Hallucination Suppression

Hallucination suppression methods fall into three categories:

**(1) Generation-time control.** Real-time intervention during model generation. Constitutional AI (CAI) [Bai 2022] has the model post-generate-then-self-correct against a set of principles. Chain-of-Verification (CoVe) [Dhuliawala 2023] uses a "draft → generate verification questions → answer verification questions → revise draft" multi-round flow to reduce hallucination. Inference-Time Intervention (ITI) [Li 2023] modifies specific attention-head activations to steer the model toward more "truthful" output.

**(2) Post-hoc verification.** An independent verification model or rule system checks output after generation. FActScore [Min 2023] and FacTool [Chern 2023] fall in this category, typically using an independent fact-checking LLM or retrieval system for post-hoc verification.

**(3) Training-time intervention.** Modify training objectives or data so the model's intrinsic hallucination tendency is reduced. RLHF [Ouyang 2022], DPO [Rafailov 2024], and KTO [Ethayarajh 2024] preference optimization methods can include "honesty" as an optimization target; FactTune [Tian 2024] fine-tunes on factuality preference data.

### 2.3.3 Positioning in This Thesis

The Multi-Agent Supervision Protocol proposed here is a hybrid of "generation-time control + post-hoc verification":

- **Generation-time control**: The Writer role is prompt-constrained to require an `evidence_id` on every assertion, with unsupported sentences structurally rejected at the generation stage.
- **Post-hoc verification**: The Fact Checker role independently verifies whether each `evidence_id` resolves to an actual record in the Fact Store / Text RAG; un-resolved cases trigger a Writer correction loop.
- **Risk layer**: The Risk Guard role checks for player-personality attacks, inflammatory refereeing commentary, and other business-rule violations, blocking when necessary.

Compared to CAI and CoVe, two key differences are: (1) the verifier role is strictly separated from the generator role, avoiding the "model grades itself" bias; (2) the reviewer roles have hard blocking authority — failed reviews do not pass downstream, rather than serving as "advisory suggestions only."

## 2.4 Multi-Agent Large Language Model Systems

### 2.4.1 Task-Decomposition Multi-Agent Frameworks

Decomposing a complex task across multiple LLM roles in coordination has emerged as a rapidly growing research direction over the past two years. AutoGen [Wu 2023] (Microsoft) provides a general "conversable agent" framework where each agent registers its own system prompt, tool set, and dialogue policy. MetaGPT [Hong 2023] maps the standardized software-engineering workflow (PRD → design → coding → testing) onto multi-role LLM coordination. CAMEL [Li 2023] introduces a "role-play" paradigm in which two LLM instances act as "user" and "assistant" to advance a task through dialogue. ChatDev [Qian 2024] simulates multiple roles in a software company (CEO, CTO, programmer, QA) cooperating.

The common pattern across these works: map a complex task's "functional pipeline" onto multiple LLM roles, advancing the workflow through inter-role dialogue or message passing. Advantages include: (1) single-role prompt complexity is reduced, with more controllable behavior; (2) separation of concerns lets each role focus on a sub-task; (3) errors can be caught at role boundaries.

### 2.4.2 Debate-Style Multi-Agent Frameworks

Another line emphasizes "debate to improve reasoning quality." Multi-Agent Debate [Du 2023] has multiple LLM instances give independent answers to the same question, then see each other's answers and engage in multiple rounds of debate, converging to a more accurate answer. ChatEval [Chan 2023] applies multi-agent debate to evaluation tasks. Liang et al. [Liang 2024] further study how "diversity of thought" in debate affects final quality.

The core assumption of this line: by having multiple model instances examine the same question from different angles, the model's "self-reflection" capability can be amplified, surfacing errors invisible to single-pass inference. However, the effectiveness of debate is highly task-dependent — it has marked impact on tasks with definitive correct answers (mathematical reasoning, common-sense QA) but limited impact on open-ended generation tasks like content production.

### 2.4.3 Positioning in This Thesis

Our Multi-Agent Supervision Protocol is structurally closer to the "task-decomposition" line: Selector, Researcher, Writer, Fact Checker, and Risk Guard each handle distinct sub-tasks, advancing in pipeline fashion. The supervision mechanism, however, absorbs the "independent verification" idea from the debate line, having Fact Checker and Risk Guard act as independent reviewers of Writer's output rather than letting Writer self-evaluate.

Compared to general frameworks like AutoGen and MetaGPT, our protocol features three sports-content specializations:

- **Domain-aware role specifications.** The Writer's prompt explicitly injects a glossary of 30+ basketball terms and negative rules ("do not force a tactical label on a non-tactical possession"), preventing the system from mislabeling transition fast breaks, second-chance putbacks, or free-throw moments.
- **Explicit evidence contracts.** Every role's output must include an `evidence_id` field linking to specific records in the Fact Store or Text RAG.
- **Inviolable review blocking.** Fact Checker and Risk Guard's rejection signals trigger substantive correction or downgrade, not merely advisory suggestions.

## 2.5 Automatic Sports Content Generation

### 2.5.1 Early Template-Based Methods

Sports content automatic generation has a research history pre-dating LLMs. Early work such as STATS LLC's Automated Insights (a NarrativeScience product) employs template-based text-filling: predefine large numbers of sentence templates (e.g., "<player A> hits a <shot type> at <time>, cutting the deficit to <margin>"), then fill in variables at runtime from structured game data to output coherent text. This approach offers: (1) full controllability — no factual errors; (2) extreme speed, suitable for real-time reporting. But the drawbacks are equally clear: (1) stylistic monotony with low diversity; (2) difficulty handling complex tactical analyses that require semantic understanding; (3) high template maintenance cost.

Domestic early work such as Xinhua News Agency's "Kuaibi Xiaoxin" (online since 2015) and Toutiao's "Xiaomingbot" (online since 2016) adopt similar template-based methods, applied primarily to post-game summary generation.

### 2.5.2 The LLM Era of Sports Content Generation

As LLM capabilities have grown rapidly, multiple research and product teams have attempted to apply LLMs to sports content generation. SportsBot [Smith 2022] combines statistical data with LLMs to generate short-text commentary, but its evaluation focuses primarily on "fluency" without systematically quantifying factual correctness. Several commercial products attempt LLM-based post-game summary generation but disclose limited technical detail.

Among published academic work, the closest related effort is [Author Year, placeholder] proposing a multimodal sports content generation framework, but it targets primarily English-language scenarios and does not address multi-agent supervision.

### 2.5.3 Status of Video-Text Alignment Research

Multimodal alignment for sports content is another related direction. BasketballGAN [Hsieh 2019] and similar early work attempt to generate tactical commentary directly from video via deep learning, but require large-scale annotated training data. Recent work such as SoccerNet [Giancola 2018; Cioppa 2020] provides multi-modal annotated datasets and baseline methods for the soccer scenario. But in basketball, high-quality multi-modal annotated datasets are scarce, making end-to-end deep-learning approaches difficult to train sufficiently.

This thesis takes a "lightweight + interpretable" alignment approach: OCR time mapping + scoreboard visibility detection, achieving high accuracy on a single game without deep-learning training, using only classic computer vision techniques like OpenCV template matching. Deployment cost is extremely low.

### 2.5.4 Positioning in This Thesis

Among published sports-content-generation work, this thesis is one of the few simultaneously covering:

- **Multimodal alignment**: precise alignment between video clips and text commentary;
- **Multi-agent supervision**: 5-role coordination with hard supervision;
- **Multi-platform stylization**: differentiated content packages for Hupu, Douyin, Weibo, Xiaohongshu;
- **End-to-end implementation**: a complete pipeline from raw video and PBP to four-platform finished articles.

## 2.6 Chapter Summary

This chapter has reviewed five lines of work closely related to this thesis. While large language models have made tremendous progress in text generation, RAG in knowledge augmentation, multi-agent systems in task decomposition, and sports content generation in engineering practice, **an end-to-end sports content generation framework simultaneously satisfying the four requirements of factual controllability, multimodal alignment, multi-platform stylization, and visual provenance remains absent from the published literature**. This thesis contributes precisely such a complete solution.

\newpage
