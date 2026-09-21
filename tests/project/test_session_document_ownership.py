import os

import ezdxf

from src.cad import session
from tests.project.fake_cad import Acad, Document


def test_open_document_does_not_claim_preexisting_document_returned_by_open(
    tmp_path,
    monkeypatch,
):
    primary_path = tmp_path / "primary.dxf"
    alias_path = tmp_path / "alias.dxf"

    drawing = ezdxf.new("R2010")
    drawing.saveas(primary_path)

    # A hard link gives two different path spellings for the exact same
    # filesystem object.
    #
    # canonical_path()/Path.resolve() do not collapse hard-link names, so
    # find_open_document() will miss it. Path.samefile(), used by the faithful
    # fake AcadDocuments.Open(), recognises that both paths identify the same
    # drawing.
    os.link(primary_path, alias_path)

    existing = Document(primary_path)
    acad = Acad([existing])

    # Prove that the Python path lookup misses this spelling.
    assert session.find_open_document(acad, str(alias_path)) is None

    # Database bookkeeping is not under test here. Item 4 will deal with its
    # failure semantics separately.
    monkeypatch.setattr(
        session,
        "mark_open",
        lambda *_args, **_kwargs: None,
    )

    opened_doc, opened_here = session.open_document(
        acad,
        str(alias_path),
    )

    # AcadDocuments.Open() must have returned the already-open document.
    assert opened_doc is existing

    # This is the critical ownership assertion.
    assert opened_here is False

    # Reproduce the exact finally-block ownership contract used by:
    #
    #   execute_commands
    #   execute_edit_plan
    #   execute_cad3d_scene
    #
    # A user's pre-existing document must therefore remain open.
    if opened_here:
        session.close_document(
            opened_doc,
            str(alias_path),
        )

    assert existing.closed is False

    # No second AutoCAD document should have been created.
    assert acad.Documents.Count == 1