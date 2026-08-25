# Parsing bake-off scorecard

| Extractor | Strategy | Fixture | Result | Detail |
| --- | --- | --- | --- | --- |
| pypdf | naive_fixed | error-codes-bound | FAIL | codes_present:ratio=1.00 missing=[]; codes_bound:unbound=['F6E1'] |
| pypdf | naive_fixed | pua-list-markers | PASS | pua_mapped:raw_markers=155 unmapped_ratio=0.0000 |
| pypdf | naive_fixed | near-dup-stable | PASS | identical_page_chunk_hashes:mismatched_pages=[] |
| pypdf | naive_fixed | reflow-not-delta | PASS | phrase_present_both:Voltage checks must be made; content_hash_equal_for_phrase_chunk:distinct_hashes=1 |
| pypdf | naive_fixed | tsp-trilingual | PASS | languages_present:found=['en', 'es', 'fr']; phrase_present:0.5s on |
| pypdf | mhtml | mhtml-decode | PASS | mhtml_body:len=12055 matched=True |
| pdfplumber | structured | error-codes-bound | PASS | codes_present:ratio=1.00 missing=[]; codes_bound:unbound=[] |
| pdfplumber | structured | pua-list-markers | PASS | pua_mapped:raw_markers=155 unmapped_ratio=0.0000 |
| pdfplumber | structured | near-dup-stable | PASS | identical_page_chunk_hashes:mismatched_pages=[] |
| pdfplumber | structured | reflow-not-delta | PASS | phrase_present_both:Voltage checks must be made; content_hash_equal_for_phrase_chunk:distinct_hashes=1 |
| pdfplumber | structured | tsp-trilingual | PASS | languages_present:found=['en', 'es', 'fr']; phrase_present:0.5s on |
| pdfplumber | mhtml | mhtml-decode | PASS | mhtml_body:len=12055 matched=True |
| pymupdf | structured | error-codes-bound | PASS | codes_present:ratio=1.00 missing=[]; codes_bound:unbound=[] |
| pymupdf | structured | pua-list-markers | PASS | pua_mapped:raw_markers=155 unmapped_ratio=0.0000 |
| pymupdf | structured | near-dup-stable | PASS | identical_page_chunk_hashes:mismatched_pages=[] |
| pymupdf | structured | reflow-not-delta | PASS | phrase_present_both:Voltage checks must be made; content_hash_equal_for_phrase_chunk:distinct_hashes=1 |
| pymupdf | structured | tsp-trilingual | PASS | languages_present:found=['en', 'es', 'fr']; phrase_present:0.5s on |
| pymupdf | mhtml | mhtml-decode | PASS | mhtml_body:len=12055 matched=True |
