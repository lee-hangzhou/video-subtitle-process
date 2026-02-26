def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(segments: list, output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for seg in segments:
            start = format_timestamp(seg.start_time)
            end = format_timestamp(seg.end_time)
            f.write(f"{seg.index}\n{start} --> {end}\n{seg.text}\n\n")
