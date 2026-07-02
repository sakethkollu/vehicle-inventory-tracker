from vehicle_inventory.ingest.progress import IngestProgress, emit_progress


def test_set_message_deduplicates_consecutive():
    progress = IngestProgress()
    progress.set_message("hello")
    progress.set_message("hello")
    assert progress.logs == ["hello"]


def test_set_message_trims_and_skips_empty():
    progress = IngestProgress()
    progress.set_message("  first  ")
    progress.set_message("")
    assert progress.message == ""
    assert progress.logs == ["first"]


def test_set_message_caps_log_history():
    progress = IngestProgress()
    for index in range(350):
        progress.set_message(f"line-{index}")
    assert len(progress.logs) == 300
    assert progress.logs[0] == "line-50"


def test_emit_progress_updates_fields_and_invokes_callback():
    progress = IngestProgress()
    seen = []

    def callback(p: IngestProgress) -> None:
        seen.append((p.status, p.percent))

    emit_progress(
        progress,
        callback,
        message="working",
        status="running",
        percent=42.0,
    )
    assert progress.status == "running"
    assert progress.percent == 42.0
    assert progress.message == "working"
    assert seen == [("running", 42.0)]


def test_to_dict_matches_dataclass_fields():
    progress = IngestProgress(status="completed", vehicles_persisted=10)
    payload = progress.to_dict()
    assert payload["status"] == "completed"
    assert payload["vehicles_persisted"] == 10
