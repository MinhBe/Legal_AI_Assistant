

def test_key_dir_reads_only_dahl_files(tmp_path):
    """keys/ chứa cả kaggle*.json: không bao giờ được coi là key Dahl (sự cố 19/11/2026)."""
    from app.config import load_key_dir

    (tmp_path / "dahl.keys").write_text("dahl_AAA\nDAHL_2=dahl_BBB\n", encoding="utf-8")
    (tmp_path / "dahl_new.keys").write_text("dahl_CCC\n", encoding="utf-8")
    (tmp_path / "kaggle.json").write_text('{"username":"u","key":"k"}', encoding="utf-8")
    (tmp_path / "kaggle (1).json").write_text('{"username":"u","key":"k2"}', encoding="utf-8")
    (tmp_path / "dahl.keys.bak").write_text("dahl_OLD\n", encoding="utf-8")
    (tmp_path / ".cool-dahl-0").write_text("123", encoding="utf-8")
    assert load_key_dir(str(tmp_path)) == ("dahl_AAA", "dahl_BBB", "dahl_CCC")
