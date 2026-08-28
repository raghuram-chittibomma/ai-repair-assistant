# Parsing bake-off scorecard

| Extractor | Strategy | Fixture | Result | Detail |
| --- | --- | --- | --- | --- |
| hybrid | structured | error-codes-bound | PASS | codes_present:ratio=1.00 missing=[]; codes_bound:unbound=[] |
| hybrid | structured | pua-list-markers | FAIL | pua_mapped:raw_markers=0 unmapped_ratio=0.0000 |
| hybrid | structured | near-dup-stable | PASS | identical_page_chunk_hashes:mismatched_pages=[] |
| hybrid | structured | reflow-not-delta | PASS | phrase_present_both:Voltage checks must be made; content_hash_equal_for_phrase_chunk:distinct_hashes=1 |
| hybrid | structured | tsp-trilingual | PASS | languages_present:found=['en', 'es', 'fr']; phrase_present:0.5s on |
| hybrid | mhtml | mhtml-decode | PASS | mhtml_body:len=12055 matched=True |
| hybrid | structured | procedure-reading-order | PASS | phrase_order_monotonic:page=12 markers=6; numbered_steps_present:missing=[] |
| pdfplumber | structured | error-codes-bound | PASS | codes_present:ratio=1.00 missing=[]; codes_bound:unbound=[] |
| pdfplumber | structured | pua-list-markers | PASS | pua_mapped:raw_markers=155 unmapped_ratio=0.0000 |
| pdfplumber | structured | near-dup-stable | PASS | identical_page_chunk_hashes:mismatched_pages=[] |
| pdfplumber | structured | reflow-not-delta | PASS | phrase_present_both:Voltage checks must be made; content_hash_equal_for_phrase_chunk:distinct_hashes=1 |
| pdfplumber | structured | tsp-trilingual | PASS | languages_present:found=['en', 'es', 'fr']; phrase_present:0.5s on |
| pdfplumber | mhtml | mhtml-decode | PASS | mhtml_body:len=12055 matched=True |
| pdfplumber | structured | procedure-reading-order | FAIL | phrase_order_monotonic:page=12 markers=6; numbered_steps_present:missing=[9, 11] |
