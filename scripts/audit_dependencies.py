"""Audit the installed graph and the public versions of CPU PyTorch wheels."""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--torch-requirements",type=Path,default=Path("backend/requirements-torch-audit.txt"))
    args=parser.parse_args()
    subprocess.run([sys.executable,"-m","pip","check"],check=True)
    frozen=subprocess.check_output([sys.executable,"-m","pip","freeze"],text=True)
    lines=[line for line in frozen.splitlines() if not line.lower().startswith(("torch==","torch @","torchaudio==","torchaudio @"))]
    # Only local +cpu version labels are converted to their upstream versions.
    # No vulnerability ID is ignored; both audits must succeed.
    with tempfile.TemporaryDirectory(prefix="dub-audit-") as folder:
        installed=Path(folder) / "installed.txt"
        installed.write_text("\n".join(lines)+"\n",encoding="utf-8")
        for requirements in (installed,args.torch_requirements):
            subprocess.run([sys.executable,"-m","pip_audit","--requirement",str(requirements),"--no-deps"],check=True)


if __name__=="__main__":
    main()
