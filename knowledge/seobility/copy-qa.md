# Seobility copy-quality gate

Use this gate for English comparison and alternative pages after factual QA. Do not use an AI-detector score. Evaluate observable writing quality, evidence use, originality, and voice fidelity.

## Automatic blockers

The copy does not pass when any of these remain:

- fabricated hands-on experience, customer consensus, or product facts;
- copied or closely imitated wording from a source article;
- an unfair competitor claim or an inference that an undocumented feature is absent;
- a major section that does not serve the approved brief, query intent, reader need, claim, or gap;
- generic product praise that could apply unchanged to almost any SEO tool;
- pricing without the official source date, currency, billing context, or material qualification;
- a conclusion that declares a universal winner without evidence.

## Editorial review

### 1. Useful specificity

- Does each major section contain a concrete fact, example, distinction, workflow consequence, or decision criterion?
- Does the copy explain why capabilities matter rather than simply listing them?
- Could the reader make a better decision without returning to the SERP for a basic unanswered question?

### 2. Natural prose

- Do sentence and paragraph lengths vary for a reason?
- Are transitions specific to the ideas around them rather than reusable filler?
- Are bullets, bold text, rhetorical questions, parentheses, and dashes used selectively?
- Have repetitive introductions, summaries, and mirrored section patterns been removed?
- Does reading the copy aloud sound like an informed person explaining the subject rather than a sequence of templates?

### 3. Brand fidelity

- Is the tone approachable, practical, reassuring, and evidence-aware?
- Are technical ideas explained in plain language without talking down to the reader?
- Is Seobility presented confidently but proportionately?
- Is the competitor treated fairly and credited for supported strengths?
- Are official Seobility feature names used correctly?

### 4. Original value

- What does this page contribute beyond combining vendor pages and existing rankings?
- Are SERP gaps converted into genuinely helpful coverage rather than extra length?
- Are user reviews used as attributed experience evidence rather than decoration?
- Are screenshots or examples tied to a reader decision?

### 5. Trust and restraint

- Are facts, anecdotes, and editorial judgments distinguishable?
- Are limitations and uncertainty stated where they affect the recommendation?
- Are promotional claims supported and placed where the reader benefit is clear?
- Is the final next step useful and proportionate rather than forced?

## Passing rule

Apply these checks through the existing QA dimensions:

- `originality` must be at least 4/5 and includes information gain and naturalness;
- `positioning_clarity` must be at least 4/5 and includes brand voice, comparison fairness, and CTA fit;
- no high- or medium-severity copy-quality issue may remain;
- all automatic blockers must be false.

List the exact weak passage and the required editorial change for every failed item. Do not request a rewrite merely because another stylistic choice would also work.
