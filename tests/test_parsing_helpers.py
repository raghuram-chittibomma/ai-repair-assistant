"""Unit tests for PUA mapping and MHTML decode — no manufacturer PDFs required."""

from repair_assistant.parsing import mhtml, pua


def test_known_pua_markers_become_bullets():
    raw = "Before \uf0d8 step one \uf06e step two"
    mapped = pua.map_pua(raw)
    assert "\uf0d8" not in mapped
    assert "\uf06e" not in mapped
    assert mapped.count("•") == 2


def test_split_list_items_after_mapping():
    raw = "Intro\n\uf0d8 First\n\uf0d8 Second"
    items = pua.split_list_items(raw)
    assert items == ["Intro", "First", "Second"] or "First" in items[1]


def test_count_pua_markers():
    raw = "\uf0d8" * 3 + "\uf06e" * 2
    counts = pua.count_pua_markers(raw)
    assert counts["U+F0D8"] == 3
    assert counts["U+F06E"] == 2


def test_collapse_overdrawn_connector_labels():
    assert pua.collapse_overdrawn_connector_labels("JJ366--11") == "J36-1"
    assert pua.collapse_overdrawn_connector_labels("JJ366 | --33") == "J36 | -3"
    assert pua.map_pua("JJ366--22") == "J36-2"
    assert pua.map_pua("Disconnect J15 from the ACU") == "Disconnect J15 from the ACU"


def test_mhtml_rejoins_quoted_printable_soft_breaks(tmp_path):
    path = tmp_path / "page.mhtml"
    path.write_text(
        "MIME-Version: 1.0\r\n"
        "Content-Type: multipart/related; boundary=\"BOUNDARY\"\r\n"
        "\r\n"
        "--BOUNDARY\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Content-Transfer-Encoding: quoted-printable\r\n"
        "\r\n"
        "<html><body>F5E2 door =\r\n"
        "lock failure on front=\r\n"
        "-load washers</body></html>\r\n"
        "--BOUNDARY--\r\n",
        encoding="utf-8",
    )
    html = mhtml.load_mhtml(path)
    text = mhtml.html_to_visible_text(html)
    assert "F5E2 door lock failure on front-load washers" in text
