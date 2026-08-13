"""Convert an EyeLink EDF and split its contents into analysis-ready CSVs.

Examples
--------
python read_eyelink_edf.py session.edf
python read_eyelink_edf.py session.edf --sample gaze --eye right

The script uses SR Research's official EDF2ASC utility installed by the
EyeLink Developers Kit.  PyLink controls a live tracker; it is not an offline
EDF reader.
"""

import argparse
import ctypes
import csv
import shutil
import subprocess
from pathlib import Path


WINDOWS_CONVERTERS = (
    Path(r"C:\Program Files (x86)\SR Research\EyeLink\bin\64\edf2asc64.exe"),
    Path(r"C:\Program Files (x86)\SR Research\EyeLink\bin\edf2asc.exe"),
)
EVENT_PREFIXES = {
    "START", "END", "SBLINK", "EBLINK", "SFIX", "EFIX",
    "SSACC", "ESACC", "BUTTON", "INPUT",
}
WINDOWS_EDFAPI_LIBRARIES = (
    Path(r"C:\Program Files (x86)\SR Research\EyeLink\libs\x64\edfapi64.dll"),
    Path(r"C:\Program Files (x86)\SR Research\EyeLink\libs\edfapi.dll"),
)
MESSAGE_EVENT = 24


def find_edf2asc(explicit_path=None):
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"EDF2ASC does not exist: {path}")
    for command in ("edf2asc64", "edf2asc"):
        located = shutil.which(command)
        if located:
            return Path(located)
    for path in WINDOWS_CONVERTERS:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "EDF2ASC was not found. Install the EyeLink Developers Kit or pass "
        "--edf2asc with its full path."
    )


def convert_edf(edf_path, output_dir, sample="href", eye="right", edf2asc=None):
    edf_path = Path(edf_path).expanduser().resolve()
    if not edf_path.is_file():
        raise FileNotFoundError(edf_path)
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    converter = find_edf2asc(edf2asc)
    sample_option = {"href": "-sh", "gaze": "-sg", "pupil": "-sp"}[sample]
    eye_option = {"right": "-r", "left": "-l"}[eye]
    command = [
        str(converter), sample_option, eye_option,
        "-p", str(output_dir), str(edf_path),
    ]
    eyelink_root = next(
        (parent for parent in converter.parents if parent.name.lower() == "eyelink"),
        None,
    )
    runtime_dir = None
    if eyelink_root is not None:
        runtime_candidates = (
            eyelink_root / "libs" / "x64",
            eyelink_root / "libs",
        )
        runtime_dir = next(
            (path for path in runtime_candidates if path.is_dir()), None
        )
    # The Windows converter dynamically loads EDFAPI from EyeLink/libs. Using
    # that folder as cwd makes a clean Developer Kit install work even when its
    # DLL directory was not added to the system PATH.
    result = subprocess.run(
        command,
        cwd=str(runtime_dir) if runtime_dir else None,
        capture_output=True,
        text=True,
    )
    candidates = [
        path for path in output_dir.iterdir()
        if path.stem.lower() == edf_path.stem.lower()
        and path.suffix.lower() == ".asc"
    ]
    # Some Windows EDF2ASC builds return -1 after a successful conversion, so
    # the output file is the authoritative success condition.
    if not candidates:
        details = (result.stderr or result.stdout or "no converter output").strip()
        raise RuntimeError(
            "EDF2ASC did not create the ASC file. Command: "
            f"{subprocess.list2cmdline(command)}\n{details}"
        )
    return candidates[0]


def parse_asc(asc_path, sample="href"):
    """Return sample, message, and event rows without external packages."""
    samples = []
    messages = []
    events = []
    coordinate_prefix = "href" if sample == "href" else sample
    with Path(asc_path).open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            fields = line.split()
            if fields[0] == "MSG" and len(fields) >= 3:
                messages.append({
                    "tracker_time_ms": fields[1],
                    "message": " ".join(fields[2:]),
                })
                continue
            if fields[0] in EVENT_PREFIXES:
                events.append({
                    "event_type": fields[0],
                    "fields": " ".join(fields[1:]),
                })
                continue
            try:
                float(fields[0])
            except (ValueError, IndexError):
                continue
            samples.append({
                "tracker_time_ms": fields[0],
                f"{coordinate_prefix}_x": fields[1] if len(fields) > 1 else "",
                f"{coordinate_prefix}_y": fields[2] if len(fields) > 2 else "",
                "pupil_area": fields[3] if len(fields) > 3 else "",
                "extra_fields": " ".join(fields[4:]),
            })
    return samples, messages, events


class _EdfAccessEvent(ctypes.Structure):
    """Packed FEVENT layout used by the 64-bit EDF Access API."""

    _pack_ = 1
    _fields_ = [
        ("time", ctypes.c_uint32),
        ("type", ctypes.c_int16),
        ("read", ctypes.c_uint16),
        ("start_time", ctypes.c_uint32),
        ("end_time", ctypes.c_uint32),
        ("measurements", ctypes.c_float * 23),
        ("eye", ctypes.c_int16),
        ("status", ctypes.c_uint16),
        ("flags", ctypes.c_uint16),
        ("input", ctypes.c_uint16),
        ("buttons", ctypes.c_uint16),
        ("parsed_by", ctypes.c_uint16),
        ("message", ctypes.c_void_p),
    ]


def read_exact_messages_from_edf(edf_path):
    """Read untruncated EDF messages with SR Research's EDF Access DLL.

    Some Windows EDF2ASC builds omit the final character of message lines.
    Using the official access DLL for messages avoids that converter issue.
    Returns ``None`` when the DLL is unavailable (for example on another OS).
    """
    library_path = next(
        (path for path in WINDOWS_EDFAPI_LIBRARIES if path.is_file()), None
    )
    if library_path is None:
        return None
    library = ctypes.CDLL(str(library_path))
    library.edf_open_file.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
    ]
    library.edf_open_file.restype = ctypes.c_void_p
    library.edf_get_next_data.argtypes = [ctypes.c_void_p]
    library.edf_get_next_data.restype = ctypes.c_int
    library.edf_get_float_data.argtypes = [ctypes.c_void_p]
    library.edf_get_float_data.restype = ctypes.c_void_p
    library.edf_close_file.argtypes = [ctypes.c_void_p]

    error = ctypes.c_int(0)
    handle = library.edf_open_file(
        str(Path(edf_path).resolve()).encode("utf-8"),
        0,
        1,
        0,
        ctypes.byref(error),
    )
    if not handle:
        raise RuntimeError(f"EDF Access API open failed with code {error.value}")
    messages = []
    try:
        while True:
            data_type = library.edf_get_next_data(handle)
            if data_type == 0:
                break
            data_pointer = library.edf_get_float_data(handle)
            if data_type != MESSAGE_EVENT or not data_pointer:
                continue
            event = _EdfAccessEvent.from_address(data_pointer)
            if not event.message:
                continue
            length = ctypes.c_int16.from_address(event.message).value
            message_bytes = ctypes.string_at(event.message + 2, max(0, length))
            messages.append({
                "tracker_time_ms": str(event.start_time),
                "message": message_bytes.decode("utf-8", errors="replace"),
            })
    finally:
        library.edf_close_file(handle)
    return messages


def write_csv(path, rows, fieldnames):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edf", help="EyeLink EDF file")
    parser.add_argument(
        "--sample", choices=("href", "gaze", "pupil"), default="href"
    )
    parser.add_argument("--eye", choices=("right", "left"), default="right")
    parser.add_argument("--output-dir", help="Default: <EDF stem>_parsed")
    parser.add_argument("--edf2asc", help="Optional full path to EDF2ASC")
    args = parser.parse_args()

    edf_path = Path(args.edf).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else edf_path.parent / f"{edf_path.stem}_parsed"
    )
    asc_path = convert_edf(
        edf_path,
        output_dir,
        sample=args.sample,
        eye=args.eye,
        edf2asc=args.edf2asc,
    )
    samples, messages, events = parse_asc(asc_path, sample=args.sample)
    exact_messages = read_exact_messages_from_edf(edf_path)
    if exact_messages is not None:
        messages = exact_messages
    coordinate_prefix = "href" if args.sample == "href" else args.sample
    write_csv(
        output_dir / "samples.csv",
        samples,
        [
            "tracker_time_ms", f"{coordinate_prefix}_x",
            f"{coordinate_prefix}_y", "pupil_area", "extra_fields",
        ],
    )
    write_csv(
        output_dir / "messages.csv",
        messages,
        ["tracker_time_ms", "message"],
    )
    write_csv(
        output_dir / "events.csv",
        events,
        ["event_type", "fields"],
    )
    print(f"ASC: {asc_path}")
    print(f"Samples: {len(samples)}; messages: {len(messages)}; events: {len(events)}")
    print(f"CSV output: {output_dir}")


if __name__ == "__main__":
    main()
