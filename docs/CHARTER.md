# AI Repair Assistant — Project Charter

> **Role of this document.** This is the project's north star: vision, constraints,
> principles, and the intended roadmap. Day-to-day architecture choices are recorded
> in [`docs/adr/`](adr/). When an ADR **deviates** from this charter, the ADR must
> say so explicitly and the deviation is listed in [§ Deviations from this charter](#deviations-from-this-charter)
> below. The README stays a short status page and links here.

> **Provenance.** Adapted from the Phase-0 project brief that started this repository
> (2026-08-25). Editorial changes are limited to this preamble, the deviations
> register, and cross-links — not silent rewrites of requirements.

---
## Product Vision

Build a production-quality, open-source **AI Repair Assistant** that helps users diagnose and troubleshoot household appliances using authoritative manufacturer knowledge.

The initial product scope is intentionally narrow:

* **Manufacturer:** Whirlpool
* **Product category:** Front-load washing machines
* **Initial product family:** WFW5620H family
* **Anchor model:** WFW5620HW0

The architecture should eventually support additional Whirlpool washer models and, later, other appliance categories and manufacturers, but do not optimize prematurely for those future expansions.

The initial system should be designed deeply for one real product family rather than superficially for many products.

---

# Core User Experience

A user should eventually be able to describe a washer problem conversationally, for example:

> My Whirlpool WFW5620HW0 powers on, but the control panel is unresponsive.

The assistant should use available device information such as:

* manufacturer
* model
* model revision
* serial number
* symptoms
* error codes
* previous troubleshooting steps
* diagnostic results

to determine which manufacturer knowledge is applicable.

The assistant should provide grounded troubleshooting guidance based on authoritative documentation and clearly show the evidence behind its recommendations.

The product should ultimately support an interactive diagnostic process rather than only one-shot question answering.

For example:

**Problem → relevant evidence → next diagnostic step → user observation → updated diagnosis → next step or resolution.**

---

# Fixed Technology Constraints

The following technologies are predetermined and should be treated as fixed unless explicitly changed by the project owner:

* **Python**
* **PostgreSQL**
* **pgvector**
* **Docker**
* **OpenAI** — for **LLM inference and LangGraph-backed generation/workflow** only (see deviation D1). Embeddings are local open-source ([ADR-0009](adr/0009-local-open-embeddings.md)).
* **LangGraph**

Do not replace these technologies.

All other technology choices should remain open until there is sufficient reason to select them.

---

# Open-Source and Cost Principles

The application should be:

* open source
* self-hostable
* cloud-independent
* runnable locally
* free of mandatory paid infrastructure services

Do not introduce AWS, Azure, GCP, managed vector databases, commercial search platforms, commercial queues, or other hosted infrastructure as required dependencies.

OpenAI API usage for **LLM inference** is an intentional exception to the zero-paid-infrastructure objective. Embedding and vector indexing must not require a paid API ([ADR-0009](adr/0009-local-open-embeddings.md)).

Where practical, prefer open-source components that can run locally.

However, do not choose technologies merely because they are open source. Select them based on product requirements, maintainability, measurable performance, ecosystem maturity, operational simplicity, and licensing suitability.

---

# Production Quality, Not Demo Quality

Treat this as a real production software product rather than a RAG demonstration.

The system should eventually address concerns such as:

* correctness
* reliability
* reproducibility
* provenance
* versioning
* incremental processing
* observability
* evaluation
* testing
* failure recovery
* security
* safety
* maintainability
* performance
* cost
* auditability

Do not take shortcuts simply because the initial corpus is small.

At the same time, do not introduce enterprise-scale complexity without evidence that the application requires it.

Favor the simplest architecture that satisfies the actual requirements.

---

# Evidence-Driven Architecture

Do not assume that a commonly used AI technique is automatically appropriate.

Important architectural choices should follow this general reasoning process:

**Requirement → candidate approaches → experiment or benchmark where useful → evidence → decision.**

Examples include:

* document parsing
* OCR
* document representation
* chunking
* embeddings
* lexical retrieval
* semantic retrieval
* hybrid retrieval
* rank fusion
* reranking
* query transformation
* context construction
* evaluation frameworks
* observability
* asynchronous processing
* user interface technologies

When multiple reasonable solutions exist, identify the alternatives and explain their tradeoffs before committing.

Use lightweight Architecture Decision Records for meaningful architectural decisions.

The purpose of an ADR is to preserve:

* the problem
* relevant constraints
* alternatives considered
* evidence
* decision
* consequences

Do not create ADRs for trivial implementation details.

---

# Research Expectations

When entering a phase involving an important technical decision, research current industry practices and current capabilities of relevant technologies rather than relying entirely on assumptions or historical knowledge.

Distinguish between:

* established production patterns
* emerging techniques
* vendor recommendations
* experimental approaches

Do not adopt a technique merely because it is currently fashionable.

For important AI system decisions, prefer empirical evidence from this project's own corpus and evaluation dataset.

---

# Manufacturer Knowledge

The assistant must operate on **real manufacturer documentation** whenever practical.

Important source categories include:

* service manuals
* technical manuals
* service bulletins / Whirlpool Technical Service Pointers
* troubleshooting guides
* technical sheets
* repair parts lists / parts manuals
* wiring information
* installation documentation
* owner documentation
* manufacturer support knowledge

The corpus should preserve the distinction between these document types.

Do not treat all documents as equally authoritative or equally applicable.

---

# Document Applicability Is a Core Product Requirement

A repair instruction can be technically correct and still be wrong for the user's appliance.

The system must eventually reason about applicability such as:

* exact model
* model family
* engineering revision
* serial-number range
* document revision
* publication/effective date
* region where relevant
* superseded documentation
* later service bulletins
* related technical documents

A highly relevant semantic search result from the wrong model or serial range is still an incorrect retrieval result.

Therefore applicability and provenance should be treated as first-class concepts throughout the system.

---

# Document Precedence

Manufacturer knowledge may evolve.

For example:

* a service manual may contain a generic repair procedure
* a later Technical Service Pointer may describe a known field issue
* a newer document revision may modify earlier guidance
* a bulletin may only apply to a particular serial-number range

The product must eventually be able to distinguish:

**relevance** from **authority and applicability**.

Do not assume that the highest semantic-similarity result is necessarily the correct source.

The system should preserve enough document metadata and relationships to make these decisions explicitly.

---

# Ingestion Philosophy

The knowledge ingestion system should ultimately support:

* PDF documents
* Word documents
* HTML knowledge pages
* other useful manufacturer formats where justified

Documents should first be preserved as source artifacts with provenance before downstream transformations occur.

Parsing should produce a structured representation rather than assuming documents are simply continuous text.

Useful document concepts may include:

* sections
* headings
* paragraphs
* procedures
* numbered steps
* warnings
* notes
* tables
* figures
* captions
* parts information
* error-code entries
* troubleshooting decision structures

Do not commit to a specific parser or representation before evaluating realistic manufacturer documents.

---

# Incremental Ingestion Is a Major Requirement

The system should eventually detect changes below the whole-document level.

If a manufacturer changes one section of a large manual, the system should not automatically:

* reprocess every page
* recreate every chunk
* regenerate every embedding

The architecture should distinguish among concepts such as:

* source document identity
* document version
* structural element identity
* textual changes
* metadata changes
* added content
* removed content
* changed content
* unchanged content

The desired behavior is to process only what has materially changed while preserving correctness.

Real manufacturer revisions should be used to test this behavior whenever possible.

Do not prematurely prescribe the exact change-detection algorithm. Investigate approaches and evaluate them against actual document revisions.

---

# Chunking Is an Experimental Decision

Do not select one chunking strategy and treat it as universally correct.

Manufacturer service documentation contains very different information structures:

* narrative explanations
* troubleshooting procedures
* error-code tables
* electrical measurements
* warnings
* parts lists
* service bulletins
* short corrective actions
* long diagnostic sections

Different document types may require different strategies.

Potential approaches may include fixed, recursive, structural, hierarchical, parent-child, procedure-aware, semantic, contextual, or other strategies.

These are candidates, not predetermined solutions.

Chunking decisions should ultimately be justified through retrieval and end-to-end evaluations.

---

# Retrieval Is an Experimental Decision

The project should explicitly compare retrieval approaches rather than assuming semantic vector search is sufficient.

Repair knowledge includes both semantic questions such as:

> The washer starts filling and then stops.

and highly lexical information such as:

* error codes
* model numbers
* part numbers
* connector identifiers
* electrical values

The system should therefore investigate appropriate combinations of:

* structured metadata filtering
* lexical retrieval
* vector retrieval
* hybrid retrieval
* rank fusion
* reranking

PostgreSQL and pgvector are fixed components, but the specific retrieval design is not predetermined.

The retrieval architecture should be selected based on measurable performance on the repair corpus.

---

# Grounding and Citations

The assistant should eventually produce responses whose factual repair claims are traceable to retrieved evidence.

Citations should be meaningful enough for a user or evaluator to identify the supporting manufacturer source.

Where possible, retain provenance such as:

* document
* revision
* section
* page
* table
* relevant structural location

The system should not manufacture citations or use citations merely as decoration.

Citation correctness must itself be evaluated.

---

# Diagnostic Workflow

LangGraph is the predetermined workflow technology.

Use it where explicit state and controlled progression provide value.

The eventual repair workflow may involve states such as:

* identify appliance
* understand symptoms
* obtain missing device information
* retrieve relevant manufacturer knowledge
* determine possible causes
* select the next diagnostic step
* ask the user to perform an observation or safe test
* incorporate the result
* refine the diagnosis
* recommend corrective action
* abstain or escalate when appropriate

Do not build an unnecessarily autonomous agent.

Prefer explicit, inspectable workflow state and controlled transitions when they improve reliability and evaluation.

The LLM should not be given unlimited freedom simply because LangGraph supports agentic patterns.

---

# Safety

Repair guidance can involve physical and electrical risk.

Safety must therefore be treated as a product requirement rather than only a prompt instruction.

The system should eventually distinguish between actions that are reasonable for a general user and actions that require greater expertise or professional service.

Examples may include:

* simple visual inspection
* resetting the appliance
* checking accessible hoses
* removing panels
* electrical measurements
* working near energized components
* operations involving stored electrical energy

The exact safety policy should be designed deliberately and evaluated.

The LLM must not be the sole authority deciding what constitutes acceptable repair risk.

The assistant should be capable of refusing to provide an unsafe procedural step while still explaining the diagnosis and appropriate next action.

---

# Eval-Driven Development

Evaluation is part of the product architecture, not something added after development.

The project should build a growing set of real repair scenarios derived from the actual manufacturer corpus.

Potential evaluation dimensions include:

### Ingestion

* document integrity
* structural preservation
* table preservation
* incremental update correctness

### Retrieval

* Recall@K
* MRR
* nDCG
* exact-source retrieval
* model applicability
* serial-range applicability
* document revision correctness
* bulletin precedence

### Generation

* factual correctness
* completeness
* groundedness
* unsupported claims
* citation correctness
* citation coverage
* relevance

### Diagnostic behavior

* appropriate next question
* correct diagnostic progression
* unnecessary steps
* trajectory correctness
* final diagnosis

### Safety

* unsafe recommendation rate
* correct escalation
* correct abstention

### System

* latency
* token usage
* processing time
* failure rate

Not every metric needs to be implemented immediately.

Add evaluations when the corresponding capability is introduced.

---

# Golden Dataset Philosophy

The evaluation dataset should primarily emerge from real manufacturer knowledge rather than synthetic examples created solely to make the system look successful.

Whenever the corpus reveals a meaningful scenario, consider whether it should become an eval.

Particularly valuable cases include:

* generic manual vs later service bulletin
* one model revision vs another
* serial number inside vs outside a bulletin's applicability range
* old document revision vs newer revision
* exact error code
* exact part number
* semantically described symptom
* information requiring multiple supporting sections
* insufficient evidence
* intentionally unanswerable question

Failures discovered during development or real usage should be candidates for permanent regression cases.

---

# Evaluator Philosophy

Use the appropriate evaluator for the task.

Possible evaluator types include:

* deterministic checks
* information-retrieval metrics
* rule-based checks
* model-based evaluators
* human review

Do not use an LLM judge for something that can be tested deterministically.

Do not assume an LLM judge is objective simply because it produces a numerical score.

Important evaluator behavior should itself be validated where practical.

---

# Regression Discipline

Changes to components such as:

* parser
* document representation
* chunking
* embedding model
* retrieval logic
* reranking
* prompts
* model
* LangGraph workflow
* safety behavior

should eventually be compared against an established baseline.

A change that improves one metric while harming another should be analyzed rather than automatically accepted.

The project should preserve enough experiment metadata to understand why performance changed.

---

# Observability

The production system should eventually make it possible to understand what happened during a repair interaction.

Useful observability may include:

* user input
* interpreted device context
* retrieval query
* filters
* retrieved candidates
* rankings
* selected context
* model calls
* workflow transitions
* citations
* evaluator results
* latency
* failures

Do not select an observability platform yet.

Evaluate open-source options when the project reaches the appropriate phase.

---

# Modularity

Components whose performance we expect to experiment with should have clear boundaries so they can be replaced without rewriting the application.

Examples include:

* parser
* chunker
* embedding provider
* retrieval strategy
* reranker
* evaluator
* model provider
* document source

Avoid abstractions that exist only for theoretical future flexibility.

Create abstractions where experimentation or meaningful substitution is actually expected.

---

# Data and Copyright

The application code and project-created metadata should be suitable for an open-source repository.

Manufacturer documentation may be publicly accessible while still being copyrighted.

Do not assume publicly downloadable manufacturer documents can be redistributed through this project's repository.

The project should therefore distinguish between:

* open-source application code
* reproducible corpus manifests and metadata
* locally acquired copyrighted source documents

Manufacturer documents should not be committed to the public repository unless redistribution rights are clearly established.

Do not circumvent:

* authentication
* paywalls
* access controls
* CAPTCHAs
* licensing restrictions

Record source provenance and retrieval restrictions.

---

# Testing Philosophy

Testing should cover both conventional software behavior and AI-system behavior.

Use conventional deterministic tests for deterministic functionality.

Do not substitute LLM evaluations for unit and integration tests.

Similarly, conventional unit tests alone are insufficient to establish the quality of retrieval or generative behavior.

The project should eventually contain both.

---

# Avoid Premature Complexity

Do not automatically introduce:

* Redis
* message brokers
* distributed queues
* Kubernetes
* dedicated search engines
* additional databases
* separate vector databases
* microservices
* GraphRAG
* knowledge graphs
* multiple autonomous agents
* proprietary SaaS dependencies

Any of these may become appropriate later.

They require a demonstrated product or technical need.

PostgreSQL should be used fully before introducing additional data infrastructure.

---

# Product Roadmap

The expected high-level development sequence is below. **README phase numbers
follow the compressed map** (deviation D2); charter titles in parentheses are
the original labels.

| README / practice | Charter label | Notes |
| --- | --- | --- |
| Phase 1 | Phase 1 — Real Manufacturer Corpus | Unchanged |
| Phase 2 | Phase 2 — Parsing **+** Phase 4 — Chunking | Chunking decided with parse bake-off (D2, D3) |
| Phase 3 | Phase 3 — Incremental Ingestion | Embeddings local (D1); depth partial (D5) |
| Phase 4 | Phase 5 — Retrieval Experiments | Bake-off recorded ([ADR-0011](adr/0011-retrieval-bakeoff.md)); ADR-0010 stays default |
| Phase 5+ | Charter Phases 6–10 | Q&A, LangGraph, safety, evals, hardening |

## Phase 1 — Real Manufacturer Corpus

Build a reproducible corpus for the Whirlpool WFW5620H front-load washer family.

Include, where available:

* service/technical manuals
* Technical Service Pointers
* troubleshooting guidance
* tech sheets
* parts documentation
* relevant supporting manufacturer material

Capture:

* provenance
* document type
* document identity
* revision
* date
* product applicability
* serial applicability
* document relationships
* content integrity

Preserve actual manufacturer files locally without redistributing copyrighted material.

This phase should also identify useful future evaluation scenarios.

---

## Phase 2 — Parsing and Canonical Document Representation

Research and benchmark candidate parsing approaches against representative documents from the corpus.

Evaluate difficult content such as:

* hierarchy
* tables
* troubleshooting procedures
* warning blocks
* diagrams
* parts lists
* scanned content where present

Select an approach based on evidence.

Define a canonical representation that downstream ingestion, chunking, retrieval, provenance, and change detection can use.

---

## Phase 3 — Incremental Ingestion

Design document/version tracking and change detection.

Use real document revisions where possible.

Demonstrate that unchanged content does not undergo unnecessary downstream processing.

Ensure correctness for:

* additions
* deletions
* modifications
* metadata-only changes
* revision changes

---

## Phase 4 — Chunking Experiments

Establish a meaningful retrieval evaluation set.

Compare several appropriate chunking strategies.

Consider whether different manufacturer document types require different policies.

Select the initial production strategy based on evidence.

---

## Phase 5 — Retrieval Experiments

Establish retrieval baselines and compare approaches.

The experiments should be capable of revealing the strengths and weaknesses of lexical, semantic, metadata-aware, hybrid, fusion, and reranking approaches.

Pay particular attention to:

* exact identifiers
* symptoms expressed conversationally
* model applicability
* serial applicability
* document revisions
* service bulletin precedence

Choose the production retrieval architecture based on eval results.

---

## Phase 6 — Grounded Repair Q&A

Introduce OpenAI-based answer generation over retrieved evidence.

Require:

* grounded responses
* provenance
* meaningful citations
* appropriate abstention

Evaluate answer quality separately from retrieval quality.

---

## Phase 7 — Stateful Diagnostic Assistant

Use LangGraph to evolve grounded Q&A into interactive troubleshooting.

Represent diagnostic state explicitly.

Build multi-turn eval cases that verify the diagnostic trajectory rather than only final-answer wording.

---

## Phase 8 — Safety and Escalation

Formalize repair-risk policy.

Introduce deterministic controls where appropriate.

Evaluate:

* unsafe guidance
* proper warnings
* abstention
* professional-service escalation

Safety-critical regression cases should have a very high release bar.

---

## Phase 9 — Integrated Evaluation and Observability

Mature the eval system into a repeatable development and regression framework.

Introduce appropriate open-source tracing/observability tooling after comparing available options.

Connect production failures and user feedback back into the evaluation dataset.

---

## Phase 10 — Product Hardening

Complete the capabilities necessary for a credible self-hosted product, based on what the preceding phases reveal.

This may include areas such as:

* user experience
* APIs
* persistence
* reliability
* concurrency
* authentication if required
* deployment
* security
* performance
* operational visibility

Do not predetermine detailed solutions before requirements become concrete.

---

# How to Work on This Project

Work one phase at a time.

Do not implement later roadmap phases simply because they are described here.

At the beginning of a phase:

1. Understand the phase objective.
2. Examine what previous phases have established.
3. Identify unresolved architectural decisions.
4. Research current approaches where appropriate.
5. Present meaningful alternatives and tradeoffs.
6. Recommend experiments where evidence would improve the decision.
7. Make important decisions explicit before embedding them deeply in the implementation.
8. Implement only what belongs to the current phase.
9. Validate the phase against its intended outcomes.
10. Record discoveries that affect future phases.

When uncertain about a technology choice, avoid silently selecting one.

Surface the decision.

When evidence can answer the question, prefer experimentation over opinion.

---

# Current Assignment

Begin with **Phase 1 — Real Manufacturer Corpus**.

Do not begin parsing, chunking, embeddings, pgvector indexing, RAG, OpenAI integration, or LangGraph implementation yet.

First develop a clear understanding of the available Whirlpool WFW5620H-family knowledge ecosystem.

Research and identify actual documents and manufacturer knowledge sources relevant to this product family.

The initial corpus should provide enough variation to support later testing of:

* document types
* document revisions
* model applicability
* serial-number applicability
* generic guidance vs specific service guidance
* incremental document changes
* technical tables and procedures
* exact identifiers
* troubleshooting scenarios

Before making substantial implementation choices for corpus acquisition, present what was discovered, important gaps, legal/licensing considerations, and any decisions that need to be made.

The objective of Phase 1 is not to maximize the number of files.

The objective is to establish a **small, authoritative, diverse, reproducible and deeply understood repair corpus** that can serve as the foundation for every subsequent engineering and evaluation decision.
---

# Deviations from this charter

Register of accepted or provisional differences between this charter and shipped
ADRs / practice. Discussed with the project owner; update when new ADRs land.

| ID | Topic | Charter says | What we did | Status |
| --- | --- | --- | --- | --- |
| D1 | Embedding provider | OpenAI is a fixed technology; API usage is the paid exception | Local `BAAI/bge-base-en-v1.5`; OpenAI = **LLM only** ([ADR-0009](adr/0009-local-open-embeddings.md)). Charter text amended to match. | **Accepted** |
| D2 | Roadmap phase map | Phases 2→3→4 chunking→5 retrieval | Compressed map in [Product Roadmap](#product-roadmap); chunking folded into Phase 2 | **Accepted** |
| D3 | Chunking justification | Via retrieval / end-to-end evals | Parsing fixtures first ([ADR-0007](adr/0007-parser-and-chunker.md)); re-score after retrieval eval harness | **Accepted interim** |
| D4 | Retrieval selection | Lexical / vector / hybrid bake-off before lock | Bake-off run ([ADR-0011](adr/0011-retrieval-bakeoff.md)); **ADR-0010 remains default**; F5E2 KB gap open | **Accepted** — experiments done |
| D5 | Incremental depth | Below-document / structural change detection | Chunk `content_hash` skip ([ADR-0008](adr/0008-incremental-ingestion.md)); deepen later if manuals churn | **Accepted MVP** |
| D6 | No downloader | Don’t redistribute / don’t circumvent | No fetcher at all ([ADR-0003](adr/0003-no-downloader.md)) | **Tightening** |
| D7 | Docker placement | Self-hostable Docker | LAN Docker host ([ADR-0006](adr/0006-lan-docker-host.md)) | **Compatible** |
| D8 | Deployment scope | Self-hostable product; auth *if required* | **LAN-only** — API/DB never internet-facing; no public auth/TLS work ([ADR-0016](adr/0016-http-api-docker.md)) | **Accepted** |

