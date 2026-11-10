"""File-type sniffing and filename cleaning. No database needed."""
import pytest

from app.services.attachment_service import clean_filename, sniff_content_type

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 20
PDF = b"%PDF-1.7\n" + b"x" * 20
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"x" * 20


@pytest.mark.parametrize(
    "data,expected",
    [(PNG, "image/png"), (JPEG, "image/jpeg"), (PDF, "application/pdf"), (WEBP, "image/webp")],
)
def test_sniff_recognises_allowed_types(data, expected):
    assert sniff_content_type(data) == expected


@pytest.mark.parametrize(
    "data",
    [b"MZ\x90\x00 windows executable", b"<html><script>alert(1)</script>", b"GIF89a....", b"", b"PK\x03\x04 zip"],
)
def test_sniff_rejects_everything_else(data):
    assert sniff_content_type(data) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd.png", "passwd.png"),
        ("C:\\Users\\me\\photo.jpg", "photo.jpg"),
        ('we"ird\r\nname.pdf', "weirdname.pdf"),
        ("normal photo.png", "normal photo.png"),
    ],
)
def test_clean_filename_strips_paths_and_control_characters(raw, expected):
    assert clean_filename(raw, ".png") == expected


def test_clean_filename_falls_back_and_truncates():
    assert clean_filename(None, ".pdf") == "attachment.pdf"
    assert clean_filename("", ".png") == "attachment.png"
    assert len(clean_filename("a" * 500 + ".png", ".png")) == 200
