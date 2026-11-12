"""Index only the six approved original corpus files from user-provided ZIP.
Usage: python scripts/import_zip.py /absolute/path/to/dataset.zip
"""

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hr_rag.bootstrap import build
from hr_rag.models import Principal
from hr_rag.policy import policy_for, Quarantined
from hr_rag.parse import MAX_BYTES


def main(src):
    _, ingestor = build()
    admin = Principal("local-import", "swiftpay", groups=("hr_rag_admin",), admin=True)
    with zipfile.ZipFile(src) as z:
        for item in z.infolist():
            if item.is_dir():
                continue
            basename = Path(item.filename).name

            # Reject unsafe paths and oversized entries before reading their bytes.
            if ".." in Path(item.filename).parts or item.file_size > MAX_BYTES:
                print("SKIPPED unsafe/oversized entry")
                continue
            try:
                # Skip files lacking an approved policy so unrelated ZIP contents do
                # not enter the corpus.
                policy_for(basename)
            except Quarantined as ex:
                print("SKIPPED", basename, "—", str(ex))
                continue
            print(basename, ingestor.ingest(basename, z.read(item), admin))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/import_zip.py path/to/source.zip")
    main(sys.argv[1])
