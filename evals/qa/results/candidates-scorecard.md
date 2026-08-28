# Candidate scenarios bench

**4/6 passed**

| scenario | family | pass | ms | detail |
| --- | --- | --- | ---: | --- |
| f5e2-technician-depth | applicability-product-category | NO | 18501 | must_cite missing 'W11320651'; got ['service-manual-w11169652-revb', 'W11169652', 'service-manual-w11169652', 'W11169652']; must_cite missing 'W11320651'; got ['service-manual-w11169652-revb', 'W11169652', 'service-manual-w11169652', 'W11169652'] |
| error-code-lookup | retrieval-exact-identifier | NO | 2418 | expect_cites_any missing one of ['W11320651', 'W11156989']; got ['service-manual-w11169652-revb', 'W11169652', 'service-manual-w11169652-revb', 'W11169652'] |
| error-code-orphaned-by-extraction | retrieval-exact-identifier | yes | 1878 | ok |
| code-to-procedure-hop | retrieval-cross-reference | yes | 1634 | ok |
| identifier-only-distinction | near-duplicate-tech-sheets | yes | 1562 | ok |
| genuine-incremental-addition | near-duplicate-tech-sheets | yes | 2574 | ok |
